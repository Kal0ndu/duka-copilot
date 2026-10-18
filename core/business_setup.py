"""Business registration, configuration, and financial goal management."""
from typing import Dict, List, Optional
from dataclasses import dataclass
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from core.config import config


@dataclass
class BusinessProfile:
    business_id: int
    name_token: str
    sector: str
    sub_sector: Optional[str]
    country_code: str
    currency_code: str
    timezone: str
    employee_count: int
    status: str


class BusinessSetup:
    """Register businesses, manage recurring expenses, and set financial goals."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.DB_PATH

    def ensure_schema(self) -> None:
        """Initialize the base schema, then create application extensions."""
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        base_schema = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        has_base_schema = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'business'"
        ).fetchone()
        if not has_base_schema:
            conn.executescript(base_schema.read_text(encoding="utf-8"))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS business_category_config (
              config_id INTEGER PRIMARY KEY,
              business_id INTEGER NOT NULL REFERENCES business(business_id),
              global_category_id INTEGER NOT NULL REFERENCES category(category_id),
              display_name TEXT,
              is_tracking_active INTEGER NOT NULL DEFAULT 1,
              monthly_budget_minor INTEGER,
              alert_threshold_pct INTEGER NOT NULL DEFAULT 80,
              auto_categorize_keywords TEXT,
              UNIQUE (business_id, global_category_id)
            );

            CREATE TABLE IF NOT EXISTS financial_goal (
              goal_id INTEGER PRIMARY KEY,
              business_id INTEGER NOT NULL REFERENCES business(business_id),
              goal_type TEXT NOT NULL CHECK (goal_type IN (
                'revenue_target','margin_target','expense_budget','personal_limit',
                'cash_buffer','savings','debt_reduction','growth'
              )),
              target_period TEXT NOT NULL CHECK (target_period IN ('monthly','quarterly','annual')),
              target_value_minor INTEGER NOT NULL,
              metric TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1,
              priority INTEGER NOT NULL DEFAULT 0,
              notes TEXT,
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );

            CREATE TABLE IF NOT EXISTS recurring_expense (
              expense_id INTEGER PRIMARY KEY,
              business_id INTEGER NOT NULL REFERENCES business(business_id),
              party_id INTEGER REFERENCES party(party_id),
              expense_type TEXT NOT NULL CHECK (expense_type IN (
                'rent','salary','utilities','insurance','supplier_credit',
                'loan_repayment','tax','maintenance','service_subscription','other'
              )),
              description TEXT NOT NULL,
              amount_minor INTEGER NOT NULL,
              cadence TEXT NOT NULL CHECK (cadence IN (
                'daily','weekly','biweekly','monthly','quarterly','annual'
              )),
              day_of_month INTEGER CHECK (day_of_month BETWEEN 1 AND 31),
              next_due TEXT NOT NULL,
              end_date TEXT,
              is_variable INTEGER NOT NULL DEFAULT 0,
              variable_formula TEXT,
              times_paid INTEGER NOT NULL DEFAULT 0,
              times_missed INTEGER NOT NULL DEFAULT 0,
              avg_actual_minor INTEGER,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );

            CREATE TABLE IF NOT EXISTS recurring_expense_instance (
              instance_id INTEGER PRIMARY KEY,
              expense_id INTEGER NOT NULL REFERENCES recurring_expense(expense_id),
              due_date TEXT NOT NULL,
              expected_amount_minor INTEGER NOT NULL,
              matched_txn_id INTEGER REFERENCES transaction_ledger(txn_id),
              actual_amount_minor INTEGER,
              status TEXT NOT NULL DEFAULT 'expected' CHECK (status IN (
                'expected','paid','late','missed','skipped'
              )),
              paid_date TEXT,
              notes TEXT,
              UNIQUE (expense_id, due_date)
            );

            CREATE TABLE IF NOT EXISTS chart_of_accounts (
              account_id INTEGER PRIMARY KEY,
              business_id INTEGER NOT NULL REFERENCES business(business_id),
              account_code TEXT NOT NULL,
              account_name TEXT NOT NULL,
              account_type TEXT NOT NULL CHECK (account_type IN (
                'asset','liability','equity','income','expense'
              )),
              parent_account_id INTEGER REFERENCES chart_of_accounts(account_id),
              description TEXT,
              is_active INTEGER NOT NULL DEFAULT 1,
              UNIQUE (business_id, account_code)
            );

            CREATE VIEW IF NOT EXISTS v_obligation_compat AS
            SELECT
              expense_id AS obligation_id,
              business_id,
              description AS label,
              amount_minor,
              cadence,
              day_of_month,
              next_due,
              active
            FROM recurring_expense;
        """)
        conn.commit()
        conn.close()

    def register_business(
        self,
        name: str,
        sector: str,
        sub_sector: Optional[str] = None,
        country_code: str = "KE",
        currency_code: str = "KES",
        timezone: str = "Africa/Nairobi",
        revenue_estimate_minor: int = 0,
        employee_count: int = 0,
        registration_type: str = "informal",
    ) -> int:
        """Register a new business and return its business_id."""
        self.ensure_schema()

        public_ref = uuid.uuid4().hex[:12]
        name_token = name

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO business (
              public_ref, name_token, sector, sub_sector,
              country_code, currency_code, timezone,
              registration_type, employee_count, start_date, is_synthetic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, date('now'), 0)
        """, (
            public_ref, name_token, sector, sub_sector,
            country_code, currency_code, timezone,
            registration_type, employee_count,
        ))

        conn.commit()
        business_id = cursor.lastrowid
        conn.close()
        return business_id

    def add_recurring_expense(
        self,
        business_id: int,
        expense_type: str,
        description: str,
        amount_minor: int,
        cadence: str,
        day_of_month: Optional[int] = None,
        party_id: Optional[int] = None,
        next_due: Optional[str] = None,
        end_date: Optional[str] = None,
        is_variable: bool = False,
        variable_formula: Optional[str] = None,
    ) -> int:
        """Add a recurring expense and return expense_id."""
        self.ensure_schema()

        if next_due is None:
            next_due = datetime.now().strftime("%Y-%m-%d")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO recurring_expense (
              business_id, expense_type, description, amount_minor,
              cadence, day_of_month, party_id, next_due, end_date,
              is_variable, variable_formula, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            business_id, expense_type, description, amount_minor,
            cadence, day_of_month, party_id, next_due, end_date,
            1 if is_variable else 0, variable_formula,
        ))

        conn.commit()
        expense_id = cursor.lastrowid
        conn.close()
        return expense_id

    def get_recurring_expenses(self, business_id: int) -> List[Dict]:
        """Get all active recurring expenses for a business."""
        self.ensure_schema()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT expense_id, expense_type, description, amount_minor,
                   cadence, day_of_month, next_due, end_date,
                   is_variable, variable_formula, times_paid, times_missed, active
            FROM recurring_expense
            WHERE business_id = ? AND active = 1
            ORDER BY next_due
        """, (business_id,))

        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def set_financial_goals(
        self,
        business_id: int,
        revenue_target: Optional[int] = None,
        margin_target: Optional[int] = None,
        buffer_target: Optional[int] = None,
        personal_limit_pct: Optional[int] = None,
    ) -> List[int]:
        """Set financial goals for a business. Returns list of goal_ids."""
        self.ensure_schema()

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        goal_ids = []

        goals_to_set = []
        if revenue_target is not None:
            goals_to_set.append(('revenue_target', revenue_target, 'minor'))
        if margin_target is not None:
            goals_to_set.append(('margin_target', margin_target, '%'))
        if buffer_target is not None:
            goals_to_set.append(('cash_buffer', buffer_target, 'minor'))
        if personal_limit_pct is not None:
            goals_to_set.append(('personal_limit', personal_limit_pct, '%'))

        for goal_type, value, metric in goals_to_set:
            cursor.execute("""
                INSERT INTO financial_goal (
                  business_id, goal_type, target_period, target_value_minor, metric, is_active
                ) VALUES (?, ?, 'monthly', ?, ?, 1)
            """, (business_id, goal_type, value, metric))
            goal_ids.append(cursor.lastrowid)

        conn.commit()
        conn.close()
        return goal_ids

    def get_financial_goals(self, business_id: int) -> List[Dict]:
        """Get all active financial goals for a business."""
        self.ensure_schema()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT goal_id, goal_type, target_period, target_value_minor,
                   metric, is_active, priority, notes, created_at
            FROM financial_goal
            WHERE business_id = ? AND is_active = 1
            ORDER BY priority DESC, created_at
        """, (business_id,))

        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_business_profile(self, business_id: int) -> Optional[BusinessProfile]:
        """Get a business profile by ID."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT business_id, name_token, sector, sub_sector,
                   country_code, currency_code, timezone,
                   employee_count, status
            FROM business
            WHERE business_id = ?
        """, (business_id,))

        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return BusinessProfile(
            business_id=row["business_id"],
            name_token=row["name_token"],
            sector=row["sector"],
            sub_sector=row["sub_sector"],
            country_code=row["country_code"],
            currency_code=row["currency_code"],
            timezone=row["timezone"],
            employee_count=row["employee_count"],
            status=row["status"],
        )

    def configure_category(
        self,
        business_id: int,
        global_category_id: int,
        display_name: Optional[str] = None,
        monthly_budget_minor: Optional[int] = None,
        alert_threshold_pct: int = 80,
        auto_categorize_keywords: Optional[str] = None,
    ) -> int:
        """Configure a category for a specific business (upsert)."""
        self.ensure_schema()

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO business_category_config (
              business_id, global_category_id, display_name,
              monthly_budget_minor, alert_threshold_pct, auto_categorize_keywords
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(business_id, global_category_id) DO UPDATE SET
              display_name = excluded.display_name,
              monthly_budget_minor = excluded.monthly_budget_minor,
              alert_threshold_pct = excluded.alert_threshold_pct,
              auto_categorize_keywords = excluded.auto_categorize_keywords
        """, (
            business_id, global_category_id, display_name,
            monthly_budget_minor, alert_threshold_pct, auto_categorize_keywords,
        ))

        conn.commit()
        config_id = cursor.lastrowid
        conn.close()
        return config_id

    def get_category_configs(self, business_id: int) -> List[Dict]:
        """Get all category configurations for a business."""
        self.ensure_schema()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT bcc.config_id, bcc.global_category_id, c.code, c.name,
                   c.kind, bcc.display_name, bcc.is_tracking_active,
                   bcc.monthly_budget_minor, bcc.alert_threshold_pct,
                   bcc.auto_categorize_keywords
            FROM business_category_config bcc
            JOIN category c ON c.category_id = bcc.global_category_id
            WHERE bcc.business_id = ?
            ORDER BY c.sort_order
        """, (business_id,))

        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
