"""POS Engine: sale creation, payment processing, receipt generation."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import sqlite3
from pathlib import Path


@dataclass
class SaleLineItem:
    product_id: int
    quantity: int
    unit_price_minor: int
    line_subtotal_minor: int
    vat_applicable: int
    vat_rate_pct: float
    vat_amount_minor: int
    line_total_minor: int
    discount_pct: Optional[float] = None
    discount_amount_minor: int = 0


@dataclass
class Sale:
    sale_id: Optional[int] = None
    business_id: int = 0
    sale_number: str = ""
    sale_date: str = ""
    customer_id: Optional[int] = None
    customer_name_token: Optional[str] = None
    subtotal_minor: int = 0
    vat_amount_minor: int = 0
    total_amount_minor: int = 0
    amount_paid_minor: int = 0
    change_due_minor: int = 0
    payment_method: str = "cash"
    payment_status: str = "completed"
    notes: Optional[str] = None
    status: str = "completed"
    created_at: str = ""
    created_by_user: Optional[str] = None
    line_items: List[SaleLineItem] = field(default_factory=list)


@dataclass
class POSSetting:
    setting_id: Optional[int] = None
    business_id: int = 0
    pos_enabled: bool = True
    default_vat_pct: float = 16.0
    invoice_prefix: str = "INV"
    quotation_prefix: str = "QT"
    invoice_sequence: int = 1000
    quotation_sequence: int = 1000
    receipt_printer_name: Optional[str] = None
    currency: str = "KES"
    business_name: Optional[str] = None
    business_address: Optional[str] = None
    business_phone: Optional[str] = None
    business_pin: Optional[str] = None


class POSEngine:
    """Handle POS sales, payment processing, and receipt generation."""

    def __init__(self, db_path: Optional[str] = None):
        from core.config import config
        self.db_path = db_path or config.DB_PATH

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # POS Settings
    # ------------------------------------------------------------------

    def get_pos_setting(self, business_id: int) -> Optional[POSSetting]:
        """Get POS configuration for a business."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pos_setting WHERE business_id = ?", (business_id,)
            ).fetchone()
            if row is None:
                return None
            return POSSetting(
                setting_id=row["setting_id"],
                business_id=row["business_id"],
                pos_enabled=bool(row["pos_enabled"]),
                default_vat_pct=row["default_vat_pct"],
                invoice_prefix=row["invoice_prefix"],
                quotation_prefix=row["quotation_prefix"],
                invoice_sequence=row["invoice_sequence"],
                quotation_sequence=row["quotation_sequence"],
                receipt_printer_name=row["receipt_printer_name"],
                currency=row["currency"],
                business_name=row["business_name"],
                business_address=row["business_address"],
                business_phone=row["business_phone"],
                business_pin=row["business_pin"],
            )

    def upsert_pos_setting(self, settings: POSSetting) -> int:
        """Create or update POS settings for a business."""
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT setting_id FROM pos_setting WHERE business_id = ?",
                (settings.business_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE pos_setting SET
                        pos_enabled=?, default_vat_pct=?, invoice_prefix=?,
                        quotation_prefix=?, invoice_sequence=?, quotation_sequence=?,
                        receipt_printer_name=?, currency=?, business_name=?,
                        business_address=?, business_phone=?, business_pin=?
                    WHERE business_id=?""",
                    (
                        int(settings.pos_enabled), settings.default_vat_pct,
                        settings.invoice_prefix, settings.quotation_prefix,
                        settings.invoice_sequence, settings.quotation_sequence,
                        settings.receipt_printer_name, settings.currency,
                        settings.business_name, settings.business_address,
                        settings.business_phone, settings.business_pin,
                        settings.business_id,
                    ),
                )
                return existing["setting_id"]
            else:
                cur = conn.execute(
                    """INSERT INTO pos_setting
                        (business_id, pos_enabled, default_vat_pct, invoice_prefix,
                         quotation_prefix, invoice_sequence, quotation_sequence,
                         receipt_printer_name, currency, business_name,
                         business_address, business_phone, business_pin)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        settings.business_id, int(settings.pos_enabled),
                        settings.default_vat_pct, settings.invoice_prefix,
                        settings.quotation_prefix, settings.invoice_sequence,
                        settings.quotation_sequence, settings.receipt_printer_name,
                        settings.currency, settings.business_name,
                        settings.business_address, settings.business_phone,
                        settings.business_pin,
                    ),
                )
                return cur.lastrowid

    def get_next_sale_number(self, business_id: int) -> str:
        """Generate next sale number: POS-{business_id}-{timestamp}-{seq}."""
        now = datetime.now()
        ts = now.strftime("%Y%m%d%H%M")
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) + 1 AS seq FROM sale WHERE business_id = ?",
                (business_id,),
            ).fetchone()
        seq = row["seq"] if row else 1
        return f"POS-{business_id}-{ts}-{seq:04d}"

    # ------------------------------------------------------------------
    # Sale Processing
    # ------------------------------------------------------------------

    def create_sale(
        self,
        business_id: int,
        line_items: List[SaleLineItem],
        customer_id: Optional[int] = None,
        customer_name_token: Optional[str] = None,
        payment_method: str = "cash",
        notes: Optional[str] = None,
        created_by_user: Optional[str] = None,
        sale_date: Optional[datetime] = None,
        sale_number: Optional[str] = None,
    ) -> Sale:
        """Create a new complete sale with line items in a single transaction.

        sale_date and sale_number default to now and the next POS number;
        imports pass their own. A credit sale is owed, not paid: it is saved
        with amount_paid 0 and payment_status 'pending'."""
        sale_number = sale_number or self.get_next_sale_number(business_id)
        sale_date = (sale_date or datetime.now()).strftime("%Y-%m-%dT%H:%M:%SZ")

        subtotal_minor = sum(li.line_subtotal_minor for li in line_items)
        vat_amount_minor = sum(li.vat_amount_minor for li in line_items)
        total_amount_minor = subtotal_minor + vat_amount_minor
        on_credit = payment_method == "credit"
        amount_paid_minor = 0 if on_credit else total_amount_minor
        payment_status = "pending" if on_credit else "completed"

        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO sale
                    (business_id, sale_number, sale_date, customer_id,
                     customer_name_token, subtotal_minor, vat_amount_minor,
                     total_amount_minor, amount_paid_minor, change_due_minor,
                     payment_method, payment_status, notes, status,
                     created_by_user)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    business_id, sale_number, sale_date, customer_id,
                    customer_name_token, subtotal_minor, vat_amount_minor,
                    total_amount_minor, amount_paid_minor, 0,
                    payment_method, payment_status, notes, "completed",
                    created_by_user,
                ),
            )
            sale_id = cur.lastrowid

            for li in line_items:
                conn.execute(
                    """INSERT INTO sale_line_item
                        (sale_id, product_id, quantity, unit_price_minor,
                         line_subtotal_minor, vat_applicable, vat_rate_pct,
                         vat_amount_minor, line_total_minor, discount_pct,
                         discount_amount_minor)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        sale_id, li.product_id, li.quantity, li.unit_price_minor,
                        li.line_subtotal_minor, li.vat_applicable, li.vat_rate_pct,
                        li.vat_amount_minor, li.line_total_minor, li.discount_pct,
                        li.discount_amount_minor,
                    ),
                )
                # Update inventory
                conn.execute(
                    """UPDATE product SET
                        current_stock_qty = current_stock_qty - ?,
                        updated_at = ?
                    WHERE product_id = ?""",
                    (li.quantity, sale_date, li.product_id),
                )
                # Log inventory transaction
                conn.execute(
                    """INSERT INTO inventory_transaction
                        (business_id, product_id, type, quantity,
                         reference_id, reference_type, recorded_by)
                    VALUES (?,?,?,?,?,?,?)""",
                    (
                        business_id, li.product_id, "sale", li.quantity,
                        sale_id, "sale", created_by_user,
                    ),
                )

        return Sale(
            sale_id=sale_id,
            business_id=business_id,
            sale_number=sale_number,
            sale_date=sale_date,
            customer_id=customer_id,
            customer_name_token=customer_name_token,
            subtotal_minor=subtotal_minor,
            vat_amount_minor=vat_amount_minor,
            total_amount_minor=total_amount_minor,
            amount_paid_minor=amount_paid_minor,
            change_due_minor=0,
            payment_method=payment_method,
            payment_status=payment_status,
            notes=notes,
            status="completed",
            created_by_user=created_by_user,
            line_items=line_items,
        )

    # ------------------------------------------------------------------
    # Sale Queries
    # ------------------------------------------------------------------

    def get_sale(self, sale_id: int) -> Optional[Sale]:
        """Get a sale by ID including line items."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM sale WHERE sale_id = ?", (sale_id,)
            ).fetchone()
            if row is None:
                return None
            line_rows = conn.execute(
                "SELECT * FROM sale_line_item WHERE sale_id = ? ORDER BY line_id",
                (sale_id,),
            ).fetchall()

        line_items = [
            SaleLineItem(
                product_id=lr["product_id"],
                quantity=lr["quantity"],
                unit_price_minor=lr["unit_price_minor"],
                line_subtotal_minor=lr["line_subtotal_minor"],
                vat_applicable=lr["vat_applicable"],
                vat_rate_pct=lr["vat_rate_pct"],
                vat_amount_minor=lr["vat_amount_minor"],
                line_total_minor=lr["line_total_minor"],
                discount_pct=lr["discount_pct"],
                discount_amount_minor=lr["discount_amount_minor"],
            )
            for lr in line_rows
        ]

        return Sale(
            sale_id=row["sale_id"],
            business_id=row["business_id"],
            sale_number=row["sale_number"],
            sale_date=row["sale_date"],
            customer_id=row["customer_id"],
            customer_name_token=row["customer_name_token"],
            subtotal_minor=row["subtotal_minor"],
            vat_amount_minor=row["vat_amount_minor"],
            total_amount_minor=row["total_amount_minor"],
            amount_paid_minor=row["amount_paid_minor"],
            change_due_minor=row["change_due_minor"],
            payment_method=row["payment_method"],
            payment_status=row["payment_status"],
            notes=row["notes"],
            status=row["status"],
            created_at=row["created_at"],
            created_by_user=row["created_by_user"],
            line_items=line_items,
        )

    def get_sales_for_business(
        self, business_id: int, limit: int = 100, offset: int = 0
    ) -> List[Sale]:
        """Get recent sales for a business (summary, no line items)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM sale
                WHERE business_id = ? AND status = 'completed'
                ORDER BY sale_date DESC LIMIT ? OFFSET ?""",
                (business_id, limit, offset),
            ).fetchall()

        return [
            Sale(
                sale_id=r["sale_id"],
                business_id=r["business_id"],
                sale_number=r["sale_number"],
                sale_date=r["sale_date"],
                customer_id=r["customer_id"],
                customer_name_token=r["customer_name_token"],
                subtotal_minor=r["subtotal_minor"],
                vat_amount_minor=r["vat_amount_minor"],
                total_amount_minor=r["total_amount_minor"],
                amount_paid_minor=r["amount_paid_minor"],
                change_due_minor=r["change_due_minor"],
                payment_method=r["payment_method"],
                payment_status=r["payment_status"],
                notes=r["notes"],
                status=r["status"],
                created_at=r["created_at"],
                created_by_user=r["created_by_user"],
            )
            for r in rows
        ]

    def get_recent_sales_table(self, business_id: int, limit: int = 50) -> List[Dict]:
        """Recent completed sales with their item count, newest first (for tables)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT s.sale_id, s.sale_number, s.sale_date, s.customer_name_token, s.payment_method,
                          s.payment_status, s.subtotal_minor, s.vat_amount_minor, s.total_amount_minor,
                          COALESCE(SUM(li.quantity), 0) AS items
                   FROM sale s LEFT JOIN sale_line_item li ON li.sale_id = s.sale_id
                   WHERE s.business_id = ? AND s.status = 'completed'
                   GROUP BY s.sale_id
                   ORDER BY s.sale_date DESC, s.sale_id DESC LIMIT ?""",
                (business_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_daily_sales(self, business_id: int, days: int = 30) -> List[Dict]:
        """Completed sales per day for the last `days` days (days with no sales included as 0)."""
        from datetime import date, timedelta
        start = date.today() - timedelta(days=days - 1)
        with self._get_conn() as conn:
            rows = {r["day"]: r for r in conn.execute(
                """SELECT substr(sale_date, 1, 10) AS day, COUNT(*) AS n, SUM(total_amount_minor) AS total
                   FROM sale WHERE business_id = ? AND status = 'completed' AND substr(sale_date, 1, 10) >= ?
                   GROUP BY day""",
                (business_id, start.isoformat()),
            )}
        out = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            r = rows.get(d)
            out.append({"date": d, "count": r["n"] if r else 0, "total_minor": r["total"] if r else 0})
        return out

    def get_top_products(self, business_id: int, days: int = 30, limit: int = 10) -> List[Dict]:
        """Products by revenue (line totals incl. VAT) over the last `days` days."""
        from datetime import date, timedelta
        start = (date.today() - timedelta(days=days - 1)).isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT COALESCE(p.name, 'Product #' || li.product_id) AS product,
                          SUM(li.quantity) AS units, SUM(li.line_total_minor) AS total
                   FROM sale_line_item li JOIN sale s ON s.sale_id = li.sale_id
                   LEFT JOIN product p ON p.product_id = li.product_id
                   WHERE s.business_id = ? AND s.status = 'completed' AND substr(s.sale_date, 1, 10) >= ?
                   GROUP BY li.product_id ORDER BY total DESC LIMIT ?""",
                (business_id, start, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_day_totals(self, business_id: int, day: str) -> Dict:
        """Count and total of completed sales on one local date (YYYY-MM-DD)."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS n, COALESCE(SUM(total_amount_minor), 0) AS total
                   FROM sale WHERE business_id = ? AND status = 'completed' AND substr(sale_date, 1, 10) = ?""",
                (business_id, day),
            ).fetchone()
        return {"count": row["n"], "total_minor": row["total"]}

    def get_sales_summary(self, business_id: int, days: int = 30) -> Dict:
        """Get sales summary for a period."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) AS sale_count,
                    COALESCE(SUM(total_amount_minor), 0) AS total_sales,
                    COALESCE(SUM(vat_amount_minor), 0) AS total_vat,
                    COALESCE(SUM(subtotal_minor), 0) AS total_subtotal
                FROM sale
                WHERE business_id = ?
                  AND status = 'completed'
                  AND sale_date >= date('now', ? || ' days')""",
                (business_id, f"-{days}"),
            ).fetchone()

            # Payment method breakdown
            pm_rows = conn.execute(
                """SELECT payment_method, COUNT(*) AS cnt,
                          COALESCE(SUM(total_amount_minor), 0) AS total
                FROM sale
                WHERE business_id = ? AND status = 'completed'
                  AND sale_date >= date('now', ? || ' days')
                GROUP BY payment_method""",
                (business_id, f"-{days}"),
            ).fetchall()

        return {
            "sale_count": row["sale_count"] if row else 0,
            "total_sales_minor": row["total_sales"] if row else 0,
            "total_vat_minor": row["total_vat"] if row else 0,
            "total_subtotal_minor": row["total_subtotal"] if row else 0,
            "payment_breakdown": {
                pm["payment_method"]: {
                    "count": pm["cnt"],
                    "total_minor": pm["total"],
                }
                for pm in pm_rows
            },
        }

    # ------------------------------------------------------------------
    # Sale Line Item Builder
    # ------------------------------------------------------------------

    @staticmethod
    def build_line_item(
        product_id: int,
        quantity: int,
        selling_price_minor: int,
        vat_rate_pct: float = 16.0,
        vat_applicable: bool = True,
        discount_pct: Optional[float] = None,
    ) -> SaleLineItem:
        """Build a sale line item with computed VAT and totals."""
        line_subtotal_minor = selling_price_minor * quantity
        discount_amount_minor = 0
        if discount_pct:
            discount_amount_minor = int(line_subtotal_minor * discount_pct / 100)
            line_subtotal_minor -= discount_amount_minor

        if vat_applicable:
            vat_amount_minor = int(line_subtotal_minor * vat_rate_pct / 100)
        else:
            vat_amount_minor = 0
            vat_rate_pct = 0.0

        line_total_minor = line_subtotal_minor + vat_amount_minor

        return SaleLineItem(
            product_id=product_id,
            quantity=quantity,
            unit_price_minor=selling_price_minor,
            line_subtotal_minor=line_subtotal_minor,
            vat_applicable=1 if vat_applicable else 0,
            vat_rate_pct=vat_rate_pct,
            vat_amount_minor=vat_amount_minor,
            line_total_minor=line_total_minor,
            discount_pct=discount_pct,
            discount_amount_minor=discount_amount_minor,
        )

    # ------------------------------------------------------------------
    # Cancellation / Refund
    # ------------------------------------------------------------------

    def cancel_sale(self, sale_id: int) -> bool:
        """Cancel a sale and reverse inventory."""
        with self._get_conn() as conn:
            sale = conn.execute(
                "SELECT * FROM sale WHERE sale_id = ? AND status = 'completed'",
                (sale_id,),
            ).fetchone()
            if sale is None:
                return False

            # Reverse inventory
            line_items = conn.execute(
                "SELECT product_id, quantity FROM sale_line_item WHERE sale_id = ?",
                (sale_id,),
            ).fetchall()
            for li in line_items:
                conn.execute(
                    "UPDATE product SET current_stock_qty = current_stock_qty + ? WHERE product_id = ?",
                    (li["quantity"], li["product_id"]),
                )

            conn.execute(
                "UPDATE sale SET status = 'cancelled' WHERE sale_id = ?",
                (sale_id,),
            )
            return True

    # ------------------------------------------------------------------
    # Receipt Formatting
    # ------------------------------------------------------------------

    def format_receipt(self, sale: Sale, pos_settings: Optional[POSSetting] = None) -> str:
        """Generate a plain-text receipt for printing."""
        currency = pos_settings.currency if pos_settings else "KES"
        biz_name = pos_settings.business_name if pos_settings else "Duka POS"
        lines = []
        lines.append("=" * 40)
        lines.append(f"  {biz_name}")
        lines.append("=" * 40)
        lines.append(f"Sale #: {sale.sale_number}")
        lines.append(f"Date  : {sale.sale_date}")
        if sale.customer_name_token:
            lines.append(f"Customer: {sale.customer_name_token}")
        lines.append("-" * 40)
        for i, li in enumerate(sale.line_items, 1):
            ext = f"{li.unit_price_minor/100:,.2f} x {li.quantity}"
            lines.append(f"{li.product_id:>3}  {ext:<20} {li.line_total_minor/100:>8,.2f}")
        lines.append("-" * 40)
        lines.append(f"Subtotal: {currency} {sale.subtotal_minor/100:,.2f}")
        lines.append(f"VAT     : {currency} {sale.vat_amount_minor/100:,.2f}")
        lines.append(f"TOTAL   : {currency} {sale.total_amount_minor/100:,.2f}")
        lines.append(f"Payment : {sale.payment_method.upper()}")
        lines.append("=" * 40)
        lines.append("  Thank you for your business!")
        lines.append("=" * 40)
        return "\n".join(lines)
