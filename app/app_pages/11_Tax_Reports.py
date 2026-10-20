"""Page 11: Tax Reports — VAT summaries, KRA filing prep, tax history."""
import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth, check_auth

from core.charts import chart_vat_by_month
from core.tax_manager import TaxManager, TaxSummary
from core.pos_engine import POSEngine
from core.invoice_manager import InvoiceManager
from app.session_helpers import SessionManager
from auth.middleware import get_business_id

st.set_page_config(page_title="Tax Reports — Duka Copilot", page_icon=":material/analytics:", layout="wide")
# ---- Authentication Gate ----
require_auth()


SessionManager.init_session()
profile = SessionManager.get_profile()
biz_id = get_business_id()
if not biz_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

tax = TaxManager()
pos = POSEngine()
inv_mgr = InvoiceManager()

st.title("Tax reports & KRA filing", icon=":material/account_balance:")
st.caption("VAT summaries, tax liability calculations, and KRA iTax preparation.")

# ---- Period Selector ----
now = datetime.now()
col_p1, col_p2 = st.columns(2)
with col_p1:
    report_year = st.selectbox("Year", list(range(now.year - 2, now.year + 1)), index=2)
with col_p2:
    report_month = st.selectbox("Month", list(range(1, 13)), index=now.month - 1,
                                format_func=lambda m: datetime(2000, m, 1).strftime("%B"))

# ---- Generate Report ----
# The report is kept in session state so buttons inside it (download, save)
# still see it on the rerun their click causes.
if st.button(":material/search: Generate Tax Report", type="primary", width="stretch"):
    st.session_state["tax_report_period"] = (report_year, report_month)

MONEY = st.column_config.NumberColumn(format="accounting")


def _vat_lines_table(lines: list, kind: str, key: str, ref_label: str, party_label: str) -> None:
    """Totals, a sortable table of the lines, and a breakdown by VAT rate."""
    df = pd.DataFrame(lines)
    df = pd.DataFrame({
        ref_label: df["ref"],
        "Date": pd.to_datetime(df["date"], format="%Y-%m-%d"),
        party_label: df["party"],
        "VAT rate (%)": df["vat_rate"].astype(float),
        "Taxable amount (KES)": df["subtotal"] / 100,
        "VAT (KES)": df["vat"] / 100,
        "Total incl. VAT (KES)": df["total"] / 100,
    }).sort_values(["Date", ref_label], ignore_index=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Taxable {kind}", f"{len(df):,}")
    c2.metric("Taxable amount", f"KES {df['Taxable amount (KES)'].sum():,.2f}")
    c3.metric("VAT", f"KES {df['VAT (KES)'].sum():,.2f}")
    c4.metric("Total incl. VAT", f"KES {df['Total incl. VAT (KES)'].sum():,.2f}")

    st.dataframe(
        df, hide_index=True, width="stretch", height=min(38 + 35 * len(df), 460),
        column_config={
            "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "VAT rate (%)": st.column_config.NumberColumn(format="%.1f%%", width="small"),
            "Taxable amount (KES)": MONEY, "VAT (KES)": MONEY, "Total incl. VAT (KES)": MONEY,
        },
    )

    by_rate = (df.groupby("VAT rate (%)", as_index=False)
                 .agg(Lines=(ref_label, "count"), **{"Taxable amount (KES)": ("Taxable amount (KES)", "sum"),
                                                     "VAT (KES)": ("VAT (KES)", "sum")}))
    left, right = st.columns([2, 1], vertical_alignment="bottom")
    with left:
        st.caption("By VAT rate")
        st.dataframe(by_rate, hide_index=True, width="stretch", column_config={
            "VAT rate (%)": st.column_config.NumberColumn(format="%.1f%%"),
            "Taxable amount (KES)": MONEY, "VAT (KES)": MONEY,
        })
    right.download_button(
        ":material/download: Download CSV", df.to_csv(index=False, date_format="%Y-%m-%d").encode(),
        file_name=f"{key}_{report['period']}.csv", mime="text/csv", key=f"dl_{key}", width="stretch",
    )


period = st.session_state.get("tax_report_period")
if period:
    shown_year, shown_month = period
    report = tax.get_vat_report(biz_id, shown_year, shown_month)
    period_label = datetime(shown_year, shown_month, 1).strftime("%B %Y")

    st.divider()
    st.subheader(f"VAT Report — {period_label}")
    if period != (report_year, report_month):
        st.caption(f"Showing {period_label}. Press **Generate Tax Report** to switch to the month selected above.")

    net = report["net_vat_payable_minor"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Output VAT on sales", f"KES {report['sales_vat_collected_minor']/100:,.2f}")
    k2.metric("Output VAT on invoices", f"KES {report['invoice_vat_collected_minor']/100:,.2f}")
    k3.metric("Input VAT on purchases", f"KES {report['purchases_vat_paid_minor']/100:,.2f}")
    k4.metric("Net VAT payable" if net >= 0 else "Net VAT refundable", f"KES {abs(net)/100:,.2f}",
              delta="Payable to KRA" if net > 0 else ("Refund due" if net < 0 else "Nothing due"),
              delta_color="inverse" if net > 0 else "normal")

    st.divider()

    tab_sales, tab_invoices, tab_purchases, tab_kra = st.tabs([
        f"Sales VAT ({len(report['sales_lines'])})",
        f"Invoice VAT ({len(report['invoice_lines'])})",
        f"Purchase VAT ({len(report['purchase_lines'])})",
        ":material/description: KRA filing"
    ])

    with tab_sales:
        if report["sales_lines"]:
            _vat_lines_table(report["sales_lines"], "sales", "sales_vat", "Sale #", "Customer")
        else:
            st.info("No taxable sales for this period.")

    with tab_invoices:
        if report["invoice_lines"]:
            _vat_lines_table(report["invoice_lines"], "invoices", "invoice_vat", "Invoice #", "Customer")
        else:
            st.info("No taxable invoices for this period.")

    with tab_purchases:
        if report["purchase_lines"]:
            _vat_lines_table(report["purchase_lines"], "purchases", "purchase_vat", "Purchase #", "Product")
        else:
            st.info("No purchase VAT data for this period. Add purchase records to track input VAT.")

    with tab_kra:
        st.subheader("KRA iTax filing summary")
        kra_text = tax.format_kra_vat_return(biz_id, shown_year, shown_month)
        st.code(kra_text, language=None)

        st.info(
            "**Instructions:** Copy the summary above into your KRA iTax VAT return form. "
            "Verify all figures before final submission. This is a convenience summary only."
        )

        if st.button(":material/save: Save Tax Summary for Records"):
            summary = tax.generate_monthly_summary(biz_id, shown_year, shown_month)
            if summary:
                st.success(f"Tax summary saved for {report['period']} (ID: {summary.summary_id})")
            else:
                st.warning("Could not save summary. It may already exist for this period.")

# ---- VAT over the last 12 months ----
st.divider()
st.subheader("VAT over the last 12 months", icon=":material/bar_chart:", anchor=False)
st.caption("Blue: VAT you collected on sales and invoices. Orange: VAT you paid on stock purchases (it reduces what "
           "you owe). Green line: what's left to pay KRA each month.")
_months = []
_y, _m = now.year, now.month
for _ in range(12):
    _months.append((_y, _m))
    _y, _m = (_y, _m - 1) if _m > 1 else (_y - 1, 12)
_vat_rows = []
for _y, _m in reversed(_months):
    _r = tax.get_vat_report(biz_id, _y, _m)
    _vat_rows.append({"month": f"{_y}-{_m:02d}", "output": _r["total_vat_collected_minor"] / 100,
                      "input": _r["purchases_vat_paid_minor"] / 100})
st.altair_chart(chart_vat_by_month(_vat_rows), width="stretch")

# ---- Saved Tax Summaries ----
st.divider()
st.subheader("Saved tax summaries")

summaries = tax.list_summaries(biz_id, limit=12)

if not summaries:
    st.info("No saved tax summaries. Generate a report and save it.")
else:
    for s in summaries:
        status_icon = {"draft": ":material/edit:", "submitted": ":material/check_circle:", "acknowledged": ":material/list_alt:"}.get(s.status, ":material/description:")
        with st.expander(
            f"{status_icon} **{s.period_month}** — Net VAT: KES {s.net_vat_payable_minor/100:,.2f} — {s.status.upper()}"
        ):
            c1, c2, c3 = st.columns(3)
            c1.metric("VAT Collected", f"KES {s.total_vat_collected_minor/100:,.2f}")
            c2.metric("VAT Paid (Input)", f"KES {s.total_vat_paid_minor/100:,.2f}")
            c3.metric("Net Payable", f"KES {s.net_vat_payable_minor/100:,.2f}",
                      delta="PAYABLE" if s.net_vat_payable_minor > 0 else "REFUND")

            if s.kra_acknowledgement:
                st.success(f"KRA Acknowledgement: {s.kra_acknowledgement}")

            col_up1, col_up2 = st.columns(2)
            new_status = col_up1.selectbox(
                "Update Status", ["draft", "submitted", "acknowledged"],
                index=["draft", "submitted", "acknowledged"].index(s.status),
                key=f"status_{s.summary_id}"
            )
            if col_up2.button(":material/save: Update", key=f"update_{s.summary_id}"):
                tax.update_tax_summary_status(s.summary_id, new_status)
                st.rerun()

st.divider()
st.caption("**Tip:** VAT on purchases (input tax) reduces your net VAT payable. Make sure to record all business purchases.")
