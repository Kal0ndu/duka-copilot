"""Streamlit auth middleware — @require_auth and @require_role decorators."""
from typing import Optional, Callable, Dict, Any
import functools

# Lazy import — streamlit is only needed at runtime in the Streamlit process
def _st():
    import streamlit as st
    return st
from typing import Optional, Callable
from pathlib import Path

from auth.session_manager import decode_session, is_session_revoked, Session


def get_current_session() -> Optional[Session]:
    """Return the current session from _st().session_state, or None if not logged in."""
    token = _st().session_state.get("auth_token")
    if not token:
        return None

    session = decode_session(token)
    if not session:
        # Token invalid — clear stale state
        _st().session_state.pop("auth_token", None)
        _st().session_state.pop("auth_session", None)
        return None

    # Check revocation
    db_path = _st().session_state.get("db_path", "data/duka.db")
    if is_session_revoked(db_path, token):
        _st().session_state.pop("auth_token", None)
        _st().session_state.pop("auth_session", None)
        return None

    return session


def require_auth(page_func: Callable = None, *, redirect: bool = True):
    """Decorator: require authentication to view a page.

    Usage:
        @require_auth
        def MyPage():
            ...

    Or as a guard at the top of a page:
        require_auth()
        if not _st().session_state.auth_session:
            _st().stop()
    """
    if page_func is None:
        # Called as @require_auth() with parens
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                session = get_current_session()
                if session:
                    _st().session_state.auth_session = session
                    return fn(*args, **kwargs)
                elif redirect:
                    _st().warning("Please log in to access this page.")
                    _st().switch_page("pages/Login.py")
                else:
                    _st().stop()
            return wrapper
        return decorator

    # Called as @require_auth (without parens)
    @functools.wraps(page_func)
    def wrapper(*args, **kwargs):
        session = get_current_session()
        if session:
            _st().session_state.auth_session = session
            return page_func(*args, **kwargs)
        else:
            _st().warning("Please log in to access this page.")
            _st().switch_page("pages/Login.py")
    return wrapper


def require_role(*allowed_roles: str):
    """Decorator: require specific role(s) to access a page.

    Usage:
        @require_role('owner', 'manager')
        def SettingsPage():
            ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            session = get_current_session()
            if not session:
                _st().warning("Please log in to access this page.")
                _st().switch_page("pages/Login.py")
                return

            if session.role not in allowed_roles:
                _st().error(f"Access denied. Your role '{session.role}' cannot access this page.")
                _st().stop()

            _st().session_state.auth_session = session
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_business_id() -> Optional[int]:
    """Get the current business_id from the session. Safe to call anywhere."""
    session = _st().session_state.get("auth_session")
    if session:
        return session.business_id
    return None


def get_user_id() -> Optional[int]:
    """Get the current user_id from the session. Safe to call anywhere."""
    session = _st().session_state.get("auth_session")
    if session:
        return session.user_id
    return None


# ---- user context injection ----

def load_user_context() -> Optional[Dict[str, Any]]:
    """Load the pre-computed user context into _st().session_state.

    Call this once at the top of authenticated pages to ensure the
    orchestrator has access to cached business data.

    Returns the context dict or None if not authenticated or computation fails.
    """
    from typing import Dict, Any

    session = _st().session_state.get("auth_session")
    if not session:
        return None

    # Return cached context if already loaded for this session
    ctx_key = f"_user_context_{session.user_id}_{session.business_id}"
    if ctx_key in _st().session_state:
        return _st().session_state[ctx_key]

    try:
        from auth.user_context import UserContext
        ctx = UserContext(
            user_id=session.user_id,
            business_id=session.business_id,
        )
        context = ctx.get()
        _st().session_state[ctx_key] = context
        return context
    except Exception:
        return None


def get_user_context() -> Optional[Dict[str, Any]]:
    """Get the currently loaded user context (without recomputing)."""
    session = _st().session_state.get("auth_session")
    if not session:
        return None
    ctx_key = f"_user_context_{session.user_id}_{session.business_id}"
    return _st().session_state.get(ctx_key)


def inject_user_context(page_func: Callable = None):
    """Decorator: inject user context into the Streamlit page.

    Ensures _st().session_state has a fresh user_context before the page renders.

    Usage:
        @inject_user_context
        def MyPage():
            ctx = _st().session_state.get("user_context")
            ...
    """
    if page_func is None:
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                ctx = load_user_context()
                if ctx:
                    _st().session_state["user_context"] = ctx
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    @functools.wraps(page_func)
    def wrapper(*args, **kwargs):
        ctx = load_user_context()
        if ctx:
            _st().session_state["user_context"] = ctx
        return page_func(*args, **kwargs)
    return wrapper


def invalidate_user_context_on_page() -> None:
    """Force-refresh the cached context (call after data changes)."""
    session = _st().session_state.get("auth_session")
    if not session:
        return
    ctx_key = f"_user_context_{session.user_id}_{session.business_id}"
    try:
        from auth.user_context import UserContext
        ctx = UserContext(
            user_id=session.user_id,
            business_id=session.business_id,
        )
        context = ctx.refresh()
        _st().session_state[ctx_key] = context
        _st().session_state["user_context"] = context
    except Exception:
        if ctx_key in _st().session_state:
            del _st().session_state[ctx_key]
