"""Page 7: Payment limits and privacy, from the business's own data. (The
audit trail and security events are admin-only: app_pages/14_Admin_Security.py.)"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth
from auth.middleware import get_business_id
from core.charts import chart_daily_outflow_vs_limit
from core.config import Config
from core.owner_settings import load_settings
from core.redaction import Redactor

st.set_page_config(page_title="Privacy & Compliance — Duka", page_icon=":material/shield:", layout="wide")
require_auth()

business_id = get_business_id()
if not business_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

st.title("Privacy & compliance", icon=":material/policy:")
st.caption("How Duka limits payments and protects your data, checked against your own records.")

settings = load_settings(Config.DB_PATH, business_id)
with sqlite3.connect(Config.DB_PATH) as conn:
    out_rows = conn.execute(
        """SELECT local_date, amount_minor FROM transaction_ledger
           WHERE business_id = ? AND direction = 'out' AND voided = 0""", (business_id,)).fetchall()
    vault = conn.execute("SELECT entity_type, COUNT(*) FROM token_vault WHERE business_id = ? GROUP BY entity_type",
                         (business_id,)).fetchall()
    flagged = conn.execute(
        """SELECT COUNT(*) FROM transaction_ledger WHERE business_id = ? AND voided = 0
           AND description_redacted = '[flagged content removed]'""", (business_id,)).fetchone()[0]
    statements = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(row_count), 0) FROM source_file WHERE business_id = ? AND status = 'loaded'",
        (business_id,)).fetchone()

# ---- safety status ----
m1, m2, m3, m4 = st.columns(4)
m1.metric("Payments sandbox", "On" if Config.SANDBOX_ONLY else "Off — live", border=True,
          help="With the sandbox on, no real money can leave your account from Duka.")
m2.metric("Your per-payment limit", f"KES {settings.per_txn_cap_minor / 100:,.0f}", border=True,
          help="Set in Business setup → Limits and preferences.")
m3.metric("Your daily limit", f"KES {settings.daily_cap_minor / 100:,.0f}", border=True,
          help="Total Duka may pay out for you in one day.")
m4.metric("Your loan limit", f"KES {settings.loan_cap_minor / 100:,.0f}", border=True,
          help="The most Duka will help you borrow at once.")

# ---- limits vs your real payments ----
st.subheader("Your limits against your real payments", icon=":material/speed:", anchor=False)
st.caption("Any payment Duka makes for you that is above **your** limit is stopped and needs your approval. "
           "Below, your statement history is checked against the same limits, so you can see whether they fit "
           "how you actually pay.")

out = pd.DataFrame(out_rows, columns=["date", "minor"])
your_txn, your_day = settings.per_txn_cap_minor / 100, settings.daily_cap_minor / 100
default_txn, default_day = Config.CAP_PER_TXN / 100, Config.CAP_DAILY / 100   # starting values, not a ceiling
if out.empty:
    st.info("Upload a statement to compare your payments with these limits.", icon=":material/info:")
else:
    daily = out.groupby("date", as_index=False)["minor"].sum()
    daily["KES"] = daily["minor"] / 100
    biggest_payment = out["minor"].max() / 100
    biggest_day = daily.loc[daily["KES"].idxmax()]
    payments_over = int((out["minor"] / 100 > your_txn).sum())
    days_over = int((daily["KES"] > your_day).sum())

    st.dataframe(pd.DataFrame([
        {"Limit": "One payment", "Your limit (KES)": your_txn, "Duka default (KES)": default_txn,
         "Your largest (KES)": biggest_payment, "Used": biggest_payment / your_txn if your_txn else 0,
         "Times over your limit": payments_over},
        {"Limit": "One day", "Your limit (KES)": your_day, "Duka default (KES)": default_day,
         "Your largest (KES)": float(biggest_day["KES"]), "Used": float(biggest_day["KES"]) / your_day if your_day else 0,
         "Times over your limit": days_over},
    ]), hide_index=True, width="stretch", column_config={
        "Your limit (KES)": st.column_config.NumberColumn(format="accounting"),
        "Duka default (KES)": st.column_config.NumberColumn(
            format="accounting", help="The limit a new business starts with, before you set your own."),
        "Your largest (KES)": st.column_config.NumberColumn(format="accounting", help="From your saved statements"),
        "Used": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1,
                                                help="Largest seen as a share of your limit (bar caps at 100%)"),
        "Times over your limit": st.column_config.NumberColumn(help="Payments or days in your statements above your limit"),
    })
    if payments_over or days_over:
        st.warning(f"{payments_over} payment(s) and {days_over} day(s) in your statements went above your limits. "
                   "If Duka had made them, it would have stopped and asked you. Raise the limits in "
                   "**Business setup** if these were normal for your business.", icon=":material/warning:")
    else:
        st.success("Everything in your statements fits inside your limits.", icon=":material/check_circle:")

    st.caption("Each bar is what you paid out that day; the amber line is your daily limit. Grey bars are within "
               "it, red bars are days above it. Hover for the exact amount.")
    limit_lines = [{"label": f"Your daily limit · KES {your_day:,.0f}", "KES": your_day}]
    st.altair_chart(chart_daily_outflow_vs_limit(daily[["date", "KES"]], limit_lines), width="stretch")
    if days_over:
        with st.expander(f"Days above your daily limit ({days_over})", icon=":material/event_busy:"):
            st.dataframe(
                daily[daily["KES"] > your_day].sort_values("KES", ascending=False)
                .assign(date=lambda d: pd.to_datetime(d["date"]))[["date", "KES"]]
                .rename(columns={"date": "Date", "KES": "Paid out (KES)"}),
                hide_index=True, width="stretch", column_config={
                    "Date": st.column_config.DateColumn(format="ddd D MMM YYYY"),
                    "Paid out (KES)": st.column_config.NumberColumn(format="accounting")})

# ---- privacy: what is actually stored ----
st.subheader("What Duka keeps about your customers", icon=":material/encrypted:", anchor=False)
names = sum(n for t, n in vault)
p1, p2, p3 = st.columns(3)
p1.metric("Names stored as tokens", f"{names:,}", border=True,
          help="Payee and customer names are replaced by tokens like PARTY_3F9A… in your ledger and in anything "
               "sent to the AI. The real name stays only on this device.")
p2.metric("Statements saved", f"{statements[0]:,}", f"{statements[1]:,} rows", delta_color="off", border=True,
          help="Only the redacted rows are kept. The original PDF or CSV is not stored.")
p3.metric("Suspicious rows quarantined", f"{flagged:,}", border=True,
          help="Rows whose text looked like instructions to the AI. Their text was removed; the amounts were kept.")

# ---- try the redaction yourself ----
st.subheader("Try it: what the AI sees", icon=":material/visibility_off:", anchor=False)
st.caption("Type any payment text. Phone numbers, ID numbers, emails and reference numbers are swapped for "
           "placeholders before anything leaves your device.")
test_text = st.text_area(
    "Text to check",
    value="Received KES 4,500 from 0722123456 (John Mwangi, ID 28472910) for stock purchase",
    height=80,
)
if test_text:
    res = Redactor().redact(test_text)
    before, after = st.columns(2)
    with before:
        st.caption("Your text")
        st.code(test_text, language=None, wrap_lines=True)
    with after:
        st.caption("What the AI receives")
        st.code(res.safe_text, language=None, wrap_lines=True)
    if res.tokens:
        st.success(f"{len(res.tokens)} sensitive item(s) hidden.", icon=":material/shield:")
        st.dataframe(pd.DataFrame([
            {"Placeholder": token, "Type": token.strip("<>").rsplit("_", 1)[0].title(), "Original (kept on device)": orig}
            for token, orig in res.tokens.items()]), hide_index=True, width="stretch")
    else:
        st.caption("Nothing sensitive found in this text.")
    if res.injection_flags:
        st.error("This text looks like instructions to the AI. In a statement it would be quarantined: "
                 + ", ".join(f.replace("_", " ").lower() for f in res.injection_flags) + ".",
                 icon=":material/gpp_bad:")
