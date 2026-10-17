"""Expense Tracking — Dashboard for expenses vs budget and upcoming obligations."""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.expense_tracker import RecurringExpenseManager
from core.business_setup import BusinessSetup
from core.config import config as cfg
import sqlite3

st.set_page_config(page_title="Expense Tracking — Duka", page_icon="📊")

st.title("📊 Expense Tracking")
st.caption("Track expenses against budgets and upcoming obligations.")

business_id = st.session_state.get("business_id")
if not business_id:
    st.warning("⚠️ Please register your business first in **Business Setup**.")
    st.stop()

manager = RecurringExpenseManager()
setup = BusinessSetup()

# ---- Current Month Summary ----
st.subheader("This Month's Spending")

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
        use_container_width=True,
    )

    st.bar_chart(df.set_index("Category")["Amount (KES)"])
else:
    st.info("No expenses recorded this month yet.")

conn.close()

# ---- Upcoming Obligations ----
st.divider()
st.subheader("📅 Upcoming Obligations (Next 30 Days)")

schedule = manager.generate_schedule(business_id, months_ahead=1)
upcoming = [s for s in schedule if s["due_date"] >= today.strftime("%Y-%m-%d")][:20]

if upcoming:
    obl_data = []
    for obl in upcoming:
        obl_data.append({
            "Due Date": obl["due_date"],
            "Description": obl["description"],
            "Amount (KES)": obl["amount_minor"] / 100,
            "Status": obl["status"],
        })

    obl_df = pd.DataFrame(obl_data)
    st.dataframe(
        obl_df.style.format({"Amount (KES)": "KES {:,.0f}"}),
        use_container_width=True,
    )

    total_due = sum(o["amount_minor"] for o in upcoming)
    st.metric("Total Due (Next 30 Days)", f"KES {total_due/100:,.0f}")
else:
    st.info("No upcoming obligations in the next 30 days.")

# ---- Budget Tracking ----
st.divider()
st.subheader("🎯 Budget vs. Actual")

configs = setup.get_category_configs(business_id)
budget_configs = [c for c in configs if c.get("monthly_budget_minor")]

if budget_configs:
    budget_data = []
    for cfg_item in budget_configs:
        cat_name = cfg_item.get("display_name") or cfg_item["name"]
        budget = cfg_item["monthly_budget_minor"]
        threshold = cfg_item["alert_threshold_pct"]

        actual_row = next((r for r in rows if r["code"] == cfg_item["code"]), None)
        actual = actual_row["total_minor"] if actual_row else 0

        pct_used = (actual / budget * 100) if budget > 0 else 0
        status = "🔴 Over" if pct_used > 100 else ("🟡 Near" if pct_used >= threshold else "🟢 OK")

        budget_data.append({
            "Category": cat_name,
            "Budget (KES)": budget / 100,
            "Actual (KES)": actual / 100,
            "% Used": round(pct_used, 1),
            "Status": status,
        })

    budget_df = pd.DataFrame(budget_data)
    st.dataframe(
        budget_df.style.format({
            "Budget (KES)": "KES {:,.0f}",
            "Actual (KES)": "KES {:,.0f}",
            "% Used": "{:.1f}%",
        }),
        use_container_width=True,
    )

    over_budget = [b for b in budget_data if b["% Used"] > 100]
    near_budget = [b for b in budget_data if 80 <= b["% Used"] <= 100]

    if over_budget:
        st.error(f"⚠️ **{len(over_budget)} categories over budget!**")
        for b in over_budget:
            st.write(f"• {b['Category']}: KES {b['Actual (KES)']:,.0f} / KES {b['Budget (KES)']:,.0f}")
    elif near_budget:
        st.warning(f"⚠️ **{len(near_budget)} categories near budget limit**")
else:
    st.info("No budgets configured. Set monthly budgets in **Business Setup → Categories**.")
