"""Duka — Streamlit application entry point."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Config
from agent.orchestrator import Orchestrator

from app.sample_loader import load_sample_business, MOCK_PROFILES
from app.auth_ui import require_auth, render_logout_button, check_auth
from auth.middleware import (
    load_user_context, get_user_context,
    invalidate_user_context_on_page,
    get_user_id, get_business_id,
)

st.set_page_config(
    page_title="Duka — Micro-Business CFO",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- auth gate ----

require_auth()

# ---- user context ----

load_user_context()  # preload business context into st.session_state


# ---- session init ----

if "orch" not in st.session_state:
    st.session_state.orch = Orchestrator(Config)
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---- sidebar ----

with st.sidebar:
    st.image("https://img.icons8.com/color/96/shop.png", width=64)
    st.title("Duka Copilot")
    st.caption("AI CFO & Business Intelligence for Kenyan SMEs")

    st.divider()

    # Active Business Profile
    profile = st.session_state.get("business_profile")
    if profile:
        st.success(f"### {profile.get('icon', '🏪')} {profile.get('name', 'Active Business')}")
        st.caption(f"**Sector:** {profile.get('sector', 'SME')}")
    else:
        st.info("No statement loaded yet. Pick a sample SME below or go to **Upload Statement**:")

    # Quick Switcher
    st.markdown("##### ⚡ Switch Sample SME:")
    col_sb1, col_sb2, col_sb3 = st.columns(3)
    if col_sb1.button("🏪 Grocery", use_container_width=True, help="Amina's Grocery"):
        st.session_state["parsed_transactions"] = load_sample_business("amina_grocery")
        st.session_state["business_profile"] = MOCK_PROFILES["amina_grocery"]
        st.rerun()
    if col_sb2.button("🚐 Boda", use_container_width=True, help="Otieno Transport"):
        st.session_state["parsed_transactions"] = load_sample_business("otieno_transport")
        st.session_state["business_profile"] = MOCK_PROFILES["otieno_transport"]
        st.rerun()
    if col_sb3.button("💇 Salon", use_container_width=True, help="Grace Salon"):
        st.session_state["parsed_transactions"] = load_sample_business("grace_salon")
        st.session_state["business_profile"] = MOCK_PROFILES["grace_salon"]
        st.rerun()

    st.divider()

    st.metric("Security Sandbox", "Active (Fail-Closed)" if Config.SANDBOX_ONLY else "Live")
    st.metric("AI Core", Config.MODEL_NAME)

    st.divider()

    if st.button("🔄 Clear Chat", use_container_width=True):
        st.session_state.orch.reset()
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.divider()
    render_logout_button()
    st.caption("v0.3.0 — Nairobi 🇰🇪")

# ---- main chat & dashboard hub ----

st.title("🏪 Duka: AI Finance Copilot & Command Center")
st.caption("Real-time mobile money intelligence, cashflow forecasting, credit aging, and decision support.")

# Feature Navigation Cards
st.markdown("### 🧭 Business Intelligence Suite")
f1, f2, f3, f4, f5 = st.columns(5)
with f1:
    st.markdown("#### [📊 Analytics](Analytics)")
    st.caption("Revenue, COGS, OPEX, margins & personal mix ratio.")
with f2:
    st.markdown("#### [📈 Forecast](Cashflow_Forecast)")
    st.caption("1,000-path Monte Carlo runway & shortfall alerts.")
with f3:
    st.markdown("#### [🤝 Customers](Party_Intelligence)")
    st.caption("Top buyers, concentration risk & churn radar.")
with f4:
    st.markdown("#### [💳 Credit Book](Working_Capital)")
    st.caption("Receivables aging, payables & SMS reminders.")
with f5:
    st.markdown("#### [💰 Financing](Financing)")
    st.caption("Digital loans compared by true EAR% and cashfit.")

st.divider()

# render history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("meta"):
            with st.expander("Details"):
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
                st.warning(f"⚠️ Number check: {len(v['violations'])} violations found")
        if result.get("output_warnings"):
            for w in result["output_warnings"]:
                st.warning(w)

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
