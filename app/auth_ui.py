"""Shared auth UI components for sign-up and login pages."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import config
from auth.phone_utils import normalise_phone, hash_phone, is_valid_kenyan_phone
from auth.password_utils import hash_password, verify_password
from auth.otp_service import generate_otp, store_otp, verify_otp, send_otp
from auth.session_manager import create_session, decode_session, revoke_jti, is_jti_revoked
from auth.rbac import get_account_role, log_security_event, login_locked, MAX_FAILED_LOGINS, LOGIN_LOCKOUT
from db.users import (
    create_user, get_user_by_phone, get_user_by_id,
    get_user_password, update_last_login
)
from app.auth_theme import inject_auth_theme, render_illustration, render_brand_header, render_progress_indicator


def _login_failed(db_path: str, user_id, method: str, reason: str, phone_hash: str = "") -> None:
    log_security_event(
        db_path, "LOGIN_FAILED", user_id=user_id, resource="login", outcome="denied",
        severity="medium", detection=f"{method} check failed: {reason}",
        handling="login refused", details={"method": method, "phone_hash_prefix": phone_hash[:12]},
    )


def _locked_out(db_path: str, user_id: int) -> bool:
    """Refuse (and log) a login attempt while the account is locked."""
    if not login_locked(db_path, user_id):
        return False
    log_security_event(
        db_path, "LOGIN_LOCKED_OUT", user_id=user_id, resource="login", outcome="blocked",
        severity="high",
        detection=f"{MAX_FAILED_LOGINS}+ failed logins within {int(LOGIN_LOCKOUT.total_seconds() // 60)} minutes",
        handling="attempt refused without checking the credential",
    )
    st.error(f"Too many failed attempts. Try again in {int(LOGIN_LOCKOUT.total_seconds() // 60)} minutes.")
    return True


def _reset_session_state() -> None:
    """Forget everything from the previous user in this browser session:
    chat history, the orchestrator, loaded statements and cached contexts."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _open_glass_card():
    """Open a styled glassmorphism container."""
    st.markdown('<div class="auth-glass-card">', unsafe_allow_html=True)


def _close_glass_card():
    """Close the glass container."""
    st.markdown('</div>', unsafe_allow_html=True)


# ──────────────────────────────────────────────────
#  SIGN UP
# ──────────────────────────────────────────────────

def render_sign_up():
    """Render the sign-up form inside a colorful split layout."""
    inject_auth_theme()

    # Track OTP flow state
    if "signup_step" not in st.session_state:
        st.session_state.signup_step = "form"
    if "signup_phone" not in st.session_state:
        st.session_state.signup_phone = ""
    if "signup_phone_hash" not in st.session_state:
        st.session_state.signup_phone_hash = ""
    if "signup_otp_code" not in st.session_state:
        st.session_state.signup_otp_code = ""

    db_path = config.DB_PATH

    col_form, col_illus = st.columns([5, 4])

    with col_form:
        _open_glass_card()
        render_brand_header()

        if st.session_state.signup_step == "form":
            _signup_form(db_path)
        elif st.session_state.signup_step == "otp":
            _signup_otp(db_path)
        elif st.session_state.signup_step == "complete":
            _signup_complete()

        _close_glass_card()

    with col_illus:
        st.markdown('<div class="auth-illustration-col">', unsafe_allow_html=True)
        render_illustration()
        st.markdown('</div>', unsafe_allow_html=True)


def _signup_form(db_path: str):
    """Step 1: registration form."""
    render_progress_indicator(1, 3)
    
    st.markdown('<div class="auth-form-section-title">Create Your Account</div>', unsafe_allow_html=True)
    
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

        st.markdown("")  # Spacing
        submitted = st.form_submit_button(":material/smartphone: Send Verification Code", width="stretch")

    if submitted:
        errors = []

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

        if not display_name.strip():
            errors.append("Display name is required.")
        elif len(display_name.strip()) < 2:
            errors.append("Display name must be at least 2 characters.")

        if not password:
            errors.append("Password is required.")
        elif len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        elif password != confirm_password:
            errors.append("Passwords do not match.")

        if not errors:
            existing = get_user_by_phone(db_path, ph)
            if existing:
                errors.append("An account with this phone number already exists. Please log in instead.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            otp = generate_otp()
            store_otp(db_path, ph, otp, purpose="signup")
            send_otp(norm, otp)

            st.session_state.signup_step = "otp"
            st.session_state.signup_phone = norm
            st.session_state.signup_phone_hash = ph
            st.session_state.signup_display_name = display_name.strip()
            st.session_state.signup_password = password
            st.session_state.signup_otp_code = otp
            st.rerun()

    st.divider()
    st.caption("Already have an account?")
    if st.button(":material/login: Log in", width="stretch", key="signup_to_login"):
        st.switch_page("app_pages/Login.py")


def _signup_otp(db_path: str):
    """Step 2: OTP verification."""
    render_progress_indicator(2, 3)
    
    st.markdown('<div class="auth-form-section-title">Verify Your Phone</div>', unsafe_allow_html=True)
    st.info(f":material/smartphone: A verification code was sent to **{st.session_state.signup_phone}**")
    st.caption("Check the console output for the OTP code (dev mode).")

    with st.form("signup_otp_form"):
        otp_input = st.text_input(
            "Enter Verification Code",
            placeholder="6-digit code",
            max_chars=6
        )
        st.markdown("")  # Spacing
        verify_btn = st.form_submit_button(":material/check_circle: Verify & Create Account", width="stretch")

        col1, col2 = st.columns(2)
        with col1:
            resend = st.form_submit_button(":material/refresh: Resend code", width="stretch")
        with col2:
            back = st.form_submit_button(":material/arrow_back: Back", width="stretch")

    if back:
        st.session_state.signup_step = "form"
        st.rerun()

    if resend:
        otp = generate_otp()
        store_otp(db_path, st.session_state.signup_phone_hash, otp, purpose="signup")
        send_otp(st.session_state.signup_phone, otp)
        st.session_state.signup_otp_code = otp
        st.success("New code sent!")
        st.rerun()

    if verify_btn:
        if not otp_input.strip():
            st.error("Please enter the verification code.")
        else:
            result = verify_otp(
                db_path,
                st.session_state.signup_phone_hash,
                otp_input.strip(),
                purpose="signup"
            )
            if not result.success:
                st.error(result.message)
            else:
                # Hash the password before storing
                password_hash, password_salt = hash_password(st.session_state.signup_password)
                user_id = create_user(
                    db_path,
                    phone_hash=st.session_state.signup_phone_hash,
                    display_name=st.session_state.signup_display_name,
                    password_hash=password_hash,
                    password_salt=password_salt
                )
                if user_id:
                    log_security_event(
                        db_path, "ACCOUNT_CREATED", user_id=user_id, resource="account",
                        outcome="success", severity="low",
                        detection="sign-up with verified phone OTP", handling="account created with role 'user'",
                    )
                    # Fetch the created user record
                    user = get_user_by_id(db_path, user_id)
                    st.session_state.signup_step = "complete"
                    st.session_state.signup_user = user
                    st.rerun()
                else:
                    st.error("Account creation failed. Please try again.")


def _signup_complete():
    """Step 3: success and redirect."""
    render_progress_indicator(3, 3)
    
    user = st.session_state.signup_user
    
    st.markdown("""
    <div style="text-align: center; margin: 2rem 0;">
        <h2 style="color: #86efac; margin: 0 0 0.5rem 0;">Welcome to Duka!</h2>
        <p style="color: #cbd5e1; margin: 0 0 2rem 0;">Your account is ready to go</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.success(f"Account created for **{user.display_name}**")
    
    st.markdown("""
    <div style="background: rgba(94, 234, 212, 0.1); border: 1px solid rgba(94, 234, 212, 0.3); 
                border-radius: 12px; padding: 1.5rem; margin: 1.5rem 0; text-align: center;">
        <p style="color: #cbd5e1; margin: 0;">You're all set! Proceed to log in with your credentials.</p>
    </div>
    """, unsafe_allow_html=True)

    for key in list(st.session_state.keys()):
        if key.startswith("signup_"):
            del st.session_state[key]

    # Reset step to prevent KeyError on re-render after state cleanup
    st.session_state.signup_step = "form"

    if st.button(":material/login: Go to login", width="stretch"):
        st.switch_page("app_pages/Login.py")


# ──────────────────────────────────────────────────
#  LOGIN
# ──────────────────────────────────────────────────

def render_login():
    """Render the login form inside a colorful split layout."""
    inject_auth_theme()

    if "login_step" not in st.session_state:
        st.session_state.login_step = "form"
    if "login_phone" not in st.session_state:
        st.session_state.login_phone = ""
    if "login_phone_hash" not in st.session_state:
        st.session_state.login_phone_hash = ""
    if "login_otp_code" not in st.session_state:
        st.session_state.login_otp_code = ""
    if "login_user_id" not in st.session_state:
        st.session_state.login_user_id = 0

    db_path = config.DB_PATH

    col_form, col_illus = st.columns([5, 4])

    with col_form:
        _open_glass_card()
        render_brand_header()

        if st.session_state.login_step == "form":
            _login_form(db_path)
        elif st.session_state.login_step == "otp":
            _login_otp(db_path)
        elif st.session_state.login_step == "password":
            _login_password(db_path)

        _close_glass_card()

    with col_illus:
        st.markdown('<div class="auth-illustration-col">', unsafe_allow_html=True)
        render_illustration()
        st.markdown('</div>', unsafe_allow_html=True)


def _login_form(db_path: str):
    """Step 1: phone number entry."""
    render_progress_indicator(1, 2)
    
    st.markdown('<div class="auth-form-section-title">Log in to Duka</div>', unsafe_allow_html=True)
    
    with st.form("login_form"):
        phone_raw = st.text_input(
            "Phone Number",
            placeholder="0712 345 678",
            help="Your registered Kenyan mobile number"
        )
        st.markdown("")  # Spacing
        submitted = st.form_submit_button(":material/search: Find Account", width="stretch")

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
                return

            user = get_user_by_phone(db_path, ph)
            if not user:
                _login_failed(db_path, None, "phone", "no account for this phone", ph)
                st.error("No account found with this phone number.")
                st.markdown("[Create an account instead →](Sign_Up)")
            else:
                st.session_state.login_step = "otp"
                st.session_state.login_phone = norm
                st.session_state.login_phone_hash = ph
                st.session_state.login_user_id = user.user_id

                otp = generate_otp()
                store_otp(db_path, ph, otp, purpose="login")
                send_otp(norm, otp)
                st.session_state.login_otp_code = otp
                st.rerun()

    st.divider()
    st.markdown("""
    <div style="text-align: center;">
        <p style="color: #cbd5e1; margin: 1rem 0 0.5rem 0;">Don't have an account?</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button(":material/person_add: Create account", width="stretch"):
        st.switch_page("app_pages/Sign_Up.py")


def _login_otp(db_path: str):
    """Step 2: OTP verification."""
    render_progress_indicator(2, 2)
    
    user = get_user_by_id(db_path, st.session_state.login_user_id)

    st.markdown('<div class="auth-form-section-title">Verify Your Phone</div>', unsafe_allow_html=True)
    st.info(f":material/smartphone: A verification code was sent to **{st.session_state.login_phone}**")
    st.caption("Check the console output for the OTP code (dev mode).")

    with st.form("login_otp_form"):
        otp_input = st.text_input(
            "Enter Verification Code",
            placeholder="6-digit code",
            max_chars=6
        )
        st.markdown("")  # Spacing
        verify_btn = st.form_submit_button(":material/check_circle: Verify & Log In", width="stretch")

        col1, col2, col3 = st.columns(3)
        with col1:
            resend = st.form_submit_button(":material/refresh: Resend", width="stretch")
        with col2:
            password_opt = st.form_submit_button(":material/key: Use password", width="stretch")
        with col3:
            back = st.form_submit_button(":material/arrow_back: Back", width="stretch")

    if back:
        st.session_state.login_step = "form"
        st.rerun()

    if verify_btn:
        if not otp_input.strip():
            st.error("Please enter the verification code.")
        elif not _locked_out(db_path, user.user_id):
            result = verify_otp(
                db_path,
                st.session_state.login_phone_hash,
                otp_input.strip(),
                purpose="login"
            )
            if result.success:
                _complete_login(db_path, user)
            else:
                _login_failed(db_path, user.user_id, "otp", result.message, user.phone_hash)
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


def _login_password(db_path: str):
    """Step 2b: password-based login."""
    user = get_user_by_id(db_path, st.session_state.login_user_id)

    st.markdown('<div class="auth-form-section-title">Enter Your Password</div>', unsafe_allow_html=True)
    st.caption(f"Logging in as: **{st.session_state.login_phone}**")

    with st.form("login_password_form"):
        pwd = st.text_input("Password", type="password", placeholder="Enter your password")
        st.markdown("")  # Spacing
        submitted = st.form_submit_button(":material/lock_open: Log in", width="stretch")

        col1, col2 = st.columns(2)
        with col1:
            otp_switch = st.form_submit_button(":material/smartphone: Use OTP instead", width="stretch")
        with col2:
            back = st.form_submit_button(":material/arrow_back: Back", width="stretch")

    if back:
        st.session_state.login_step = "form"
        st.rerun()

    if otp_switch:
        st.session_state.login_step = "otp"
        st.rerun()

    if submitted:
        if not pwd:
            st.error("Please enter your password.")
        elif not _locked_out(db_path, user.user_id):
            pw_hash, pw_salt = get_user_password(db_path, user.user_id)
            if verify_password(pwd, pw_hash, pw_salt):
                _complete_login(db_path, user)
            else:
                _login_failed(db_path, user.user_id, "password", "incorrect password", user.phone_hash)
                st.error("Incorrect password.")


def _clear_user_context_cache():
    for key in list(st.session_state.keys()):
        if key.startswith("_user_context_"):
            del st.session_state[key]


def activate_business(business_id: int) -> None:
    """Re-issue the session token scoped to business_id.

    The business lives in the signed token (not just st.session_state), so
    every page's get_business_id() sees it and it survives page switches."""
    token = st.session_state.get("auth_token")
    session = decode_session(token) if token else None
    if session is None:
        return
    new_token = create_session(
        user_id=session.user_id,
        business_id=business_id,
        display_name=session.display_name,
        role=session.role,
        phone_hash=session.phone_hash,
    )
    st.session_state.auth_token = new_token
    st.session_state.auth_session = decode_session(new_token)
    st.session_state.business_id = business_id
    revoke_jti(config.DB_PATH, session, reason="reissued")  # the old token must not stay usable
    _clear_user_context_cache()


def _resolve_business(session):
    """Sessions issued before the user finished setup carry business_id=0.
    Look the user's business up in the DB and switch the session to it."""
    if session.business_id:
        return session
    from core.business_setup import BusinessSetup
    business_id = BusinessSetup(config.DB_PATH).get_business_for_user(session.user_id)
    if business_id:
        activate_business(business_id)
        return st.session_state.auth_session
    return session


def _complete_login(db_path: str, user):
    """Finalize login: create session, update last login, set auth state.

    A returning user goes straight to the dashboard with their saved
    business; only a user with no business yet is sent to Business Setup."""
    from core.business_setup import BusinessSetup
    business_id = BusinessSetup(db_path).get_business_for_user(user.user_id) or 0
    # The account role comes from the database; the token only mirrors it
    # for display. Permission checks re-read it (auth/rbac.py).
    role = get_account_role(db_path, user.user_id) or "user"

    token = create_session(
        user_id=user.user_id,
        business_id=business_id,
        display_name=user.display_name,
        role=role,
        phone_hash=user.phone_hash,
    )
    update_last_login(db_path, user.user_id)
    log_security_event(
        db_path, "LOGIN_SUCCESS", user_id=user.user_id, business_id=business_id or None,
        resource="login", outcome="success", severity="low",
        detection="credential verified", handling=f"session issued (role '{role}')",
    )

    # Nothing from a previous user of this browser session may carry over.
    _reset_session_state()
    st.session_state.auth_token = token
    st.session_state.auth_user = {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "phone_hash": user.phone_hash,
        "role": role,
    }

    st.session_state.auth_session = decode_session(token)
    if business_id:
        st.session_state.business_id = business_id
    _clear_user_context_cache()

    st.success(f"Logged in as **{user.display_name}**!")

    st.switch_page("app_pages/home.py" if business_id else "app_pages/0_Business_Setup.py")


# ──────────────────────────────────────────────────
#  SHARED HELPERS
# ──────────────────────────────────────────────────

def check_auth():
    """Return True if user is authenticated, False otherwise."""
    token = st.session_state.get("auth_token")
    if not token:
        return False
    session = decode_session(token)
    if not session:
        st.session_state.pop("auth_token", None)
        st.session_state.pop("auth_user", None)
        return False
    return True


def validate_and_refresh_session():
    """Check if auth token is still valid; clear stale state if not."""
    token = st.session_state.get("auth_token")
    if not token:
        return False
    session = decode_session(token)
    if session and is_jti_revoked(config.DB_PATH, session):
        log_security_event(
            config.DB_PATH, "REVOKED_SESSION_USED", user_id=session.user_id, resource="session",
            outcome="denied", severity="high", detection="token id is on the logged-out list",
            handling="session refused and cleared",
        )
        _reset_session_state()
        return False
    if not session:
        st.session_state.pop("auth_token", None)
        st.session_state.pop("auth_user", None)
        st.session_state.pop("business_id", None)
        st.session_state.pop("auth_session", None)
        for key in list(st.session_state.keys()):
            if key.startswith("_user_context_"):
                del st.session_state[key]
        return False
    # get_business_id() and friends read auth_session, so keep it in step
    # with the token on every page, not only pages using auth.middleware.
    st.session_state.auth_session = session
    session = _resolve_business(session)
    if session.business_id:
        st.session_state.business_id = session.business_id
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = {
            "user_id": session.user_id,
            "display_name": session.display_name,
            "phone_hash": session.phone_hash,
            "role": session.role,
        }
    return True


def render_logout_button():
    """Render a logout button in the sidebar."""
    if st.session_state.get("auth_token"):
        with st.sidebar:
            st.divider()
            user = st.session_state.get("auth_user", {})
            st.caption(f":material/person: {user.get("display_name", "User")}")
            if st.button(":material/logout: Log out", width="stretch"):
                logout()
                st.switch_page("app_pages/Login.py")


def logout() -> None:
    """Revoke the session token, log the event and forget all session state."""
    token = st.session_state.get("auth_token")
    session = decode_session(token) if token else None
    if session:
        revoke_jti(config.DB_PATH, session, reason="logout")
        log_security_event(
            config.DB_PATH, "LOGOUT", user_id=session.user_id, business_id=session.business_id or None,
            resource="session", outcome="success", severity="low",
            detection="user pressed Log out", handling="token revoked; session state cleared",
        )
        try:
            from auth.user_context import invalidate_user_cache
            if session.business_id:
                invalidate_user_cache(session.user_id, session.business_id)
        except Exception:
            pass
    _reset_session_state()


def require_auth():
    """Gate: if not authenticated, show login prompt and stop."""
    if not validate_and_refresh_session():
        st.warning(":material/lock: Please log in to access Duka.")
        st.markdown("[Log In](Login)  |  [Sign Up](Sign_Up)")
        st.stop()


def require_admin(resource: str):
    """Gate for admin-only pages. The role is checked against the database
    on every page load (auth/rbac.py); a regular user gets a generic refusal
    and the attempt is logged as a security event."""
    from auth.rbac import AccessDenied, require_admin as _require_admin
    require_auth()
    session = st.session_state.get("auth_session")
    try:
        _require_admin(config.DB_PATH, session.user_id if session else None, resource)
    except AccessDenied as e:
        st.error(str(e), icon=":material/block:")
        st.stop()
    return session


def require_auth_with_redirect():
    """Gate: redirect to Login page instead of showing inline prompt."""
    if not validate_and_refresh_session():
        st.switch_page("app_pages/Login.py")
