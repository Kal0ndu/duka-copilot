"""Page 11: Tax Reports — VAT summaries, KRA filing prep, tax history."""
import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth, check_auth

from core.tax_manager import TaxManager, TaxSummary
from core.pos_engine import POSEngine
from core.invoice_manager import InvoiceManager
from app.session_helpers import SessionManager

st.set_page_config(page_title="Tax Reports — Duka", page_icon=":material/analytics:", layout="wide")
# ---- Authentication Gate ----
require_auth()


SessionManager.init_session()
profile = SessionManager.get_profile()
biz_id = profile.get("business_id", 1) if profile else 1

tax = TaxManager()
pos = POSEngine()
inv_mgr = InvoiceManager()

st.title("Tax Reports & KRA Filing")
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
if st.button(":material/search: Generate Tax Report", type="primary", width="stretch"):
    report = tax.get_vat_report(biz_id, report_year, report_month)

    st.divider()
    st.subheader(f"VAT Report — {datetime(report_year, report_month, 1).strftime('%B %Y')}")

    # KPI Row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("VAT on Sales", f"KES {report['sales_vat_collected_minor']/100:,.2f}")
    k2.metric("VAT on Invoices", f"KES {report['invoice_vat_collected_minor']/100:,.2f}")
    k3.metric("VAT on Purchases", f"KES {report['purchases_vat_paid_minor']/100:,.2f}",
              delta=f"KES {report['purchases_vat_paid_minor']/100:,.2f}", delta_color="inverse")
    k4.metric("NET VAT PAYABLE",
              f"KES {report['net_vat_payable_minor']/100:,.2f}",
              delta="PAYABLE" if report['net_vat_payable_minor'] > 0 else "REFUND",
              delta_color="inverse" if report['net_vat_payable_minor'] > 0 else "normal")

    st.divider()

    # ---- Sales VAT Breakdown ----
    tab_sales, tab_invoices, tab_purchases, tab_kra = st.tabs([
        "Sales VAT",
        "Invoice VAT",
        "Purchase VAT",
        ":material/description: KRA filing"
    ])

    with tab_sales:
        if report["sales_lines"]:
            st.caption(f"{len(report['sales_lines'])} taxable sale entries")
            for line in report["sales_lines"]:
                st.write(
                    f"**{line['ref']}** — {line['date']} — {line['party']} — "
                    f"Subtotal: KES {line['subtotal']/100:,.2f} — "
                    f"VAT @ {line['vat_rate']}%: KES {line['vat']/100:,.2f} — "
                    f"Total: KES {line['total']/100:,.2f}"
                )
            st.metric("Total Sales VAT", f"KES {report['sales_vat_collected_minor']/100:,.2f}")
        else:
            st.info("No taxable sales for this period.")

    with tab_invoices:
        if report["invoice_lines"]:
            st.caption(f"{len(report['invoice_lines'])} taxable invoice entries")
            for line in report["invoice_lines"]:
                st.write(
                    f"**{line['ref']}** — {line['date']} — {line['party']} — "
                    f"Subtotal: KES {line['subtotal']/100:,.2f} — "
                    f"VAT @ {line['vat_rate']}%: KES {line['vat']/100:,.2f} — "
                    f"Total: KES {line['total']/100:,.2f}"
                )
            st.metric("Total Invoice VAT", f"KES {report['invoice_vat_collected_minor']/100:,.2f}")
        else:
            st.info("No taxable invoices for this period.")

    with tab_purchases:
        if report["purchase_lines"]:
            st.caption(f"{len(report['purchase_lines'])} purchase VAT entries")
            for line in report["purchase_lines"]:
                st.write(
                    f"**{line['ref']}** — {line['date']} — {line['party']} — "
                    f"Subtotal: KES {line['subtotal']/100:,.2f} — "
                    f"VAT @ {line['vat_rate']}%: KES {line['vat']/100:,.2f} — "
                    f"Total: KES {line['total']/100:,.2f}"
                )
            st.metric("Total Purchase VAT (Input)", f"KES {report['purchases_vat_paid_minor']/100:,.2f}")
        else:
            st.info("No purchase VAT data for this period. Add purchase records to track input VAT.")

    with tab_kra:
        st.subheader("KRA iTax Filing Summary")
        kra_text = tax.format_kra_vat_return(biz_id, report_year, report_month)
        st.code(kra_text, language=None)

        st.info(
            "**Instructions:** Copy the summary above into your KRA iTax VAT return form. "
            "Verify all figures before final submission. This is a convenience summary only."
        )

        # Save tax summary
        if st.button(":material/save: Save Tax Summary for Records"):
            summary = tax.generate_monthly_summary(biz_id, report_year, report_month)
            if summary:
                st.success(f"Tax summary saved for {report['period']} (ID: {summary.summary_id})")
            else:
                st.warning("Could not save summary. It may already exist for this period.")

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
