"""Spending Advisor — Purchase decision support and cash allocation guidance."""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.spending_advisor import SpendingAdvisor
from core.charts import chart_allocation, chart_forecast_confidence
from core.config import config as cfg

st.set_page_config(page_title="Spending Advisor — Duka", page_icon=":material/lightbulb:")
# ---- Authentication Gate ----
require_auth()


st.title("Spending advisor", icon=":material/lightbulb:")
st.caption("Make smarter spending decisions with data-backed advice.")

business_id = st.session_state.get("business_id")
if not business_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

advisor = SpendingAdvisor()

tab_purchase, tab_allocate, tab_forecast = st.tabs(
    ["Purchase Advice", "Cash Allocation", "Forecast"]
)

# =========================================================================
# Tab 1: Purchase Advice
# =========================================================================
with tab_purchase:
    st.subheader("Should I make this purchase?")

    col1, col2 = st.columns(2)
    with col1:
        purchase_label = st.text_input(
            "What are you buying?",
            placeholder="e.g., New fridge for shop",
            key="purchase_label",
        )
    with col2:
        purchase_amount = st.number_input(
            "Purchase amount (KES)",
            min_value=100,
            value=5000,
            step=500,
            key="purchase_amount",
        )

    expected_roi = st.slider(
        "Expected return on investment (%)",
        min_value=-50.0,
        max_value=200.0,
        value=10.0,
        step=5.0,
        help="How much return do you expect? Negative = loss-making purchase.",
        key="expected_roi",
    )

    if st.button("Analyze Purchase", type="primary", width="stretch"):
        with st.spinner("Analyzing..."):
            purchase_amount_minor = int(round(purchase_amount * 100))
            advice = advisor.advise_on_purchase(
                business_id=business_id,
                purchase_amount_minor=purchase_amount_minor,
                purchase_label=purchase_label,
                expected_roi_pct=expected_roi,
            )

        # Verdict display
        verdict_color = {
            "GO": "green",
            "WAIT": "orange",
            "NO": "red",
        }.get(advice.verdict, "grey")

        st.markdown(f"### Verdict: :{verdict_color}[{advice.verdict}]")
        st.caption(f"Confidence: {advice.confidence}%")

        # Reasons
        if advice.reasons:
            st.markdown("##### Why?")
            for reason in advice.reasons:
                st.markdown(f"- {reason}")

        # Impact analysis
        st.divider()
        st.markdown("##### Impact Analysis")

        icol1, icol2, icol3 = st.columns(3)
        with icol1:
            st.metric(
                "Balance Before",
                f"KES {advice.balance_before_minor/100:,.0f}",
            )
        with icol2:
            delta = advice.balance_after_minor - advice.balance_before_minor
            st.metric(
                "Balance After",
                f"KES {advice.balance_after_minor/100:,.0f}",
                delta=f"KES {delta/100:,.0f}",
            )
        with icol3:
            st.metric(
                "Days of Cash After",
                f"{advice.days_of_cash_after:.1f}",
            )

        icol4, icol5 = st.columns(2)
        with icol4:
            st.metric(
                "Safety Buffer",
                f"KES {advice.buffer_minor/100:,.0f}",
            )
        with icol5:
            st.metric(
                "Upcoming Obligations (14d)",
                f"KES {advice.upcoming_obligations_minor/100:,.0f}",
            )

        if advice.shortfall_risk_bp > 0:
            st.warning(
                f"Shortfall risk: {advice.shortfall_risk_bp / 100:.1f}% probability "
                f"of falling below buffer within 14 days."
            )

        # Suggested actions
        if advice.suggested_actions:
            st.markdown("##### Suggested Actions")
            for action in advice.suggested_actions:
                st.markdown(f"- {action}")

# =========================================================================
# Tab 2: Cash Allocation
# =========================================================================
with tab_allocate:
    st.subheader("How should I allocate my cash?")

    use_custom = st.checkbox("Use custom available cash amount", key="use_custom_cash")
    custom_cash = None
    if use_custom:
        custom_cash_kes = st.number_input(
            "Available cash (KES)",
            min_value=0,
            value=50000,
            step=1000,
            key="custom_cash_kes",
        )
        custom_cash = int(round(custom_cash_kes * 100))

    if st.button("Get Allocation Advice", type="primary", width="stretch"):
        with st.spinner("Computing allocation..."):
            result = advisor.allocate_spending(
                business_id=business_id,
                available_cash_minor=custom_cash,
            )

        # Summary metrics
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Available Cash", f"KES {result.available_cash_minor/100:,.0f}")
        with c2:
            st.metric("Obligations Due (30d)", f"KES {result.total_obligations_minor/100:,.0f}")
        with c3:
            delta_color = "inverse" if result.surplus_minor < 0 else "normal"
            st.metric(
                "Surplus / Deficit",
                f"KES {result.surplus_minor/100:,.0f}",
                delta_color=delta_color,
            )

        # Warnings
        if result.warnings:
            for w in result.warnings:
                st.warning(w)

        # Allocation table
        if result.allocations:
            st.markdown("##### Priority Allocation")

            alloc_data = []
            for a in result.allocations:
                alloc_data.append({
                    "Priority": a["priority"],
                    "Category": a["label"],
                    "Amount (KES)": a["amount_minor"] / 100,
                    "Rationale": a["rationale"],
                })

            alloc_df = pd.DataFrame(alloc_data)
            st.dataframe(
                alloc_df.style.format({"Amount (KES)": "KES {:,.0f}"}),
                width="stretch",
                hide_index=True,
            )

            st.altair_chart(chart_allocation(result.allocations), width="stretch")

# =========================================================================
# Tab 3: Forecast
# =========================================================================
with tab_forecast:
    st.subheader("14-day cashflow forecast")

    horizon = st.slider(
        "Forecast horizon (days)",
        min_value=7,
        max_value=30,
        value=14,
        step=1,
        key="forecast_horizon",
    )

    if st.button("Generate Forecast", type="primary", width="stretch"):
        with st.spinner("Running forecast..."):
            summary = advisor.get_forecast_summary(business_id, horizon_days=horizon)

        st.markdown(f"**As of:** {summary['as_of_date']}")

        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            st.metric(
                "Opening Balance",
                f"KES {summary['opening_balance']/100:,.0f}",
            )
        with fc2:
            st.metric(
                "Lowest (P10)",
                f"KES {summary['lowest_p10']/100:,.0f}",
                help="Worst-case balance at 10th percentile",
            )
        with fc3:
            st.metric(
                "Final (P50)",
                f"KES {summary['final_p50']/100:,.0f}",
                help="Median ending balance",
            )
        with fc4:
            st.metric(
                "Final (P10)",
                f"KES {summary['final_p10']/100:,.0f}",
                help="Worst-case ending balance",
            )

        st.caption(
            f"Buffer target: KES {summary['buffer_minor']/100:,.0f} | "
            f"Days below buffer: {summary['shortfall_days']}"
        )

        # Forecast chart
        if summary["points"]:
            st.caption("Shaded band: 8 in 10 simulated futures land inside it. Blue line: expected balance. "
                       "Yellow line: a bad week. Red dashed line: your safety buffer; red diamonds mark risky days.")
            st.altair_chart(chart_forecast_confidence(summary["points"], buffer_kes=summary["buffer_minor"] / 100),
                            width="stretch")

        # Shortfall alerts
        if summary["shortfalls"]:
            st.divider()
            st.markdown("##### Shortfall Alerts")

            for sf in summary["shortfalls"]:
                prob_pct = sf["probability_bp"] / 100
                st.error(
                    f"**{sf['date']}**: KES {sf['gap_minor']/100:,.0f} below buffer "
                    f"(~{prob_pct:.1f}% probability)"
                )
                for action in sf["actions"]:
                    st.markdown(f"- {action}")
        else:
            st.success("No shortfall risks detected within the forecast horizon.")
