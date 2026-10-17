"""Page 5: Working Capital, Customer Credit (Kitabu), and A/R / A/P Aging."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.working_capital import WorkingCapitalAnalyzer
from core.charts import chart_aging_buckets
from app.sample_loader import load_sample_business, MOCK_PROFILES

st.set_page_config(page_title="Working Capital — Duka", page_icon="💳", layout="wide")

transactions = st.session_state.get("parsed_transactions")
profile = st.session_state.get("business_profile")

if not transactions:
    st.warning("⚠️ No statement currently loaded.")
    st.info("Load a sample business profile to inspect working capital cycles and customer credit aging:")
    col1, col2, col3 = st.columns(3)
    if col1.button("🏪 Load Amina's Grocery", use_container_width=True):
        st.session_state["parsed_transactions"] = load_sample_business("amina_grocery")
        st.session_state["business_profile"] = MOCK_PROFILES["amina_grocery"]
        st.rerun()
    if col2.button("🚐 Load Otieno Transport", use_container_width=True):
        st.session_state["parsed_transactions"] = load_sample_business("otieno_transport")
        st.session_state["business_profile"] = MOCK_PROFILES["otieno_transport"]
        st.rerun()
    if col3.button("💇 Load Grace Salon", use_container_width=True):
        st.session_state["parsed_transactions"] = load_sample_business("grace_salon")
        st.session_state["business_profile"] = MOCK_PROFILES["grace_salon"]
        st.rerun()
    st.stop()

analyzer = WorkingCapitalAnalyzer(transactions)
wc_metrics = analyzer.compute_working_capital_metrics()
biz_name = profile.get("name", "Your Business") if profile else "Your Business"

st.title("💳 Working Capital & Aging Management")
st.caption(f"Track customer store credit (*kitabu*), supplier payables, and cash conversion cycle for **{biz_name}**.")

# ---- ROW 1: WORKING CAPITAL KPIS ----
w1, w2, w3, w4 = st.columns(4)
w1.metric(
    "Total Customer Credit (A/R)",
    f"KES {wc_metrics['total_receivables_kes']:,.0f}",
    help="Money owed to your business by customers."
)
w2.metric(
    "Total Payables Owed (A/P)",
    f"KES {wc_metrics['total_payables_kes']:,.0f}",
    help="Money your business owes to suppliers and utilities."
)
net_wc = wc_metrics["net_working_capital_kes"]
w3.metric(
    "Net Working Capital",
    f"KES {net_wc:,.0f}",
    delta="Positive (Net Asset)" if net_wc >= 0 else "Negative (Net Liability)",
    delta_color="normal" if net_wc >= 0 else "inverse"
)
ccc = wc_metrics["cash_conversion_cycle_days"]
w4.metric(
    "Cash Conversion Cycle",
    f"{ccc} days",
    help="Days between paying suppliers and receiving customer cash (DSO - DPO)."
)

# Operational efficiency row
sub_c1, sub_c2, sub_c3 = st.columns(3)
sub_c1.caption(f"⏱️ **Days Sales Outstanding (DSO):** {wc_metrics['dso_days']} days to collect cash")
sub_c2.caption(f"⏳ **Days Payable Outstanding (DPO):** {wc_metrics['dpo_days']} days to settle supplier bills")
overdue_ar = wc_metrics["overdue_receivables_kes"]
sub_c3.caption(f"⚠️ **Total Overdue Receivables:** KES {overdue_ar:,.0f}")

st.divider()

# ---- ROW 2: AGING BUCKETS VISUALIZATION ----
col_ar_chart, col_ap_chart = st.columns(2)

with col_ar_chart:
    st.subheader("📊 Customer Credit Aging (A/R)")
    st.caption("Breakdown of customer debts by overdue age.")
    ar_buckets = wc_metrics["ar_buckets"]
    st.altair_chart(chart_aging_buckets(ar_buckets, title="Customer Aging"), use_container_width=True)

with col_ap_chart:
    st.subheader("📑 Supplier Payables Aging (A/P)")
    st.caption("Upcoming and overdue payments to suppliers.")
    ap_buckets = wc_metrics["ap_buckets"]
    st.altair_chart(chart_aging_buckets(ap_buckets, title="Payables Aging"), use_container_width=True)

st.divider()

# ---- SECTION 3: CUSTOMER CREDIT BOOK (KITABU) & REMINDER GENERATOR ----
st.subheader("📖 Customer Credit Book (*Duka Kitabu*)")
st.caption("Active store credit balances with one-click collection reminders.")

receivables = wc_metrics["receivables_list"]

if receivables:
    rec_table = []
    for r in receivables:
        rec_table.append({
            "ID": r.entry_id,
            "Customer Name": r.counterparty,
            "Contact Phone": r.phone_token,
            "Balance (KES)": f"{r.amount_kes:,.2f}",
            "Due Date": r.due_date,
            "Days Overdue": f"{r.days_overdue} days" if r.days_overdue > 0 else "Current",
            "Aging Bucket": r.bucket,
        })
    st.dataframe(rec_table, use_container_width=True)

    # Friendly Reminder Generator
    st.markdown("#### 📱 Automated Payment Reminder Generator")
    st.caption("Select an overdue customer to generate a courteous SMS or WhatsApp payment reminder:")

    overdue_customers = [r for r in receivables if r.days_overdue > 0]
    if not overdue_customers:
        overdue_customers = receivables

    selected_cust = st.selectbox(
        "Choose Customer to Remind",
        options=overdue_customers,
        format_func=lambda r: f"{r.counterparty} — KES {r.amount_kes:,.0f} ({r.bucket})"
    )

    if selected_cust:
        st.markdown(f"**Draft SMS / WhatsApp for {selected_cust.counterparty} ({selected_cust.phone_token}):**")
        st.code(selected_cust.reminder_msg, language="text")
        st.button("📋 Copy Message Text", key="btn_copy_sms", on_click=lambda: None)
else:
    st.info("No active customer receivables.")

st.divider()

# ---- SECTION 4: UPCOMING PAYABLES & BILLS SCHEDULE ----
st.subheader("🗓️ Accounts Payable & Supplier Bills Schedule")
st.caption("Obligations to settle to maintain good supplier credit terms and avoid service disruption.")

payables = wc_metrics["payables_list"]
if payables:
    pay_table = []
    for p in payables:
        pay_table.append({
            "Payable ID": p.entry_id,
            "Supplier / Payee": p.counterparty,
            "Category / Details": p.phone_token,
            "Amount Due (KES)": f"{p.amount_kes:,.2f}",
            "Due Date": p.due_date,
            "Status": "⚠️ Overdue" if p.days_overdue > 0 else "🟢 Upcoming",
            "Aging Bucket": p.bucket,
        })
    st.dataframe(pay_table, use_container_width=True)
else:
    st.info("No active supplier payables.")
