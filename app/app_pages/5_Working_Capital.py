"""Page 5: Working capital from the business's own records.

Current assets (cash, unpaid invoices, stock at cost) against current
liabilities (overdraft, overdue bills, open standing-order payments), plus
what falls due in the next weeks. Every figure comes from the database:
core/working_capital.py:working_capital_position."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import pandas as pd

from app.auth_ui import require_auth
from auth.middleware import get_business_id
from core.charts import chart_aging_buckets
from core.config import Config
from core.working_capital import AGING_BUCKETS, open_invoices, working_capital_position

st.set_page_config(page_title="Working Capital — Duka", page_icon=":material/credit_card:", layout="wide")
require_auth()

business_id = get_business_id()
if not business_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()


def kes(minor: int) -> str:
    return f"KES {minor / 100:,.0f}"


st.title("Working capital", icon=":material/currency_exchange:")
st.caption("What your business owns and owes right now, and whether cash covers the bills coming up. "
           "Figures come from your statements, invoices, stock and recurring expenses.")

horizon = st.segmented_control("Look ahead", [7, 14, 30, 60], default=30,
                               format_func=lambda d: f"{d} days") or 30
wc = working_capital_position(Config.DB_PATH, business_id, horizon_days=horizon)

w1, w2, w3, w4 = st.columns(4)
w1.metric("Current assets", kes(wc["current_assets_minor"]))
w2.metric("Current liabilities", kes(wc["current_liabilities_minor"]))
nwc = wc["net_working_capital_minor"]
w3.metric("Net working capital", kes(nwc), delta="Positive" if nwc >= 0 else "Negative",
          delta_color="normal" if nwc >= 0 else "inverse")
w4.metric("Current ratio", f"{wc['current_ratio']:.2f}" if wc["current_ratio"] is not None else "No liabilities",
          help="Current assets ÷ current liabilities. Below 1 means you owe more right now than you hold.")

if wc["as_of_statement"]:
    st.caption(f"Cash is the balance at the end of your latest statement ({wc['as_of_statement']}). "
               "Upload a newer statement to update it.")
else:
    st.info("No statement uploaded yet, so cash is KES 0. Upload one on **Upload Statement**.")

col_a, col_l = st.columns(2)
with col_a:
    st.subheader("Current assets")
    st.dataframe(pd.DataFrame([
        {"Item": "Cash (latest statement balance)", "KES": wc["cash_minor"] / 100},
        {"Item": "Unpaid customer invoices", "KES": wc["receivables_minor"] / 100},
        {"Item": "Stock on hand (at cost)", "KES": wc["inventory_minor"] / 100},
    ]), hide_index=True, width="stretch", column_config={"KES": st.column_config.NumberColumn(format="%,.0f")})
with col_l:
    st.subheader("Current liabilities")
    st.dataframe(pd.DataFrame([
        {"Item": "Overdraft owed (incl. fees)", "KES": wc["overdraft_minor"] / 100},
        {"Item": "Overdue recurring bills", "KES": wc["overdue_bills_minor"] / 100},
        {"Item": "Standing-order payments awaiting payment", "KES": wc["open_payments_minor"] / 100},
    ]), hide_index=True, width="stretch", column_config={"KES": st.column_config.NumberColumn(format="%,.0f")})

st.divider()
st.subheader(f"Next {horizon} days")
gap = wc["liquidity_gap_minor"]
c1, c2, c3 = st.columns(3)
c1.metric("Bills falling due", kes(wc["bills_due_minor"]),
          help=None if wc["bills_due_high_minor"] == wc["bills_due_minor"] else
          f"Up to {kes(wc['bills_due_high_minor'])} if variable bills come in 10% higher.")
c2.metric("Invoices you expect to collect", kes(wc["invoices_due_minor"]))
c3.metric("Cash left after bills", kes(gap), delta="Covered" if gap >= 0 else "Shortfall",
          delta_color="normal" if gap >= 0 else "inverse",
          help="Cash + invoices due − what you owe now − bills falling due.")
if gap >= 0 > wc["liquidity_gap_low_minor"]:
    st.warning(f"Covered at average amounts, but if variable bills run 10% high you would be short by "
               f"{kes(-wc['liquidity_gap_low_minor'])}.", icon=":material/warning:")
if gap < 0:
    st.error(f"Your cash and expected collections fall short of your bills by {kes(-gap)} within "
             f"{horizon} days. Collect overdue invoices first, then see **Financing** for options.",
             icon=":material/warning:")

if wc["bills"]:
    st.dataframe(pd.DataFrame([{
        "Due": b["original_due_date"], "Bill": b["label"], "Repeats": b["frequency"],
        "KES": b["amount_minor"] / 100,
        "Range": (f"{b['amount_low_minor'] / 100:,.0f}–{b['amount_high_minor'] / 100:,.0f}"
                  if b["is_variable"] else "fixed"),
        "Status": f"Overdue {b['days_overdue']} days" if b["days_overdue"] else "Upcoming",
    } for b in wc["bills"]]), hide_index=True, width="stretch",
        column_config={"KES": st.column_config.NumberColumn(format="%,.0f")})
else:
    st.caption("No recurring bills in this window. Add rent, salaries and utilities in **Business Setup**.")

st.divider()
st.subheader("Customer invoices (accounts receivable)")
invoices = open_invoices(Config.DB_PATH, business_id)
if invoices:
    buckets = {b: sum(i["balance_due_minor"] for i in invoices if i["bucket"] == b) / 100 for b in AGING_BUCKETS}
    left, right = st.columns([2, 3])
    with left:
        st.altair_chart(chart_aging_buckets(buckets, title="Receivables aging"), width="stretch")
    with right:
        st.dataframe(pd.DataFrame([{
            "Invoice": i["invoice_number"], "Customer": i["customer_name_token"] or "-",
            "Due": i["due_date"][:10], "Balance (KES)": i["balance_due_minor"] / 100,
            "Age": i["bucket"],
        } for i in invoices]), hide_index=True, width="stretch",
            column_config={"Balance (KES)": st.column_config.NumberColumn(format="%,.0f")})
    overdue = [i for i in invoices if i["days_overdue"] > 0]
    if overdue:
        pick = st.selectbox("Draft a reminder for", overdue,
                            format_func=lambda i: f"{i['invoice_number']} — {kes(i['balance_due_minor'])}")
        st.code(f"Habari {pick['customer_name_token'] or ''}, a friendly reminder that invoice "
                f"{pick['invoice_number']} of {kes(pick['balance_due_minor'])} was due on {pick['due_date'][:10]}. "
                "Kindly pay via Till or M-Pesa. Asante!", language="text")
else:
    st.info("No unpaid invoices. Create invoices on the **Invoicing** page to track money customers owe you.")
