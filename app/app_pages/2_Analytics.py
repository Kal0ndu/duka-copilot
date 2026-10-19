"""Page 2: Executive business health & analytics dashboard."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.analytics import BusinessAnalytics
from core.charts import (
    MONEY_IN, chart_cashflow_trend, chart_category_breakdown, chart_monthly_pnl, chart_weekday_seasonality,
)
from app.sample_loader import load_sample_business, MOCK_PROFILES
from app.session_helpers import SessionManager, render_data_info_banner

st.set_page_config(page_title="Analytics — Duka", page_icon=":material/analytics:", layout="wide")
# ---- Authentication Gate ----
require_auth()


# Initialize session and check for data
SessionManager.init_session()
transactions = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if not transactions:
    st.warning("No statement currently loaded.", icon=":material/warning:")
    st.info(
        "You can upload a CSV on the **Upload statement** page or load a pre-built demo business below.",
        icon=":material/info:",
    )
    col1, col2, col3 = st.columns(3)
    if col1.button(":material/storefront: Load Amina's Grocery", width="stretch"):
        SessionManager.set_transactions(load_sample_business("amina_grocery"), MOCK_PROFILES["amina_grocery"])
        st.rerun()
    if col2.button(":material/directions_bike: Load Otieno Transport", width="stretch"):
        SessionManager.set_transactions(load_sample_business("otieno_transport"), MOCK_PROFILES["otieno_transport"])
        st.rerun()
    if col3.button(":material/content_cut: Load Grace Salon", width="stretch"):
        SessionManager.set_transactions(load_sample_business("grace_salon"), MOCK_PROFILES["grace_salon"])
        st.rerun()
    st.stop()

# Initialize analytics engine
analytics = BusinessAnalytics(transactions)
kpi = analytics.kpi_summary()
biz_name = profile.get("name", "Your Business") if profile else "Your Business"

st.title(f"Business health cockpit: {biz_name}", icon=":material/analytics:")
st.caption("Comprehensive revenue, margins, expense patterns, and liquidity health.")

# Show what data is currently loaded
render_data_info_banner()

# ---- ROW 1: PRIMARY FINANCIAL KPIS ----
row1_1, row1_2, row1_3, row1_4 = st.columns(4)
row1_1.metric("Total revenue", f"KES {kpi['total_revenue']:,.0f}", help="Gross inflows from sales and customer receipts.")
row1_2.metric("Total expenses", f"KES {kpi['total_costs']:,.0f}", help="Sum of COGS, OPEX, and financing costs.")
row1_3.metric("Net operating profit", f"KES {kpi['net_profit']:,.0f}", delta=f"{kpi['operating_margin_pct']:.1f}% margin")
row1_4.metric("Avg daily sales", f"KES {kpi['avg_daily_revenue']:,.0f}", f"{kpi['txn_count']} total txns")

# ---- ROW 2: OPERATIONAL & MARGIN METRICS ----
row2_1, row2_2, row2_3, row2_4 = st.columns(4)
row2_1.metric("COGS (direct costs)", f"KES {kpi['cogs']:,.0f}", help="Wholesale stock, inventory, and raw materials.")
row2_2.metric("OPEX (overheads)", f"KES {kpi['opex']:,.0f}", help="Rent, staff wages, electricity, utilities, transport.")
row2_3.metric("Gross margin", f"{kpi['gross_margin_pct']:.1f}%", help="(Revenue - COGS) / Revenue")
row2_4.metric("Operating margin", f"{kpi['operating_margin_pct']:.1f}%", help="Net operating cashflow / revenue")

# ---- SPECIAL SME INSIGHT: PERSONAL VS BUSINESS MIX ----
personal_pct = kpi["personal_mix_pct"]
personal_kes = kpi["personal_outflow"]

if personal_pct > 25.0:
    st.error(
        f"High personal withdrawal risk ({personal_pct:.1f}% of total outflows / KES {personal_kes:,.0f}): "
        "personal draws are taking a heavy toll on business working capital. "
        "Recommended limit for micro-enterprises is below 15-20% to prevent supplier payment defaults.",
        icon=":material/error:",
    )
elif personal_pct > 15.0:
    st.warning(
        f"Moderate personal draw ratio ({personal_pct:.1f}% / KES {personal_kes:,.0f}): "
        "monitor personal household withdrawals closely during slow trading weeks.",
        icon=":material/warning:",
    )
else:
    st.success(
        f"Healthy capital separation ({personal_pct:.1f}% / KES {personal_kes:,.0f}): "
        "you maintain strong discipline between household expenses and business reinvestment.",
        icon=":material/check_circle:",
    )

# ---- ROW 3: CASHFLOW TREND CHART ----
st.subheader("Money in and out over time", icon=":material/trending_up:")
st.caption("Blue bars: money received. Orange bars (below zero): money paid out. Green line: what was left "
           "(in minus out). Long periods are grouped by week. Hover for exact amounts.")
daily_df = analytics.daily_in_out_df()
st.altair_chart(chart_cashflow_trend(daily_df), width="stretch")

st.subheader("Profit and loss by month", icon=":material/stacked_bar_chart:")
st.caption("Sales income against the cost of what you sell, running costs (rent, wages, power, fees, tax) and "
           "money taken out for personal use. When the orange, green and gold bars together pass the blue one, "
           "the month lost money.")
st.altair_chart(chart_monthly_pnl(transactions), width="stretch")

# ---- ROW 4: WHERE MONEY COMES FROM AND GOES ----
col_chart_left, col_chart_right = st.columns(2)

with col_chart_left:
    st.subheader("Spending by category", icon=":material/shopping_cart:")
    st.caption("Where your money goes. Labels show each category's share of all spending.")
    cat_breakdown = analytics.category_breakdown()
    if cat_breakdown:
        st.altair_chart(chart_category_breakdown(cat_breakdown), width="stretch")
    else:
        st.info("No expense categories found.", icon=":material/info:")

with col_chart_right:
    st.subheader("Income by source", icon=":material/payments:")
    st.caption("Where your money comes from. Loans and transfers from your own accounts show here too.")
    income_breakdown = analytics.revenue_by_category()
    if income_breakdown:
        st.altair_chart(chart_category_breakdown(income_breakdown, color=MONEY_IN), width="stretch")
    else:
        st.info("No income recorded.", icon=":material/info:")

with st.container():
    st.subheader("Busy days of the week", icon=":material/calendar_month:")
    st.caption("Average money in and out on each weekday: plan stock and staff for your busiest days.")
    weekday_df = analytics.weekday_distribution()
    if not weekday_df.empty:
        st.altair_chart(chart_weekday_seasonality(weekday_df), width="stretch")
        best_day_idx = weekday_df["avg_inflow"].idxmax()
        best_day_name = weekday_df.loc[best_day_idx, "day_name"]
        best_day_val = weekday_df.loc[best_day_idx, "avg_inflow"]
        st.caption(f"Busiest day for sales: **{best_day_name}** (average KES {best_day_val:,.0f} received)")
    else:
        st.info("Insufficient daily history for weekday seasonality.", icon=":material/info:")

# ---- ROW 5: TOP COUNTERPARTIES TABLE ----
st.subheader("Key counterparties & trading partners", icon=":material/groups:")
tab_cust, tab_supp = st.tabs(["Top inflow sources (customers)", "Top outflow payees (suppliers / overhead)"])

with tab_cust:
    top_cust = analytics.top_counterparties(n=10, direction="in")
    if top_cust:
        st.dataframe(
            [{"Customer": c, "Total Paid In (KES)": f"{v:,.2f}"} for c, v in top_cust],
            width="stretch",
        )
    else:
        st.info("No customer inflow records.", icon=":material/info:")

with tab_supp:
    top_supp = analytics.top_counterparties(n=10, direction="out")
    if top_supp:
        st.dataframe(
            [{"Supplier / Payee": s, "Total Paid Out (KES)": f"{v:,.2f}"} for s, v in top_supp],
            width="stretch",
        )
    else:
        st.info("No supplier outflow records.", icon=":material/info:")

st.caption(f"Analysis generated from {kpi['txn_count']} transactions across {daily_df['date'].nunique()} trading days.")
