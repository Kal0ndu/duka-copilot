"""Inventory Manager: product CRUD, stock tracking, reorder alerts."""
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import sqlite3


@dataclass
class Product:
    product_id: Optional[int] = None
    business_id: int = 0
    sku: str = ""
    name: str = ""
    description: Optional[str] = None
    category: Optional[str] = None
    cost_price_minor: int = 0
    selling_price_minor: int = 0
    vat_applicable: bool = True
    vat_rate_pct: float = 16.0
    current_stock_qty: int = 0
    reorder_level_qty: int = 10
    reorder_qty: int = 50
    supplier_id: Optional[int] = None
    is_active: bool = True
    barcode: Optional[str] = None
    image_url: Optional[str] = None
    last_restocked_at: Optional[str] = None
    margin_pct: Optional[float] = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def cost_price(self) -> float:
        return self.cost_price_minor / 100

    @property
    def selling_price(self) -> float:
        return self.selling_price_minor / 100

    @property
    def stock_value_minor(self) -> int:
        return self.cost_price_minor * self.current_stock_qty

    @property
    def needs_reorder(self) -> bool:
        return self.current_stock_qty <= self.reorder_level_qty and self.is_active

    @property
    def margin_amount_minor(self) -> int:
        return self.selling_price_minor - self.cost_price_minor

    def compute_margin_pct(self) -> float:
        if self.selling_price_minor > 0:
            return (self.margin_amount_minor / self.selling_price_minor) * 100
        return 0.0


@dataclass
class InventoryTransaction:
    txn_id: Optional[int] = None
    business_id: int = 0
    product_id: int = 0
    type: str = "adjustment"  # purchase, sale, adjustment, return, damaged, loss
    quantity: int = 0
    reference_id: Optional[int] = None
    reference_type: Optional[str] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: str = ""


class InventoryManager:
    """Manage products, stock levels, and inventory transactions."""

    def __init__(self, db_path: Optional[str] = None):
        from core.config import config
        self.db_path = db_path or config.DB_PATH

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # Product CRUD
    # ------------------------------------------------------------------

    def create_product(self, p: Product) -> int:
        """Create a new product. Returns product_id."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO product
                    (business_id, sku, name, description, category,
                     cost_price_minor, selling_price_minor, vat_applicable,
                     vat_rate_pct, current_stock_qty, reorder_level_qty,
                     reorder_qty, supplier_id, is_active, barcode, image_url,
                     margin_pct, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    p.business_id, p.sku, p.name, p.description, p.category,
                    p.cost_price_minor, p.selling_price_minor,
                    int(p.vat_applicable), p.vat_rate_pct,
                    p.current_stock_qty, p.reorder_level_qty, p.reorder_qty,
                    p.supplier_id, int(p.is_active), p.barcode, p.image_url,
                    p.margin_pct, now, now,
                ),
            )
            return cur.lastrowid

    def update_product(self, p: Product) -> bool:
        """Update an existing product. Returns True if updated."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.execute(
                """UPDATE product SET
                    sku=?, name=?, description=?, category=?,
                    cost_price_minor=?, selling_price_minor=?,
                    vat_applicable=?, vat_rate_pct=?,
                    reorder_level_qty=?, reorder_qty=?,
                    supplier_id=?, is_active=?, barcode=?, image_url=?,
                    margin_pct=?, updated_at=?
                WHERE product_id=? AND business_id=?""",
                (
                    p.sku, p.name, p.description, p.category,
                    p.cost_price_minor, p.selling_price_minor,
                    int(p.vat_applicable), p.vat_rate_pct,
                    p.reorder_level_qty, p.reorder_qty,
                    p.supplier_id, int(p.is_active), p.barcode, p.image_url,
                    p.margin_pct, now,
                    p.product_id, p.business_id,
                ),
            )
            return cur.rowcount > 0


    def toggle_product_active(self, product_id: int) -> bool:
        """Toggle the active status of a product."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE product SET is_active = 1 - is_active WHERE product_id = ?",
                (product_id,),
            )
            return conn.total_changes > 0

    def get_product(self, product_id: int) -> Optional[Product]:
        """Get a single product by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM product WHERE product_id = ?", (product_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_product(row)

    def get_product_by_sku(self, business_id: int, sku: str) -> Optional[Product]:
        """Get a product by SKU within a business."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM product WHERE business_id = ? AND sku = ?",
                (business_id, sku),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_product(row)

    def get_product_by_barcode(self, barcode: str) -> Optional[Product]:
        """Get a product by barcode (globally unique)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM product WHERE barcode = ?", (barcode,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_product(row)

    def list_products(
        self,
        business_id: int,
        category: Optional[str] = None,
        active_only: bool = True,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Product]:
        """List products with optional filters."""
        query = "SELECT * FROM product WHERE business_id = ?"
        params: list = [business_id]

        if active_only:
            query += " AND is_active = 1"
        if category:
            query += " AND category = ?"
            params.append(category)
        if search:
            query += " AND (name LIKE ? OR sku LIKE ? OR barcode LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like])

        query += " ORDER BY name LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_product(r) for r in rows]

    def get_reorder_alerts(self, business_id: int) -> List[Product]:
        """Get products at or below reorder level."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM product
                WHERE business_id = ? AND is_active = 1
                  AND current_stock_qty <= reorder_level_qty
                ORDER BY current_stock_qty ASC""",
                (business_id,),
            ).fetchall()
        return [self._row_to_product(r) for r in rows]

    def get_categories(self, business_id: int) -> List[str]:
        """Get distinct product categories."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT category FROM product WHERE business_id = ? AND category IS NOT NULL ORDER BY category",
                (business_id,),
            ).fetchall()
        return [r["category"] for r in rows]

    def delete_product(self, product_id: int, business_id: int) -> bool:
        """Soft-delete (deactivate) a product."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE product SET is_active = 0, updated_at = ? WHERE product_id = ? AND business_id = ?",
                (datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"), product_id, business_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Stock Operations
    # ------------------------------------------------------------------

    def adjust_stock(
        self,
        product_id: int,
        business_id: int,
        quantity_delta: int,
        txn_type: str = "adjustment",
        notes: Optional[str] = None,
        recorded_by: Optional[str] = None,
    ) -> bool:
        """Adjust stock quantity and log the transaction."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.execute(
                """UPDATE product SET
                    current_stock_qty = current_stock_qty + ?,
                    updated_at = ?,
                    last_restocked_at = CASE WHEN ? > 0 THEN ? ELSE last_restocked_at END
                WHERE product_id = ? AND business_id = ?""",
                (quantity_delta, now, quantity_delta, now, product_id, business_id),
            )
            if cur.rowcount == 0:
                return False

            conn.execute(
                """INSERT INTO inventory_transaction
                    (business_id, product_id, type, quantity, notes, recorded_by)
                VALUES (?,?,?,?,?,?)""",
                (business_id, product_id, txn_type, abs(quantity_delta), notes, recorded_by),
            )
            return True

    def restock(
        self,
        product_id: int,
        business_id: int,
        quantity: int,
        notes: Optional[str] = None,
        recorded_by: Optional[str] = None,
    ) -> bool:
        """Restock (purchase) a product — adds to inventory."""
        return self.adjust_stock(product_id, business_id, quantity, "purchase", notes, recorded_by)

    # ------------------------------------------------------------------
    # Inventory Valuation
    # ------------------------------------------------------------------

    def get_inventory_valuation(self, business_id: int) -> Dict:
        """Get total inventory value and summary."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) AS product_count,
                    COALESCE(SUM(current_stock_qty), 0) AS total_units,
                    COALESCE(SUM(cost_price_minor * current_stock_qty), 0) AS total_cost_value,
                    COALESCE(SUM(selling_price_minor * current_stock_qty), 0) AS total_retail_value
                FROM product
                WHERE business_id = ? AND is_active = 1""",
                (business_id,),
            ).fetchone()

            # Category breakdown
            cat_rows = conn.execute(
                """SELECT category,
                    COUNT(*) AS cnt,
                    COALESCE(SUM(current_stock_qty), 0) AS units,
                    COALESCE(SUM(cost_price_minor * current_stock_qty), 0) AS cost_val
                FROM product
                WHERE business_id = ? AND is_active = 1 AND category IS NOT NULL
                GROUP BY category ORDER BY cost_val DESC""",
                (business_id,),
            ).fetchall()

        return {
            "product_count": row["product_count"] if row else 0,
            "total_units": row["total_units"] if row else 0,
            "total_cost_value_minor": row["total_cost_value"] if row else 0,
            "total_retail_value_minor": row["total_retail_value"] if row else 0,
            "by_category": {
                cr["category"]: {
                    "count": cr["cnt"],
                    "units": cr["units"],
                    "cost_value_minor": cr["cost_val"],
                }
                for cr in cat_rows
            },
        }

    def get_stock_movement(
        self, business_id: int, days: int = 30
    ) -> List[InventoryTransaction]:
        """Get recent inventory transactions."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM inventory_transaction
                WHERE business_id = ?
                  AND created_at >= date('now', ? || ' days')
                ORDER BY created_at DESC LIMIT 500""",
                (business_id, f"-{days}"),
            ).fetchall()

        return [
            InventoryTransaction(
                txn_id=r["txn_id"],
                business_id=r["business_id"],
                product_id=r["product_id"],
                type=r["type"],
                quantity=r["quantity"],
                reference_id=r["reference_id"],
                reference_type=r["reference_type"],
                notes=r["notes"],
                recorded_by=r["recorded_by"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_product(row) -> Product:
        return Product(
            product_id=row["product_id"],
            business_id=row["business_id"],
            sku=row["sku"],
            name=row["name"],
            description=row["description"],
            category=row["category"],
            cost_price_minor=row["cost_price_minor"],
            selling_price_minor=row["selling_price_minor"],
            vat_applicable=bool(row["vat_applicable"]),
            vat_rate_pct=row["vat_rate_pct"],
            current_stock_qty=row["current_stock_qty"],
            reorder_level_qty=row["reorder_level_qty"],
            reorder_qty=row["reorder_qty"],
            supplier_id=row["supplier_id"],
            is_active=bool(row["is_active"]),
            barcode=row["barcode"],
            image_url=row["image_url"],
            last_restocked_at=row["last_restocked_at"],
            margin_pct=row["margin_pct"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
