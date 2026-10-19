"""Business registration, configuration, and financial goal management."""
from typing import Dict, List, Optional
from dataclasses import dataclass
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from core import recurrence
from core.config import config

EXPENSE_TYPES = (
    "rent", "salary", "utilities", "insurance", "supplier_credit",
    "loan_repayment", "tax", "maintenance", "service_subscription", "other",
)


class ExpenseError(ValueError):
    """A recurring expense could not be saved (bad input)."""


class ExpenseNotFound(LookupError):
    """No such expense for this business (also returned for another business's expense)."""


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
    registration_type: str = "informal"


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
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
              last_paid_date TEXT,
              interval_count INTEGER NOT NULL DEFAULT 1 CHECK (interval_count BETWEEN 1 AND 365)
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
        from db.migrate import ensure_006
        ensure_006(self.db_path)

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
        owner_user_id: Optional[int] = None,
    ) -> int:
        """Register a new business and return its business_id.

        When owner_user_id is given the business is linked to that user
        (business.owner_user_id + an 'owner' business_member row), so the
        next login finds it instead of asking for setup again."""
        self.ensure_schema()

        public_ref = uuid.uuid4().hex[:12]
        name_token = name

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            phone_hash = None
            if owner_user_id is not None:
                row = conn.execute(
                    "SELECT phone_hash FROM app_user WHERE user_id = ?", (owner_user_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"No user with user_id={owner_user_id}")
                phone_hash = row[0]

            cursor = conn.execute("""
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
            business_id = cursor.lastrowid

            if owner_user_id is not None:
                conn.execute(
                    "UPDATE business SET owner_user_id = ?, owner_phone_hash = ? WHERE business_id = ?",
                    (owner_user_id, phone_hash, business_id),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO business_member
                       (business_id, user_id, phone_hash, role, is_active)
                       VALUES (?, ?, ?, 'owner', 1)""",
                    (business_id, owner_user_id, phone_hash),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return business_id

    def get_business_for_user(self, user_id: int) -> Optional[int]:
        """The business this user last set up or joined, or None if they
        have never completed Business Setup."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """SELECT bm.business_id FROM business_member bm
                   JOIN business b ON b.business_id = bm.business_id
                   WHERE bm.user_id = ? AND bm.is_active = 1 AND b.status = 'active'
                   ORDER BY bm.added_at DESC, bm.business_id DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """SELECT business_id FROM business
                       WHERE owner_user_id = ? AND status = 'active'
                       ORDER BY business_id DESC LIMIT 1""",
                    (user_id,),
                ).fetchone()
            return row[0] if row else None
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()

    def update_business_profile(
        self,
        business_id: int,
        name: str,
        sector: str,
        sub_sector: Optional[str] = None,
        country_code: str = "KE",
        employee_count: int = 0,
        registration_type: str = "informal",
    ) -> None:
        """Edit the profile captured during setup."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("""
                UPDATE business
                SET name_token = ?, sector = ?, sub_sector = ?, country_code = ?,
                    employee_count = ?, registration_type = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
                WHERE business_id = ?
            """, (name, sector, sub_sector, country_code, employee_count,
                  registration_type, business_id))
            conn.commit()
        finally:
            conn.close()

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
        last_paid_date: Optional[str] = None,
        interval_count: int = 1,
        today: Optional[date] = None,
    ) -> int:
        """Add a recurring expense and return expense_id.

        amount_minor is the amount of each payment, or, when is_variable, the
        approximate monthly average (payments are planned within +/-10%).

        When last_paid_date is given, next_due is calculated from it (see
        core/recurrence.py) and any next_due passed in is ignored. Without
        it, next_due is the owner's first payment date, or the first
        day_of_month on or after today, or today."""
        self.ensure_schema()
        today = today or date.today()
        description = self._validate_expense(expense_type, description, amount_minor,
                                             cadence, interval_count, day_of_month)
        last_paid = recurrence.to_date(last_paid_date)
        if last_paid is not None:
            if last_paid > today:
                raise ExpenseError("The last payment date can't be in the future.")
            next_due = recurrence.next_due_after_payment(
                last_paid, cadence, interval_count, day_of_month).isoformat()
        elif next_due is None:
            first = today
            if day_of_month and cadence in ("monthly", "quarterly", "annual"):
                first = recurrence._add_months(today, 0, day_of_month)
                if first < today:
                    first = recurrence._add_months(today, 1, day_of_month)
            next_due = first.isoformat()
        else:
            next_due = recurrence.to_date(next_due).isoformat()
        if end_date and recurrence.to_date(end_date) < recurrence.to_date(next_due):
            raise ExpenseError("The end date is before the next payment.")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            cursor = conn.execute("""
                INSERT INTO recurring_expense (
                  business_id, expense_type, description, amount_minor,
                  cadence, interval_count, day_of_month, party_id, next_due, end_date,
                  last_paid_date, is_variable, variable_formula, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                business_id, expense_type, description, amount_minor,
                cadence, interval_count, day_of_month, party_id, next_due, end_date,
                last_paid.isoformat() if last_paid else None,
                1 if is_variable else 0, variable_formula,
            ))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as e:
            raise ExpenseError(f"Could not save the expense: {e}") from e
        finally:
            conn.close()

    @staticmethod
    def _validate_expense(expense_type, description, amount_minor, cadence,
                          interval_count, day_of_month) -> str:
        if expense_type not in EXPENSE_TYPES:
            raise ExpenseError(f"Unknown expense type {expense_type!r}.")
        description = (description or "").strip()
        if not description:
            raise ExpenseError("Please describe the expense (e.g. 'Shop rent').")
        if len(description) > 120:
            raise ExpenseError("Keep the description under 120 characters.")
        if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
            raise ExpenseError("The amount must be more than zero.")
        try:
            recurrence.validate(cadence, interval_count, day_of_month)
        except recurrence.RecurrenceError as e:
            raise ExpenseError(str(e)) from e
        return description

    def _get_expense_row(self, conn, business_id: int, expense_id: int) -> sqlite3.Row:
        """The expense, only if it belongs to business_id."""
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM recurring_expense WHERE expense_id = ? AND business_id = ? AND active = 1",
            (expense_id, business_id),
        ).fetchone()
        if row is None:
            raise ExpenseNotFound("That expense was not found for this business.")
        return row

    def update_recurring_expense(self, business_id: int, expense_id: int,
                                 today: Optional[date] = None, **changes) -> Dict:
        """Edit an expense of this business. Changing the schedule (or the
        last payment date) recalculates next_due from last_paid_date."""
        self.ensure_schema()
        allowed = {"expense_type", "description", "amount_minor", "cadence", "interval_count",
                   "day_of_month", "last_paid_date", "next_due", "end_date", "is_variable"}
        unknown = set(changes) - allowed
        if unknown:
            raise ExpenseError(f"Can't change: {', '.join(sorted(unknown))}.")
        today = today or date.today()
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            row = dict(self._get_expense_row(conn, business_id, expense_id))
            new = {**row, **changes}
            new["description"] = self._validate_expense(
                new["expense_type"], new["description"], new["amount_minor"],
                new["cadence"], new["interval_count"], new["day_of_month"])
            last_paid = recurrence.to_date(new["last_paid_date"])
            if last_paid is not None and last_paid > today:
                raise ExpenseError("The last payment date can't be in the future.")
            schedule_keys = ("cadence", "interval_count", "day_of_month", "last_paid_date")
            schedule_changed = any(
                (recurrence.to_date(new[k]) if k == "last_paid_date" else new[k])
                != (recurrence.to_date(row[k]) if k == "last_paid_date" else row[k])
                for k in schedule_keys)
            if last_paid is not None and schedule_changed and "next_due" not in changes:
                new["next_due"] = recurrence.next_due_after_payment(
                    last_paid, new["cadence"], new["interval_count"], new["day_of_month"]).isoformat()
            new["next_due"] = recurrence.to_date(new["next_due"]).isoformat()
            if new["end_date"] and recurrence.to_date(new["end_date"]) < recurrence.to_date(new["next_due"]):
                raise ExpenseError("The end date is before the next payment.")
            conn.execute("""
                UPDATE recurring_expense
                SET expense_type = ?, description = ?, amount_minor = ?, cadence = ?,
                    interval_count = ?, day_of_month = ?, last_paid_date = ?, next_due = ?,
                    end_date = ?, is_variable = ?
                WHERE expense_id = ? AND business_id = ?
            """, (new["expense_type"], new["description"], new["amount_minor"], new["cadence"],
                  new["interval_count"], new["day_of_month"],
                  last_paid.isoformat() if last_paid else None, new["next_due"],
                  new["end_date"], 1 if new["is_variable"] else 0, expense_id, business_id))
            conn.commit()
        finally:
            conn.close()
        return next(e for e in self.get_recurring_expenses(business_id, today=today)
                    if e["expense_id"] == expense_id)

    def delete_recurring_expense(self, business_id: int, expense_id: int) -> None:
        """Stop tracking an expense of this business. The row is kept
        (active = 0) so its payment history stays intact."""
        self.ensure_schema()
        conn = sqlite3.connect(self.db_path)
        try:
            self._get_expense_row(conn, business_id, expense_id)
            conn.execute("UPDATE recurring_expense SET active = 0 WHERE expense_id = ? AND business_id = ?",
                         (expense_id, business_id))
            conn.commit()
        finally:
            conn.close()

    def record_expense_payment(self, business_id: int, expense_id: int,
                               paid_date: Optional[str] = None,
                               amount_minor: Optional[int] = None,
                               today: Optional[date] = None) -> Dict:
        """The owner paid the current instalment: log it, set last_paid_date
        and move next_due to the next period after the payment."""
        self.ensure_schema()
        today = today or date.today()
        paid = recurrence.to_date(paid_date) or today
        if paid > today:
            raise ExpenseError("The payment date can't be in the future.")
        if amount_minor is not None and (not isinstance(amount_minor, int) or amount_minor <= 0):
            raise ExpenseError("The amount paid must be more than zero.")
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            row = self._get_expense_row(conn, business_id, expense_id)
            due = recurrence.to_date(row["next_due"])
            interval = row["interval_count"] or 1
            nxt = recurrence.next_due_after_payment(paid, row["cadence"], interval, row["day_of_month"])
            # Paying early must still move past the instalment just paid.
            while nxt <= due:
                nxt = recurrence.step(nxt, row["cadence"], interval, row["day_of_month"] or due.day)
            expected = recurrence.instalment_amount(
                row["amount_minor"], row["cadence"], interval, bool(row["is_variable"]))
            amount = amount_minor or expected
            conn.execute("""
                INSERT INTO recurring_expense_instance
                  (expense_id, due_date, expected_amount_minor, actual_amount_minor, status, paid_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(expense_id, due_date) DO UPDATE SET
                  actual_amount_minor = excluded.actual_amount_minor,
                  status = excluded.status, paid_date = excluded.paid_date
            """, (expense_id, due.isoformat(), expected, amount,
                  "late" if paid > due else "paid", paid.isoformat()))
            conn.execute("""
                UPDATE recurring_expense
                SET last_paid_date = ?, next_due = ?, times_paid = times_paid + 1
                WHERE expense_id = ? AND business_id = ?
            """, (paid.isoformat(), nxt.isoformat(), expense_id, business_id))
            conn.commit()
        finally:
            conn.close()
        return next(e for e in self.get_recurring_expenses(business_id, today=today)
                    if e["expense_id"] == expense_id)

    def get_recurring_expenses(self, business_id: int, today: Optional[date] = None) -> List[Dict]:
        """Active recurring expenses of a business, each with its live
        countdown: days_until (negative when overdue), days_overdue,
        due_state ('overdue' | 'due_today' | 'upcoming') and due_label."""
        self.ensure_schema()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT expense_id, expense_type, description, amount_minor,
                   cadence, interval_count, day_of_month, last_paid_date, next_due, end_date,
                   is_variable, variable_formula, times_paid, times_missed, active
            FROM recurring_expense
            WHERE business_id = ? AND active = 1
            ORDER BY next_due
        """, (business_id,)).fetchall()
        conn.close()

        out = []
        for r in rows:
            e = dict(r)
            e["interval_count"] = e["interval_count"] or 1
            e["frequency_label"] = recurrence.describe(e["cadence"], e["interval_count"])
            # amount_minor is per payment, or the monthly average when variable.
            e["instalment_minor"] = recurrence.instalment_amount(
                e["amount_minor"], e["cadence"], e["interval_count"], bool(e["is_variable"]))
            e["instalment_low_minor"], e["instalment_high_minor"] = recurrence.amount_range(
                e["instalment_minor"], bool(e["is_variable"]))
            try:
                st = recurrence.due_status(e["next_due"], today)
                e.update(days_until=st.days_until, days_overdue=st.days_overdue,
                         due_state=st.state, due_label=st.label)
            except recurrence.RecurrenceError:
                e.update(days_until=None, days_overdue=0, due_state="unknown", due_label="No valid due date")
            out.append(e)
        return out

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
                   employee_count, status, registration_type
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
            registration_type=row["registration_type"],
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
