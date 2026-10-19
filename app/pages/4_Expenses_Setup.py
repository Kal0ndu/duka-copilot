"""Expense Setup — Manage recurring expenses with auto-detection."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.expense_tracker import ExpenseTracker, RecurringExpenseManager
from core.business_setup import BusinessSetup, ExpenseError
from app.expense_ui import render_add_form, render_expense_list
from auth.middleware import invalidate_user_context_on_page

st.set_page_config(page_title="Expense Setup — Duka", page_icon=":material/description:")
# ---- Authentication Gate ----
require_auth()


st.title("Expense Setup")
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
    st.subheader("Auto-Detect Recurring Expenses")
    st.caption("Scan your transaction history for repeating patterns.")

    if st.button(":material/search: Scan transactions", type="primary"):
        with st.spinner("Analyzing transaction history..."):
            patterns = tracker.detect_recurring_expenses(business_id)

        if patterns:
            st.success(f"Found {len(patterns)} potential recurring patterns")

            for i, p in enumerate(patterns):
                with st.expander(
                    f"KES {p['amount_minor']/100:,.0f} — Day {p['day_of_month']} "
                    f"({p['cadence']}, {p['frequency']}×, confidence: {p['confidence']}%)"
                ):
                    st.write(f"**Amount:** KES {p['amount_minor']/100:,.0f}")
                    st.write(f"**Day of month:** {p['day_of_month']}")
                    st.write(f"**Cadence:** {p['cadence']}")
                    st.write(f"**Occurrences:** {p['frequency']}")
                    st.write(f"**Confidence:** {p['confidence']}%")

                    col1, col2 = st.columns(2)
                    with col1:
                        description = st.text_input(
                            "Description", value=f"Auto-detected expense",
                            key=f"desc_{i}"
                        )
                    with col2:
                        exp_type = st.selectbox(
                            "Type", ["rent", "salary", "utilities", "insurance",
                                     "supplier_credit", "loan_repayment", "other"],
                            key=f"type_{i}"
                        )

                    if st.button("Add as Recurring Expense", key=f"add_{i}"):
                        try:
                            setup.add_recurring_expense(
                                business_id=business_id,
                                expense_type=exp_type,
                                description=description,
                                amount_minor=p["amount_minor"],
                                cadence=p["cadence"],
                                day_of_month=p["day_of_month"],
                                party_id=p["party_id"],
                                last_paid_date=p.get("last_seen"),
                            )
                        except ExpenseError as e:
                            st.error(str(e))
                        else:
                            invalidate_user_context_on_page()
                            st.success(f"✓ Added: {description}")
                            st.rerun()
        else:
            st.info("No recurring patterns detected. You need at least 2 months of transaction history with the same payee and amount.")

with tab2:
    st.subheader("Your Recurring Expenses")
    render_add_form(setup, business_id, prefix="es_add")
    st.divider()
    render_expense_list(setup, business_id, prefix="es_list")
