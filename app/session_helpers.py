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

    @classmethod
    def get_transactions(cls) -> Optional[List[Dict[str, Any]]]:
        """Retrieve stored transactions from session state.
        
        Returns:
            List of transactions or None if not loaded
        """
        cls.init_session()
        return st.session_state.get(cls.TRANSACTIONS_KEY)

    @classmethod
    def get_profile(cls) -> Optional[Dict[str, str]]:
        """Retrieve stored business profile from session state.
        
        Returns:
            Profile dict or None if not loaded
        """
        cls.init_session()
        return st.session_state.get(cls.PROFILE_KEY)

    @classmethod
    def has_data(cls) -> bool:
        """Check if transaction data is currently loaded in session state.
        
        Returns:
            True if transactions are loaded, False otherwise
        """
        cls.init_session()
        txns = st.session_state.get(cls.TRANSACTIONS_KEY)
        return txns is not None and len(txns) > 0

    @classmethod
    def clear_data(cls):
        """Clear all loaded transaction data from session state."""
        st.session_state[cls.TRANSACTIONS_KEY] = None
        st.session_state[cls.PROFILE_KEY] = None
        st.session_state.pop(cls.UPLOAD_TIMESTAMP_KEY, None)

    @classmethod
    def require_data(cls, page_name: str = "this page") -> bool:
        """Check if data is loaded; show warning and stop if not.
        
        Args:
            page_name: Name of current page for messaging
            
        Returns:
            True if data is available, False if not (page should st.stop())
        """
        if not cls.has_data():
            st.warning("⚠️ No statement currently loaded.")
            st.info(
                f"📝 To use {page_name}, please first:\n"
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
        icon = profile.get("icon", "🏪")
        name = profile.get("name", "Loaded Business")
        sector = profile.get("sector", "Unknown Sector")

        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.info(f"{icon} **Currently analyzing:** {name}")
        with col2:
            st.caption(f"Sector: {sector}")
        with col3:
            if st.button("🔄 Upload Different Data", use_container_width=True):
                st.switch_page("pages/1_Upload_Statement.py")
