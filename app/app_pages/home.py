"""Home: today's numbers, what needs attention, and the Duka Copilot assistant chat."""
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.orchestrator import Orchestrator
from app.auth_ui import require_auth
from app.sample_loader import MOCK_PROFILES, load_sample_business
from app.session_helpers import SessionManager
from auth.middleware import get_business_id, get_user_id, load_user_context
from core.config import Config

require_auth()
load_user_context()  # preload business context into st.session_state

# ---- session init ----
if "orch" not in st.session_state:
    st.session_state.orch = Orchestrator(Config)
if "messages" not in st.session_state:
    st.session_state.messages = []

business_id = get_business_id()
profile = SessionManager.get_profile() or {}
transactions = SessionManager.get_transactions() or []

SUGGESTIONS = {
    ":blue[:material/insights:] How is my business doing?": "How is my business doing this month?",
    ":orange[:material/trending_up:] Will I run short of cash?": "Will I run short of cash in the next 2 weeks?",
    ":red[:material/receipt_long:] Bills due this week": "Which bills are due this week?",
    ":green[:material/groups:] My top customers": "Who are my top customers?",
    ":violet[:material/savings:] Can I afford KES 20,000?": "Can I afford to spend KES 20,000 on stock this week?",
}


# ---- sidebar: assistant settings and demo data ----
with st.sidebar:
    with st.expander("Assistant settings", icon=":material/tune:"):
        swahili = st.toggle("Reply in Kiswahili", key="ui_swahili",
                            help="Without this, Duka Copilot replies in the language you write in.")
        st.session_state.orch.force_language = "sw" if swahili else None
        st.session_state.orch.offline = st.toggle(
            "Offline mode", key="ui_offline",
            help="Answer with the built-in helper from your own figures, without calling the AI service.",
        )
        st.caption(f":material/smart_toy: {Config.MODEL_NAME if Config.LLM_API_KEY else 'Offline helper (no API key)'}"
                   f"  \n:material/shield: Payments sandbox {'on (fail-closed)' if Config.SANDBOX_ONLY else 'off — live'}")
        if st.button(":material/delete_sweep: Clear chat", width="stretch", disabled=not st.session_state.messages):
            st.session_state.orch.reset()
            st.session_state.messages = []
            st.rerun()

    with st.expander("Try a demo business", icon=":material/science:"):
        st.caption("Explore Duka Copilot with sample data. Your own statements stay saved.")
        demo = st.segmented_control(
            "Demo business", list(MOCK_PROFILES), key="ui_demo", label_visibility="collapsed",
            format_func=lambda k: MOCK_PROFILES[k]["name"].split()[0],
        )
        if demo and profile.get("name") != MOCK_PROFILES[demo]["name"]:
            SessionManager.set_transactions(load_sample_business(demo), MOCK_PROFILES[demo])
            st.rerun()
        if profile and profile.get("source") != "ledger" and business_id:
            if st.button(":material/restore: Back to my data", width="stretch"):
                st.session_state.pop("ui_demo", None)
                SessionManager.use_ledger()
                st.rerun()


# ---- greeting ----
auth_user = st.session_state.get("auth_user") or {}
first_name = (auth_user.get("display_name") or "there").split(" ")[0].split("@")[0]
st.title(f"Habari, {first_name.title()}", anchor=False)
if profile:
    st.caption(f"{profile.get('name', 'Your business')} · {profile.get('sector', 'SME')}"
               + (" · demo data" if profile.get("source") != "ledger" else ""))
else:
    st.caption("Upload an M-Pesa statement to see your numbers here.")


# ---- KPIs: last 30 days of data vs the 30 before ----
def _kpis(records: list) -> dict | None:
    if not records:
        return None
    df = pd.DataFrame(records)
    # Ledger rows carry local_date; demo and unsaved-upload rows carry date.
    date_col = "local_date" if "local_date" in df.columns else "date"
    if date_col not in df.columns or "amount_minor" not in df.columns or "direction" not in df.columns:
        return None
    df["day"] = pd.to_datetime(df[date_col].astype(str).str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
    df = df.dropna(subset=["day"])
    if df.empty:
        return None
    end = df["day"].max().normalize()
    cur = df[df["day"] > end - pd.Timedelta(days=30)]
    prev = df[(df["day"] <= end - pd.Timedelta(days=30)) & (df["day"] > end - pd.Timedelta(days=60))]

    def totals(frame):
        income = frame[frame["direction"] == "in"]
        if "category_kind" in frame.columns:   # loans and own transfers are not sales
            income = income[income["category_kind"].fillna("income") == "income"]
        return {"in": income["amount_minor"].sum() / 100,
                "out": frame[frame["direction"] == "out"]["amount_minor"].sum() / 100}

    days = pd.date_range(end - pd.Timedelta(days=29), end)
    daily = cur.assign(signed=cur["amount_minor"].where(cur["direction"] == "in", -cur["amount_minor"]) / 100)
    daily_in = cur[cur["direction"] == "in"].groupby("day")["amount_minor"].sum().reindex(days, fill_value=0) / 100
    daily_out = cur[cur["direction"] == "out"].groupby("day")["amount_minor"].sum().reindex(days, fill_value=0) / 100
    daily_net = daily.groupby("day")["signed"].sum().reindex(days, fill_value=0)
    return {"end": end.date(), "cur": totals(cur), "prev": totals(prev) if not prev.empty else None,
            "daily_in": daily_in.tolist(), "daily_out": daily_out.tolist(), "daily_net": daily_net.cumsum().tolist()}


kpi = _kpis(transactions)
review_count = 0
overdue_bills = []
if business_id:
    with sqlite3.connect(Config.DB_PATH) as conn:
        review_count = conn.execute(
            "SELECT COUNT(*) FROM transaction_ledger WHERE business_id = ? AND needs_review = 1 AND voided = 0",
            (business_id,)).fetchone()[0]
    try:
        from core.business_setup import BusinessSetup
        overdue_bills = [e for e in BusinessSetup().get_recurring_expenses(business_id) if e["due_state"] == "overdue"]
    except Exception:
        overdue_bills = []

if kpi:
    c, p = kpi["cur"], kpi["prev"]

    def _delta(now: float, before: float | None):
        return None if before is None else f"{now - before:+,.0f} vs previous 30 days"

    with st.container(horizontal=True, gap="medium"):
        st.metric("Money in from sales", f"KES {c['in']:,.0f}", _delta(c["in"], p and p["in"]),
                  chart_data=kpi["daily_in"], chart_type="bar", border=True,
                  help="Sales income in the last 30 days of your data")
        st.metric("Money out", f"KES {c['out']:,.0f}", _delta(c["out"], p and p["out"]), delta_color="inverse",
                  chart_data=kpi["daily_out"], chart_type="bar", border=True,
                  help="Everything paid out in the last 30 days of your data")
        st.metric("Net cash flow", f"KES {c['in'] - c['out']:,.0f}",
                  _delta(c["in"] - c["out"], p and (p["in"] - p["out"])),
                  chart_data=kpi["daily_net"], chart_type="area", border=True,
                  help="Sales income minus money out; the chart is the running total")
        st.metric("To review", f"{review_count:,}", "transactions" if review_count else None, delta_color="off",
                  border=True, help="Transactions Duka Copilot wasn't sure how to categorise")
    st.caption(f":material/calendar_month: 30 days to {kpi['end']:%d %b %Y}")


# ---- needs your attention ----
def _shortfall_message(bid: int, swahili: bool):
    """The SMS the owner would get if the 14-day forecast dips below the buffer."""
    from types import SimpleNamespace
    from core.forecaster import forecast_balance
    with sqlite3.connect(Config.DB_PATH) as conn:   # recompute after uploads / teach-once fixes
        version = conn.execute("SELECT COUNT(*), COALESCE(MAX(txn_id), 0) FROM transaction_ledger "
                               "WHERE business_id = ?", (bid,)).fetchone()
    key = f"_sms_alert_{bid}_{version[0]}_{version[1]}"
    if key not in st.session_state:
        st.session_state[key] = forecast_balance(SimpleNamespace(horizon_days=14), bid, Config.DB_PATH)
    f = st.session_state[key]
    if "error" in f:
        return None
    below = [pt for pt in f["points"] if pt["low_kes"] < f["buffer_kes"]]
    if not below:
        return None
    first = date.fromisoformat(below[0]["date"]).strftime("%a %d %b")
    need = f["buffer_kes"] - f["lowest_low_kes"]
    if swahili:
        return (f"Duka Copilot: Tahadhari! Pesa zako zinaweza kushuka chini ya akiba ya KES {f['buffer_kes']:,.0f} "
                f"kuanzia {first}. Unaweza kuhitaji takriban KES {need:,.0f}. Fungua Duka Copilot kuona njia za "
                f"kujiandaa. Duka Copilot haitakuuliza PIN kwa SMS.")
    return (f"Duka Copilot: Heads up! Your money may drop below your KES {f['buffer_kes']:,.0f} safety buffer from "
            f"{first}. You may need about KES {need:,.0f}. Open Duka Copilot to see your options. "
            f"Duka Copilot never asks for your PIN by SMS.")


attention = []
if business_id:
    sms = _shortfall_message(business_id, st.session_state.get("ui_swahili", False))
    if sms:
        attention.append(("warning", "Cash may run short in the next 14 days", sms,
                          "app_pages/3_Cashflow_Forecast.py", "See the forecast"))
    if overdue_bills:
        total = sum(e["instalment_minor"] for e in overdue_bills) / 100
        names = ", ".join(e["description"] for e in overdue_bills[:3]) + ("…" if len(overdue_bills) > 3 else "")
        attention.append(("error", f"{len(overdue_bills)} bill(s) overdue · KES {total:,.0f}", names,
                          "app_pages/4_Expenses_Setup.py", "Mark as paid"))
    if review_count:
        attention.append(("info", f"{review_count:,} transaction(s) to check",
                          "Pick the right category once per payee and Duka Copilot remembers it.",
                          "app_pages/1_Upload_Statement.py", "Review payees"))
elif not profile:
    attention.append(("info", "Set up your business", "Register your business to save statements and get advice.",
                      "app_pages/0_Business_Setup.py", "Business setup"))

if attention:
    st.subheader("Needs your attention", anchor=False)
    cols = st.columns(len(attention))
    for col, (kind, title, body, target, action) in zip(cols, attention):
        with col:
            getattr(st, kind)(body, title=title, icon={"warning": ":material/warning:", "error": ":material/error:",
                                                       "info": ":material/info:"}[kind])
            st.page_link(target, label=action, icon=":material/arrow_forward:")

# ---- quick actions ----
with st.container(horizontal=True, gap="small"):
    st.page_link("app_pages/1_Upload_Statement.py", label="Upload statement", icon=":material/upload_file:")
    st.page_link("app_pages/8_POS_Dashboard.py", label="New sale", icon=":material/point_of_sale:")
    st.page_link("app_pages/9_Invoicing.py", label="New invoice", icon=":material/receipt_long:")
    st.page_link("app_pages/2_Analytics.py", label="Analytics", icon=":material/analytics:")
    st.page_link("app_pages/3_Cashflow_Forecast.py", label="Forecast", icon=":material/trending_up:")
    st.page_link("app_pages/4_Party_Intelligence.py", label="Customers", icon=":material/groups:")

st.space("small")


# ---- assistant chat ----
st.subheader("Ask Duka Copilot", anchor=False)
st.caption("Your AI CFO answers from your own books. It can't move money: payments always need your PIN.")

AVATARS = {"user": ":material/person:", "assistant": ":material/storefront:"}


def _tool_label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _render_checks(meta: dict) -> None:
    """Which tools the answer used and whether its numbers checked out."""
    tools = meta.get("tools_used") or []
    verification = meta.get("verification") or {}
    violations = verification.get("violations") or []
    with st.container(horizontal=True, gap="small"):
        for t in tools:
            st.badge(_tool_label(t), icon=":material/build:", color="gray")
        if verification:
            if violations:
                st.badge(f"{len(violations)} number(s) not found in your data", icon=":material/warning:",
                         color="orange")
            else:
                st.badge("Numbers checked", icon=":material/verified:", color="green")


for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
        st.markdown(msg["content"])
        if msg.get("meta"):
            _render_checks(msg["meta"])
            for w in msg["meta"].get("warnings") or []:
                st.warning(w, icon=":material/warning:")

prompt = st.chat_input("Ask about sales, cash, bills or customers…", submit_mode="disable")
if not st.session_state.messages:
    suggestions = st.empty()
    picked = suggestions.pills("Try asking", list(SUGGESTIONS), label_visibility="collapsed", key="ui_suggestion")
    if picked:
        prompt = SUGGESTIONS[picked]
    if prompt:
        suggestions.empty()

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=AVATARS["user"]):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        started = time.monotonic()
        with st.status(":shimmer[Reading your books]", type="compact") as status:
            result = st.session_state.orch.process(prompt, user_id=get_user_id(), business_id=business_id)
            tools = list(result.get("tool_results", {}).keys())
            for t in tools:
                with st.status(_tool_label(t), type="step", state="complete"):
                    st.caption("Ran on your own data, on this device.")
            seconds = time.monotonic() - started
            status.update(label=f"Checked {len(tools)} source(s) in {seconds:.1f}s" if tools
                          else f"Answered in {seconds:.1f}s", state="complete")

        response = result.get("response", "Sorry, I couldn't process that.")
        st.markdown(response)
        meta = {"verification": result.get("verification"), "warnings": result.get("output_warnings"),
                "tools_used": tools}
        _render_checks(meta)
        for w in meta["warnings"] or []:
            st.warning(w, icon=":material/warning:")

    st.session_state.messages.append({"role": "assistant", "content": response, "meta": meta})
