"""Page 3: Cashflow forecast, Monte Carlo simulation & shortfall early warning."""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd

from core.dates import parse_local_dates
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth
from auth.middleware import get_business_id

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

    default_buffer_minor = Config.SAFETY_BUFFER_MINOR
    if get_business_id():
        from core.owner_settings import load_settings
        default_buffer_minor = load_settings(Config.DB_PATH, get_business_id()).safety_buffer_minor
    buffer_input = col_c2.number_input(
        "Safety buffer target (KES)",
        min_value=500.0,
        value=max(500.0, float(default_buffer_minor / 100.0)),
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
daily_grouped["weekday"] = parse_local_dates(daily_grouped["local_date"]).dt.dayofweek

daily_flows = daily_grouped.groupby(["local_date", "weekday"]).agg(
    inflow_minor=("amount_minor", lambda x: int(x[daily_grouped.loc[x.index, "direction"] == "in"].sum())),
    outflow_minor=("amount_minor", lambda x: int(x[daily_grouped.loc[x.index, "direction"] == "out"].sum())),
).reset_index()

# Scheduled obligations: the owner's saved recurring expenses (overdue ones
# land on day 1, since they are still unpaid) plus the stress-test expense.
due_date_str = (datetime.now() + timedelta(days=obl_day)).strftime("%Y-%m-%d")
obligations = []
if get_business_id():
    from core.expense_tracker import RecurringExpenseManager
    _today = datetime.now().date()
    obligations += RecurringExpenseManager().obligations_between(
        get_business_id(), _today + timedelta(days=1), _today + timedelta(days=horizon_days))
if obl_amount > 0:
    obligations.append({
        "due_date": due_date_str,
        "amount_minor": int(round(obl_amount * 100)),
        "label": obl_label,
    })

# Run forecaster
forecaster = BalanceForecaster(seed=42)
forecast_res = forecaster.forecast(
    daily_flows=daily_flows,
    obligations=obligations,
    opening_balance=int(round(current_bal_input * 100)),
    buffer_minor=int(round(buffer_input * 100)),
    horizon_days=horizon_days,
    n_paths=1000,
)

shortfalls = forecaster.detect_shortfalls(forecast_res)

saved = [o for o in obligations if o.get("source") == "recurring_expense"]
if saved:
    with st.expander(f"Included: {len(saved)} recurring payment(s) from your expenses, "
                     f"KES {sum(o['amount_minor'] for o in saved) / 100:,.0f}", icon=":material/event_repeat:"):
        st.dataframe(pd.DataFrame([{
            "Forecast date": o["due_date"], "Due date": o["original_due_date"], "Expense": o["label"],
            "Amount (KES)": o["amount_minor"] / 100,
            "Status": f"Overdue {o['days_overdue']}d" if o["days_overdue"] else "Scheduled",
        } for o in saved]), hide_index=True, width="stretch")

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
st.subheader("Where your balance could go", icon=":material/analytics:")
st.caption(
    "Duka replays your past days 1,000 times to see the range of balances you might have. "
    "**Shaded band:** 8 in 10 of those futures land inside it. **Blue line:** the expected balance. "
    "**Yellow line:** a bad week (only 1 in 10 futures end lower). **Red dashed line:** your safety buffer; "
    "**red diamonds** mark days the bad-week balance falls under it. **White triangles** are bills due. "
    "Hover anywhere for that day's numbers."
)

st.altair_chart(chart_forecast_confidence(forecast_res.points, buffer_kes=buffer_input, bills=obligations),
                width="stretch")

# ---- SHORTFALL ALERTS & ADVISORY ----
# The forecaster suggests actions per risky day, each with that day's gap.
# Show each kind of action once, sized for the worst day and due before the
# first risky day, instead of one near-identical line per day.
ACTION_KINDS = [
    ("Delay non-essential spending", "Hold back spending", ":material/pause_circle:",
     "Push purchases that can wait until after {worst:%d %b}. That keeps about KES {gap:,.0f} in the till.",
     "app_pages/4_Expenses_Setup.py", "See upcoming bills"),
    ("Reduce personal withdrawals", "Take less out for personal use", ":material/person_remove:",
     "Draw about KES {gap:,.0f} less for personal and family needs before {first:%d %b}.",
     "app_pages/6_Spending_Advisor.py", "Plan spending"),
    ("Consider a short-term overdraft", "Line up short-term credit", ":material/account_balance:",
     "Have about KES {gap:,.0f} of overdraft ready by {first:%d %b}, and compare the true cost first.",
     "app_pages/3_Financing.py", "Compare options"),
    ("Chase outstanding customer credit", "Collect what customers owe", ":material/request_quote:",
     "Follow up overdue customer payments now, so the money is in before {first:%d %b}.",
     "app_pages/5_Working_Capital.py", "See who owes you"),
]

if shortfalls:
    first = min(shortfalls, key=lambda s: s.day_offset)
    worst = max(shortfalls, key=lambda s: s.gap_minor)
    first_day = datetime.strptime(first.date[:10], "%Y-%m-%d")
    worst_day = datetime.strptime(worst.date[:10], "%Y-%m-%d")

    when = ("today" if first.day_offset == 0 else
            f"in {first.day_offset} day{'s' if first.day_offset != 1 else ''}")
    # The forecast includes today (day 0), so a 30-day horizon has 31 days.
    st.error(
        f"In a bad week your cash could drop below your KES {buffer_input:,.0f} safety buffer on "
        f"**{len(shortfalls)} of {len(forecast_res.points)} days** (today to "
        f"{datetime.strptime(forecast_res.points[-1]['date'][:10], '%Y-%m-%d'):%d %b}), starting "
        f"**{first_day:%a %d %b}** ({when}). The worst day is "
        f"**{worst_day:%a %d %b}**, about **KES {worst.gap_minor / 100:,.0f}** short.",
        title="Cash may run short",
        icon=":material/error:",
    )

    st.subheader("What to do", icon=":material/lightbulb:", anchor=False)
    plan = []
    for prefix, title, icon, body, target, link_label in ACTION_KINDS:
        days_with_it = [s for s in shortfalls if any(a.startswith(prefix) for a in s.suggested_actions)]
        if days_with_it:
            gap = max(s.gap_minor for s in days_with_it) / 100
            plan.append((title, icon, body.format(gap=gap, first=first_day, worst=worst_day), target, link_label))

    for start_i in range(0, len(plan), 2):
        cols = st.columns(2)
        for col, (n, (title, icon, body, target, link_label)) in zip(cols, enumerate(plan[start_i:start_i + 2],
                                                                                      start=start_i + 1)):
            with col.container(border=True, height="stretch"):
                st.markdown(f"**{n}. {title}**")
                st.caption(body)
                st.page_link(target, label=link_label, icon=icon)

    with st.expander(f"Risky days ({len(shortfalls)})", icon=":material/event_busy:"):
        st.dataframe(
            pd.DataFrame([{
                "Date": pd.Timestamp(s.date[:10]),
                "In": s.day_offset,
                "Short by (KES)": s.gap_minor / 100,
                "Chance": "50% or more" if s.probability_bp >= 5000 else "10% or more",
            } for s in sorted(shortfalls, key=lambda s: s.day_offset)]),
            hide_index=True, width="stretch",
            column_config={
                "Date": st.column_config.DateColumn(format="ddd D MMM"),
                "In": st.column_config.NumberColumn(format="%d days", help="Days from today"),
                "Short by (KES)": st.column_config.NumberColumn(
                    format="accounting", help="How far the conservative (P10) balance falls below your buffer"),
                "Chance": st.column_config.TextColumn(
                    help="10% or more: only the bad-week (P10) path dips. 50% or more: even the expected path dips."),
            },
        )
else:
    st.success(
        f"Your cash stays above your KES {buffer_input:,.0f} safety buffer for all {horizon_days} days, "
        "even in a bad week.",
        title="Safe runway",
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
