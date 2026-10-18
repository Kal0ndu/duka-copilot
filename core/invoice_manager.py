"""Invoice Manager: invoicing, quotations, payments, follow-ups."""
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import sqlite3


@dataclass
class InvoiceLineItem:
    line_id: Optional[int] = None
    invoice_id: Optional[int] = None
    product_id: Optional[int] = None
    description: str = ""
    quantity: int = 1
    unit_price_minor: int = 0
    line_subtotal_minor: int = 0
    vat_applicable: bool = True
    vat_rate_pct: float = 16.0
    vat_amount_minor: int = 0
    line_total_minor: int = 0
    discount_pct: Optional[float] = None
    discount_amount_minor: int = 0


@dataclass
class Invoice:
    invoice_id: Optional[int] = None
    business_id: int = 0
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    customer_id: int = 0
    customer_name_token: Optional[str] = None
    customer_contact: Optional[str] = None
    subtotal_minor: int = 0
    vat_amount_minor: int = 0
    total_amount_minor: int = 0
    amount_paid_minor: int = 0
    balance_due_minor: int = 0
    payment_status: str = "unpaid"
    last_payment_date: Optional[str] = None
    follow_up_status: str = "none"
    follow_up_count: int = 0
    last_follow_up_date: Optional[str] = None
    notes: Optional[str] = None
    status: str = "draft"
    created_at: str = ""
    created_by: Optional[str] = None
    line_items: List[InvoiceLineItem] = field(default_factory=list)

    @property
    def is_overdue(self) -> bool:
        if self.payment_status in ("paid", "cancelled"):
            return False
        return datetime.now().strftime("%Y-%m-%d") > self.due_date[:10]


@dataclass
class QuotationLineItem:
    line_id: Optional[int] = None
    quotation_id: Optional[int] = None
    product_id: Optional[int] = None
    description: str = ""
    quantity: int = 1
    unit_price_minor: int = 0
    line_subtotal_minor: int = 0
    vat_applicable: bool = True
    vat_rate_pct: float = 16.0
    vat_amount_minor: int = 0
    line_total_minor: int = 0


@dataclass
class Quotation:
    quotation_id: Optional[int] = None
    business_id: int = 0
    quotation_number: str = ""
    quotation_date: str = ""
    valid_until_date: str = ""
    customer_id: int = 0
    customer_name_token: Optional[str] = None
    subtotal_minor: int = 0
    vat_amount_minor: int = 0
    total_minor: int = 0
    status: str = "draft"
    converted_to_invoice_id: Optional[int] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    created_at: str = ""
    created_by: Optional[str] = None
    line_items: List[QuotationLineItem] = field(default_factory=list)


@dataclass
class PaymentRecord:
    payment_id: Optional[int] = None
    business_id: int = 0
    payment_date: str = ""
    reference_number: Optional[str] = None
    invoice_id: Optional[int] = None
    sale_id: Optional[int] = None
    customer_id: int = 0
    amount_minor: int = 0
    payment_method: str = "cash"
    mpesa_reference: Optional[str] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: str = ""


class InvoiceManager:
    """Manage invoices, quotations, payments, and follow-ups."""

    def __init__(self, db_path: str = "data/duka.db"):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # Number Generation
    # ------------------------------------------------------------------

    def _get_next_invoice_number(self, business_id: int) -> str:
        """Generate next invoice number using prefix + sequence."""
        with self._get_conn() as conn:
            pos = conn.execute(
                "SELECT invoice_prefix, invoice_sequence FROM pos_setting WHERE business_id = ?",
                (business_id,),
            ).fetchone()

        prefix = pos["invoice_prefix"] if pos else "INV"
        seq = pos["invoice_sequence"] if pos else 1000

        with self._get_conn() as conn:
            conn.execute(
                "UPDATE pos_setting SET invoice_sequence = invoice_sequence + 1 WHERE business_id = ?",
                (business_id,),
            )
            count = conn.execute(
                "SELECT COUNT(*) + 1 AS cnt FROM invoice WHERE business_id = ?",
                (business_id,),
            ).fetchone()["cnt"]

        return f"{prefix}-{business_id}-{seq:06d}"

    def _get_next_quotation_number(self, business_id: int) -> str:
        """Generate next quotation number."""
        with self._get_conn() as conn:
            pos = conn.execute(
                "SELECT quotation_prefix, quotation_sequence FROM pos_setting WHERE business_id = ?",
                (business_id,),
            ).fetchone()

        prefix = pos["quotation_prefix"] if pos else "QT"
        seq = pos["quotation_sequence"] if pos else 1000

        with self._get_conn() as conn:
            conn.execute(
                "UPDATE pos_setting SET quotation_sequence = quotation_sequence + 1 WHERE business_id = ?",
                (business_id,),
            )

        return f"{prefix}-{business_id}-{seq:06d}"

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    def create_invoice(
        self,
        business_id: int,
        customer_id: int,
        line_items: List[InvoiceLineItem],
        customer_name_token: Optional[str] = None,
        customer_contact: Optional[str] = None,
        due_days: int = 30,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
        status: str = "active",
    ) -> Invoice:
        """Create a new invoice with line items."""
        invoice_number = self._get_next_invoice_number(business_id)
        now = datetime.now()
        invoice_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        due_date = (now + timedelta(days=due_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        subtotal_minor = sum(li.line_subtotal_minor for li in line_items)
        vat_amount_minor = sum(li.vat_amount_minor for li in line_items)
        total_amount_minor = subtotal_minor + vat_amount_minor

        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO invoice
                    (business_id, invoice_number, invoice_date, due_date,
                     customer_id, customer_name_token, customer_contact,
                     subtotal_minor, vat_amount_minor, total_amount_minor,
                     amount_paid_minor, balance_due_minor, payment_status,
                     notes, status, created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    business_id, invoice_number, invoice_date, due_date,
                    customer_id, customer_name_token, customer_contact,
                    subtotal_minor, vat_amount_minor, total_amount_minor,
                    0, total_amount_minor, "unpaid",
                    notes, status, created_by,
                ),
            )
            invoice_id = cur.lastrowid

            for li in line_items:
                conn.execute(
                    """INSERT INTO invoice_line_item
                        (invoice_id, product_id, description, quantity,
                         unit_price_minor, line_subtotal_minor, vat_applicable,
                         vat_rate_pct, vat_amount_minor, line_total_minor,
                         discount_pct, discount_amount_minor)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        invoice_id, li.product_id, li.description, li.quantity,
                        li.unit_price_minor, li.line_subtotal_minor,
                        int(li.vat_applicable), li.vat_rate_pct,
                        li.vat_amount_minor, li.line_total_minor,
                        li.discount_pct, li.discount_amount_minor,
                    ),
                )

        return Invoice(
            invoice_id=invoice_id,
            business_id=business_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            customer_id=customer_id,
            customer_name_token=customer_name_token,
            customer_contact=customer_contact,
            subtotal_minor=subtotal_minor,
            vat_amount_minor=vat_amount_minor,
            total_amount_minor=total_amount_minor,
            amount_paid_minor=0,
            balance_due_minor=total_amount_minor,
            payment_status="unpaid",
            notes=notes,
            status=status,
            created_by=created_by,
            line_items=line_items,
        )

    def get_invoice(self, invoice_id: int) -> Optional[Invoice]:
        """Get invoice with line items."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM invoice WHERE invoice_id = ?", (invoice_id,)
            ).fetchone()
            if row is None:
                return None
            line_rows = conn.execute(
                "SELECT * FROM invoice_line_item WHERE invoice_id = ? ORDER BY line_id",
                (invoice_id,),
            ).fetchall()

        line_items = [
            InvoiceLineItem(
                line_id=lr["line_id"],
                invoice_id=lr["invoice_id"],
                product_id=lr["product_id"],
                description=lr["description"],
                quantity=lr["quantity"],
                unit_price_minor=lr["unit_price_minor"],
                line_subtotal_minor=lr["line_subtotal_minor"],
                vat_applicable=bool(lr["vat_applicable"]),
                vat_rate_pct=lr["vat_rate_pct"],
                vat_amount_minor=lr["vat_amount_minor"],
                line_total_minor=lr["line_total_minor"],
                discount_pct=lr["discount_pct"],
                discount_amount_minor=lr["discount_amount_minor"],
            )
            for lr in line_rows
        ]

        return Invoice(
            invoice_id=row["invoice_id"],
            business_id=row["business_id"],
            invoice_number=row["invoice_number"],
            invoice_date=row["invoice_date"],
            due_date=row["due_date"],
            customer_id=row["customer_id"],
            customer_name_token=row["customer_name_token"],
            customer_contact=row["customer_contact"],
            subtotal_minor=row["subtotal_minor"],
            vat_amount_minor=row["vat_amount_minor"],
            total_amount_minor=row["total_amount_minor"],
            amount_paid_minor=row["amount_paid_minor"],
            balance_due_minor=row["balance_due_minor"],
            payment_status=row["payment_status"],
            last_payment_date=row["last_payment_date"],
            follow_up_status=row["follow_up_status"],
            follow_up_count=row["follow_up_count"],
            last_follow_up_date=row["last_follow_up_date"],
            notes=row["notes"],
            status=row["status"],
            created_at=row["created_at"],
            created_by=row["created_by"],
            line_items=line_items,
        )

    def list_invoices(
        self,
        business_id: int,
        status: Optional[str] = None,
        payment_status: Optional[str] = None,
        overdue_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Invoice]:
        """List invoices with optional filters."""
        query = "SELECT * FROM invoice WHERE business_id = ?"
        params: list = [business_id]

        if status:
            query += " AND status = ?"
            params.append(status)
        if payment_status:
            query += " AND payment_status = ?"
            params.append(payment_status)
        if overdue_only:
            query += " AND due_date < date('now') AND payment_status NOT IN ('paid','cancelled')"

        query += " ORDER BY invoice_date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            Invoice(
                invoice_id=r["invoice_id"],
                business_id=r["business_id"],
                invoice_number=r["invoice_number"],
                invoice_date=r["invoice_date"],
                due_date=r["due_date"],
                customer_id=r["customer_id"],
                customer_name_token=r["customer_name_token"],
                customer_contact=r["customer_contact"],
                subtotal_minor=r["subtotal_minor"],
                vat_amount_minor=r["vat_amount_minor"],
                total_amount_minor=r["total_amount_minor"],
                amount_paid_minor=r["amount_paid_minor"],
                balance_due_minor=r["balance_due_minor"],
                payment_status=r["payment_status"],
                last_payment_date=r["last_payment_date"],
                follow_up_status=r["follow_up_status"],
                follow_up_count=r["follow_up_count"],
                last_follow_up_date=r["last_follow_up_date"],
                notes=r["notes"],
                status=r["status"],
                created_at=r["created_at"],
                created_by=r["created_by"],
            )
            for r in rows
        ]

    def get_invoice_summary(self, business_id: int) -> Dict:
        """Get invoice KPIs."""
        with self._get_conn() as conn:
            totals = conn.execute(
                """SELECT
                    COUNT(*) AS total_count,
                    COALESCE(SUM(total_amount_minor), 0) AS total_amount,
                    COALESCE(SUM(amount_paid_minor), 0) AS total_paid,
                    COALESCE(SUM(balance_due_minor), 0) AS total_outstanding,
                    COALESCE(SUM(CASE WHEN payment_status = 'overdue'
                         OR (due_date < date('now') AND payment_status NOT IN ('paid','cancelled'))
                         THEN balance_due_minor ELSE 0 END), 0) AS overdue_amount
                FROM invoice
                WHERE business_id = ? AND status = 'active'""",
                (business_id,),
            ).fetchone()

            by_status = conn.execute(
                """SELECT payment_status, COUNT(*) AS cnt,
                          COALESCE(SUM(balance_due_minor), 0) AS balance
                FROM invoice
                WHERE business_id = ? AND status = 'active'
                GROUP BY payment_status""",
                (business_id,),
            ).fetchall()

        return {
            "total_count": totals["total_count"] if totals else 0,
            "total_amount_minor": totals["total_amount"] if totals else 0,
            "total_paid_minor": totals["total_paid"] if totals else 0,
            "total_outstanding_minor": totals["total_outstanding"] if totals else 0,
            "overdue_amount_minor": totals["overdue_amount"] if totals else 0,
            "by_status": {
                s["payment_status"]: {"count": s["cnt"], "balance_minor": s["balance"]}
                for s in by_status
            },
        }

    # ------------------------------------------------------------------
    # Payment Recording
    # ------------------------------------------------------------------

    def record_payment(
        self,
        business_id: int,
        invoice_id: int,
        amount_minor: int,
        payment_method: str = "cash",
        reference_number: Optional[str] = None,
        mpesa_reference: Optional[str] = None,
        notes: Optional[str] = None,
        recorded_by: Optional[str] = None,
    ) -> bool:
        """Record a payment against an invoice."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._get_conn() as conn:
            inv = conn.execute(
                "SELECT * FROM invoice WHERE invoice_id = ? AND business_id = ?",
                (invoice_id, business_id),
            ).fetchone()
            if inv is None:
                return False

            new_paid = inv["amount_paid_minor"] + amount_minor
            new_balance = inv["total_amount_minor"] - new_paid

            if new_balance <= 0:
                payment_status = "paid"
                new_balance = 0
            else:
                payment_status = "partial"

            conn.execute(
                """UPDATE invoice SET
                    amount_paid_minor = ?, balance_due_minor = ?,
                    payment_status = ?, last_payment_date = ?,
                    follow_up_status = CASE WHEN ? = 'paid' THEN 'payment_received' ELSE follow_up_status END
                WHERE invoice_id = ?""",
                (new_paid, new_balance, payment_status, now, payment_status, invoice_id),
            )

            # Get customer_id from invoice
            customer_id = inv["customer_id"]

            conn.execute(
                """INSERT INTO payment_record
                    (business_id, payment_date, reference_number, invoice_id,
                     customer_id, amount_minor, payment_method, mpesa_reference,
                     notes, recorded_by)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    business_id, now, reference_number, invoice_id,
                    customer_id, amount_minor, payment_method, mpesa_reference,
                    notes, recorded_by,
                ),
            )
            return True

    def get_payments_for_invoice(self, invoice_id: int) -> List[PaymentRecord]:
        """Get all payments for an invoice."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM payment_record WHERE invoice_id = ? ORDER BY payment_date DESC",
                (invoice_id,),
            ).fetchall()

        return [
            PaymentRecord(
                payment_id=r["payment_id"],
                business_id=r["business_id"],
                payment_date=r["payment_date"],
                reference_number=r["reference_number"],
                invoice_id=r["invoice_id"],
                sale_id=r["sale_id"],
                customer_id=r["customer_id"],
                amount_minor=r["amount_minor"],
                payment_method=r["payment_method"],
                mpesa_reference=r["mpesa_reference"],
                notes=r["notes"],
                recorded_by=r["recorded_by"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Quotations
    # ------------------------------------------------------------------

    def create_quotation(
        self,
        business_id: int,
        customer_id: int,
        line_items: List[QuotationLineItem],
        customer_name_token: Optional[str] = None,
        valid_days: int = 14,
        notes: Optional[str] = None,
        terms: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Quotation:
        """Create a new quotation."""
        quotation_number = self._get_next_quotation_number(business_id)
        now = datetime.now()
        quotation_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        valid_until = (now + timedelta(days=valid_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        subtotal_minor = sum(li.line_subtotal_minor for li in line_items)
        vat_amount_minor = sum(li.vat_amount_minor for li in line_items)
        total_minor = subtotal_minor + vat_amount_minor

        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO quotation
                    (business_id, quotation_number, quotation_date, valid_until_date,
                     customer_id, customer_name_token, subtotal_minor, vat_amount_minor,
                     total_minor, status, notes, terms, created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    business_id, quotation_number, quotation_date, valid_until,
                    customer_id, customer_name_token, subtotal_minor, vat_amount_minor,
                    total_minor, "draft", notes, terms, created_by,
                ),
            )
            quotation_id = cur.lastrowid

            for li in line_items:
                conn.execute(
                    """INSERT INTO quotation_line_item
                        (quotation_id, product_id, description, quantity,
                         unit_price_minor, line_subtotal_minor, vat_applicable,
                         vat_rate_pct, vat_amount_minor, line_total_minor)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        quotation_id, li.product_id, li.description, li.quantity,
                        li.unit_price_minor, li.line_subtotal_minor,
                        int(li.vat_applicable), li.vat_rate_pct,
                        li.vat_amount_minor, li.line_total_minor,
                    ),
                )

        return Quotation(
            quotation_id=quotation_id,
            business_id=business_id,
            quotation_number=quotation_number,
            quotation_date=quotation_date,
            valid_until_date=valid_until,
            customer_id=customer_id,
            customer_name_token=customer_name_token,
            subtotal_minor=subtotal_minor,
            vat_amount_minor=vat_amount_minor,
            total_minor=total_minor,
            status="draft",
            notes=notes,
            terms=terms,
            created_by=created_by,
            line_items=line_items,
        )

    def convert_quotation_to_invoice(
        self, quotation_id: int, due_days: int = 30, created_by: Optional[str] = None
    ) -> Optional[Invoice]:
        """Convert an accepted quotation to an invoice."""
        with self._get_conn() as conn:
            qt = conn.execute(
                "SELECT * FROM quotation WHERE quotation_id = ? AND status IN ('accepted','sent')",
                (quotation_id,),
            ).fetchone()
            if qt is None:
                return None

            qt_lines = conn.execute(
                "SELECT * FROM quotation_line_item WHERE quotation_id = ?",
                (quotation_id,),
            ).fetchall()

        line_items = [
            InvoiceLineItem(
                product_id=ql["product_id"],
                description=ql["description"],
                quantity=ql["quantity"],
                unit_price_minor=ql["unit_price_minor"],
                line_subtotal_minor=ql["line_subtotal_minor"],
                vat_applicable=bool(ql["vat_applicable"]),
                vat_rate_pct=ql["vat_rate_pct"],
                vat_amount_minor=ql["vat_amount_minor"],
                line_total_minor=ql["line_total_minor"],
            )
            for ql in qt_lines
        ]

        invoice = self.create_invoice(
            business_id=qt["business_id"],
            customer_id=qt["customer_id"],
            line_items=line_items,
            customer_name_token=qt["customer_name_token"],
            due_days=due_days,
            notes=f"Converted from Quotation {qt['quotation_number']}",
            created_by=created_by,
        )

        with self._get_conn() as conn:
            conn.execute(
                "UPDATE quotation SET status = 'converted_to_invoice', converted_to_invoice_id = ? WHERE quotation_id = ?",
                (invoice.invoice_id, quotation_id),
            )

        return invoice

    def get_quotation(self, quotation_id: int) -> Optional[Quotation]:
        """Get quotation with line items."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM quotation WHERE quotation_id = ?", (quotation_id,)
            ).fetchone()
            if row is None:
                return None
            line_rows = conn.execute(
                "SELECT * FROM quotation_line_item WHERE quotation_id = ? ORDER BY line_id",
                (quotation_id,),
            ).fetchall()

        return Quotation(
            quotation_id=row["quotation_id"],
            business_id=row["business_id"],
            quotation_number=row["quotation_number"],
            quotation_date=row["quotation_date"],
            valid_until_date=row["valid_until_date"],
            customer_id=row["customer_id"],
            customer_name_token=row["customer_name_token"],
            subtotal_minor=row["subtotal_minor"],
            vat_amount_minor=row["vat_amount_minor"],
            total_minor=row["total_minor"],
            status=row["status"],
            converted_to_invoice_id=row["converted_to_invoice_id"],
            notes=row["notes"],
            terms=row["terms"],
            created_at=row["created_at"],
            created_by=row["created_by"],
            line_items=[
                QuotationLineItem(
                    line_id=lr["line_id"],
                    quotation_id=lr["quotation_id"],
                    product_id=lr["product_id"],
                    description=lr["description"],
                    quantity=lr["quantity"],
                    unit_price_minor=lr["unit_price_minor"],
                    line_subtotal_minor=lr["line_subtotal_minor"],
                    vat_applicable=bool(lr["vat_applicable"]),
                    vat_rate_pct=lr["vat_rate_pct"],
                    vat_amount_minor=lr["vat_amount_minor"],
                    line_total_minor=lr["line_total_minor"],
                )
                for lr in line_rows
            ],
        )

    def list_quotations(
        self, business_id: int, status: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> List[Quotation]:
        """List quotations."""
        query = "SELECT * FROM quotation WHERE business_id = ?"
        params: list = [business_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY quotation_date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            Quotation(
                quotation_id=r["quotation_id"],
                business_id=r["business_id"],
                quotation_number=r["quotation_number"],
                quotation_date=r["quotation_date"],
                valid_until_date=r["valid_until_date"],
                customer_id=r["customer_id"],
                customer_name_token=r["customer_name_token"],
                subtotal_minor=r["subtotal_minor"],
                vat_amount_minor=r["vat_amount_minor"],
                total_minor=r["total_minor"],
                status=r["status"],
                converted_to_invoice_id=r["converted_to_invoice_id"],
                notes=r["notes"],
                terms=r["terms"],
                created_at=r["created_at"],
                created_by=r["created_by"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # VAT Breakdown (for a given invoice)
    # ------------------------------------------------------------------

    def get_invoice_vat_breakdown(self, invoice_id: int) -> Dict:
        """Get VAT breakdown for an invoice by rate."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT vat_rate_pct,
                    COALESCE(SUM(line_subtotal_minor), 0) AS subtotal,
                    COALESCE(SUM(vat_amount_minor), 0) AS vat
                FROM invoice_line_item
                WHERE invoice_id = ? AND vat_applicable = 1
                GROUP BY vat_rate_pct""",
                (invoice_id,),
            ).fetchall()

        return {
            "breakdown": [
                {"vat_rate_pct": r["vat_rate_pct"], "subtotal_minor": r["subtotal"], "vat_amount_minor": r["vat"]}
                for r in rows
            ],
            "total_vat": sum(r["vat"] for r in rows),
        }

    def get_outstanding_invoices(self, business_id: int) -> List[Invoice]:
        """Get all outstading (unpaid/overdue) invoices."""
        return self.list_invoices(
            business_id, status="active", payment_status="unpaid", limit=500
        )

    def get_recent_payments(
        self, business_id: int, days: int = 30, limit: int = 50
    ) -> List[PaymentRecord]:
        """Get recent payment records across all invoices."""
        cut = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM payment_record
                WHERE invoice_id IN (
                    SELECT invoice_id FROM invoice WHERE business_id = ?
                )
                AND payment_date >= ?
                ORDER BY payment_date DESC LIMIT ?""",
                (business_id, cut, limit),
            ).fetchall()

        return [
            PaymentRecord(
                payment_id=r["payment_id"],
                invoice_id=r["invoice_id"],
                amount_minor=r["amount_minor"],
                payment_method=r["payment_method"],
                payment_reference=r["payment_reference"],
                payment_date=r["payment_date"],
                notes=r["notes"],
            )
            for r in rows
        ]

    def update_quotation_status(self, quotation_id: int, status: str) -> bool:
        """Update a quotation's status (draft, sent, accepted, declined, converted)."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE quotation SET status = ? WHERE quotation_id = ?",
                (status, quotation_id),
            )
            return conn.total_changes > 0
