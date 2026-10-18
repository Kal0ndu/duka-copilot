"""Page 1: Upload and preview a mobile-money statement or load sample SME profile."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.adapters.mobile_money_ke import MobileMoneyKeAdapter
from core.redaction import Redactor
from core.categoriser import Categoriser
from app.sample_loader import MOCK_PROFILES, load_sample_business
from app.session_helpers import SessionManager

st.set_page_config(page_title="Upload Statement — Duka", page_icon="📄", layout="wide")
# ---- Authentication Gate ----
require_auth()


st.title("📄 Statement Upload & SME Profiles")
st.caption("Upload your M-Pesa / mobile money statement CSV or choose a pre-loaded Kenyan small business profile.")

# Initialize session
SessionManager.init_session()

# ---- Option A: Pre-loaded Demo Profiles ----
st.subheader("⚡ Quick-Load Demo Business Profiles")
st.markdown("Instantly test Duka's analytics, charts, and forecasts with realistic Kenyan enterprise data:")

demo_cols = st.columns(3)

for idx, (p_id, p_info) in enumerate(MOCK_PROFILES.items()):
    with demo_cols[idx]:
        st.markdown(f"### {p_info['icon']} {p_info['name']}")
        st.caption(f"**Sector:** {p_info['sector']}")
        st.write(p_info["description"])
        if st.button(f"Load {p_info['name'].split()[0]}'s Data", key=f"btn_{p_id}", use_container_width=True):
            with st.spinner(f"Loading {p_info['name']} statement..."):
                txns = load_sample_business(p_id)
                SessionManager.set_transactions(txns, p_info)
                st.success(f"✅ Loaded {len(txns)} transactions for {p_info['name']}!")
                st.rerun()

st.divider()

# ---- Option B: File Upload ----
st.subheader("📤 Upload Custom Statement (CSV)")
uploaded = st.file_uploader("Choose an M-Pesa CSV statement export", type=["csv"], accept_multiple_files=False)

if uploaded:
    raw_bytes = uploaded.read()
    raw_text = raw_bytes.decode("utf-8", errors="replace")

    with st.expander("Raw File Preview (first 10 lines)", expanded=False):
        st.code("\n".join(raw_text.splitlines()[:10]), language="text")

    if st.button("🔍 Parse & Redact PII", type="primary", use_container_width=True):
        adapter = MobileMoneyKeAdapter()
        try:
            with st.spinner("Parsing transactions & tokenizing PII..."):
                parsed = adapter.parse(raw_bytes)
                redactor = Redactor()
                redacted = redactor.redact_transactions(parsed)
                categoriser = Categoriser()

                for r in redacted:
                    cur_cat = str(r.get("category", "")).lower()
                    if not cur_cat or cur_cat in ("uncategorised", "unclassified", "other"):
                        res = categoriser.categorise(
                            description=r.get("description", r.get("counterparty", "")),
                            channel=r.get("channel", "other"),
                            direction=r.get("direction", "out"),
                            amount_minor=r.get("amount_minor", int(round(abs(r.get("amount", 0)) * 100))),
                            counterparty=r.get("counterparty", ""),
                        )
                        r["category"] = res.category_code

                st.session_state["parsed_transactions"] = redacted
                st.session_state["business_profile"] = {
                    "name": "Custom Uploaded Business",
                    "sector": "Retail / Service SME",
                    "icon": "🏪",
                }
                SessionManager.set_transactions(
                    redacted,
                    {
                        "name": "Custom Uploaded Business",
                        "sector": "Retail / Service SME",
                        "icon": "🏪",
                    }
                )
                st.success(f"Successfully processed {len(redacted)} transactions!")
                st.rerun()
        except Exception as e:
            st.error(f"Error parsing statement: {e}")

# ---- Display Current Loaded Data Summary ----
txns = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if txns:
    st.divider()
    active_name = profile.get("name", "Active Business") if profile else "Active Business"
    active_icon = profile.get("icon", "🏪") if profile else "🏪"
    st.subheader(f"📋 Current Statement: {active_icon} {active_name}")

    credits = sum(r.get("amount", 0) for r in txns if r.get("amount", 0) > 0)
    debits = sum(abs(r.get("amount", 0)) for r in txns if r.get("amount", 0) < 0)
    net = credits - debits

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Total Transactions", f"{len(txns):,}")
    kpi2.metric("Total Inflow (Revenue)", f"KES {credits:,.0f}")
    kpi3.metric("Total Outflow (Expenses)", f"KES {debits:,.0f}")
    kpi4.metric("Net Cashflow", f"KES {net:,.0f}", delta=f"{net:,.0f}")

    st.markdown("#### Parsed & PII-Redacted Ledger (Sample View)")
    table_data = []
    for r in txns[:30]:
        amt = r.get("amount", 0)
        table_data.append({
            "Date": r.get("date", r.get("local_date", "")),
            "Direction": "Inflow (Sale)" if amt > 0 or r.get("direction") == "in" else "Outflow (Expense)",
            "Amount (KES)": f"{abs(amt):,.2f}",
            "Category": str(r.get("category", "Uncategorised")).replace("_", " ").title(),
            "Counterparty (Redacted)": r.get("counterparty", r.get("counterparty_token", "")),
            "Channel": r.get("channel", "other").title(),
        })

    st.dataframe(table_data, use_container_width=True)

    st.info("💡 **Next Steps:** Navigate using the sidebar to explore **2. Analytics**, **3. Cashflow Forecast**, **4. Party Intelligence**, **5. Working Capital**, and **6. Financing Advisor**.")
