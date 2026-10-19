"""Duka — Streamlit application entry point."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Config
from agent.orchestrator import Orchestrator

from app.sample_loader import load_sample_business, MOCK_PROFILES
from app.auth_ui import require_auth_with_redirect, render_logout_button, check_auth, validate_and_refresh_session
from app.auth_theme import render_landing, render_authenticated_hero, inject_auth_theme
from auth.middleware import (
    load_user_context, get_user_context,
    invalidate_user_context_on_page,
    get_user_id, get_business_id,
)

st.set_page_config(
    page_title="Duka — Micro-Business CFO",
    page_icon=":material/storefront:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Check if user is authenticated
if not validate_and_refresh_session():
    # Show landing page for unauthenticated users
    inject_auth_theme()
    render_landing()
    st.stop()

# ---- user context ----

load_user_context()  # preload business context into st.session_state


# ---- session init ----

if "orch" not in st.session_state:
    st.session_state.orch = Orchestrator(Config)
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---- sidebar ----

with st.sidebar:
    st.logo("https://img.icons8.com/color/96/shop.png", size="medium")
    st.title("Duka Copilot", icon=":material/storefront:")
    st.caption("AI CFO & business intelligence for Kenyan SMEs")

    # Payments waiting for the owner's authorization
    if get_business_id():
        try:
            from core.standing_orders import StandingOrderService
            _due = [p for p in StandingOrderService().open_payments(get_business_id())
                    if p["status"] in ("pending", "notified", "failed")]
        except Exception:
            _due = []
        if _due:
            _urgent = sum(1 for p in _due if p["priority_band"] in ("critical", "high"))
            st.warning(
                f"{len(_due)} payment(s) to authorize" + (f", {_urgent} urgent" if _urgent else ""),
                icon=":material/notifications_active:",
            )
            st.page_link("pages/12_Standing_Orders.py", label="Review payments", icon=":material/event_repeat:")

    # Requests from the assistant waiting for the owner's PIN
    if get_business_id():
        try:
            from core.approvals import ApprovalService
            _waiting = ApprovalService().list_actions(get_business_id(), ["PENDING_APPROVAL"])
        except Exception:
            _waiting = []
        if _waiting:
            st.warning(f"{len(_waiting)} request(s) from your assistant need your PIN",
                       icon=":material/verified_user:")
            st.page_link("pages/13_Approvals.py", label="Review approvals", icon=":material/verified_user:")

    # Active Business Profile
    profile = st.session_state.get("business_profile")
    if profile:
        st.success(
            f"{profile.get('icon', ':material/storefront:')} {profile.get('name', 'Active Business')}",
            icon=":material/check_circle:",
        )
        st.caption(f"Sector: {profile.get('sector', 'SME')}")
    else:
        st.info(
            "No statement loaded yet. Pick a sample SME below or go to **Upload statement**.",
            icon=":material/info:",
        )

    # Quick Switcher
    st.markdown("##### Switch sample SME")
    col_sb1, col_sb2, col_sb3 = st.columns(3)
    if col_sb1.button(
        ":material/storefront: Grocery", width="stretch", help="Amina's Grocery"
    ):
        st.session_state["parsed_transactions"] = load_sample_business("amina_grocery")
        st.session_state["business_profile"] = MOCK_PROFILES["amina_grocery"]
        st.rerun()
    if col_sb2.button(
        ":material/directions_bike: Boda", width="stretch", help="Otieno Transport"
    ):
        st.session_state["parsed_transactions"] = load_sample_business("otieno_transport")
        st.session_state["business_profile"] = MOCK_PROFILES["otieno_transport"]
        st.rerun()
    if col_sb3.button(
        ":material/content_cut: Salon", width="stretch", help="Grace Salon"
    ):
        st.session_state["parsed_transactions"] = load_sample_business("grace_salon")
        st.session_state["business_profile"] = MOCK_PROFILES["grace_salon"]
        st.rerun()

    st.divider()

    st.metric("Security sandbox", "Active (fail-closed)" if Config.SANDBOX_ONLY else "Live")
    st.metric("AI core", Config.MODEL_NAME if Config.LLM_API_KEY else "Offline helper (no API key)")

    swahili = st.toggle("Kiswahili", key="ui_swahili",
                        help="Reply in Swahili. Without this, Duka replies in the language you write in.")
    st.session_state.orch.force_language = "sw" if swahili else None
    st.session_state.orch.offline = st.toggle(
        "Offline demo mode", key="ui_offline",
        help="Answer with the built-in helper from your own figures, without calling the AI service.",
    )

    st.divider()

    if st.button(":material/delete: Clear chat", width="stretch"):
        st.session_state.orch.reset()
        st.session_state.messages = []
        st.rerun()

    render_logout_button()
    st.caption("v0.3.0 — Nairobi, Kenya")

# ---- main chat & dashboard hub ----

inject_auth_theme()
auth_user = st.session_state.get("auth_user") or {}
render_authenticated_hero(
    display_name=auth_user.get("display_name", ""),
    business_profile=st.session_state.get("business_profile"),
)

# Feature Navigation Cards
st.subheader("Business intelligence suite", icon=":material/explore:")

f1, f2, f3, f4, f5 = st.columns(5)
with f1:
    with st.container(border=True):
        st.markdown("##### :material/analytics: [Analytics](Analytics)")
        st.caption("Revenue, COGS, OPEX, margins & personal mix ratio.")
with f2:
    with st.container(border=True):
        st.markdown("##### :material/trending_up: [Forecast](Cashflow_Forecast)")
        st.caption("1,000-path Monte Carlo runway & shortfall alerts.")
with f3:
    with st.container(border=True):
        st.markdown("##### :material/groups: [Customers](Party_Intelligence)")
        st.caption("Top buyers, concentration risk & churn radar.")
with f4:
    with st.container(border=True):
        st.markdown("##### :material/credit_card: [Credit book](Working_Capital)")
        st.caption("Receivables aging, payables & SMS reminders.")
with f5:
    with st.container(border=True):
        st.markdown("##### :material/account_balance: [Financing](Financing)")
        st.caption("Digital loans compared by true EAR% and cashfit.")

st.divider()

# ---- SMS-style shortfall alert: what the owner would get on their phone ----

def _sms_alert(business_id: int, swahili: bool):
    from types import SimpleNamespace
    from core.forecaster import forecast_balance
    import sqlite3
    with sqlite3.connect(Config.DB_PATH) as conn:   # recompute after uploads / teach-once fixes
        version = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(txn_id), 0) FROM transaction_ledger WHERE business_id = ?",
            (business_id,),
        ).fetchone()
    key = f"_sms_alert_{business_id}_{version[0]}_{version[1]}"
    if key not in st.session_state:
        st.session_state[key] = forecast_balance(SimpleNamespace(horizon_days=14), business_id, Config.DB_PATH)
    f = st.session_state[key]
    if "error" in f:
        return None
    below = [p for p in f["points"] if p["low_kes"] < f["buffer_kes"]]
    if not below:
        return None
    from datetime import date
    first = date.fromisoformat(below[0]["date"]).strftime("%a %d %b")
    need = f["buffer_kes"] - f["lowest_low_kes"]
    if swahili:
        return (f"Duka: Tahadhari! Pesa zako zinaweza kushuka chini ya akiba ya KES {f['buffer_kes']:,.0f} "
                f"kuanzia {first}. Unaweza kuhitaji takriban KES {need:,.0f}. Fungua Duka kuona njia za "
                f"kujiandaa. Duka haitakuuliza PIN kwa SMS.")
    return (f"Duka: Heads up! Your money may drop below your KES {f['buffer_kes']:,.0f} safety buffer from "
            f"{first}. You may need about KES {need:,.0f}. Open Duka to see your options. "
            f"Duka never asks for your PIN by SMS.")

if get_business_id():
    _msg = _sms_alert(get_business_id(), st.session_state.get("ui_swahili", False))
    if _msg:
        with st.container(border=True):
            st.markdown("##### :material/sms: Shortfall alert (SMS preview)")
            st.caption("This is how the forecast warning reads as a text message on your phone.")
            st.markdown(
                f"<div style='max-width:26rem;background:#e7f6e7;color:#102a12;border-radius:1rem 1rem 1rem 0.25rem;"
                f"padding:0.75rem 1rem;font-size:0.95rem;line-height:1.4'>{_msg}</div>",
                unsafe_allow_html=True,
            )

# render history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("meta"):
            with st.expander("Details", icon=":material/info:"):
                st.json(msg["meta"])

# input
if prompt := st.chat_input("e.g. How's my business doing this month?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analysing..."):
            user_id = get_user_id()
            business_id = get_business_id()
            result = st.session_state.orch.process(
                prompt,
                user_id=user_id,
                business_id=business_id,
            )

        response = result.get("response", "Sorry, I couldn't process that.")
        st.markdown(response)

        if result.get("verification"):
            v = result["verification"]
            if v.get("violations"):
                st.warning(
                    f":material/warning: Number check: {len(v['violations'])} violations found",
                    icon=":material/warning:",
                )
        if result.get("output_warnings"):
            for w in result["output_warnings"]:
                st.warning(w, icon=":material/warning:")

        meta = {
            "verification": result.get("verification"),
            "warnings": result.get("output_warnings"),
            "tools_used": list(result.get("tool_results", {}).keys()),
        }
        st.session_state.messages.append({
            "role": "assistant",
            "content": response,
            "meta": meta,
        })
