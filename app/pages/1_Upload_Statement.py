"""Page 1: Upload and preview a mobile-money statement or load sample SME profile."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.redaction import Redactor
from core.categoriser import Categoriser
from app.sample_loader import MOCK_PROFILES, load_sample_business
from app.session_helpers import SessionManager
from auth.middleware import get_business_id, get_user_id, invalidate_user_context_on_page
from core.adapters.mpesa_pdf import StatementPasswordError
from core.ingestion import StatementIngestor

st.set_page_config(page_title="Upload Statement — Duka", page_icon=":material/upload_file:", layout="wide")
# ---- Authentication Gate ----
require_auth()


st.title("Statement Upload & SME Profiles")
st.caption("Upload your M-Pesa statement (PDF or CSV) or choose a pre-loaded Kenyan small business profile.")

# Initialize session
SessionManager.init_session()

# ---- Option A: Pre-loaded Demo Profiles ----
st.subheader(" Quick-Load Demo Business Profiles")
st.markdown("Instantly test Duka's analytics, charts, and forecasts with realistic Kenyan enterprise data:")

demo_cols = st.columns(3)

for idx, (p_id, p_info) in enumerate(MOCK_PROFILES.items()):
    with demo_cols[idx]:
        st.markdown(f"### {p_info['icon']} {p_info['name']}")
        st.caption(f"**Sector:** {p_info['sector']}")
        st.write(p_info["description"])
        if st.button(f"Load {p_info['name'].split()[0]}'s Data", key=f"btn_{p_id}", width="stretch"):
            with st.spinner(f"Loading {p_info['name']} statement..."):
                txns = load_sample_business(p_id)
                SessionManager.set_transactions(txns, p_info)
                st.success(f"Loaded {len(txns)} transactions for {p_info['name']}!")
                st.rerun()

st.divider()

# ---- Option B: File Upload ----
st.subheader("Upload Your Statement (CSV or PDF)")
st.caption(
    "Upload the M-Pesa statement Safaricom sends you (PDF) or a CSV export. "
    "It is saved to your business ledger so Duka's assistant can answer questions about it."
)
uploaded = st.file_uploader("Choose an M-Pesa statement", type=["csv", "pdf"], accept_multiple_files=False)

if uploaded:
    raw_bytes = uploaded.getvalue()
    is_pdf = raw_bytes[:5] == b"%PDF-"
    password = None
    if is_pdf:
        password = st.text_input(
            "Statement password (if any)", type="password",
            help="M-Pesa PDF statements are usually locked with your ID number.",
        )
    else:
        with st.expander("Raw File Preview (first 10 lines)", expanded=False):
            raw_text = raw_bytes.decode("utf-8", errors="replace")
            st.code("\n".join(raw_text.splitlines()[:10]), language="text")

    if st.button(":material/search: Process & Save Statement", type="primary", width="stretch"):
        business_id = get_business_id()
        user_id = get_user_id()
        ingestor = StatementIngestor()
        try:
            with st.spinner("Parsing, redacting PII and saving to your ledger..."):
                parsed = ingestor.parse(raw_bytes, password=password or None)
                report = None
                if business_id:
                    report = ingestor.ingest(
                        raw_bytes, uploaded.name, business_id, user_id, password=password or None,
                    )
                    invalidate_user_context_on_page()

                redacted = Redactor().redact_transactions(parsed)
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

                profile = {
                    "name": "Uploaded Statement",
                    "sector": "Retail / Service SME",
                    "icon": ":material/store:",
                }
                SessionManager.set_transactions(redacted, profile)
                st.session_state["last_ingest_report"] = report
                st.rerun()
        except StatementPasswordError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Error processing statement: {e}")

report = st.session_state.get("last_ingest_report")
if report is not None:
    if report.status == "duplicate":
        st.info(f":material/info: {report.message}")
    else:
        st.success(f":material/check_circle: {report.message}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Period", f"{report.period_start} → {report.period_end}")
        c2.metric("Need review", f"{report.rows_needs_review:,}")
        c3.metric("Regular payments found", report.obligations_detected)
        c4.metric("Flagged rows", report.rows_flagged)
        if report.rows_flagged:
            st.warning(
                f":material/gpp_maybe: {report.rows_flagged} row(s) contained text that looked like "
                "instructions to the AI. Their descriptions were removed; the amounts were kept."
            )
        for issue in report.validation_issues:
            st.caption(f":material/warning: {issue}")
elif uploaded is None and not get_business_id():
    st.caption(
        ":material/info: Finish **Business Setup** first so uploads are saved to your ledger. "
        "Until then they are only kept for this session."
    )

# ---- Display Current Loaded Data Summary ----
txns = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if txns:
    st.divider()
    active_name = profile.get("name", "Active Business") if profile else "Active Business"
    active_icon = profile.get("icon", ":material/store:") if profile else ":material/store:"
    st.subheader(f"Current Statement: {active_icon} {active_name}")

    credits = sum(r.get("amount", 0) for r in txns if r.get("amount", 0) > 0)
    debits = sum(abs(r.get("amount", 0)) for r in txns if r.get("amount", 0) < 0)
    net = credits - debits

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Total Transactions", f"{len(txns):,}")
    kpi2.metric("Total Inflow (Revenue)", f"KES {credits:,.0f}")
    kpi3.metric("Total Outflow (Expenses)", f"KES {debits:,.0f}")
    kpi4.metric("Net Cashflow", f"KES {net:,.0f}", delta=f"{net:,.0f}")

    st.markdown("##### Parsed & PII-Redacted Ledger (Sample View)")
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

    st.dataframe(table_data, width="stretch")

    st.info("**Next Steps:** Navigate using the sidebar to explore **2. Analytics**, **3. Cashflow Forecast**, **4. Party Intelligence**, **5. Working Capital**, and **6. Financing Advisor**.")
