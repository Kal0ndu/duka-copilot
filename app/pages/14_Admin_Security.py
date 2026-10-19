"""Admin only: audit trail, security events and accounts.

Every read goes through AdminAuditService, which re-checks the admin role
against the database, so the page gate is not the only protection."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import pandas as pd

from app.auth_ui import require_admin
from auth.rbac import AdminAuditService
from core.config import Config

st.set_page_config(page_title="Admin — Security", page_icon=":material/admin_panel_settings:", layout="wide")
session = require_admin("admin_security_page")

svc = AdminAuditService(Config.DB_PATH)
uid = session.user_id

st.title("Security monitoring", icon=":material/admin_panel_settings:")
st.caption("Visible to the administrator only. Every event below was recorded by the running system.")

verdict = svc.verify_chain(uid)
security = svc.security_events(uid, limit=500)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Audit events", verdict.get("checked", 0))
k2.metric("Security events", len(security))
k3.metric("Denied / blocked", sum(1 for e in security if e["decision"] in ("denied", "blocked")))
k4.metric("Failed logins", sum(1 for e in security if e["event_type"] == "LOGIN_FAILED"))

if verdict.get("valid") and verdict.get("checked", 0) > 0:
    st.success(f"Audit chain verified across {verdict['checked']} event(s): no entry was changed or removed.",
               icon=":material/verified:")
elif verdict.get("valid"):
    st.info("The audit log is empty.")
else:
    st.error(f"Audit chain check FAILED at seq #{verdict.get('first_break_seq')}: possible tampering.",
             icon=":material/gpp_bad:")

tab_sec, tab_all, tab_summary, tab_accounts = st.tabs(
    ["Security events", "Full audit trail", "Summary", "Accounts"])

with tab_sec:
    st.caption("Failed logins, lockouts, denied access, blocked escalation, prompt-injection and guard blocks: "
               "what happened, how it was detected and how it was handled.")
    if security:
        st.dataframe(pd.DataFrame([{
            "Seq": e["seq"], "Time (UTC)": e["ts"], "Event": e["event_type"],
            "Outcome": e["decision"] or "-", "Severity": e["details"].get("severity", "-"),
            "User": e["details"].get("user_id") or e["entity_id"],
            "Business": e["business_id"],
            "Resource": e["details"].get("resource") or e["tool"] or "-",
            "Detected by": e["details"].get("detection") or e["details"].get("rule") or "-",
            "Handled": e["details"].get("handling") or "-",
        } for e in security]), hide_index=True, width="stretch")
    else:
        st.info("No security events recorded yet.")

with tab_all:
    events = svc.recent_events(uid, limit=300)
    if events:
        st.dataframe(pd.DataFrame([{
            "Seq": e["seq"], "Time (UTC)": e["ts"], "Actor": e["actor"], "Event": e["event_type"],
            "Business": e["business_id"], "Tool": e["tool"] or "-", "Decision": e["decision"] or "-",
            "Hash": e["hash"][:16] + "…", "Prev": e["prev_hash"][:16] + "…",
        } for e in events]), hide_index=True, width="stretch")
    else:
        st.info("No audit events recorded yet.")

with tab_summary:
    summary = svc.summary(uid)
    if summary:
        st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")

with tab_accounts:
    st.caption("Roles can only be changed on the server with scripts/set_admin.py. There is one admin.")
    st.dataframe(pd.DataFrame(svc.accounts(uid)), hide_index=True, width="stretch")
