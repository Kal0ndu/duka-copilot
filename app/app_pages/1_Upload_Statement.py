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

st.set_page_config(page_title="Upload Statement — Duka Copilot", page_icon=":material/upload_file:", layout="wide")
# ---- Authentication Gate ----
require_auth()

# Initialize session
SessionManager.init_session()

st.title("Statements", icon=":material/upload_file:", anchor=False)
st.caption("Upload your M-Pesa statement (PDF or CSV), or explore Duka Copilot with a sample Kenyan small business.")

# ---- Status strip: where uploads go and what is loaded now ----
_profile = SessionManager.get_profile() or {}
with st.container(horizontal=True, gap="small"):
    if get_business_id():
        st.badge("Uploads saved to your ledger", icon=":material/cloud_done:", color="green")
    else:
        st.badge("Session only: finish Business Setup to save", icon=":material/cloud_off:", color="orange")
    st.badge("Names & numbers redacted before analysis", icon=":material/shield_lock:", color="blue")
    if SessionManager.get_transactions():
        st.badge(f"Viewing: {_profile.get('name', 'Active business')}", icon=":material/visibility:", color="gray")

st.space("small")

upload_col, demo_col = st.columns([3, 2], gap="large")

# ---- Option A: File Upload ----
with upload_col:
    with st.container(border=True):
        st.subheader("Upload your statement", icon=":material/cloud_upload:", anchor=False)
        st.caption(
            "Use the PDF statement Safaricom sends you, or a CSV export. "
            "It is saved to your business ledger so Duka Copilot's assistant can answer questions about it."
        )
        uploaded = st.file_uploader(
            "Choose an M-Pesa statement", type=["csv", "pdf"], accept_multiple_files=False,
            label_visibility="collapsed",
        )

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
                with st.expander("Preview first 10 lines", icon=":material/description:", expanded=False):
                    raw_text = raw_bytes.decode("utf-8", errors="replace")
                    st.code("\n".join(raw_text.splitlines()[:10]), language="text")

            if st.button("Process & save statement", icon=":material/rocket_launch:", type="primary",
                         width="stretch"):
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

                        if report is not None:
                            # Saved: every page now reads the business's whole ledger.
                            SessionManager.use_ledger()
                        else:
                            SessionManager.set_transactions(redacted, {
                                "name": "Uploaded Statement (not saved)",
                                "sector": "Retail / Service SME",
                                "icon": ":material/store:",
                            })
                        st.session_state["last_ingest_report"] = report
                        st.rerun()
                except StatementPasswordError as e:
                    st.error(str(e), icon=":material/lock:")
                except Exception as e:
                    st.error(f"Error processing statement: {e}", icon=":material/error:")
        else:
            with st.container(horizontal=True, gap="small"):
                st.badge("1 · Upload PDF or CSV", color="gray")
                st.badge("2 · We redact personal details", color="gray")
                st.badge("3 · Categorised & saved", color="gray")

    report = st.session_state.get("last_ingest_report")
    if report is not None:
        with st.container(border=True):
            if report.status == "duplicate":
                st.info(report.message, icon=":material/info:")
            else:
                st.success(report.message, icon=":material/check_circle:")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Period", f"{report.period_start} → {report.period_end}")
                c2.metric("Need review", f"{report.rows_needs_review:,}")
                c3.metric("Regular payments", report.obligations_detected)
                c4.metric("Flagged rows", report.rows_flagged)
                if report.rows_flagged:
                    st.warning(
                        f"{report.rows_flagged} row(s) contained text that looked like instructions to the AI. "
                        "Their descriptions were removed; the amounts were kept.",
                        icon=":material/gpp_maybe:",
                    )
                for issue in report.validation_issues:
                    st.caption(f":material/warning: {issue}")

# ---- Option B: Pre-loaded Demo Profiles ----
with demo_col:
    st.subheader("Or try a demo business", icon=":material/science:", anchor=False)
    st.caption("Explore analytics, charts and forecasts with realistic Kenyan SME data.")
    for p_id, p_info in MOCK_PROFILES.items():
        with st.container(border=True):
            info_col, btn_col = st.columns([3, 1], vertical_alignment="center")
            with info_col:
                st.markdown(f"**{p_info['icon']} {p_info['name']}**")
                st.caption(p_info["sector"])
            if btn_col.button("Load", key=f"btn_{p_id}", icon=":material/play_arrow:", width="stretch",
                              help=p_info["description"]):
                with st.spinner(f"Loading {p_info['name']} statement..."):
                    txns = load_sample_business(p_id)
                    SessionManager.set_transactions(txns, p_info)
                    st.toast(f"Loaded {len(txns)} transactions for {p_info['name']}!",
                             icon=":material/check_circle:")
                    st.rerun()

# ---- Saved statements: stored with the business, there after every login ----
if get_business_id():
    from core.config import config as _store_cfg
    from core.statement_store import list_statements, remove_statement

    saved = list_statements(_store_cfg.DB_PATH, get_business_id())
    st.divider()
    st.subheader("Your saved statements", icon=":material/folder_open:", anchor=False)
    st.caption("Every statement you upload is kept with your business (as redacted ledger rows), so "
               "you don't need to upload it again after logging out. The original file is not stored.")
    if SessionManager.get_transactions() and _profile.get("source") != "ledger":
        with st.container(horizontal=True, vertical_alignment="center"):
            st.info(f"You are viewing demo data ({_profile.get('name', 'sample')}).", icon=":material/science:",
                    width="stretch")
            if saved and st.button("Show my saved statements", icon=":material/restore:"):
                SessionManager.use_ledger()
                st.rerun()
    if saved:
        for f in saved:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([4, 3, 2, 1], vertical_alignment="center")
                c1.markdown(f":material/description: **{f['filename']}**")
                c1.caption(f"Uploaded {f['uploaded_at'][:16].replace('T', ' ')} UTC")
                c2.markdown(f":material/date_range: {f['period_start'] or '?'} → {f['period_end'] or '?'}")
                if f["active_rows"]:
                    with c3:
                        st.markdown(f"**{f['active_rows']:,}** transactions")
                        if f["risk_flag"]:
                            st.badge("Flagged rows", icon=":material/gpp_maybe:", color="orange")
                    with c4.popover(":material/delete:", help="Remove this statement"):
                        st.caption("Removes its transactions from your ledger, forecasts and assistant.")
                        if st.button("Remove", key=f"rm_file_{f['file_id']}", type="primary"):
                            remove_statement(_store_cfg.DB_PATH, get_business_id(), f["file_id"])
                            invalidate_user_context_on_page()
                            st.session_state.pop("last_ingest_report", None)
                            st.rerun()
                else:
                    with c3:
                        st.badge("Removed", color="gray")
    else:
        with st.container(border=True):
            st.caption(":material/inbox: No statements saved yet. Upload one above to get started.")

# ---- Teach it once: the owner fixes a payee's category one time ----
if get_business_id():
    import sqlite3
    from core.categoriser import teach_category
    from core.config import config as _cfg

    with sqlite3.connect(_cfg.DB_PATH) as _conn:
        _conn.row_factory = sqlite3.Row
        review = _conn.execute(
            """SELECT t.counterparty_token AS token, MIN(t.txn_id) AS txn_id, COUNT(*) AS n,
                      SUM(t.amount_minor) AS total_minor, t.direction, c.code AS category,
                      v.original_value AS name
               FROM transaction_ledger t
               LEFT JOIN category c ON c.category_id = t.category_id
               LEFT JOIN token_vault v ON v.token = t.counterparty_token AND v.business_id = t.business_id
               WHERE t.business_id = ? AND t.needs_review = 1 AND t.voided = 0
                 AND t.counterparty_token IS NOT NULL
               GROUP BY t.counterparty_token, t.direction
               ORDER BY total_minor DESC LIMIT 15""",
            (get_business_id(),),
        ).fetchall()
        codes = [r[0] for r in _conn.execute(
            "SELECT code FROM category WHERE active = 1 ORDER BY kind, sort_order")]
    if review:
        st.divider()
        st.subheader("Check these payees once", icon=":material/school:", anchor=False)
        st.caption(
            "Duka Copilot wasn't sure about these. Pick the right category once and every past and future "
            "payment to that payee will follow it."
        )
        with st.container(border=True):
            for i, r in enumerate(review):
                if i:
                    st.divider()
                col1, col2, col3 = st.columns([3, 2, 1], vertical_alignment="center")
                with col1:
                    st.markdown(f"**{r['name'] or r['token']}**")
                    with st.container(horizontal=True, gap="small"):
                        if r["direction"] == "in":
                            st.badge("Money in", icon=":material/south_west:", color="green")
                        else:
                            st.badge("Money out", icon=":material/north_east:", color="red")
                        st.caption(f"{r['n']} payment(s) · KES {r['total_minor'] / 100:,.0f}")
                current = r["category"] if r["category"] in codes else codes[0]
                choice = col2.selectbox(
                    "Category", codes, index=codes.index(current), key=f"teach_{r['token']}_{r['direction']}",
                    format_func=lambda c: c.replace("_", " ").title(), label_visibility="collapsed",
                )
                if col3.button("Save", key=f"teach_btn_{r['token']}_{r['direction']}", icon=":material/check:",
                               width="stretch"):
                    result = teach_category(_cfg.DB_PATH, get_business_id(), r["txn_id"], choice)
                    invalidate_user_context_on_page()
                    st.toast(f"Learned: {r['name'] or r['token']} → {choice.replace('_', ' ').title()} "
                             f"({result['updated']} transaction(s) updated)")
                    st.rerun()

# ---- Display Current Loaded Data Summary ----
txns = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if txns:
    st.divider()
    active_name = profile.get("name", "Active Business") if profile else "Active Business"
    active_icon = profile.get("icon", ":material/store:") if profile else ":material/store:"
    st.subheader(active_name, icon=active_icon, anchor=False)
    if profile and profile.get("sector"):
        st.caption(profile["sector"])

    credits = sum(r.get("amount", 0) for r in txns if r.get("amount", 0) > 0)
    debits = sum(abs(r.get("amount", 0)) for r in txns if r.get("amount", 0) < 0)
    net = credits - debits

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Transactions", f"{len(txns):,}", border=True)
    kpi2.metric("Money in", f"KES {credits:,.0f}", border=True)
    kpi3.metric("Money out", f"KES {debits:,.0f}", border=True)
    kpi4.metric("Net cashflow", f"KES {net:,.0f}", delta=f"{net:,.0f}", border=True)

    st.markdown("##### Ledger preview")
    st.caption("First 30 rows, parsed and with personal details redacted.")
    table_data = []
    for r in txns[:30]:
        amt = r.get("amount", 0)
        table_data.append({
            "Date": r.get("date", r.get("local_date", "")),
            "Direction": "In" if amt > 0 or r.get("direction") == "in" else "Out",
            "Amount": abs(amt),
            "Category": str(r.get("category", "Uncategorised")).replace("_", " ").title(),
            "Counterparty": r.get("counterparty", r.get("counterparty_token", "")),
            "Channel": r.get("channel", "other").title(),
        })

    st.dataframe(
        table_data, width="stretch", hide_index=True,
        column_config={
            "Amount": st.column_config.NumberColumn("Amount (KES)", format="accounting"),
            "Counterparty": st.column_config.TextColumn("Counterparty (redacted)"),
        },
    )

    st.markdown("##### Next steps")
    with st.container(horizontal=True, gap="small"):
        st.page_link("app_pages/2_Analytics.py", label="Analytics", icon=":material/analytics:")
        st.page_link("app_pages/3_Cashflow_Forecast.py", label="Cashflow forecast", icon=":material/trending_up:")
        st.page_link("app_pages/4_Party_Intelligence.py", label="Customers & suppliers", icon=":material/groups:")
        st.page_link("app_pages/5_Working_Capital.py", label="Working capital",
                     icon=":material/currency_exchange:")
        st.page_link("app_pages/3_Financing.py", label="Financing", icon=":material/savings:")
