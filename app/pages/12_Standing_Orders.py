"""Standing Orders — scheduled payments ranked by priority, authorized by the owner.

Duka reminds and ranks; it never pays. Each payment needs the owner to tap
Authorize here and then enter their M-Pesa PIN on the prompt sent to their phone.
"""
import streamlit as st
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth
from auth.middleware import get_business_id, get_user_id, invalidate_user_context_on_page

from core.standing_orders import CADENCES, KINDS, PaymentNotAllowed, StandingOrderService
from integrations.mpesa_daraja import DarajaError

st.set_page_config(page_title="Standing Orders — Duka", page_icon=":material/event_repeat:", layout="wide")
# ---- Authentication Gate ----
require_auth()

st.title("Standing Orders")
st.caption(
    "Set up regular payments like M-Pesa Ratiba. Duka reminds you and ranks what to pay first. "
    "Nothing is paid until you tap **Authorize** and enter your M-Pesa PIN on your phone."
)

business_id = get_business_id() or st.session_state.get("business_id")
user_id = get_user_id()
if not business_id or not user_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

service = StandingOrderService()

# Scheduler tick on page load (idempotent); cron runs the same thing for SMS.
try:
    service.run(business_id)
except Exception as e:
    st.error(f"Could not refresh scheduled payments: {e}")

BAND_COLOR = {"critical": "red", "high": "orange", "medium": "blue", "low": "gray"}
STATUS_LABEL = {
    "pending": "Waiting", "notified": "Reminder sent", "authorized": "Authorizing…",
    "stk_sent": "Check your phone", "failed": "Not completed", "paid": "Paid", "skipped": "Skipped",
}
KIND_LABEL = {k: k.replace("_", " ").title() for k in KINDS}

try:
    daraja = service.daraja
except DarajaError as e:
    st.error(f":material/block: {e}")
    st.stop()
if daraja.env == "simulated":
    st.info(":material/science: Payments are **simulated** (DARAJA_ENV=simulated). No M-Pesa prompt is sent.")
elif not daraja.configured:
    st.warning(
        ":material/key: M-Pesa Daraja is not configured yet, so Authorize will not work. "
        "Missing in `.env`: " + ", ".join(daraja.missing_settings())
    )
elif daraja.env == "sandbox":
    st.caption(
        ":material/science: Daraja **sandbox**: prompts are real but use test money, and every payment goes "
        f"to the test paybill {daraja.shortcode}. The till/paybill below is used as the account reference."
    )

contact = service.get_contact(business_id, user_id)
highlight = st.query_params.get("pay")
unread = service.unread_count(business_id, user_id)

tab_pay, tab_orders, tab_settings, tab_history = st.tabs([
    f"To authorize{f' ({unread} new)' if unread else ''}",
    "Standing orders",
    "Notification settings",
    "History",
])

# ---- Payments to authorize ----
with tab_pay:
    payments = service.open_payments(business_id)
    if unread:
        service.mark_read(business_id, user_id)
    if not payments:
        st.info("Nothing to pay right now. Upcoming payments show here a few days before they are due.")
    if payments and not contact:
        st.warning("Add your M-Pesa number in **Notification settings** to authorize payments.")

    for p in payments:
        with st.container(border=True):
            top_l, top_r = st.columns([3, 1])
            with top_l:
                is_target = highlight and str(p["payment_id"]) == str(highlight)
                st.markdown(f"#### {':material/arrow_forward: ' if is_target else ''}{p['label']}")
                st.badge(f"{p['priority_band'].upper()} · {p['priority_score']}",
                         color=BAND_COLOR[p["priority_band"]])
                dest = p["destination_number"] if p["destination_type"] != "phone" else "phone ···" + p["destination_number"][-3:]
                st.caption(
                    f"{KIND_LABEL.get(p['kind'], p['kind'])} · due {p['due_date']} · "
                    f"{p['destination_type'].title()} {dest}"
                    + (f" · Acc {p['account_reference']}" if p["account_reference"] else "")
                )
                for reason in p["priority_reasons"]:
                    st.markdown(f"- {reason}")
            with top_r:
                st.metric("Amount", f"KES {p['amount_minor'] / 100:,.0f}")
                st.caption(f"Status: **{STATUS_LABEL.get(p['status'], p['status'])}**")

            b1, b2, _ = st.columns([1, 1, 2])
            pid = p["payment_id"]
            if p["status"] in ("pending", "notified", "failed"):
                if b1.button(":material/verified_user: Authorize & pay", key=f"auth_{pid}", type="primary",
                             disabled=not contact, width="stretch"):
                    try:
                        res = service.authorize_and_push(pid, business_id, user_id)
                        st.toast(f"M-Pesa prompt sent to {res['phone_masked']}. Enter your PIN to pay.",
                                 icon=":material/smartphone:")
                        st.rerun()
                    except PaymentNotAllowed as e:
                        st.error(str(e))
                if b2.button("Skip this time", key=f"skip_{pid}", width="stretch"):
                    try:
                        service.skip(pid, business_id, user_id)
                        st.rerun()
                    except PaymentNotAllowed as e:
                        st.error(str(e))
            elif p["status"] == "stk_sent":
                st.caption(":material/smartphone: Check your phone and enter your M-Pesa PIN, then confirm below.")
                if b1.button(":material/refresh: Check payment", key=f"chk_{pid}", type="primary", width="stretch"):
                    res = service.check_status(pid, business_id)
                    if res["state"] == "success":
                        st.toast("Payment confirmed.", icon=":material/check_circle:")
                        invalidate_user_context_on_page()
                        st.rerun()
                    elif res["state"] == "pending":
                        st.info(f"Still waiting for M-Pesa: {res['result_desc']}")
                    else:
                        st.warning(f"Payment not completed ({res['state']}): {res['result_desc']}. You can try again.")
                        st.rerun()

    if payments:
        st.caption(
            "Priority is calculated from due date, type of payment, late fees and whether your current "
            "balance covers it. Ask the Duka assistant to explain it."
        )

# ---- Standing orders ----
with tab_orders:
    with st.expander(":material/add: New standing order", expanded=not service.list_orders(business_id)):
        with st.form("new_standing_order", clear_on_submit=True):
            c1, c2 = st.columns(2)
            label = c1.text_input("Name", placeholder="e.g., Shop rent")
            kind = c2.selectbox("Type", KINDS, format_func=lambda k: KIND_LABEL[k])
            c3, c4, c5 = st.columns(3)
            dest_type = c3.selectbox("Pay to", ["paybill", "till", "phone"], format_func=str.title)
            dest_number = c4.text_input("Paybill / till / phone number")
            account_ref = c5.text_input("Account number (paybill only)")
            c6, c7, c8 = st.columns(3)
            amount = c6.number_input("Amount (KES)", min_value=1, step=100, value=1000)
            cadence = c7.selectbox("How often", CADENCES, index=CADENCES.index("monthly"),
                                   format_func=lambda c: c.replace("_", "-").title())
            start = c8.date_input("First payment date", value=date.today() + timedelta(days=3))
            c9, c10, c11 = st.columns(3)
            remind = c9.number_input("Remind me (days before)", min_value=0, max_value=14, value=2)
            penalty = c10.number_input("Late fee if missed (KES)", min_value=0, step=100, value=0)
            end = c11.date_input("End date (optional)", value=None)
            essential = st.checkbox("Essential (rent, loans, wages, utilities)", value=True)
            if st.form_submit_button("Create standing order", type="primary"):
                try:
                    service.create_order(
                        business_id, user_id, label, kind, dest_type, dest_number, int(amount), cadence,
                        start, end_date=end, account_reference=account_ref, essential=essential,
                        late_penalty_kes=int(penalty), remind_days_before=int(remind),
                    )
                    invalidate_user_context_on_page()
                    st.success("Standing order created.")
                    st.rerun()
                except (ValueError, PaymentNotAllowed) as e:
                    st.error(str(e))

    orders = service.list_orders(business_id)
    if not orders:
        st.info("No standing orders yet.")
    for o in orders:
        with st.container(border=True):
            l, m, r = st.columns([3, 1, 1])
            l.markdown(f"**{o['label']}** · {KIND_LABEL.get(o['kind'], o['kind'])}")
            l.caption(
                f"KES {o['amount_minor'] / 100:,.0f} {o['cadence'].replace('_', '-')} to "
                f"{o['destination_type']} {o['destination_number']} · next due {o['next_due'] or '—'}"
            )
            m.caption(f"Status: **{o['status']}**")
            if o["status"] == "active":
                if m.button("Pause", key=f"pause_{o['standing_order_id']}"):
                    service.set_order_status(business_id, o["standing_order_id"], "paused")
                    st.rerun()
            else:
                if m.button("Resume", key=f"resume_{o['standing_order_id']}"):
                    service.set_order_status(business_id, o["standing_order_id"], "active")
                    st.rerun()
            if r.button("End", key=f"end_{o['standing_order_id']}"):
                service.set_order_status(business_id, o["standing_order_id"], "ended")
                invalidate_user_context_on_page()
                st.rerun()

# ---- Notification settings ----
with tab_settings:
    st.markdown(
        "Payment prompts and SMS reminders go to **your own** M-Pesa number. "
        "It must be the number you log in with."
    )
    if contact:
        st.success(f"Using {contact['phone_masked']} · SMS reminders {'on' if contact['sms_enabled'] else 'off'}")
    with st.form("contact_form"):
        phone = st.text_input("M-Pesa phone number", placeholder="0712 345 678")
        sms_on = st.checkbox("Send SMS reminders", value=contact["sms_enabled"] if contact else True)
        if st.form_submit_button("Save", type="primary"):
            try:
                masked = service.set_contact(business_id, user_id, phone, sms_on)
                st.success(f"Saved {masked}.")
                st.rerun()
            except (ValueError, PaymentNotAllowed) as e:
                st.error(str(e))

# ---- History ----
with tab_history:
    hist = service.history(business_id)
    if not hist:
        st.info("No completed or skipped payments yet.")
    else:
        st.dataframe(
            [
                {
                    "Payment": h["label"],
                    "Due": h["due_date"],
                    "Amount (KES)": f"{h['amount_minor'] / 100:,.0f}",
                    "Status": STATUS_LABEL.get(h["status"], h["status"]),
                    "Paid at": h["paid_at"] or "",
                }
                for h in hist
            ],
            width="stretch",
        )
