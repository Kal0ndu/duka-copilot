"""Page 2: Executive Business Health & Analytics Dashboard."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.analytics import BusinessAnalytics
from core.charts import chart_cashflow_trend, chart_category_breakdown, chart_weekday_seasonality
from app.sample_loader import load_sample_business, MOCK_PROFILES
from app.session_helpers import SessionManager, render_data_info_banner

st.set_page_config(page_title="Analytics — Duka", page_icon="📊", layout="wide")

# Initialize session and check for data
SessionManager.init_session()
transactions = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if not transactions:
    st.warning("⚠️ No statement currently loaded.")
    st.info("You can upload a CSV on the **Upload Statement** page or load a pre-built demo business below:")
    col1, col2, col3 = st.columns(3)
    if col1.button("🏪 Load Amina's Grocery", use_container_width=True):
        SessionManager.set_transactions(load_sample_business("amina_grocery"), MOCK_PROFILES["amina_grocery"])
        st.rerun()
    if col2.button("🚐 Load Otieno Transport", use_container_width=True):
        SessionManager.set_transactions(load_sample_business("otieno_transport"), MOCK_PROFILES["otieno_transport"])
        st.rerun()
    if col3.button("💇 Load Grace Salon", use_container_width=True):
        SessionManager.set_transactions(load_sample_business("grace_salon"), MOCK_PROFILES["grace_salon"])
        st.rerun()
    st.stop()

# Initialize analytics engine
analytics = BusinessAnalytics(transactions)
kpi = analytics.kpi_summary()
biz_name = profile.get("name", "Your Business") if profile else "Your Business"
biz_icon = profile.get("icon", "🏪") if profile else "🏪"

st.title(f"{biz_icon} Business Health Cockpit: {biz_name}")
st.caption("Comprehensive revenue, margins, expense patterns, and liquidity health.")

# Show what data is currently loaded
render_data_info_banner()

# ---- ROW 1: PRIMARY FINANCIAL KPIS ----
row1_1, row1_2, row1_3, row1_4 = st.columns(4)
row1_1.metric("Total Revenue", f"KES {kpi['total_revenue']:,.0f}", help="Gross inflows from sales and customer receipts.")
row1_2.metric("Total Expenses", f"KES {kpi['total_costs']:,.0f}", help="Sum of COGS, OPEX, and financing costs.")
row1_3.metric("Net Operating Profit", f"KES {kpi['net_profit']:,.0f}", delta=f"{kpi['operating_margin_pct']:.1f}% Margin")
row1_4.metric("Avg Daily Sales", f"KES {kpi['avg_daily_revenue']:,.0f}", f"{kpi['txn_count']} total txns")

# ---- ROW 2: OPERATIONAL & MARGIN METRICS ----
row2_1, row2_2, row2_3, row2_4 = st.columns(4)
row2_1.metric("COGS (Direct Costs)", f"KES {kpi['cogs']:,.0f}", help="Wholesale stock, inventory, and raw materials.")
row2_2.metric("OPEX (Overheads)", f"KES {kpi['opex']:,.0f}", help="Rent, staff wages, electricity, utilities, transport.")
row2_3.metric("Gross Margin", f"{kpi['gross_margin_pct']:.1f}%", help="(Revenue - COGS) / Revenue")
row2_4.metric("Operating Margin", f"{kpi['operating_margin_pct']:.1f}%", help="Net Operating Cashflow / Revenue")

st.divider()

# ---- SPECIAL SME INSIGHT: PERSONAL VS BUSINESS MIX ----
personal_pct = kpi["personal_mix_pct"]
personal_kes = kpi["personal_outflow"]

if personal_pct > 25.0:
    st.error(
        f"🚨 **High Personal Withdrawal Risk ({personal_pct:.1f}% of total outflows / KES {personal_kes:,.0f}):** "
        "Personal draws are taking a heavy toll on business working capital. "
        "Recommended limit for micro-enterprises is below 15-20% to prevent supplier payment defaults."
    )
elif personal_pct > 15.0:
    st.warning(
        f"⚠️ **Moderate Personal Draw Ratio ({personal_pct:.1f}% / KES {personal_kes:,.0f}):** "
        "Monitor personal household withdrawals closely during slow trading weeks."
    )
else:
    st.success(
        f"✅ **Healthy Capital Separation ({personal_pct:.1f}% / KES {personal_kes:,.0f}):** "
        "You maintain strong discipline between household expenses and business reinvestment."
    )

st.divider()

# ---- ROW 3: CASHFLOW TREND CHART ----
st.subheader("📈 Daily Cash Inflow vs Outflow Trend")
st.caption("Compare daily sales velocity against business expenses and net margin line.")
daily_df = analytics.daily_in_out_df()
st.altair_chart(chart_cashflow_trend(daily_df), use_container_width=True)

# ---- ROW 4: EXPENSE BREAKDOWN & WEEKDAY SEASONALITY ----
col_chart_left, col_chart_right = st.columns(2)

with col_chart_left:
    st.subheader("🛒 Spending by Category")
    st.caption("Distribution of business outflows across operational accounts.")
    cat_breakdown = analytics.category_breakdown()
    if cat_breakdown:
        st.altair_chart(chart_category_breakdown(cat_breakdown), use_container_width=True)
    else:
        st.info("No expense categories found.")

with col_chart_right:
    st.subheader("📅 Day-of-Week Seasonality")
    st.caption("Identify peak sales days to schedule inventory orders and staffing.")
    weekday_df = analytics.weekday_distribution()
    if not weekday_df.empty:
        st.altair_chart(chart_weekday_seasonality(weekday_df), use_container_width=True)
        best_day_idx = weekday_df["avg_inflow"].idxmax()
        best_day_name = weekday_df.loc[best_day_idx, "day_name"]
        best_day_val = weekday_df.loc[best_day_idx, "avg_inflow"]
        st.caption(f"🌟 **Peak Revenue Day:** **{best_day_name}** (Avg KES {best_day_val:,.0f}/day)")
    else:
        st.info("Insufficient daily history for weekday seasonality.")

st.divider()

# ---- ROW 5: TOP COUNTERPARTIES TABLE ----
st.subheader("👥 Key Counterparties & Trading Partners")
tab_cust, tab_supp = st.tabs(["Top Inflow Sources (Customers)", "Top Outflow Payees (Suppliers / Overhead)"])

with tab_cust:
    top_cust = analytics.top_counterparties(n=10, direction="in")
    if top_cust:
        st.dataframe(
            [{"Customer": c, "Total Paid In (KES)": f"{v:,.2f}"} for c, v in top_cust],
            use_container_width=True
        )
    else:
        st.info("No customer inflow records.")

with tab_supp:
    top_supp = analytics.top_counterparties(n=10, direction="out")
    if top_supp:
        st.dataframe(
            [{"Supplier / Payee": s, "Total Paid Out (KES)": f"{v:,.2f}"} for s, v in top_supp],
            use_container_width=True
        )
    else:
        st.info("No supplier outflow records.")

st.caption(f"Analysis generated from {kpi['txn_count']} transactions across {daily_df['date'].nunique()} trading days.")
