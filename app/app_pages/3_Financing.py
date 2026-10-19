"""Page 3: Compare digital financing options and test affordability."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from sandbox.mock_lender import MockLender
from core.cost_engine import CostEngine
from core.analytics import BusinessAnalytics
from core.charts import chart_loan_comparison
from core.config import Config
from app.sample_loader import load_sample_business, MOCK_PROFILES
from app.session_helpers import SessionManager, render_data_info_banner

st.set_page_config(page_title="Financing — Duka", page_icon=":material/payments:", layout="wide")
# ---- Authentication Gate ----
require_auth()


st.title("Digital financing & loan cost advisor", icon=":material/savings:")
st.caption("Compare digital micro-credit products in Kenya with transparent Effective Annual Rate (EAR) and cashflow affordability.")

# Initialize session and check for data
SessionManager.init_session()
transactions = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if not transactions:
    st.info("Load a sample business to auto-evaluate loan affordability against real operating cashflow:")
    col1, col2, col3 = st.columns(3)
    if col1.button(":material/storefront: Load Amina's Grocery", key="f_load_amina", width="stretch"):
        SessionManager.set_transactions(load_sample_business("amina_grocery"), MOCK_PROFILES["amina_grocery"])
        st.rerun()
    if col2.button(":material/directions_bike: Load Otieno Transport", key="f_load_otieno", width="stretch"):
        SessionManager.set_transactions(load_sample_business("otieno_transport"), MOCK_PROFILES["otieno_transport"])
        st.rerun()
    if col3.button(":material/content_cut: Load Grace Salon", key="f_load_grace", width="stretch"):
        SessionManager.set_transactions(load_sample_business("grace_salon"), MOCK_PROFILES["grace_salon"])
        st.rerun()

# Determine daily cashflow if transactions loaded
avg_daily_cashflow = 1500.0
if transactions:
    analytics = BusinessAnalytics(transactions)
    kpi = analytics.kpi_summary()
    avg_daily_cashflow = max(100.0, kpi["net_profit"] / max(1, kpi["txn_count"] / 10))

# ---- INPUT CONTROLS ----
col1, col2, col3 = st.columns(3)
amount = col1.number_input("Loan Principal Needed (KES)", min_value=1000, value=25000, step=5000)
term = col2.number_input("Repayment Term (Days)", min_value=7, max_value=365, value=30, step=7)
daily_budget = col3.number_input(
    "Daily Repayment Budget (KES)",
    min_value=0,
    value=int(round(avg_daily_cashflow * 0.4)),
    step=100,
    help="Maximum you can safely repay each day without choking your business. Defaults to 40% of estimated daily net profit."
)

offers = MockLender.compare_all(int(round(amount * 100)), int(term))

if daily_budget > 0:
    affordable = [o for o in offers if (o.daily_repayment_minor / 100.0) <= daily_budget]
else:
    affordable = offers

# ---- SUMMARY METRICS ----
best = offers[0] if offers else None
cheapest_ear = best.ear_pct if best else 0.0
highest_ear = max(o.ear_pct for o in offers) if offers else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric("Available Products", len(offers))
m2.metric("Affordable Within Budget", len(affordable))
m3.metric("Lowest EAR (Best Rate)", f"{cheapest_ear:.1f}%")
m4.metric("Highest EAR (Most Expensive)", f"{highest_ear:.1f}%", delta="High Cost Alert", delta_color="inverse")

st.divider()

# ---- PRODUCT COMPARISON CHART ----
st.subheader("Disbursed amount vs. total repayable")
st.caption("Inspect the true cost gap between what you receive in your M-Pesa vs what you must repay.")
st.altair_chart(chart_loan_comparison(offers), width="stretch")

# ---- OFFERS TABLE ----
st.subheader("Digital loan products ranked by effective annual rate (EAR)")
table_rows = []
for o in offers:
    daily_repay_kes = o.daily_repayment_minor / 100.0
    is_ok = daily_repay_kes <= daily_budget if daily_budget > 0 else True
    table_rows.append({
        "Lender": o.lender,
        "Product": o.product,
        "Net Disbursed": f"KES {o.disbursed_minor / 100:,.0f}",
        "Total Repayable": f"KES {o.total_repayable_minor / 100:,.0f}",
        "Daily Repayment": f"KES {daily_repay_kes:,.0f}/day",
        "EAR % (True Cost)": f"{o.ear_pct:.1f}%",
        "TCC % (Fee & Interest)": f"{o.tcc_pct:.1f}%",
        "Affordability": "Affordable" if is_ok else "Exceeds Budget",
    })

st.dataframe(table_rows, width="stretch")

# ---- AFFORDABILITY CHECKER & CFO ADVISORY ----
if best:
    st.divider()
    st.subheader(f"Top Recommended Product: {best.lender} ({best.product})")

    engine = CostEngine()
    best_daily_kes = best.daily_repayment_minor / 100.0
    check = engine.affordability_check(
        daily_repayment=int(best.daily_repayment_minor / 100),
        avg_daily_profit=int(daily_budget if daily_budget > 0 else avg_daily_cashflow),
        buffer_minor=int(Config.SAFETY_BUFFER_MINOR / 100),
    )

    col_res1, col_res2 = st.columns(2)
    with col_res1:
        if check["affordable"]:
            st.success(
                f"**Cashflow Check Passed:** The required repayment of **KES {best_daily_kes:,.0f}/day** "
                f"leaves sufficient operating surplus above your daily safety buffer."
            )
        else:
            st.error(
                f"**Cashflow Warning:** The required repayment of **KES {best_daily_kes:,.0f}/day** "
                f"exceeds your safe daily surplus. Consider choosing a longer repayment term (e.g. 60 days) to lower the daily burden."
            )

    with col_res2:
        st.markdown("##### Duka CFO Cost Transparency Tip:")
        st.info(
            f"Lenders often market loans as having 'just 1% daily interest' or 'low flat fee'. "
            f"Over a {term}-day term, that compounds to an Effective Annual Rate (EAR) of "
            f"**{best.ear_pct:.1f}%**! Always borrow the minimum required for revenue-generating stock."
        )

st.caption("Rates and products are indicative models based on prevailing Kenyan digital micro-lending regulations.")
