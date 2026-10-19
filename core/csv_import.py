"""CSV imports for the invoicing system: products, customers and past sales.

Each import validates every row and loads the good ones; bad rows are
reported with their line number and reason and change nothing. Re-importing
the same file is safe: products and customers are matched (SKU, name) and
updated, and sales already imported (same sale_ref) are skipped.

Money is parsed with Decimal, never float, so "19.99" is exactly 1999 cents.
Customer phone numbers and emails are stored only as hashes
(party_identifier), like every other identifier in Duka.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from core.config import config

PRODUCT_COLUMNS = ["sku", "name", "category", "description", "cost_price", "selling_price",
                   "vat_applicable", "vat_rate_pct", "stock_qty", "reorder_level", "reorder_qty", "barcode"]
CUSTOMER_COLUMNS = ["name", "phone", "email", "notes"]
SALE_COLUMNS = ["sale_ref", "sale_date", "customer", "sku", "quantity", "unit_price",
                "discount_pct", "payment_method", "notes"]

PRODUCT_TEMPLATE = (
    ",".join(PRODUCT_COLUMNS) + "\n"
    "RTR-TPL-01,Dual-band Wi-Fi router,Hardware,Router for home plans,3200.00,4500.00,yes,16,10,3,10,\n"
)
CUSTOMER_TEMPLATE = ",".join(CUSTOMER_COLUMNS) + "\nAcme Cyber Cafe,0712345678,accounts@acme.co.ke,Pays on the 5th\n"
SALE_TEMPLATE = (
    ",".join(SALE_COLUMNS) + "\n"
    "S-0001,2026-10-01 10:30,Acme Cyber Cafe,RTR-TPL-01,1,,0,m_pesa,\n"
)

PAYMENT_METHODS = ("cash", "m_pesa", "card", "cheque", "credit")
_TRUE = {"yes", "y", "true", "1"}
_FALSE = {"no", "n", "false", "0"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MAX_ROWS = 5000


class CSVImportError(ValueError):
    """The file itself can't be imported (bad encoding, wrong columns)."""


@dataclass
class ImportReport:
    kind: str
    rows_read: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[Tuple[int, str]] = field(default_factory=list)  # (line number, reason)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        parts = [f"{self.created} created", f"{self.updated} updated"]
        if self.skipped:
            parts.append(f"{self.skipped} already imported")
        if self.errors:
            parts.append(f"{len(self.errors)} row(s) rejected")
        return f"{self.kind.title()}: " + ", ".join(parts) + f" ({self.rows_read} rows read)."


# ---- parsing helpers ----

def _read_rows(data, required: List[str], allowed: List[str]) -> List[Tuple[int, Dict[str, str]]]:
    """(line number, {column: stripped value}) for each non-blank data row."""
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise CSVImportError("The file is not UTF-8 text. Save it as 'CSV UTF-8' and try again.") from e
    reader = csv.reader(io.StringIO(data))
    try:
        header = next(reader)
    except StopIteration:
        raise CSVImportError("The file is empty.")
    header = [h.strip().lower().replace(" ", "_") for h in header]
    missing = [c for c in required if c not in header]
    if missing:
        raise CSVImportError(f"Missing column(s): {', '.join(missing)}. Expected: {', '.join(allowed)}.")
    unknown = [h for h in header if h and h not in allowed]
    if unknown:
        raise CSVImportError(f"Unknown column(s): {', '.join(unknown)}. Expected: {', '.join(allowed)}.")
    if len(set(header)) != len(header):
        raise CSVImportError("A column name appears twice in the header.")
    rows = []
    for line_no, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue
        if len(values) > len(header):
            rows.append((line_no, {"__error__": f"has {len(values)} values but the header has {len(header)} columns"}))
            continue
        values += [""] * (len(header) - len(values))
        rows.append((line_no, {h: v.strip() for h, v in zip(header, values)}))
        if len(rows) > MAX_ROWS:
            raise CSVImportError(f"Too many rows; import at most {MAX_ROWS} at a time.")
    return rows


def parse_money(raw: str, field_name: str, allow_zero: bool = True) -> int:
    """'1,200.50' / 'KES 1200' -> minor units. No float rounding; more than
    two decimals is an error rather than a silent rounding."""
    s = re.sub(r"(?i)^(kes|ksh)\s*", "", (raw or "").replace(",", "").strip())
    if s == "":
        raise ValueError(f"{field_name} is required")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"{field_name} {raw!r} is not a number")
    if not d.is_finite():
        raise ValueError(f"{field_name} {raw!r} is not a number")
    if d < 0:
        raise ValueError(f"{field_name} can't be negative")
    if d != d.quantize(Decimal("0.01")):
        raise ValueError(f"{field_name} {raw!r} has more than 2 decimal places")
    minor = int(d * 100)
    if minor == 0 and not allow_zero:
        raise ValueError(f"{field_name} must be more than 0")
    return minor


def _parse_int(raw: str, field_name: str, default: Optional[int] = None, minimum: int = 0) -> int:
    if (raw or "") == "":
        if default is None:
            raise ValueError(f"{field_name} is required")
        return default
    if not re.fullmatch(r"-?\d+", raw.replace(",", "")):
        raise ValueError(f"{field_name} {raw!r} must be a whole number")
    n = int(raw.replace(",", ""))
    if n < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return n


def _parse_pct(raw: str, field_name: str, default: float) -> float:
    if (raw or "") == "":
        return default
    try:
        d = Decimal(raw.rstrip("%").strip())
    except InvalidOperation:
        raise ValueError(f"{field_name} {raw!r} is not a number")
    if not d.is_finite() or not Decimal(0) <= d <= Decimal(100):
        raise ValueError(f"{field_name} must be between 0 and 100")
    return float(d)


def _parse_bool(raw: str, field_name: str, default: bool) -> bool:
    v = (raw or "").lower()
    if v == "":
        return default
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError(f"{field_name} {raw!r} must be yes or no")


def _parse_when(raw: str, today: datetime) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            when = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"sale_date {raw!r} must look like 2026-10-01 or 2026-10-01 14:30")
    if when > today:
        raise ValueError(f"sale_date {raw} is in the future")
    return when


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---- products ----

def import_products(data, business_id: int, db_path: Optional[str] = None) -> ImportReport:
    """Create or update products by SKU. stock_qty sets the stock level; a
    change to an existing product's stock is logged as an adjustment."""
    db_path = db_path or config.DB_PATH
    report = ImportReport("products")
    rows = _read_rows(data, ["sku", "name", "cost_price", "selling_price"], PRODUCT_COLUMNS)
    report.rows_read = len(rows)
    seen_skus: Dict[str, int] = {}
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _connect(db_path)
    try:
        for line, r in rows:
            try:
                if "__error__" in r:
                    raise ValueError(r["__error__"])
                sku, name = r.get("sku", ""), re.sub(r"\s+", " ", r.get("name", ""))
                if not sku:
                    raise ValueError("sku is required")
                if len(sku) > 64 or not re.fullmatch(r"[\w\-./]+", sku):
                    raise ValueError(f"sku {sku!r} may only use letters, digits and - _ . / (max 64)")
                if sku.upper() in seen_skus:
                    raise ValueError(f"sku {sku} is repeated (first on line {seen_skus[sku.upper()]})")
                if not name or len(name) > 120:
                    raise ValueError("name is required (max 120 characters)")
                cost = parse_money(r.get("cost_price", ""), "cost_price")
                price = parse_money(r.get("selling_price", ""), "selling_price", allow_zero=False)
                vat_on = _parse_bool(r.get("vat_applicable", ""), "vat_applicable", True)
                vat_rate = _parse_pct(r.get("vat_rate_pct", ""), "vat_rate_pct", 16.0) if vat_on else 0.0
                stock = _parse_int(r.get("stock_qty", ""), "stock_qty", default=0)
                reorder_level = _parse_int(r.get("reorder_level", ""), "reorder_level", default=10)
                reorder_qty = _parse_int(r.get("reorder_qty", ""), "reorder_qty", default=50)
                barcode = r.get("barcode") or None
                if barcode:
                    clash = conn.execute("SELECT business_id, sku FROM product WHERE barcode = ?", (barcode,)).fetchone()
                    if clash and not (clash["business_id"] == business_id and clash["sku"].upper() == sku.upper()):
                        raise ValueError(f"barcode {barcode} already belongs to another product")
            except ValueError as e:
                report.errors.append((line, str(e)))
                continue
            seen_skus[sku.upper()] = line
            existing = conn.execute(
                "SELECT product_id, current_stock_qty FROM product WHERE business_id = ? AND UPPER(sku) = ?",
                (business_id, sku.upper()),
            ).fetchone()
            fields = (name, r.get("description") or None, r.get("category") or None, cost, price,
                      1 if vat_on else 0, vat_rate, reorder_level, reorder_qty, barcode)
            if existing:
                conn.execute(
                    """UPDATE product SET name=?, description=?, category=?, cost_price_minor=?,
                           selling_price_minor=?, vat_applicable=?, vat_rate_pct=?, reorder_level_qty=?,
                           reorder_qty=?, barcode=?, current_stock_qty=?, is_active=1, updated_at=?
                       WHERE product_id=?""",
                    (*fields, stock, now, existing["product_id"]),
                )
                delta = stock - existing["current_stock_qty"]
                if delta:
                    conn.execute(
                        """INSERT INTO inventory_transaction (business_id, product_id, type, quantity, notes, recorded_by)
                           VALUES (?, ?, 'adjustment', ?, ?, 'csv_import')""",
                        (business_id, existing["product_id"], abs(delta),
                         f"CSV import set stock {existing['current_stock_qty']} -> {stock}"),
                    )
                report.updated += 1
            else:
                conn.execute(
                    """INSERT INTO product (name, description, category, cost_price_minor, selling_price_minor,
                           vat_applicable, vat_rate_pct, reorder_level_qty, reorder_qty, barcode,
                           business_id, sku, current_stock_qty, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*fields, business_id, sku, stock, now, now),
                )
                report.created += 1
        conn.commit()
    finally:
        conn.close()
    return report


# ---- customers ----

def import_customers(data, business_id: int, db_path: Optional[str] = None) -> ImportReport:
    """Create customers by name (existing names are updated). Phone and
    email are validated and stored hashed."""
    from auth.phone_utils import hash_email, hash_phone, normalise_phone
    from core.invoice_manager import normalise_customer_name, upsert_customer

    db_path = db_path or config.DB_PATH
    report = ImportReport("customers")
    rows = _read_rows(data, ["name"], CUSTOMER_COLUMNS)
    report.rows_read = len(rows)
    seen: Dict[str, int] = {}
    conn = _connect(db_path)
    try:
        for line, r in rows:
            try:
                if "__error__" in r:
                    raise ValueError(r["__error__"])
                key = normalise_customer_name(r.get("name"))
                if not key:
                    raise ValueError("name is required")
                if key in seen:
                    raise ValueError(f"customer {key} is repeated (first on line {seen[key]})")
                phone = r.get("phone", "")
                phone_hash = hash_phone(normalise_phone(phone)) if phone else None
                email = r.get("email", "").lower()
                if email and not _EMAIL.match(email):
                    raise ValueError(f"email {email!r} is not a valid address")
            except ValueError as e:
                report.errors.append((line, str(e)))
                continue
            seen[key] = line
            from core.ingestion import _party_token
            existed = conn.execute(
                "SELECT 1 FROM party WHERE business_id = ? AND display_token = ? AND kind = 'customer'",
                (business_id, _party_token(business_id, key)),
            ).fetchone()
            party_id = upsert_customer(conn, business_id, key)
            if r.get("notes"):
                conn.execute("UPDATE party SET note = ? WHERE party_id = ?", (r["notes"][:500], party_id))
            for id_type, value in (("phone_hash", phone_hash), ("email_hash", hash_email(email) if email else None)):
                if value:
                    conn.execute(
                        "INSERT OR IGNORE INTO party_identifier (party_id, id_type, value_hash) VALUES (?, ?, ?)",
                        (party_id, id_type, value),
                    )
            if existed:
                report.updated += 1
            else:
                report.created += 1
        conn.commit()
    finally:
        conn.close()
    return report


# ---- sales ----

def import_sales(data, business_id: int, db_path: Optional[str] = None,
                 today: Optional[datetime] = None, recorded_by: str = "csv_import") -> ImportReport:
    """Import past sales. Rows sharing a sale_ref are one sale (its line
    items); date, customer and payment method must agree across them. VAT
    uses each product's own rate; stock is reduced as at the POS. A sale is
    all-or-nothing: one bad line rejects the whole sale. A sale_ref already
    imported is skipped, so re-importing a file adds nothing twice."""
    from core.invoice_manager import upsert_customer
    from core.pos_engine import POSEngine

    db_path = db_path or config.DB_PATH
    today = today or datetime.now()
    report = ImportReport("sales")
    rows = _read_rows(data, ["sale_ref", "sale_date", "sku", "quantity", "payment_method"], SALE_COLUMNS)
    report.rows_read = len(rows)

    groups: Dict[str, List[Tuple[int, Dict[str, str]]]] = {}
    for line, r in rows:
        if "__error__" in r:
            report.errors.append((line, r["__error__"]))
            continue
        ref = r.get("sale_ref", "")
        if not ref:
            report.errors.append((line, "sale_ref is required"))
            continue
        groups.setdefault(ref, []).append((line, r))

    pos = POSEngine(db_path)
    conn = _connect(db_path)
    try:
        products = {row["sku"].upper(): row for row in conn.execute(
            "SELECT * FROM product WHERE business_id = ? AND is_active = 1", (business_id,))}
        stock = {sku: p["current_stock_qty"] for sku, p in products.items()}
    finally:
        conn.close()

    for ref, lines in groups.items():
        first_line = lines[0][0]
        sale_number = f"IMP-{business_id}-{ref}"[:60]
        try:
            with _connect(db_path) as c:
                if c.execute("SELECT 1 FROM sale WHERE sale_number = ?", (sale_number,)).fetchone():
                    report.skipped += 1
                    continue
            head = lines[0][1]
            for line, r in lines[1:]:
                for col in ("sale_date", "customer", "payment_method"):
                    if r.get(col, "").lower() != head.get(col, "").lower():
                        raise ValueError(f"line {line}: {col} differs from line {first_line} of the same sale")
            when = _parse_when(head.get("sale_date", ""), today)
            method = head.get("payment_method", "").lower()
            if method not in PAYMENT_METHODS:
                raise ValueError(f"payment_method {method!r} must be one of {', '.join(PAYMENT_METHODS)}")
            items, need = [], {}
            for line, r in lines:
                sku = r.get("sku", "").upper()
                product = products.get(sku)
                if product is None:
                    raise ValueError(f"line {line}: unknown or inactive sku {r.get('sku')!r}")
                qty = _parse_int(r.get("quantity", ""), f"line {line}: quantity", minimum=1)
                price = (parse_money(r["unit_price"], f"line {line}: unit_price", allow_zero=False)
                         if r.get("unit_price") else product["selling_price_minor"])
                discount = _parse_pct(r.get("discount_pct", ""), f"line {line}: discount_pct", 0.0)
                need[sku] = need.get(sku, 0) + qty
                items.append(POSEngine.build_line_item(
                    product_id=product["product_id"], quantity=qty, selling_price_minor=price,
                    vat_rate_pct=product["vat_rate_pct"], vat_applicable=bool(product["vat_applicable"]),
                    discount_pct=discount or None,
                ))
            short = [f"{sku} (needs {n}, {stock[sku]} in stock)" for sku, n in need.items() if n > stock[sku]]
            if short:
                raise ValueError("not enough stock: " + "; ".join(short))
        except ValueError as e:
            report.errors.append((first_line, f"sale {ref}: {e}"))
            continue

        customer = head.get("customer", "")
        customer_id = None
        if customer:
            with _connect(db_path) as c:
                customer_id = upsert_customer(c, business_id, customer)
        pos.create_sale(
            business_id=business_id, line_items=items, customer_id=customer_id,
            customer_name_token=customer or None, payment_method=method,
            notes=head.get("notes") or None, created_by_user=recorded_by,
            sale_date=when, sale_number=sale_number,
        )
        for sku, n in need.items():
            stock[sku] -= n
        report.created += 1
    return report
