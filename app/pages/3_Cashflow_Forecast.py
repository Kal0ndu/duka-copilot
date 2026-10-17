"""Page 3: Cashflow Forecast, Monte Carlo Simulation & Shortfall Early Warning."""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.analytics import BusinessAnalytics
from core.forecaster import BalanceForecaster
from core.charts import chart_forecast_confidence
from core.config import Config
from app.sample_loader import load_sample_business, MOCK_PROFILES

st.set_page_config(page_title="Cashflow Forecast — Duka", page_icon="📈", layout="wide")

transactions = st.session_state.get("parsed_transactions")
profile = st.session_state.get("business_profile")

if not transactions:
    st.warning("⚠️ No statement currently loaded.")
    st.info("Load a sample business profile to run predictive cash forecasts:")
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

analytics = BusinessAnalytics(transactions)
df_clean = analytics.to_dataframe()
biz_name = profile.get("name", "Your Business") if profile else "Your Business"

st.title("📈 Cashflow Forecast & Liquidity Runway")
st.caption(f"Monte Carlo simulation (1,000 paths) with weekday seasonality patterns for **{biz_name}**.")

# ---- FORECAST CONTROLS IN SIDEBAR / EXPANDER ----
with st.expander("⚙️ Forecast Settings & Stress-Test Simulation", expanded=True):
    col_c1, col_c2, col_c3 = st.columns(3)

    # Detect current balance
    default_balance = 15000.0
    if "balance" in df_clean.columns and df_clean["balance"].dropna().any():
        default_balance = float(df_clean["balance"].dropna().iloc[-1])
    elif "balance_after_minor" in df_clean.columns and df_clean["balance_after_minor"].dropna().any():
        default_balance = float(df_clean["balance_after_minor"].dropna().iloc[-1]) / 100.0

    current_bal_input = col_c1.number_input(
        "Opening Cash Balance (KES)",
        min_value=0.0,
        value=max(1000.0, default_balance),
        step=1000.0,
        help="Current cash in your Till / M-Pesa account."
    )

    buffer_input = col_c2.number_input(
        "Safety Buffer Target (KES)",
        min_value=500.0,
        value=float(Config.SAFETY_BUFFER_MINOR / 100.0),
        step=1000.0,
        help="Minimum liquid cash floor you want to protect at all times."
    )

    horizon_days = col_c3.slider(
        "Forecast Horizon",
        min_value=7,
        max_value=60,
        value=30,
        step=7,
        help="Number of days forward to project."
    )

    # Scenario Simulation: Scheduled Obligations
    st.markdown("##### 📌 Stress-Test: Planned Large Expenses")
    sim_col1, sim_col2, sim_col3 = st.columns(3)
    obl_label = sim_col1.text_input("Upcoming Expense Name", value="Monthly Rent & Utilities")
    obl_amount = sim_col2.number_input("Amount (KES)", min_value=0, value=12000, step=1000)
    obl_day = sim_col3.slider("Due in Days from Today", min_value=1, max_value=horizon_days, value=min(10, horizon_days))

# Prepare daily flows DataFrame for forecaster
daily_grouped = df_clean.copy()
daily_grouped["weekday"] = pd.to_datetime(daily_grouped["local_date"]).dt.dayofweek

daily_flows = daily_grouped.groupby(["local_date", "weekday"]).agg(
    inflow_minor=("amount_minor", lambda x: int(x[daily_grouped.loc[x.index, "direction"] == "in"].sum())),
    outflow_minor=("amount_minor", lambda x: int(x[daily_grouped.loc[x.index, "direction"] == "out"].sum())),
).reset_index()

# Setup scheduled obligation
due_date_str = (datetime.now() + timedelta(days=obl_day)).strftime("%Y-%m-%d")
obligations = []
if obl_amount > 0:
    obligations.append({
        "due_date": due_date_str,
        "amount_minor": int(obl_amount * 100),
        "label": obl_label,
    })

# Run forecaster
forecaster = BalanceForecaster(seed=42)
forecast_res = forecaster.forecast(
    daily_flows=daily_flows,
    obligations=obligations,
    opening_balance=int(current_bal_input * 100),
    buffer_minor=int(buffer_input * 100),
    horizon_days=horizon_days,
    n_paths=1000,
)

shortfalls = forecaster.detect_shortfalls(forecast_res)

# ---- SUMMARY KPIS ----
p50_end = forecast_res.points[-1]["p50"] / 100.0
p10_end = forecast_res.points[-1]["p10"] / 100.0
min_p10 = min(p["p10"] for p in forecast_res.points) / 100.0

k1, k2, k3, k4 = st.columns(4)
k1.metric("Current Balance", f"KES {current_bal_input:,.0f}")
k2.metric(f"Expected Day {horizon_days} (P50)", f"KES {p50_end:,.0f}", delta=f"{p50_end - current_bal_input:,.0f}")
k3.metric("Worst-Case Floor (P10)", f"KES {min_p10:,.0f}", delta="Conservative" if min_p10 >= buffer_input else "Breaches Buffer", delta_color="normal" if min_p10 >= buffer_input else "inverse")
k4.metric("Shortfall Risk Days", len(shortfalls), help="Days where conservative forecast dips below safety buffer.")

st.divider()

# ---- ALTAIR FAN CHART ----
st.subheader("📊 1,000-Path Monte Carlo Simulation")
st.caption(
    "Blue shaded band represents 80% confidence interval (P10 to P90). "
    "Solid line is median expected cash. Red dashed line is your required safety buffer."
)

st.altair_chart(chart_forecast_confidence(forecast_res.points, buffer_kes=buffer_input), use_container_width=True)

# ---- SHORTFALL ALERTS & ADVISORY ----
if shortfalls:
    st.error(f"⚠️ **Liquidity Warning:** Detected **{len(shortfalls)}** potential cash shortfall dates below your KES {buffer_input:,.0f} safety buffer!")

    # Unique dates with breaches
    alert_rows = []
    for s in shortfalls:
        alert_rows.append({
            "Date": s.date,
            "Timeline": f"In {s.day_offset} days",
            "Cash Gap Below Buffer": f"KES {s.gap_minor / 100:,.0f}",
            "Breach Probability": f"{s.probability_bp / 100:.0f}%",
            "Recommended Mitigations": "; ".join(s.suggested_actions[:2]),
        })
    st.dataframe(alert_rows, use_container_width=True)

    st.markdown("#### 💡 AI CFO Actionable Recommendations:")
    unique_actions = set()
    for s in shortfalls:
        for a in s.suggested_actions:
            unique_actions.add(a)
    for act in sorted(unique_actions):
        st.markdown(f"- 🔔 **{act}**")
else:
    st.success(
        f"✅ **Safe Runway Confirmed:** Your projected cash balance stays safely above your "
        f"KES {buffer_input:,.0f} buffer for the entire {horizon_days}-day horizon."
    )

# ---- DETAILED DAILY PROJECTIONS TABLE ----
with st.expander("📋 View Full Daily Forecast Projections Table", expanded=False):
    daily_rows = []
    for p in forecast_res.points:
        daily_rows.append({
            "Day Offset": f"Day {p['day_offset']}",
            "Date": p["date"],
            "Conservative (P10) KES": f"{p['p10'] / 100:,.0f}",
            "Expected (P50) KES": f"{p['p50'] / 100:,.0f}",
            "Optimistic (P90) KES": f"{p['p90'] / 100:,.0f}",
            "Buffer Status": "✅ Safe" if (p['p10'] / 100) >= buffer_input else "⚠️ Buffer Breach Risk",
        })
    st.dataframe(daily_rows, use_container_width=True)
