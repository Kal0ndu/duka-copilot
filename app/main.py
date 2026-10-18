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
    st.metric("AI core", Config.MODEL_NAME)

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
