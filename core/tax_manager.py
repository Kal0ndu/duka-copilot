"""Tax Manager: VAT computation, tax summaries, KRA reporting prep."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3


@dataclass
class TaxSummary:
    summary_id: Optional[int] = None
    business_id: int = 0
    period_month: str = ""  # YYYY-MM
    total_sales_with_vat_minor: int = 0
    total_vat_collected_minor: int = 0
    total_purchases_with_vat_minor: int = 0
    total_vat_paid_minor: int = 0
    net_vat_payable_minor: int = 0
    total_withholding_tax_minor: int = 0
    total_taxable_revenue_minor: int = 0
    total_allowed_deductions_minor: int = 0
    taxable_income_minor: int = 0
    status: str = "draft"
    kra_acknowledgement: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class VATReportLine:
    """A single VAT report entry."""
    source_type: str  # sale, invoice, purchase
    reference_number: str
    date: str
    customer_supplier: str
    subtotal_minor: int
    vat_rate_pct: float
    vat_amount_minor: int
    total_minor: int


class TaxManager:
    """Compute VAT, generate tax summaries, prepare KRA reporting data."""

    def __init__(self, db_path: str = "data/duka.db"):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # VAT from Sales
    # ------------------------------------------------------------------

    def get_sales_vat(
        self, business_id: int, start_date: str, end_date: str
    ) -> Tuple[int, List[VATReportLine]]:
        """Get VAT collected from sales in a date range."""
        with self._get_conn() as conn:
            sales = conn.execute(
                """SELECT * FROM sale
                WHERE business_id = ? AND status = 'completed'
                  AND sale_date >= ? AND sale_date < ?
                ORDER BY sale_date""",
                (business_id, start_date, end_date),
            ).fetchall()

        total_vat = 0
        lines: List[VATReportLine] = []

        for sale in sales:
            line_rows = conn.execute(
                """SELECT sli.*, p.name AS product_name
                FROM sale_line_item sli
                LEFT JOIN product p ON sli.product_id = p.product_id
                WHERE sli.sale_id = ? AND sli.vat_applicable = 1""",
                (sale["sale_id"],),
            ).fetchall()

            sale_vat = sum(lr["vat_amount_minor"] for lr in line_rows)
            total_vat += sale_vat

            if sale_vat > 0:
                vat_rates = set(lr["vat_rate_pct"] for lr in line_rows)
                for rate in vat_rates:
                    rate_items = [lr for lr in line_rows if lr["vat_rate_pct"] == rate]
                    rate_vat = sum(lr["vat_amount_minor"] for lr in rate_items)
                    rate_subtotal = sum(lr["line_subtotal_minor"] for lr in rate_items)
                    lines.append(VATReportLine(
                        source_type="sale",
                        reference_number=sale["sale_number"],
                        date=sale["sale_date"][:10],
                        customer_supplier=sale["customer_name_token"] or f"Customer #{sale['customer_id']}" if sale["customer_id"] else "Walk-in",
                        subtotal_minor=rate_subtotal,
                        vat_rate_pct=rate,
                        vat_amount_minor=rate_vat,
                        total_minor=rate_subtotal + rate_vat,
                    ))

        return total_vat, lines

    # ------------------------------------------------------------------
    # VAT from Invoices
    # ------------------------------------------------------------------

    def get_invoices_vat(
        self, business_id: int, start_date: str, end_date: str
    ) -> Tuple[int, List[VATReportLine]]:
        """Get VAT on issued invoices in a date range."""
        with self._get_conn() as conn:
            invoices = conn.execute(
                """SELECT * FROM invoice
                WHERE business_id = ? AND status IN ('active','sent','paid','overdue')
                  AND invoice_date >= ? AND invoice_date < ?
                ORDER BY invoice_date""",
                (business_id, start_date, end_date),
            ).fetchall()

        total_vat = 0
        lines: List[VATReportLine] = []

        for inv in invoices:
            line_rows = conn.execute(
                """SELECT * FROM invoice_line_item
                WHERE invoice_id = ? AND vat_applicable = 1""",
                (inv["invoice_id"],),
            ).fetchall()

            inv_vat = sum(lr["vat_amount_minor"] for lr in line_rows)
            total_vat += inv_vat

            if inv_vat > 0:
                vat_rates = set(lr["vat_rate_pct"] for lr in line_rows)
                for rate in vat_rates:
                    rate_items = [lr for lr in line_rows if lr["vat_rate_pct"] == rate]
                    rate_vat = sum(lr["vat_amount_minor"] for lr in rate_items)
                    rate_subtotal = sum(lr["line_subtotal_minor"] for lr in rate_items)
                    lines.append(VATReportLine(
                        source_type="invoice",
                        reference_number=inv["invoice_number"],
                        date=inv["invoice_date"][:10],
                        customer_supplier=inv["customer_name_token"] or f"Customer #{inv['customer_id']}",
                        subtotal_minor=rate_subtotal,
                        vat_rate_pct=rate,
                        vat_amount_minor=rate_vat,
                        total_minor=rate_subtotal + rate_vat,
                    ))

        return total_vat, lines

    # ------------------------------------------------------------------
    # VAT from Purchases (inventory restock)
    # ------------------------------------------------------------------

    def get_purchases_vat(
        self, business_id: int, start_date: str, end_date: str
    ) -> Tuple[int, List[VATReportLine]]:
        """Estimate VAT paid on inventory purchases in a date range.
        Uses inventory_transaction type='purchase' joined to product cost_price.
        """
        with self._get_conn() as conn:
            purchases = conn.execute(
                """SELECT it.*, p.name AS product_name, p.cost_price_minor,
                          p.vat_rate_pct, p.vat_applicable
                FROM inventory_transaction it
                JOIN product p ON it.product_id = p.product_id
                WHERE it.business_id = ? AND it.type = 'purchase'
                  AND it.created_at >= ? AND it.created_at < ?
                ORDER BY it.created_at""",
                (business_id, start_date, end_date),
            ).fetchall()

        total_vat = 0
        lines: List[VATReportLine] = []

        for pur in purchases:
            if not pur["vat_applicable"]:
                continue
            subtotal = pur["cost_price_minor"] * pur["quantity"]
            vat = int(subtotal * pur["vat_rate_pct"] / 100)
            total_vat += vat
            lines.append(VATReportLine(
                source_type="purchase",
                reference_number=f"PUR-{pur['txn_id']}",
                date=pur["created_at"][:10],
                customer_supplier=pur["product_name"],
                subtotal_minor=subtotal,
                vat_rate_pct=pur["vat_rate_pct"],
                vat_amount_minor=vat,
                total_minor=subtotal + vat,
            ))

        return total_vat, lines

    # ------------------------------------------------------------------
    # Tax Summary Generation
    # ------------------------------------------------------------------

    def generate_monthly_summary(
        self, business_id: int, year: int, month: int
    ) -> TaxSummary:
        """Generate a monthly tax summary for VAT filing prep."""
        period_month = f"{year}-{month:02d}"
        start_date = f"{period_month}-01"
        if month == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month + 1:02d}-01"

        sales_vat, _ = self.get_sales_vat(business_id, start_date, end_date)
        invoices_vat, _ = self.get_invoices_vat(business_id, start_date, end_date)
        purchases_vat, _ = self.get_purchases_vat(business_id, start_date, end_date)

        total_vat_collected = sales_vat + invoices_vat
        total_vat_paid = purchases_vat
        net_vat_payable = total_vat_collected - total_vat_paid

        # Taxable revenue = all sales + invoice subtotals
        with self._get_conn() as conn:
            sales_rev = conn.execute(
                """SELECT COALESCE(SUM(subtotal_minor), 0) FROM sale
                WHERE business_id = ? AND status = 'completed'
                  AND sale_date >= ? AND sale_date < ?""",
                (business_id, start_date, end_date),
            ).fetchone()[0]

            inv_rev = conn.execute(
                """SELECT COALESCE(SUM(subtotal_minor), 0) FROM invoice
                WHERE business_id = ? AND status IN ('active','sent','paid','overdue')
                  AND invoice_date >= ? AND invoice_date < ?""",
                (business_id, start_date, end_date),
            ).fetchone()[0]

        total_taxable_revenue = sales_rev + inv_rev

        # Check if summary already exists for this period
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT summary_id FROM tax_summary WHERE business_id = ? AND period_month = ?",
                (business_id, period_month),
            ).fetchone()

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        if existing:
            with self._get_conn() as conn:
                conn.execute(
                    """UPDATE tax_summary SET
                        total_sales_with_vat_minor = ?,
                        total_vat_collected_minor = ?,
                        total_purchases_with_vat_minor = ?,
                        total_vat_paid_minor = ?,
                        net_vat_payable_minor = ?,
                        total_taxable_revenue_minor = ?,
                        taxable_income_minor = ?,
                        updated_at = ?
                    WHERE summary_id = ?""",
                    (
                        total_taxable_revenue,
                        total_vat_collected,
                        total_taxable_revenue,  # approximate
                        total_vat_paid,
                        net_vat_payable,
                        total_taxable_revenue,
                        total_taxable_revenue,
                        now,
                        existing["summary_id"],
                    ),
                )
                summary_id = existing["summary_id"]
        else:
            with self._get_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO tax_summary
                        (business_id, period_month, total_sales_with_vat_minor,
                         total_vat_collected_minor, total_purchases_with_vat_minor,
                         total_vat_paid_minor, net_vat_payable_minor,
                         total_taxable_revenue_minor, taxable_income_minor,
                         status, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        business_id, period_month, total_taxable_revenue,
                        total_vat_collected, total_taxable_revenue,
                        total_vat_paid, net_vat_payable,
                        total_taxable_revenue, total_taxable_revenue,
                        "draft", now, now,
                    ),
                )
                summary_id = cur.lastrowid

        return TaxSummary(
            summary_id=summary_id,
            business_id=business_id,
            period_month=period_month,
            total_sales_with_vat_minor=total_taxable_revenue,
            total_vat_collected_minor=total_vat_collected,
            total_purchases_with_vat_minor=total_taxable_revenue,
            total_vat_paid_minor=total_vat_paid,
            net_vat_payable_minor=net_vat_payable,
            total_withholding_tax_minor=0,
            total_taxable_revenue_minor=total_taxable_revenue,
            total_allowed_deductions_minor=0,
            taxable_income_minor=total_taxable_revenue,
            status="draft",
            created_at=now,
            updated_at=now,
        )

    def get_summary(self, summary_id: int) -> Optional[TaxSummary]:
        """Get a tax summary by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tax_summary WHERE summary_id = ?", (summary_id,)
            ).fetchone()
        if row is None:
            return None
        return TaxSummary(
            summary_id=row["summary_id"],
            business_id=row["business_id"],
            period_month=row["period_month"],
            total_sales_with_vat_minor=row["total_sales_with_vat_minor"],
            total_vat_collected_minor=row["total_vat_collected_minor"],
            total_purchases_with_vat_minor=row["total_purchases_with_vat_minor"],
            total_vat_paid_minor=row["total_vat_paid_minor"],
            net_vat_payable_minor=row["net_vat_payable_minor"],
            total_withholding_tax_minor=row["total_withholding_tax_minor"],
            total_taxable_revenue_minor=row["total_taxable_revenue_minor"],
            total_allowed_deductions_minor=row["total_allowed_deductions_minor"],
            taxable_income_minor=row["taxable_income_minor"],
            status=row["status"],
            kra_acknowledgement=row["kra_acknowledgement"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_summaries(
        self, business_id: int, limit: int = 24
    ) -> List[TaxSummary]:
        """List tax summaries for a business."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM tax_summary
                WHERE business_id = ?
                ORDER BY period_month DESC LIMIT ?""",
                (business_id, limit),
            ).fetchall()

        return [
            TaxSummary(
                summary_id=r["summary_id"],
                business_id=r["business_id"],
                period_month=r["period_month"],
                total_sales_with_vat_minor=r["total_sales_with_vat_minor"],
                total_vat_collected_minor=r["total_vat_collected_minor"],
                total_purchases_with_vat_minor=r["total_purchases_with_vat_minor"],
                total_vat_paid_minor=r["total_vat_paid_minor"],
                net_vat_payable_minor=r["net_vat_payable_minor"],
                total_withholding_tax_minor=r["total_withholding_tax_minor"],
                total_taxable_revenue_minor=r["total_taxable_revenue_minor"],
                total_allowed_deductions_minor=r["total_allowed_deductions_minor"],
                taxable_income_minor=r["taxable_income_minor"],
                status=r["status"],
                kra_acknowledgement=r["kra_acknowledgement"],
                notes=r["notes"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # VAT Report (full breakdown for a period)
    # ------------------------------------------------------------------

    def get_vat_report(
        self, business_id: int, year: int, month: int
    ) -> Dict:
        """Generate a comprehensive VAT report for a month."""
        period = f"{year}-{month:02d}"
        start = f"{period}-01"
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"

        sales_vat, sales_lines = self.get_sales_vat(business_id, start, end)
        invoices_vat, invoice_lines = self.get_invoices_vat(business_id, start, end)
        purchases_vat, purchase_lines = self.get_purchases_vat(business_id, start, end)

        return {
            "period": period,
            "sales_vat_collected_minor": sales_vat,
            "invoice_vat_collected_minor": invoices_vat,
            "total_vat_collected_minor": sales_vat + invoices_vat,
            "purchases_vat_paid_minor": purchases_vat,
            "net_vat_payable_minor": sales_vat + invoices_vat - purchases_vat,
            "sales_lines": [
                {"source": l.source_type, "ref": l.reference_number, "date": l.date,
                 "party": l.customer_supplier, "subtotal": l.subtotal_minor,
                 "vat_rate": l.vat_rate_pct, "vat": l.vat_amount_minor,
                 "total": l.total_minor}
                for l in sales_lines
            ],
            "invoice_lines": [
                {"source": l.source_type, "ref": l.reference_number, "date": l.date,
                 "party": l.customer_supplier, "subtotal": l.subtotal_minor,
                 "vat_rate": l.vat_rate_pct, "vat": l.vat_amount_minor,
                 "total": l.total_minor}
                for l in invoice_lines
            ],
            "purchase_lines": [
                {"source": l.source_type, "ref": l.reference_number, "date": l.date,
                 "party": l.customer_supplier, "subtotal": l.subtotal_minor,
                 "vat_rate": l.vat_rate_pct, "vat": l.vat_amount_minor,
                 "total": l.total_minor}
                for l in purchase_lines
            ],
        }

    # ------------------------------------------------------------------
    # KRA Filing Prep
    # ------------------------------------------------------------------

    def format_kra_vat_return(self, business_id: int, year: int, month: int) -> str:
        """Format a VAT return summary for KRA iTax copy-paste."""
        report = self.get_vat_report(business_id, year, month)

        with self._get_conn() as conn:
            pos = conn.execute(
                "SELECT * FROM pos_setting WHERE business_id = ?", (business_id,)
            ).fetchone()

        pin = pos["business_pin"] if pos else "N/A"
        name = pos["business_name"] if pos else "N/A"

        lines = []
        lines.append("=" * 60)
        lines.append("  KRA VAT RETURN — MONTHLY FILING SUMMARY")
        lines.append("=" * 60)
        lines.append(f"  Taxpayer PIN  : {pin}")
        lines.append(f"  Business Name : {name}")
        lines.append(f"  Period        : {report['period']}")
        lines.append("-" * 60)
        lines.append(f"  VAT on Sales        : KES {report['sales_vat_collected_minor']/100:,.2f}")
        lines.append(f"  VAT on Invoices     : KES {report['invoice_vat_collected_minor']/100:,.2f}")
        lines.append(f"  Total VAT Collected : KES {report['total_vat_collected_minor']/100:,.2f}")
        lines.append(f"  VAT on Purchases    : KES {report['purchases_vat_paid_minor']/100:,.2f}")
        lines.append(f"  NET VAT PAYABLE     : KES {report['net_vat_payable_minor']/100:,.2f}")
        lines.append("=" * 60)
        lines.append("  Generated by Duka POS — verify before filing.")
        return "\n".join(lines)

    def update_tax_summary_status(self, summary_id: int, status: str) -> bool:
        """Update the status of a tax summary (draft, submitted, acknowledged)."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tax_summary SET status = ?, updated_at = ? WHERE summary_id = ?",
                (status, now, summary_id),
            )
            return conn.total_changes > 0
