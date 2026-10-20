"""Page 7: Financial Health Dashboard — liquidity, runway, leverage, and health scoring."""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.financial_health import FinancialHealthAnalyzer
from core.charts import chart_cashflow_trend, PRIMARY_GREEN, SECONDARY_BLUE, ACCENT_CORAL, AMBER_WARNING
from app.sample_loader import load_sample_business, MOCK_PROFILES
from app.session_helpers import SessionManager, render_data_info_banner

st.set_page_config(page_title="Financial Health — Duka Copilot", page_icon=":material/monitor_heart:", layout="wide")
# ---- Authentication Gate ----
require_auth()


# Initialize session and check for data
SessionManager.init_session()
transactions = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if not transactions:
    st.warning("No statement currently loaded.")
    st.info("Load a sample business profile to run a financial health check:")
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

biz_name = profile.get("name", "Your Business") if profile else "Your Business"

analyzer = FinancialHealthAnalyzer(transactions)
report = analyzer.assess()

st.title("Financial health dashboard", icon=":material/monitor_heart:")
st.caption(f"Comprehensive financial health check for **{biz_name}** — {report.period_start} to {report.period_end}")

# ---- HEALTH SCORE CARD ----
score_color = (
    "#10B981" if report.health_score >= 60
    else "#F59E0B" if report.health_score >= 40
    else "#EF4444"
)

st.markdown(
    f"""
    <div style="text-align:center; padding: 24px 0 8px 0;">
        <div style="font-size: 64px; font-weight: 800; color: {score_color}; line-height: 1;">
            {report.health_score}/100
        </div>
        <div style="font-size: 20px; color: {score_color}; font-weight: 600; margin-top: 4px;">
            {report.health_label}
        </div>
        <div style="font-size: 13px; color: #6B7280; margin-top: 4px;">
            {report.txn_count} transactions analysed
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---- ROW 1: LIQUIDITY & RUNWAY KPIs ----
st.subheader("Liquidity & runway", icon=":material/water_drop:")
l1, l2, l3, l4 = st.columns(4)

l1.metric(
    "Cash Balance (est.)",
    f"KES {report.cash_balance_kes:,.0f}",
    help="Estimated available cash based on cumulative net flow."
)
l2.metric(
    "Days of Cash",
    f"{report.days_of_cash} days",
    help="How many days you can operate at current burn rate without new revenue."
)
l3.metric(
    "Current Ratio",
    f"{report.current_ratio:.2f}",
    help="Current assets / current liabilities. Above 1.0 means you can cover short-term obligations.",
    delta="Healthy" if report.current_ratio >= 1.0 else "Low",
    delta_color="normal" if report.current_ratio >= 1.0 else "inverse",
)
l4.metric(
    "Quick Ratio",
    f"{report.quick_ratio:.2f}",
    help="Cash-only coverage of short-term obligations (more conservative than current ratio).",
)

st.divider()

# ---- ROW 2: PROFITABILITY & LEVERAGE ----
st.subheader("Profitability & leverage")
p1, p2, p3, p4 = st.columns(4)

p1.metric(
    "Gross Margin",
    f"{report.gross_margin_pct:.1f}%",
    help="(Revenue - COGS) / Revenue"
)
p2.metric(
    "Operating Margin",
    f"{report.operating_margin_pct:.1f}%",
    help="Operating cashflow as % of revenue."
)
p3.metric(
    "Net Margin",
    f"{report.net_margin_pct:.1f}%",
    help="Bottom-line profit after all expenses.",
    delta="Profitable" if report.net_margin_pct >= 0 else "Loss-Making",
    delta_color="normal" if report.net_margin_pct >= 0 else "inverse",
)
p4.metric(
    "Burn Multiple",
    f"{report.burn_multiple:.2f}x",
    help="Expenses / Revenue. Below 1.0 means you're spending less than you earn.",
)

st.divider()

# ---- ROW 3: GROWTH & STABILITY ----
st.subheader("Growth & stability")
g1, g2, g3, g4 = st.columns(4)

rev_growth_str = f"{report.revenue_growth_pct:+.1f}%" if report.revenue_growth_pct is not None else "N/A"
g1.metric(
    "Revenue Growth",
    rev_growth_str,
    help="Period-over-period revenue trend (first half vs second half).",
    delta=rev_growth_str if report.revenue_growth_pct is not None and report.revenue_growth_pct >= 0 else None,
    delta_color="normal" if report.revenue_growth_pct is not None and report.revenue_growth_pct >= 0 else "inverse",
)
g2.metric(
    "Revenue Volatility",
    f"{report.revenue_volatility_pct:.0f}%",
    help="Coefficient of variation of daily revenue. Lower is more stable.",
)
g3.metric(
    "Customer Concentration",
    f"{report.revenue_concentration_pct:.1f}%",
    help="Share of revenue from largest customer. Above 30% is a concentration risk.",
)
g4.metric(
    "Debt / Revenue",
    f"{report.debt_to_revenue_ratio:.1%}",
    help="Financing costs as a share of total revenue.",
)

st.divider()

# ---- RISK FLAGS & RECOMMENDATIONS ----
col_risks, col_recs = st.columns(2)

with col_risks:
    st.subheader("Risk flags", icon=":material/flag:")
    if report.risk_flags:
        for flag in report.risk_flags:
            st.warning(flag)
    else:
        st.success("No significant risk flags detected. Business appears healthy.")

with col_recs:
    st.subheader("Recommendations")
    if report.recommendations:
        for rec in report.recommendations:
            st.info(rec)
    else:
        st.success("No urgent recommendations. Keep doing what you're doing!")

st.divider()

# ---- CASHFLOW TREND CHART ----
st.subheader("Daily cashflow trend")
daily_df = analyzer.daily_trend_df()
if not daily_df.empty:
    st.altair_chart(chart_cashflow_trend(daily_df), width="stretch")
else:
    st.info("Not enough data for trend chart.")

# ---- WEEKLY SUMMARY TABLE ----
with st.expander("Weekly Revenue & Margin Summary", expanded=False):
    weekly_df = analyzer.weekly_summary()
    if not weekly_df.empty:
        display_df = weekly_df.copy()
        display_df["revenue"] = display_df["revenue"].apply(lambda x: f"KES {x:,.0f}")
        display_df["expenses"] = display_df["expenses"].apply(lambda x: f"KES {x:,.0f}")
        display_df["net"] = display_df["net"].apply(lambda x: f"KES {x:,.0f}")
        display_df["margin_pct"] = display_df["margin_pct"].apply(lambda x: f"{x:.1f}%")
        display_df.columns = ["Week", "Revenue", "Expenses", "Transactions", "Net", "Margin %"]
        st.dataframe(display_df, width="stretch", hide_index=True)
    else:
        st.info("Not enough data for weekly summary.")

# ---- HEALTH SCORE BREAKDOWN ----
with st.expander(":material/help: How this score is calculated", expanded=False):
    st.markdown("""
    The **Duka Copilot Financial Health Score** is a weighted composite from 0–100:

    | Factor | Weight | What It Measures |
    |--------|--------|------------------|
    | **Runway** | 25% | Days of cash at current burn rate |
    | **Profitability** | 25% | Net margin (profit after all expenses) |
    | **Liquidity** | 15% | Current ratio (ability to cover short-term obligations) |
    | **Growth** | 15% | Period-over-period revenue trend |
    | **Leverage** | 10% | Debt service as % of revenue |
    | **Stability** | 10% | Revenue consistency (lower volatility = higher score) |

    **Labels**: 80+ Excellent · 60–79 Good · 40–59 Fair · 20–39 At Risk · 0–19 Critical
    """)
