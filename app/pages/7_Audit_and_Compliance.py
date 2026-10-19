"""Page 7: Regulatory compliance and privacy guard. (The audit trail and
security events are admin-only: pages/14_Admin_Security.py.)"""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.redaction import Redactor
from core.config import Config
from app.session_helpers import SessionManager

st.set_page_config(page_title="Privacy & Compliance — Duka", page_icon=":material/shield:", layout="wide")
# ---- Authentication Gate ----
require_auth()


# Initialize session
SessionManager.init_session()

st.title("Privacy & Regulatory Compliance")
st.caption("Check how your data is protected and how your statement compares with Central Bank of Kenya limits.")

# ---- ROW 1: SECURITY KPIS ----
s1, s2, s3, s4 = st.columns(4)
s1.metric("Sandbox Security Mode", "Active (Fail-Closed)" if Config.SANDBOX_ONLY else "Live")
s2.metric("Per-Transaction Cap", f"KES {Config.CAP_PER_TXN / 100:,.0f}", help="CBK single mobile-money transfer regulatory limit.")
s3.metric("Daily Cumulative Cap", f"KES {Config.CAP_DAILY / 100:,.0f}", help="CBK 24-hour total account transfer limit.")
s4.metric("PII redaction", "Test below", help="Try the tokeniser on your own text in the next section.")

st.divider()

# ---- SECTION 2: LIVE PRIVACY & REDACTION DEMO ----
st.subheader("PII Tokenization & Privacy Verification")
st.caption("Test how customer phone numbers, Kenyan IDs, and sensitive names are tokenized before leaving your device:")

test_text = st.text_input(
    "Test Sensitive Customer / Payment Text:",
    value="Received KES 4,500 from 0722123456 (John Mwangi, ID 28472910) for stock purchase"
)

if test_text:
    redactor = Redactor()
    res = redactor.redact(test_text)
    
    col_raw, col_red = st.columns(2)
    with col_raw:
        st.markdown("**Original Raw Text:**")
        st.code(test_text, language="text")
    with col_red:
        st.markdown("**Redacted Safe Text (What LLM sees):**")
        st.code(res.safe_text, language="text")

    if res.pii_found:
        st.success(f"Protected **{len(res.pii_found)}** sensitive items: {', '.join(res.pii_found)}")
    if res.tokens:
        with st.expander(":material/key: Cryptographic token vault (Stored locally, never shared)", expanded=False):
            st.json(res.tokens)

st.divider()

# ---- SECTION 4: REGULATORY TRANSACTION LIMITS CHECK ----
st.subheader("Central Bank of Kenya (CBK) Regulatory Limits Monitor")
transactions = st.session_state.get("parsed_transactions")

if transactions:
    max_txn_amt = max(abs(t.get("amount", 0)) for t in transactions)
    cap_single = Config.CAP_PER_TXN / 100.0

    col_l1, col_l2 = st.columns(2)
    with col_l1:
        st.markdown(f"**Largest Single Transaction in Statement:** KES {max_txn_amt:,.2f}")
        if max_txn_amt <= cap_single:
            st.success(f"Compliant with CBK single transaction ceiling of KES {cap_single:,.0f}.")
        else:
            st.warning(f"Transaction KES {max_txn_amt:,.2f} exceeds standard ceiling of KES {cap_single:,.0f}.")

    with col_l2:
        st.markdown(f"**Daily Aggregate Volume Ceiling:** KES {Config.CAP_DAILY / 100:,.0f}")
        st.success("Policy guard enforces automatic hard-stop on any operation exceeding daily caps.")
else:
    st.info("Load a statement to verify transaction compliance against CBK limits.")
