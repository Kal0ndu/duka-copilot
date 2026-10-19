"""Invoice Manager: invoicing, quotations, payments, follow-ups."""
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re
import sqlite3

# An invoice the customer owes on: issued, not a draft and not cancelled.
ISSUED_STATUSES = ("active", "sent", "overdue")
OPEN_PAYMENT_STATUSES = ("unpaid", "partial", "overdue")
_ISSUED_SQL = "(" + ",".join(f"'{s}'" for s in ISSUED_STATUSES) + ")"
_OPEN_SQL = "(" + ",".join(f"'{s}'" for s in OPEN_PAYMENT_STATUSES) + ")"


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


def normalise_customer_name(name: Optional[str]) -> str:
    """How customer names are keyed: single spaces, upper case, max 80 chars."""
    return re.sub(r"\s+", " ", (name or "")).strip().upper()[:80]


def upsert_customer(conn, business_id: int, name: Optional[str]) -> int:
    """party_id of this business's customer called `name`, created on first
    use. Names are tokenised the same way statement payers are (original
    kept only in the local token_vault), so "Acme Ltd" on an invoice, an
    import and an M-Pesa receipt is one party."""
    key = normalise_customer_name(name)
    if not key:
        raise ValueError("A customer name is required.")
    from core.ingestion import _party_token
    token = _party_token(business_id, key)
    conn.execute(
        """INSERT INTO party (business_id, kind, display_token, is_business_related, first_seen, last_seen)
           VALUES (?, 'customer', ?, 1, date('now'), date('now'))
           ON CONFLICT (business_id, display_token) DO UPDATE SET
             kind = CASE WHEN party.kind = 'unknown' THEN 'customer' ELSE party.kind END,
             last_seen = date('now')""",
        (business_id, token),
    )
    conn.execute(
        "INSERT OR IGNORE INTO token_vault (token, business_id, entity_type, original_value) VALUES (?, ?, 'PERSON', ?)",
        (token, business_id, key),
    )
    return conn.execute(
        "SELECT party_id FROM party WHERE business_id = ? AND display_token = ?", (business_id, token)
    ).fetchone()[0]


def list_customers(db_path: str, business_id: int) -> List[Dict]:
    """This business's customer parties with their names (from the local vault)."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT p.party_id, COALESCE(v.original_value, p.display_token) AS name, p.note, p.first_seen
               FROM party p
               LEFT JOIN token_vault v ON v.token = p.display_token AND v.business_id = p.business_id
               WHERE p.business_id = ? AND p.kind = 'customer'
               ORDER BY name""",
            (business_id,),
        ).fetchall()
    return [dict(r) for r in rows]


class InvoiceManager:
    """Manage invoices, quotations, payments, and follow-ups."""

    def __init__(self, db_path: Optional[str] = None):
        from core.config import config
        self.db_path = db_path or config.DB_PATH

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _resolve_customer(self, conn, business_id: int, customer_id: int,
                          customer_name: Optional[str]) -> int:
        """The party_id to bill: customer_id when given, else the customer
        party for the typed name (created on first use)."""
        if customer_id:
            return customer_id
        return upsert_customer(conn, business_id, customer_name)

    # ------------------------------------------------------------------
    # Number Generation
    # ------------------------------------------------------------------

    def _next_number(self, business_id: int, kind: str) -> str:
        """Next free {prefix}-{business_id}-{seq:06d} for 'invoice' or
        'quotation'. The sequence lives in pos_setting; a business without
        POS settings starts at 1000. Numbers already used are skipped, so
        the sequence can never hand out a duplicate."""
        table, number_col = ("invoice", "invoice_number") if kind == "invoice" else ("quotation", "quotation_number")
        default_prefix = "INV" if kind == "invoice" else "QT"
        with self._get_conn() as conn:
            pos = conn.execute(
                f"SELECT {kind}_prefix AS prefix, {kind}_sequence AS seq FROM pos_setting WHERE business_id = ?",
                (business_id,),
            ).fetchone()
            prefix = (pos["prefix"] if pos else None) or default_prefix
            seq = (pos["seq"] if pos else None) or 1000
            while conn.execute(f"SELECT 1 FROM {table} WHERE {number_col} = ?",
                               (f"{prefix}-{business_id}-{seq:06d}",)).fetchone():
                seq += 1
            conn.execute(f"UPDATE pos_setting SET {kind}_sequence = ? WHERE business_id = ?",
                         (seq + 1, business_id))
        return f"{prefix}-{business_id}-{seq:06d}"

    def _get_next_invoice_number(self, business_id: int) -> str:
        """Generate next invoice number using prefix + sequence."""
        return self._next_number(business_id, "invoice")

    def _get_next_quotation_number(self, business_id: int) -> str:
        """Generate next quotation number."""
        return self._next_number(business_id, "quotation")

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
        invoice_date: Optional[date] = None,
    ) -> Invoice:
        """Create a new invoice with line items. invoice_date defaults to now;
        the due date is due_days after it."""
        invoice_number = self._get_next_invoice_number(business_id)
        issued = datetime.combine(invoice_date, datetime.min.time()) if invoice_date else datetime.now()
        invoice_date = issued.strftime("%Y-%m-%dT%H:%M:%SZ")
        due_date = (issued + timedelta(days=due_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        subtotal_minor = sum(li.line_subtotal_minor for li in line_items)
        vat_amount_minor = sum(li.vat_amount_minor for li in line_items)
        total_amount_minor = subtotal_minor + vat_amount_minor

        with self._get_conn() as conn:
            customer_id = self._resolve_customer(conn, business_id, customer_id, customer_name_token)
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
                WHERE business_id = ? AND status IN """ + _ISSUED_SQL,
                (business_id,),
            ).fetchone()

            by_status = conn.execute(
                """SELECT payment_status, COUNT(*) AS cnt,
                          COALESCE(SUM(balance_due_minor), 0) AS balance
                FROM invoice
                WHERE business_id = ? AND status IN """ + _ISSUED_SQL + """
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
        """Record a payment against an issued, unpaid invoice of this business.
        Returns False when the amount is not positive or the invoice is not
        found, is a draft, or is already paid or cancelled."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        if not isinstance(amount_minor, int) or amount_minor <= 0:
            return False

        with self._get_conn() as conn:
            inv = conn.execute(
                "SELECT * FROM invoice WHERE invoice_id = ? AND business_id = ?",
                (invoice_id, business_id),
            ).fetchone()
            if (inv is None or inv["status"] not in ISSUED_STATUSES
                    or inv["payment_status"] not in OPEN_PAYMENT_STATUSES):
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
        quotation_date: Optional[date] = None,
    ) -> Quotation:
        """Create a new quotation. quotation_date defaults to now; it is
        valid for valid_days after it."""
        quotation_number = self._get_next_quotation_number(business_id)
        now = datetime.combine(quotation_date, datetime.min.time()) if quotation_date else datetime.now()
        quotation_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        valid_until = (now + timedelta(days=valid_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        subtotal_minor = sum(li.line_subtotal_minor for li in line_items)
        vat_amount_minor = sum(li.vat_amount_minor for li in line_items)
        total_minor = subtotal_minor + vat_amount_minor

        with self._get_conn() as conn:
            customer_id = self._resolve_customer(conn, business_id, customer_id, customer_name_token)
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
        """Convert a quotation the customer accepted into an invoice. Works
        from draft, sent or accepted; returns None for one that was
        rejected, expired or already converted."""
        with self._get_conn() as conn:
            qt = conn.execute(
                "SELECT * FROM quotation WHERE quotation_id = ? AND status IN ('draft','sent','accepted')",
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
        """Issued invoices with money still owed (unpaid, partial or overdue)."""
        with self._get_conn() as conn:
            ids = [r["invoice_id"] for r in conn.execute(
                "SELECT invoice_id FROM invoice WHERE business_id = ? AND status IN " + _ISSUED_SQL
                + " AND payment_status IN " + _OPEN_SQL + " ORDER BY due_date LIMIT 500",
                (business_id,),
            )]
        return [self.get_invoice(i) for i in ids]

    def get_recent_payments(
        self, business_id: int, days: int = 30, limit: int = 50
    ) -> List[Dict]:
        """Payments recorded against this business's invoices in the last
        `days` days, newest first, each with its invoice_number."""
        cut = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT pr.payment_id, pr.invoice_id, pr.payment_date, pr.amount_minor,
                          pr.payment_method, pr.reference_number, pr.mpesa_reference,
                          pr.notes, i.invoice_number
                FROM payment_record pr
                JOIN invoice i ON i.invoice_id = pr.invoice_id
                WHERE pr.business_id = ? AND i.business_id = ? AND pr.payment_date >= ?
                ORDER BY pr.payment_date DESC LIMIT ?""",
                (business_id, business_id, cut, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_quotation_status(self, quotation_id: int, status: str) -> bool:
        """Update a quotation's status (draft, sent, accepted, declined, converted)."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE quotation SET status = ? WHERE quotation_id = ?",
                (status, quotation_id),
            )
            return conn.total_changes > 0
