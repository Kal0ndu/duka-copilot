"""Login page — authenticate with phone + password or OTP."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth_ui import render_login, check_auth, render_brand_header
from app.auth_theme import inject_auth_theme

st.set_page_config(
    page_title="Login — Duka",
    page_icon=":material/login:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if check_auth():
    st.info("You're already logged in.")
    if st.button("Go to dashboard"):
        st.switch_page("main.py" if st.session_state.get("business_id") else "pages/0_Business_Setup.py")
else:
    render_login()

