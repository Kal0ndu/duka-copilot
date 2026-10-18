"""Sign Up page — new user registration with phone + OTP verification."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth_ui import render_sign_up, check_auth

st.set_page_config(
    page_title="Sign Up — Duka",
    page_icon=":material/person_add:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if check_auth():
    st.info("You're already logged in.")
    if st.button("Go to dashboard"):
        st.switch_page("pages/0_Business_Setup.py")
else:
    render_sign_up()
