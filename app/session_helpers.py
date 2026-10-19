"""Session state management for persisting data across pages."""
import streamlit as st
from typing import Optional, List, Dict, Any
import json
import pickle
from pathlib import Path


class SessionManager:
    """Manages persistent session data across Streamlit pages."""

    # Session state keys for uploaded data
    TRANSACTIONS_KEY = "parsed_transactions"
    PROFILE_KEY = "business_profile"
    UPLOAD_TIMESTAMP_KEY = "_upload_timestamp"
    CACHE_DIR = Path(".streamlit_cache")

    @classmethod
    def init_session(cls):
        """Initialize session state with defaults if not present."""
        if cls.TRANSACTIONS_KEY not in st.session_state:
            st.session_state[cls.TRANSACTIONS_KEY] = None
        if cls.PROFILE_KEY not in st.session_state:
            st.session_state[cls.PROFILE_KEY] = None

    @classmethod
    def set_transactions(cls, transactions: List[Dict[str, Any]], profile: Optional[Dict[str, str]] = None):
        """Store parsed transactions and business profile in session state.
        
        Args:
            transactions: List of transaction dictionaries
            profile: Business profile dict with name, sector, icon
        """
        st.session_state[cls.TRANSACTIONS_KEY] = transactions
        if profile:
            st.session_state[cls.PROFILE_KEY] = profile
        st.session_state[cls.UPLOAD_TIMESTAMP_KEY] = st.session_state.get("_timestamp_now", "")

    LEDGER_VERSION_KEY = "_ledger_version"

    @classmethod
    def _business_id(cls) -> Optional[int]:
        session = st.session_state.get("auth_session")
        return session.business_id if session and session.business_id else None

    @classmethod
    def load_from_ledger(cls, force: bool = False) -> bool:
        """Load the business's saved statements (transaction_ledger) into the
        session. Runs again whenever the ledger changes (upload, removal,
        recategorisation), so pages never show a stale copy. A demo sample
        loaded on purpose is left alone. Returns True if ledger data is loaded."""
        from core.config import config
        from core.statement_store import ledger_version, load_ledger_records
        business_id = cls._business_id()
        if not business_id:
            return False
        profile = st.session_state.get(cls.PROFILE_KEY) or {}
        if st.session_state.get(cls.TRANSACTIONS_KEY) and profile.get("source") != "ledger" and not force:
            return False  # a demo sample the owner chose
        version = (business_id, *ledger_version(config.DB_PATH, business_id))
        if not force and st.session_state.get(cls.LEDGER_VERSION_KEY) == version:
            return bool(st.session_state.get(cls.TRANSACTIONS_KEY))
        records = load_ledger_records(config.DB_PATH, business_id)
        st.session_state[cls.LEDGER_VERSION_KEY] = version
        if not records:
            if profile.get("source") == "ledger":
                st.session_state[cls.TRANSACTIONS_KEY] = None
                st.session_state[cls.PROFILE_KEY] = None
            return False
        from core.business_setup import BusinessSetup
        biz = BusinessSetup(config.DB_PATH).get_business_profile(business_id)
        st.session_state[cls.TRANSACTIONS_KEY] = records
        st.session_state[cls.PROFILE_KEY] = {
            "name": biz.name_token if biz else "Your business",
            "sector": (biz.sector.title() if biz else "SME"),
            "icon": ":material/store:",
            "source": "ledger",
        }
        return True

    @classmethod
    def use_ledger(cls) -> bool:
        """Switch back from a demo sample to the business's saved statements."""
        cls.clear_data()
        return cls.load_from_ledger(force=True)

    @classmethod
    def get_transactions(cls) -> Optional[List[Dict[str, Any]]]:
        """Retrieve stored transactions: the demo sample if one was chosen,
        otherwise the business's saved statements from the database.

        Returns:
            List of transactions or None if not loaded
        """
        cls.init_session()
        cls.load_from_ledger()
        return st.session_state.get(cls.TRANSACTIONS_KEY)

    @classmethod
    def get_profile(cls) -> Optional[Dict[str, str]]:
        """Retrieve stored business profile from session state.

        Returns:
            Profile dict or None if not loaded
        """
        cls.init_session()
        cls.load_from_ledger()
        return st.session_state.get(cls.PROFILE_KEY)

    @classmethod
    def has_data(cls) -> bool:
        """Check if transaction data is currently loaded in session state.
        
        Returns:
            True if transactions are loaded, False otherwise
        """
        cls.init_session()
        cls.load_from_ledger()
        txns = st.session_state.get(cls.TRANSACTIONS_KEY)
        return txns is not None and len(txns) > 0

    @classmethod
    def clear_data(cls):
        """Clear all loaded transaction data from session state."""
        st.session_state[cls.TRANSACTIONS_KEY] = None
        st.session_state[cls.PROFILE_KEY] = None
        st.session_state.pop(cls.UPLOAD_TIMESTAMP_KEY, None)
        st.session_state.pop(cls.LEDGER_VERSION_KEY, None)

    @classmethod
    def require_data(cls, page_name: str = "this page") -> bool:
        """Check if data is loaded; show warning and stop if not.
        
        Args:
            page_name: Name of current page for messaging
            
        Returns:
            True if data is available, False if not (page should st.stop())
        """
        if not cls.has_data():
            st.warning("No statement currently loaded.")
            st.info(
                f":material/edit_note: To use {page_name}, please first:\n"
                "1. Go to **Upload Statement** page\n"
                "2. Upload a CSV file OR load a demo profile\n"
                "3. Return here to view your data"
            )
            return False
        return True


def render_data_info_banner():
    """Render a banner showing what data is currently loaded.
    
    Call this at the top of pages that use transaction data.
    """
    txns = SessionManager.get_transactions()
    profile = SessionManager.get_profile()

    if txns and profile:
        icon = profile.get("icon", ":material/store:")
        name = profile.get("name", "Loaded Business")
        sector = profile.get("sector", "Unknown Sector")

        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.info(f" **Currently analyzing:** {name}")
        with col2:
            st.caption(f"Sector: {sector}")
        with col3:
            if st.button(":material/refresh: Upload different data", width="stretch"):
                st.switch_page("pages/1_Upload_Statement.py")
