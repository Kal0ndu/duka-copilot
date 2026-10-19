"""Expense Setup — Manage recurring expenses with auto-detection."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.expense_tracker import ExpenseTracker, RecurringExpenseManager
from core.business_setup import EXPENSE_TYPES, BusinessSetup, ExpenseError
from app.expense_ui import render_add_form, render_expense_list
from auth.middleware import invalidate_user_context_on_page

st.set_page_config(page_title="Expense Setup — Duka", page_icon=":material/description:")
# ---- Authentication Gate ----
require_auth()


st.title("Expense setup", icon=":material/event_repeat:")
st.caption("Manage recurring expenses and auto-detect patterns.")

business_id = st.session_state.get("business_id")
if not business_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

tracker = ExpenseTracker()
manager = RecurringExpenseManager()
setup = BusinessSetup()

tab1, tab2 = st.tabs([":material/search: Auto-detect patterns", "Manage expenses"])

with tab1:
    st.subheader("Auto-detect recurring expenses")
    st.caption("Scan your saved statements for payments that repeat: same payee, a regular gap "
               "(daily, weekly, every 2 weeks, monthly, every 2–3 months, yearly). Amounts that change "
               "are shown as a monthly average, planned at ±10%.")

    from core.config import config as _cfg
    from core.statement_store import list_statements
    statements = [f for f in list_statements(_cfg.DB_PATH, business_id) if f["active_rows"]]
    if not statements:
        st.info("No saved statement yet. Upload one on **Upload Statement**; it stays saved with your business.")
    else:
        options = [None] + [f["file_id"] for f in statements]
        names = {f["file_id"]: f"{f['filename']} ({f['period_start']} → {f['period_end']})" for f in statements}
        source = st.selectbox("Statement to scan", options,
                              format_func=lambda fid: "All saved statements" if fid is None else names[fid])
        if st.button(":material/search: Scan statement", type="primary"):
            with st.spinner("Looking for repeating payments..."):
                st.session_state["_detected_expenses"] = tracker.detect_recurring_expenses(business_id, file_id=source)
            st.session_state["_detected_source"] = source

    patterns = st.session_state.get("_detected_expenses")
    if patterns is not None:
        if not patterns:
            st.info("No repeating payments found. A payee needs at least 2 payments with a regular gap.")
        else:
            st.success(f"Found {len(patterns)} repeating payment(s).")
        for i, p in enumerate(patterns or []):
            amount_txt = (f"~KES {p['amount_minor'] / 100:,.0f}/month (varies ±{p['amount_spread_pct']:.0f}%)"
                          if p["is_variable"] else f"KES {p['amount_minor'] / 100:,.0f}")
            title = f"{p['payee']} — {amount_txt} · {p['frequency_label']}"
            with st.expander(title + (" · already tracked" if p["already_tracked"] else ""),
                             icon=":material/check_circle:" if p["already_tracked"] else ":material/event_repeat:"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Payments seen", p["frequency"])
                c2.metric("Last paid", p["last_paid_date"])
                c3.metric("Next due", p["next_due"])
                st.caption(f"Category in your ledger: {p['category_code'].replace('_', ' ').title() or '—'} · "
                           f"first seen {p['first_seen']} · confidence {p['confidence']}%"
                           + (f" · paid around day {p['day_of_month']} of the month" if p["fixed_day"] else ""))
                if p["already_tracked"]:
                    st.caption("You already track this payee. Edit it on the **Manage expenses** tab.")
                    continue
                with st.form(f"detected_{i}"):
                    col1, col2 = st.columns(2)
                    description = col1.text_input("Description", value=f"{p['payee']}".title()[:120])
                    types = list(EXPENSE_TYPES)
                    exp_type = col2.selectbox("Type", types, index=types.index(p["suggested_type"]),
                                              format_func=lambda x: x.replace("_", " ").title())
                    if st.form_submit_button(":material/add: Track this expense", type="primary"):
                        try:
                            setup.add_recurring_expense(
                                business_id=business_id, expense_type=exp_type, description=description,
                                amount_minor=p["amount_minor"], cadence=p["cadence"],
                                interval_count=p["interval_count"],
                                day_of_month=p["day_of_month"] if p["fixed_day"] else None,
                                party_id=p["party_id"], is_variable=p["is_variable"],
                                last_paid_date=p["last_paid_date"],
                            )
                        except ExpenseError as e:
                            st.error(str(e))
                        else:
                            invalidate_user_context_on_page()
                            p["already_tracked"] = True
                            st.toast(f"Now tracking {description}", icon=":material/check_circle:")
                            st.rerun()

with tab2:
    st.subheader("Your recurring expenses")
    render_add_form(setup, business_id, prefix="es_add")
    st.divider()
    render_expense_list(setup, business_id, prefix="es_list")
