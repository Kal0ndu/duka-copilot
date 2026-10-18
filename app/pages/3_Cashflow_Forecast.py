"""Page 3: Cashflow forecast, Monte Carlo simulation & shortfall early warning."""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.analytics import BusinessAnalytics
from core.forecaster import BalanceForecaster
from core.charts import chart_forecast_confidence
from core.config import Config
from app.sample_loader import load_sample_business, MOCK_PROFILES
from app.session_helpers import SessionManager, render_data_info_banner

st.set_page_config(page_title="Cashflow Forecast — Duka", page_icon=":material/trending_up:", layout="wide")
# ---- Authentication Gate ----
require_auth()


# Initialize session and check for data
SessionManager.init_session()
transactions = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if not transactions:
    st.warning("No statement currently loaded.", icon=":material/warning:")
    st.info("Load a sample business profile to run predictive cash forecasts:", icon=":material/info:")
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

analytics = BusinessAnalytics(transactions)
df_clean = analytics.to_dataframe()
biz_name = profile.get("name", "Your Business") if profile else "Your Business"

st.title("Cashflow forecast & liquidity runway", icon=":material/trending_up:")
st.caption(f"Monte Carlo simulation (1,000 paths) with weekday seasonality patterns for {biz_name}.")

# ---- FORECAST CONTROLS IN SIDEBAR / EXPANDER ----
with st.expander("Forecast settings & stress-test simulation", icon=":material/tune:", expanded=True):
    col_c1, col_c2, col_c3 = st.columns(3)

    # Detect current balance
    default_balance = 15000.0
    if "balance" in df_clean.columns and df_clean["balance"].dropna().any():
        default_balance = float(df_clean["balance"].dropna().iloc[-1])
    elif "balance_after_minor" in df_clean.columns and df_clean["balance_after_minor"].dropna().any():
        default_balance = float(df_clean["balance_after_minor"].dropna().iloc[-1]) / 100.0

    current_bal_input = col_c1.number_input(
        "Opening cash balance (KES)",
        min_value=0.0,
        value=max(1000.0, default_balance),
        step=1000.0,
        help="Current cash in your Till / M-Pesa account."
    )

    buffer_input = col_c2.number_input(
        "Safety buffer target (KES)",
        min_value=500.0,
        value=float(Config.SAFETY_BUFFER_MINOR / 100.0),
        step=1000.0,
        help="Minimum liquid cash floor you want to protect at all times."
    )

    horizon_days = col_c3.slider(
        "Forecast horizon",
        min_value=7,
        max_value=60,
        value=30,
        step=7,
        help="Number of days forward to project."
    )

    # Scenario Simulation: Scheduled Obligations
    st.markdown("##### Stress-test: planned large expenses")
    sim_col1, sim_col2, sim_col3 = st.columns(3)
    obl_label = sim_col1.text_input("Upcoming expense name", value="Monthly Rent & Utilities")
    obl_amount = sim_col2.number_input("Amount (KES)", min_value=0, value=12000, step=1000)
    obl_day = sim_col3.slider("Due in days from today", min_value=1, max_value=horizon_days, value=min(10, horizon_days))

# Prepare daily flows DataFrame for forecaster
daily_grouped = df_clean.copy()
daily_grouped["weekday"] = pd.to_datetime(daily_grouped["local_date"], format='mixed', dayfirst=True).dt.dayofweek

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
k1.metric("Current balance", f"KES {current_bal_input:,.0f}")
k2.metric(f"Expected day {horizon_days} (P50)", f"KES {p50_end:,.0f}", delta=f"{p50_end - current_bal_input:,.0f}")
k3.metric("Worst-case floor (P10)", f"KES {min_p10:,.0f}", delta="Conservative" if min_p10 >= buffer_input else "Breaches buffer", delta_color="normal" if min_p10 >= buffer_input else "inverse")
k4.metric("Shortfall risk days", len(shortfalls), help="Days where conservative forecast dips below safety buffer.")

# ---- ALTAIR FAN CHART ----
st.subheader("1,000-path Monte Carlo simulation", icon=":material/analytics:")
st.caption(
    "Blue shaded band represents 80% confidence interval (P10 to P90). "
    "Solid line is median expected cash. Red dashed line is your required safety buffer."
)

st.altair_chart(chart_forecast_confidence(forecast_res.points, buffer_kes=buffer_input), width="stretch")

# ---- SHORTFALL ALERTS & ADVISORY ----
if shortfalls:
    st.error(
        f"Liquidity warning: detected {len(shortfalls)} potential cash shortfall dates below your KES {buffer_input:,.0f} safety buffer.",
        icon=":material/error:",
    )

    # Unique dates with breaches
    alert_rows = []
    for s in shortfalls:
        alert_rows.append({
            "Date": s.date,
            "Timeline": f"In {s.day_offset} days",
            "Cash gap below buffer": f"KES {s.gap_minor / 100:,.0f}",
            "Breach probability": f"{s.probability_bp / 100:.0f}%",
            "Recommended mitigations": "; ".join(s.suggested_actions[:2]),
        })
    st.dataframe(alert_rows, width="stretch")

    st.subheader("AI CFO actionable recommendations", icon=":material/lightbulb:")
    unique_actions = set()
    for s in shortfalls:
        for a in s.suggested_actions:
            unique_actions.add(a)
    for act in sorted(unique_actions):
        st.markdown(f"- :material/notifications: {act}")
else:
    st.success(
        f"Safe runway confirmed: your projected cash balance stays safely above your "
        f"KES {buffer_input:,.0f} buffer for the entire {horizon_days}-day horizon.",
        icon=":material/check_circle:",
    )

# ---- DETAILED DAILY PROJECTIONS TABLE ----
with st.expander("View full daily forecast projections table", icon=":material/description:", expanded=False):
    daily_rows = []
    for p in forecast_res.points:
        daily_rows.append({
            "Day offset": f"Day {p['day_offset']}",
            "Date": p["date"],
            "Conservative (P10) KES": f"{p['p10'] / 100:,.0f}",
            "Expected (P50) KES": f"{p['p50'] / 100:,.0f}",
            "Optimistic (P90) KES": f"{p['p90'] / 100:,.0f}",
            "Buffer status": "Safe" if (p['p10'] / 100) >= buffer_input else "Buffer breach risk",
        })
    st.dataframe(daily_rows, width="stretch")
