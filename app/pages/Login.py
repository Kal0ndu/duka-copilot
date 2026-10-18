"""Login page — authenticate with phone + password or OTP."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth_ui import render_login, check_auth

# If already logged in, redirect to main
if check_auth():
    st.info("You're already logged in.")
    if st.button("Go to Dashboard"):
        st.switch_page("pages/0_Business_Setup.py")  # Go to first dashboard page
else:
    render_login()
