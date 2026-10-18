"""Shared auth UI components for sign-up and login pages."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import config
from auth.phone_utils import normalise_phone, hash_phone, is_valid_kenyan_phone
from auth.password_utils import hash_password, verify_password
from auth.otp_service import generate_otp, store_otp, verify_otp, send_otp
from auth.session_manager import create_session, decode_session
from db.users import (
    create_user, get_user_by_phone, get_user_by_id,
    get_user_password, update_last_login
)


def render_sign_up():
    """Render the sign-up form and handle registration flow."""
    st.title("📱 Create Your Duka Account")
    st.caption("Sign up with your phone number to get started.")

    # Track OTP flow state
    if "signup_step" not in st.session_state:
        st.session_state.signup_step = "form"  # form | otp | complete
    if "signup_phone" not in st.session_state:
        st.session_state.signup_phone = ""
    if "signup_phone_hash" not in st.session_state:
        st.session_state.signup_phone_hash = ""
    if "signup_otp_code" not in st.session_state:
        st.session_state.signup_otp_code = ""

    db_path = config.DB_PATH

    # ---- Step 1: Registration form ----
    if st.session_state.signup_step == "form":
        with st.form("signup_form"):
            phone_raw = st.text_input(
                "Phone Number",
                placeholder="0712 345 678",
                help="Kenyan mobile number (Safaricom, Airtel, Telkom)"
            )
            display_name = st.text_input(
                "Display Name",
                placeholder="Your name or business name",
                help="How you'll appear in Duka"
            )
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Min 8 characters",
                help="At least 8 characters with a mix of letters and numbers"
            )
            confirm_password = st.text_input(
                "Confirm Password",
                type="password",
                placeholder="Re-enter password"
            )

            submitted = st.form_submit_button("📱 Send Verification Code", use_container_width=True)

        if submitted:
            errors = []

            # Validate phone
            if not phone_raw.strip():
                errors.append("Phone number is required.")
            elif not is_valid_kenyan_phone(phone_raw):
                errors.append("Please enter a valid Kenyan mobile number.")
            else:
                try:
                    norm = normalise_phone(phone_raw)
                    ph = hash_phone(norm)
                except ValueError as e:
                    errors.append(str(e))

            # Validate name
            if not display_name.strip():
                errors.append("Display name is required.")
            elif len(display_name.strip()) < 2:
                errors.append("Display name must be at least 2 characters.")

            # Validate password
            if not password:
                errors.append("Password is required.")
            elif len(password) < 8:
                errors.append("Password must be at least 8 characters.")
            elif password != confirm_password:
                errors.append("Passwords do not match.")

            # Check if user already exists
            if not errors:
                existing = get_user_by_phone(db_path, ph)
                if existing:
                    errors.append("An account with this phone number already exists. Please log in instead.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                # Generate and send OTP
                otp = generate_otp()
                store_otp(db_path, ph, otp, purpose="signup")
                send_otp(norm, otp)

                st.session_state.signup_step = "otp"
                st.session_state.signup_phone = norm
                st.session_state.signup_phone_hash = ph
                st.session_state.signup_display_name = display_name.strip()
                st.session_state.signup_password = password
                st.session_state.signup_otp_code = otp  # stored for verification
                st.rerun()

    # ---- Step 2: OTP verification ----
    elif st.session_state.signup_step == "otp":
        st.info(f"📱 A verification code was sent to {st.session_state.signup_phone}")
        st.caption("Check the console output for the OTP code (dev mode).")

        with st.form("signup_otp_form"):
            otp_input = st.text_input(
                "Enter Verification Code",
                placeholder="6-digit code",
                max_chars=6
            )
            verify_btn = st.form_submit_button("✅ Verify & Create Account", use_container_width=True)

            col1, col2 = st.columns(2)
            with col1:
                resend = st.form_submit_button("🔄 Resend Code")
            with col2:
                back = st.form_submit_button("⬅ Back")

        if verify_btn:
            if not otp_input or len(otp_input) != 6:
                st.error("Please enter the 6-digit verification code.")
            else:
                result = verify_otp(
                    db_path,
                    st.session_state.signup_phone_hash,
                    otp_input,
                    purpose="signup"
                )
                if result.success:
                    # Create user
                    pw_hash, pw_salt = hash_password(st.session_state.signup_password)
                    user_id = create_user(
                        db_path,
                        phone_hash=st.session_state.signup_phone_hash,
                        display_name=st.session_state.signup_display_name,
                        password_hash=pw_hash,
                        password_salt=pw_salt,
                    )
                    if user_id:
                        st.session_state.signup_step = "complete"
                        st.session_state.signup_user_id = user_id
                        st.rerun()
                    else:
                        st.error("Failed to create account. Please try again.")
                else:
                    st.error(result.message)

        if resend:
            otp = generate_otp()
            store_otp(db_path, st.session_state.signup_phone_hash, otp, purpose="signup")
            send_otp(st.session_state.signup_phone, otp)
            st.session_state.signup_otp_code = otp
            st.success("New code sent!")
            st.rerun()

        if back:
            st.session_state.signup_step = "form"
            st.rerun()

    # ---- Step 3: Complete ----
    elif st.session_state.signup_step == "complete":
        st.success("✅ Account created successfully!")
        st.balloons()
        st.markdown(f"Welcome, **{st.session_state.signup_display_name}**! 🎉")

        # Auto-login: create session token
        token = create_session(
            user_id=st.session_state.signup_user_id,
            business_id=0,  # no business yet
            display_name=st.session_state.signup_display_name,
            role="owner",
            phone_hash=st.session_state.signup_phone_hash,
        )
        update_last_login(db_path, st.session_state.signup_user_id)

        st.session_state.auth_token = token
        st.session_state.auth_user = {
            "user_id": st.session_state.signup_user_id,
            "display_name": st.session_state.signup_display_name,
            "phone_hash": st.session_state.signup_phone_hash,
            "role": "owner",
        }

        # Clean up signup state
        for key in list(st.session_state.keys()):
            if key.startswith("signup_"):
                del st.session_state[key]

        # Auto-redirect to dashboard
        st.switch_page("pages/0_Business_Setup.py")


def render_login():
    """Render the login form and handle authentication flow."""
    st.title("🔐 Log In to Duka")
    st.caption("Welcome back! Log in with your phone number.")

    if "login_step" not in st.session_state:
        st.session_state.login_step = "form"  # form | otp | password
    if "login_phone" not in st.session_state:
        st.session_state.login_phone = ""
    if "login_phone_hash" not in st.session_state:
        st.session_state.login_phone_hash = ""
    if "login_user" not in st.session_state:
        st.session_state.login_user = None

    db_path = config.DB_PATH

    # ---- Step 1: Enter phone ----
    if st.session_state.login_step == "form":
        with st.form("login_form"):
            phone_raw = st.text_input(
                "Phone Number",
                placeholder="0712 345 678",
                help="Your registered Kenyan mobile number"
            )
            submitted = st.form_submit_button("🔍 Find Account", use_container_width=True)

        if submitted:
            if not phone_raw.strip():
                st.error("Please enter your phone number.")
            elif not is_valid_kenyan_phone(phone_raw):
                st.error("Please enter a valid Kenyan mobile number.")
            else:
                try:
                    norm = normalise_phone(phone_raw)
                    ph = hash_phone(norm)
                except ValueError as e:
                    st.error(str(e))
                    st.stop()

                user = get_user_by_phone(db_path, ph)
                if not user:
                    st.error("No account found with this phone number.")
                    st.markdown("[Create a new account](Sign_Up)")
                elif user.status == "suspended":
                    st.error("This account has been suspended. Contact support.")
                else:
                    st.session_state.login_phone = norm
                    st.session_state.login_phone_hash = ph
                    st.session_state.login_user = user

                    # Check if user has a password set
                    pw_hash, pw_salt = get_user_password(db_path, user.user_id)
                    if pw_hash:
                        st.session_state.login_step = "password"
                    else:
                        st.session_state.login_step = "otp"
                    st.rerun()

        # Link to sign-up
        st.markdown("---")
        st.markdown("Don't have an account? [Sign Up](Sign_Up)")

    # ---- Step 2a: Password login ----
    elif st.session_state.login_step == "password":
        user = st.session_state.login_user
        st.info(f"👋 Welcome back, **{user.display_name}**!")

        with st.form("login_password_form"):
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password"
            )
            login_btn = st.form_submit_button("🔓 Log In", use_container_width=True)

            col1, col2 = st.columns(2)
            with col1:
                otp_option = st.form_submit_button("📱 Use OTP instead")
            with col2:
                back_btn = st.form_submit_button("⬅ Back")

        if login_btn:
            if not password:
                st.error("Please enter your password.")
            else:
                pw_hash, pw_salt = get_user_password(db_path, user.user_id)
                if verify_password(password, pw_hash, pw_salt):
                    _complete_login(db_path, user)
                else:
                    st.error("Incorrect password. Please try again.")

        if otp_option:
            otp = generate_otp()
            store_otp(db_path, st.session_state.login_phone_hash, otp, purpose="login")
            send_otp(st.session_state.login_phone, otp)
            st.session_state.login_otp_code = otp
            st.session_state.login_step = "otp"
            st.rerun()

        if back_btn:
            st.session_state.login_step = "form"
            st.rerun()

    # ---- Step 2b: OTP login ----
    elif st.session_state.login_step == "otp":
        user = st.session_state.login_user
        st.info(f"📱 A verification code was sent to {st.session_state.login_phone}")
        st.caption("Check the console output for the OTP code (dev mode).")

        with st.form("login_otp_form"):
            otp_input = st.text_input(
                "Enter Verification Code",
                placeholder="6-digit code",
                max_chars=6
            )
            verify_btn = st.form_submit_button("✅ Verify & Log In", use_container_width=True)

            col1, col2, col3 = st.columns(3)
            with col1:
                resend = st.form_submit_button("🔄 Resend")
            with col2:
                password_opt = st.form_submit_button("🔑 Use Password")
            with col3:
                back = st.form_submit_button("⬅ Back")

        if verify_btn:
            if not otp_input or len(otp_input) != 6:
                st.error("Please enter the 6-digit code.")
            else:
                result = verify_otp(
                    db_path,
                    st.session_state.login_phone_hash,
                    otp_input,
                    purpose="login"
                )
                if result.success:
                    _complete_login(db_path, user)
                else:
                    st.error(result.message)

        if resend:
            otp = generate_otp()
            store_otp(db_path, st.session_state.login_phone_hash, otp, purpose="login")
            send_otp(st.session_state.login_phone, otp)
            st.session_state.login_otp_code = otp
            st.success("New code sent!")
            st.rerun()

        if password_opt:
            pw_hash, _ = get_user_password(db_path, user.user_id)
            if pw_hash:
                st.session_state.login_step = "password"
            else:
                st.warning("No password set on this account. Use OTP to log in.")
            st.rerun()

        if back:
            st.session_state.login_step = "form"
            st.rerun()


def _complete_login(db_path: str, user):
    """Finalize login: create session, update last login, set auth state."""
    token = create_session(
        user_id=user.user_id,
        business_id=0,
        display_name=user.display_name,
        role="owner",
        phone_hash=user.phone_hash,
    )
    update_last_login(db_path, user.user_id)

    st.session_state.auth_token = token
    st.session_state.auth_user = {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "phone_hash": user.phone_hash,
        "role": "owner",
    }

    # Clean up login state
    for key in list(st.session_state.keys()):
        if key.startswith("login_"):
            del st.session_state[key]

    st.success(f"✅ Logged in as **{user.display_name}**!")
    
    # Auto-redirect to dashboard
    st.switch_page("pages/0_Business_Setup.py")


def check_auth():
    """Return True if user is authenticated, False otherwise.
    Call this at the top of protected pages.
    """
    token = st.session_state.get("auth_token")
    if not token:
        return False

    session = decode_session(token)
    if not session:
        # Token is invalid/expired, clear it
        st.session_state.pop("auth_token", None)
        st.session_state.pop("auth_user", None)
        return False

    return True


def render_logout_button():
    """Render a logout button in the sidebar."""
    if st.session_state.get("auth_token"):
        with st.sidebar:
            st.divider()
            user = st.session_state.get("auth_user", {})
            st.caption(f"👤 {user.get('display_name', 'User')}")
            if st.button("🚪 Log Out", use_container_width=True):
                st.session_state.pop("auth_token", None)
                st.session_state.pop("auth_user", None)
                st.rerun()


def require_auth():
    """Gate: if not authenticated, show login prompt and stop rendering."""
    if not check_auth():
        st.warning("🔐 Please log in to access Duka.")
        st.markdown("[Log In](Login)  |  [Sign Up](Sign_Up)")
        st.stop()
