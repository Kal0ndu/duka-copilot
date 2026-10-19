"""Approvals — the owner approves what the assistant proposed, with their PIN.

The assistant can only PROPOSE a supplier payment or a loan. Nothing happens
until the owner approves it here with their Duka PIN; it then runs in the
sandbox account (no real money). Standing-order bills are authorized on the
Standing Orders page with the owner's M-Pesa PIN; both share one daily cap.
"""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth
from auth.middleware import get_business_id, get_user_id, invalidate_user_context_on_page

from core.approvals import ApprovalService, committed_today_minor
from core.owner_settings import OwnerPin, load_settings

st.set_page_config(page_title="Approvals — Duka", page_icon=":material/verified_user:", layout="wide")
# ---- Authentication Gate ----
require_auth()

st.title("Approvals")
st.caption(
    "Your assistant can only **propose** payments and loans. Nothing happens until you approve it here "
    "with your Duka PIN. Approved requests run in the **sandbox** account; no real money moves."
)

business_id = get_business_id() or st.session_state.get("business_id")
user_id = get_user_id()
if not business_id or not user_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

service = ApprovalService()
settings = load_settings(service.db_path, business_id)

if not OwnerPin(service.db_path).is_set(business_id):
    st.warning(
        ":material/pin: Set your owner PIN in **Business Setup → Owner rules & PIN** before you can approve anything."
    )

unread = service.unread_count(business_id, user_id)
if unread:
    service.mark_read(business_id, user_id)

# ---- today's limits (shared with standing orders) ----
import sqlite3
from datetime import datetime, timezone
with sqlite3.connect(service.db_path) as _conn:
    used_today = committed_today_minor(_conn, business_id, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
c1, c2, c3 = st.columns(3)
c1.metric("Per-payment cap", f"KES {settings.per_txn_cap_minor / 100:,.0f}")
c2.metric("Daily cap", f"KES {settings.daily_cap_minor / 100:,.0f}")
c3.metric("Used today", f"KES {used_today / 100:,.0f}",
          help="AI requests (waiting, approved or paid) plus standing-order payments you authorized today.")

# ---- waiting for the owner ----
st.subheader(f"Waiting for you{f' ({unread} new)' if unread else ''}", anchor=False)
pending = service.list_actions(business_id, ["PENDING_APPROVAL"])
if not pending:
    st.info("Nothing is waiting. When you ask the assistant to pay a supplier or take a loan, it appears here.",
            icon=":material/check_circle:")

for a in pending:
    with st.container(border=True):
        if a["kind"] == "supplier_payment":
            st.markdown(f"#### :material/payments: Pay **{a['payee_name']}** KES {a['amount_minor'] / 100:,.0f}")
        else:
            st.markdown(
                f"#### :material/account_balance: {a['product_name'] or 'Loan'} of "
                f"KES {a['amount_minor'] / 100:,.0f} over {a['term_days']} days"
            )
        st.caption(f"Request #{a['action_id']} · proposed by {a['created_by'].replace('_', ' ')} · "
                   f"{a['created_at'].replace('T', ' ')[:16]} UTC · expires {a['expires_at'].replace('T', ' ')[:16]} UTC")
        with st.form(f"approve_{a['action_id']}", border=False):
            col_pin, col_ok, col_no = st.columns([2, 1, 1], vertical_alignment="bottom")
            pin = col_pin.text_input("Your Duka PIN", type="password", max_chars=6,
                                     key=f"pin_{a['action_id']}", placeholder="4-6 digits")
            approve = col_ok.form_submit_button(":material/check: Approve", type="primary", width="stretch")
            decline = col_no.form_submit_button(":material/close: Decline", width="stretch")
        if approve:
            result = service.approve_and_execute(
                a["action_id"], business_id, pin, user_id=user_id,
                ui_session_id=str(st.session_state.get("auth_session").jti if st.session_state.get("auth_session") else "ui"),
            )
            if result["status"] == "done":
                st.success(f"Done in the sandbox. Receipt **{result['receipt']}**. "
                           f"Sandbox balance now KES {result['balance_kes']:,.0f}.", icon=":material/task_alt:")
                invalidate_user_context_on_page()
            else:
                st.error(result["reason"], icon=":material/block:")
        if decline:
            try:
                service.decline(a["action_id"], business_id, user_id=user_id)
                st.info("Declined. Nothing was done.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

# ---- standing orders waiting on the other page ----
try:
    from core.standing_orders import StandingOrderService
    bills = [p for p in StandingOrderService().open_payments(business_id)
             if p["status"] in ("pending", "notified", "failed")]
except Exception:
    bills = []
if bills:
    st.subheader("Standing-order bills to authorize", anchor=False)
    st.caption("These are paid with your own M-Pesa PIN on the Standing Orders page. They count towards the same daily cap.")
    for p in bills[:5]:
        st.markdown(f"- **{p['label']}** KES {p['amount_minor'] / 100:,.0f}, due {p['due_date']} "
                    f"({p['priority_band']} priority)")
    st.page_link("pages/12_Standing_Orders.py", label="Open Standing Orders", icon=":material/event_repeat:")

# ---- history ----
st.subheader("History", anchor=False)
history = service.list_actions(business_id, ["APPROVED", "EXECUTED", "REJECTED", "EXPIRED", "BLOCKED"], limit=50)
if not history:
    st.caption("No decisions yet.")
else:
    STATUS = {"EXECUTED": "Done", "REJECTED": "Declined", "EXPIRED": "Expired", "BLOCKED": "Blocked by your rules",
              "APPROVED": "Approved"}
    rows = []
    for a in history:
        what = (f"Pay {a['payee_name']}" if a["kind"] == "supplier_payment"
                else f"Loan: {a['product_name'] or 'offer'}")
        rows.append({
            "#": a["action_id"],
            "When (UTC)": a["created_at"].replace("T", " ")[:16],
            "Request": what,
            "KES": a["amount_minor"] / 100,
            "Status": STATUS.get(a["status"], a["status"]),
            "Receipt / reason": a["receipt"] or (a["reason"] if a["status"] == "BLOCKED" else ""),
        })
    st.dataframe(rows, hide_index=True, width="stretch",
                 column_config={"KES": st.column_config.NumberColumn(format="%,.0f")})
