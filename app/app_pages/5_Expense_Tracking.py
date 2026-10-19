"""Expense Tracking — Dashboard for expenses vs budget and upcoming obligations."""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.expense_tracker import RecurringExpenseManager
from core.business_setup import BusinessSetup
from core.config import config as cfg
import sqlite3

from core.charts import chart_budget_vs_actual, chart_category_breakdown

st.set_page_config(page_title="Expense Tracking — Duka", page_icon=":material/analytics:")
# ---- Authentication Gate ----
require_auth()


st.title("Expense tracking", icon=":material/donut_large:")
st.caption("Track expenses against budgets and upcoming obligations.")

business_id = st.session_state.get("business_id")
if not business_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

manager = RecurringExpenseManager()
setup = BusinessSetup()

# ---- Current Month Summary ----
st.subheader("This month's spending")

conn = sqlite3.connect(cfg.DB_PATH)
conn.row_factory = sqlite3.Row

today = datetime.now()
month_start = today.replace(day=1).strftime("%Y-%m-%d")
month_end = today.strftime("%Y-%m-%d")

cursor = conn.cursor()
cursor.execute("""
    SELECT c.code, c.name, c.kind,
           SUM(tl.amount_minor) as total_minor,
           COUNT(*) as txn_count
    FROM transaction_ledger tl
    JOIN category c ON c.category_id = tl.category_id
    WHERE tl.business_id = ?
      AND tl.direction = 'out'
      AND tl.voided = 0
      AND tl.local_date BETWEEN ? AND ?
    GROUP BY tl.category_id
    ORDER BY total_minor DESC
""", (business_id, month_start, month_end))

rows = cursor.fetchall()

if rows:
    data = []
    for row in rows:
        cat_code = row["code"]
        cat_name = row["name"]
        total = row["total_minor"]
        data.append({
            "Category": cat_name,
            "Code": cat_code,
            "Kind": row["kind"],
            "Amount (KES)": total / 100,
            "Transactions": row["txn_count"],
        })

    df = pd.DataFrame(data)

    col1, col2, col3 = st.columns(3)
    with col1:
        total_spent = df["Amount (KES)"].sum()
        st.metric("Total Spent This Month", f"KES {total_spent:,.0f}")
    with col2:
        st.metric("Transactions", df["Transactions"].sum())
    with col3:
        categories_count = len(df)
        st.metric("Categories Used", categories_count)

    st.dataframe(
        df.style.format({"Amount (KES)": "KES {:,.0f}"}),
        width="stretch",
    )

    st.caption("Where this month's money went. Labels show each category's share.")
    st.altair_chart(chart_category_breakdown(dict(zip(df["Category"], df["Amount (KES)"]))), width="stretch")
else:
    st.info("No expenses recorded this month yet.")

conn.close()

# ---- Upcoming Obligations ----
st.divider()
st.subheader("Overdue and upcoming payments (next 30 days)")

schedule = manager.generate_schedule(business_id, months_ahead=1)

if schedule:
    def _countdown(o):
        if o["status"] == "overdue":
            return f"Overdue by {o['days_overdue']} day{'s' if o['days_overdue'] != 1 else ''}"
        return "Due today" if o["days_until"] == 0 else f"In {o['days_until']} day{'s' if o['days_until'] != 1 else ''}"

    obl_df = pd.DataFrame([{
        "Due Date": o["due_date"],
        "Description": o["description"],
        "Amount (KES)": o["amount_minor"] / 100,
        "Countdown": _countdown(o),
        "Status": o["status"],
    } for o in schedule])
    st.dataframe(
        obl_df.style.format({"Amount (KES)": "KES {:,.0f}"}),
        width="stretch", hide_index=True,
    )

    overdue_total = sum(o["amount_minor"] for o in schedule if o["status"] == "overdue")
    total_due = sum(o["amount_minor"] for o in schedule)
    m1, m2 = st.columns(2)
    m1.metric("Total due (overdue + next 30 days)", f"KES {total_due/100:,.0f}")
    m2.metric("Of which overdue", f"KES {overdue_total/100:,.0f}")
    if overdue_total:
        st.caption("Record a payment in **Business Setup → Recurring Expenses** to move its next due date.")
else:
    st.info("No payments overdue or due in the next 30 days.")

# ---- Budget Tracking ----
st.divider()
st.subheader("Budget vs. actual")

configs = setup.get_category_configs(business_id)
budget_configs = [c for c in configs if c.get("monthly_budget_minor")]

if budget_configs:
    STATUS_LABEL = {"ok": "OK", "near": "Near limit", "over": "Over budget"}
    budget_data = []
    for cfg_item in budget_configs:
        cat_name = cfg_item.get("display_name") or cfg_item["name"]
        budget = cfg_item["monthly_budget_minor"]
        threshold = cfg_item["alert_threshold_pct"]

        actual_row = next((r for r in rows if r["code"] == cfg_item["code"]), None)
        actual = actual_row["total_minor"] if actual_row else 0

        pct_used = (actual / budget * 100) if budget > 0 else 0
        state = "over" if pct_used > 100 else ("near" if pct_used >= threshold else "ok")

        budget_data.append({
            "Category": cat_name,
            "Budget (KES)": budget / 100,
            "Actual (KES)": actual / 100,
            "% Used": round(pct_used, 1),
            "Status": [STATUS_LABEL[state]],
            "_state": state,
        })

    st.caption("Bars show what you've spent this month; the white tick is the budget. Green is within budget, "
               "amber is past your alert level, red is over budget. The label is the share of the budget used.")
    st.altair_chart(chart_budget_vs_actual([
        {"Category": b["Category"], "Budget": b["Budget (KES)"], "Actual": b["Actual (KES)"],
         "Status": STATUS_LABEL[b["_state"]]} for b in budget_data]), width="stretch")

    budget_df = pd.DataFrame(budget_data).drop(columns="_state")
    # Dataframe cells can't render :material/...: icons, so show status as colored pills
    st.dataframe(
        budget_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Budget (KES)": st.column_config.NumberColumn(format="localized"),
            "Actual (KES)": st.column_config.NumberColumn(format="localized"),
            "% Used": st.column_config.NumberColumn(format="%.1f%%"),
            "Status": st.column_config.MultiselectColumn(
                options=list(STATUS_LABEL.values()),
                color=["green", "orange", "red"],
            ),
        },
    )

    over_budget = [b for b in budget_data if b["_state"] == "over"]
    near_budget = [b for b in budget_data if b["_state"] == "near"]

    if over_budget:
        n = len(over_budget)
        st.error(f"**{n} {'category' if n == 1 else 'categories'} over budget!**", icon=":material/error:")
        for b in over_budget:
            st.write(f"• {b['Category']}: KES {b['Actual (KES)']:,.0f} / KES {b['Budget (KES)']:,.0f}")
    elif near_budget:
        n = len(near_budget)
        st.warning(f"**{n} {'category' if n == 1 else 'categories'} near budget limit**", icon=":material/warning:")
        for b in near_budget:
            st.write(f"• {b['Category']}: KES {b['Actual (KES)']:,.0f} / KES {b['Budget (KES)']:,.0f} ({b['% Used']:.1f}%)")
else:
    st.info("No budgets configured. Set monthly budgets in **Business Setup → Categories**.")
