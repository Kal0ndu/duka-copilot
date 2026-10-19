"""Recurring-expense editor shared by Business Setup and Expense Setup.

Captures the last payment date, how often the expense repeats (every N
days / weeks / months / years) and shows the next due date with a live
countdown, or how many days it is overdue."""
from datetime import date
from typing import Optional

import streamlit as st

from auth.middleware import invalidate_user_context_on_page
from core import recurrence
from core.business_setup import EXPENSE_TYPES, BusinessSetup, ExpenseError, ExpenseNotFound

FREQ_LABELS = {"daily": "Day(s)", "weekly": "Week(s)", "monthly": "Month(s)", "annual": "Year(s)"}
STATE_ICON = {"overdue": ":material/error:", "due_today": ":material/schedule:",
              "upcoming": ":material/event:", "unknown": ":material/help:"}


def _type_label(t: str) -> str:
    return t.replace("_", " ").title()


def _frequency_of(exp: dict):
    """Legacy cadences shown as frequency + interval (biweekly = 2 weeks)."""
    n = exp.get("interval_count") or 1
    if exp["cadence"] == "biweekly":
        return "weekly", 2 * n
    if exp["cadence"] == "quarterly":
        return "monthly", 3 * n
    return exp["cadence"], n


def _changed(setup: BusinessSetup) -> None:
    invalidate_user_context_on_page()  # the assistant sees the change at once
    st.rerun()


def _schedule_inputs(prefix: str, exp: Optional[dict] = None):
    freq0, n0 = _frequency_of(exp) if exp else ("monthly", 1)
    c1, c2, c3 = st.columns(3)
    interval = c1.number_input("Repeats every", min_value=1, max_value=recurrence.MAX_INTERVAL,
                               value=int(n0), step=1, key=f"{prefix}_n")
    freq = c2.selectbox("Unit", list(FREQ_LABELS), index=list(FREQ_LABELS).index(freq0),
                        format_func=FREQ_LABELS.get, key=f"{prefix}_f")
    dom0 = exp.get("day_of_month") if exp else None
    dom = c3.number_input("Fixed day of month (0 = none)", min_value=0, max_value=31,
                          value=int(dom0 or 0), key=f"{prefix}_dom",
                          help="For monthly or yearly bills paid on the same day, e.g. rent on the 5th. "
                               "Short months use their last day.")
    return freq, int(interval), (int(dom) or None) if freq in ("monthly", "annual") else None


def render_add_form(setup: BusinessSetup, business_id: int, prefix: str = "add") -> None:
    with st.form(f"{prefix}_recurring", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 2, 1])
        exp_type = c1.selectbox("Type", EXPENSE_TYPES, format_func=_type_label, key=f"{prefix}_type")
        description = c2.text_input("Description", placeholder="e.g. Monthly shop rent", key=f"{prefix}_desc")
        amount = c3.number_input("Amount (KES)", min_value=0, value=0, step=500, key=f"{prefix}_amt",
                                 help="Each payment's amount. If the amount changes, tick the box below "
                                      "and enter your approximate monthly average instead.")
        freq, interval, dom = _schedule_inputs(prefix)
        c4, c5 = st.columns(2)
        last_paid = c4.date_input("Last paid on (leave empty if never)", value=None,
                                  max_value=date.today(), key=f"{prefix}_last",
                                  help="The next due date is calculated from this.")
        first_due = c5.date_input("First payment due (only if never paid)", value=None, key=f"{prefix}_first")
        is_variable = st.checkbox("The amount changes each time (amount above = approximate monthly average)",
                                  key=f"{prefix}_var",
                                  help="Duka plans each payment within ±10% of its share of that average.")
        if st.form_submit_button(":material/add: Add expense", type="primary"):
            try:
                setup.add_recurring_expense(
                    business_id=business_id, expense_type=exp_type, description=description,
                    amount_minor=int(round(amount * 100)), cadence=freq, interval_count=interval,
                    day_of_month=dom, last_paid_date=last_paid.isoformat() if last_paid else None,
                    next_due=first_due.isoformat() if first_due and not last_paid else None,
                    is_variable=is_variable,
                )
            except ExpenseError as e:
                st.error(str(e))
            else:
                st.toast(f"Added {description.strip()}", icon=":material/check_circle:")
                _changed(setup)


def _render_row(setup: BusinessSetup, business_id: int, exp: dict, prefix: str) -> None:
    eid = exp["expense_id"]
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([3, 2, 2, 3], vertical_alignment="center")
        c1.markdown(f"**{exp['description']}**  \n{_type_label(exp['expense_type'])}"
                    + (" · variable" if exp.get("is_variable") else ""))
        if exp.get("is_variable"):
            c2.markdown(f"~KES {exp['instalment_minor'] / 100:,.0f} per payment "
                        f"({exp['instalment_low_minor'] / 100:,.0f}–{exp['instalment_high_minor'] / 100:,.0f})  \n"
                        f"{exp['frequency_label']} · avg KES {exp['amount_minor'] / 100:,.0f}/month")
        else:
            c2.markdown(f"KES {exp['amount_minor'] / 100:,.0f}  \n{exp['frequency_label']}")
        c3.markdown(f"Next: **{exp['next_due'][:10]}**  \nLast paid: {exp.get('last_paid_date') or '—'}")
        label = f"{STATE_ICON.get(exp['due_state'], '')} {exp['due_label']}"
        if exp["due_state"] == "overdue":
            c4.error(label)
        elif exp["due_state"] == "due_today" or (exp["days_until"] is not None and exp["days_until"] <= 3):
            c4.warning(label)
        else:
            c4.info(label)

        b1, b2, b3 = st.columns(3)
        with b1.popover(":material/payments: Mark paid", width="stretch"):
            with st.form(f"{prefix}_pay_{eid}"):
                paid_on = st.date_input("Paid on", value=date.today(), max_value=date.today())
                paid_amt = st.number_input("Amount paid (KES)", min_value=0,
                                           value=int(exp["instalment_minor"] // 100), step=100)
                if st.form_submit_button("Save payment", type="primary"):
                    try:
                        setup.record_expense_payment(business_id, eid, paid_on.isoformat(),
                                                     int(round(paid_amt * 100)) or None)
                    except (ExpenseError, ExpenseNotFound) as e:
                        st.error(str(e))
                    else:
                        _changed(setup)
        with b2.popover(":material/edit: Edit", width="stretch"):
            with st.form(f"{prefix}_edit_{eid}"):
                desc = st.text_input("Description", value=exp["description"])
                amt = st.number_input("Monthly average (KES)" if exp.get("is_variable") else "Amount (KES)",
                                      min_value=0, value=int(exp["amount_minor"] // 100), step=500)
                var = st.checkbox("Variable amount (±10%)", value=bool(exp.get("is_variable")))
                freq, interval, dom = _schedule_inputs(f"{prefix}_e{eid}", exp)
                last = st.date_input("Last paid on", max_value=date.today(),
                                     value=recurrence.to_date(exp.get("last_paid_date")))
                nxt = st.date_input("Next due (used only if never paid)", value=recurrence.to_date(exp["next_due"]))
                if st.form_submit_button("Save changes", type="primary"):
                    changes = dict(description=desc, amount_minor=int(round(amt * 100)), cadence=freq,
                                   interval_count=interval, day_of_month=dom, is_variable=var,
                                   last_paid_date=last.isoformat() if last else None)
                    if not last and nxt:
                        changes["next_due"] = nxt.isoformat()
                    try:
                        setup.update_recurring_expense(business_id, eid, **changes)
                    except (ExpenseError, ExpenseNotFound) as e:
                        st.error(str(e))
                    else:
                        _changed(setup)
        with b3.popover(":material/delete: Delete", width="stretch"):
            st.caption("Stops tracking this expense. Past payments stay in the history.")
            if st.button("Delete expense", key=f"{prefix}_del_{eid}", type="primary"):
                try:
                    setup.delete_recurring_expense(business_id, eid)
                except ExpenseNotFound as e:
                    st.error(str(e))
                else:
                    _changed(setup)


def render_expense_list(setup: BusinessSetup, business_id: int, prefix: str = "list") -> None:
    expenses = setup.get_recurring_expenses(business_id)
    if not expenses:
        st.info("No recurring expenses yet. Add your first one above.")
        return
    overdue = [e for e in expenses if e["due_state"] == "overdue"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Active recurring expenses", len(expenses))
    m2.metric("Overdue", len(overdue))
    m3.metric("Overdue amount", f"KES {sum(e['amount_minor'] for e in overdue) / 100:,.0f}")
    for exp in expenses:
        _render_row(setup, business_id, exp, prefix)
