"""Automated expense detection and recurring expense management."""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import sqlite3

from core.config import config


class ExpenseTracker:
    """Automatically detect and categorize expenses from transaction history."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.DB_PATH

    def detect_recurring_expenses(self, business_id: int) -> List[Dict]:
        """Analyze transaction history to detect recurring patterns.

        Returns a list of detected patterns with confidence scores.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
              party_id,
              amount_minor,
              CAST(strftime('%d', local_date) AS INTEGER) as day_of_month,
              category_id,
              COUNT(*) as frequency
            FROM transaction_ledger
            WHERE business_id = ?
              AND direction = 'out'
              AND voided = 0
              AND party_id IS NOT NULL
              AND julianday('now') - julianday(local_date) <= 365
            GROUP BY party_id, amount_minor, day_of_month, category_id
            HAVING frequency >= 2
            ORDER BY frequency DESC
        """, (business_id,))

        recurring = []
        for row in cursor.fetchall():
            freq = row["frequency"]

            if freq >= 12:
                cadence = "monthly"
            elif freq >= 6:
                cadence = "biweekly"
            elif freq >= 3:
                cadence = "weekly"
            else:
                cadence = "other"

            recurring.append({
                "party_id": row["party_id"],
                "amount_minor": row["amount_minor"],
                "day_of_month": row["day_of_month"],
                "cadence": cadence,
                "frequency": freq,
                "category_id": row["category_id"],
                "confidence": min(100, freq * 10),
            })

        conn.close()
        return recurring

    def auto_categorize_expense(
        self,
        business_id: int,
        description: str,
        amount_minor: int,
        channel: str = "",
    ) -> Optional[int]:
        """Auto-categorize based on business-specific keywords.

        Returns category_id if matched, None otherwise.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT bcc.global_category_id, bcc.auto_categorize_keywords
            FROM business_category_config bcc
            WHERE bcc.business_id = ?
              AND bcc.auto_categorize_keywords IS NOT NULL
              AND bcc.auto_categorize_keywords != ''
        """, (business_id,))

        configs = cursor.fetchall()
        conn.close()

        desc_lower = description.lower()
        channel_lower = channel.lower()

        for row in configs:
            keywords = [k.strip().lower() for k in row["auto_categorize_keywords"].split(",") if k.strip()]
            for kw in keywords:
                if kw in desc_lower or (channel_lower and kw in channel_lower):
                    return row["global_category_id"]

        return None

    def categorize_batch(self, business_id: int, txns: List[Dict]) -> List[Dict]:
        """Categorize multiple transactions at once."""
        categorized = []

        for txn in txns:
            cat_id = self.auto_categorize_expense(
                business_id,
                txn.get("description", ""),
                txn.get("amount_minor", 0),
                txn.get("channel", ""),
            )

            result = dict(txn)
            result["auto_category_id"] = cat_id
            result["needs_review"] = cat_id is None
            categorized.append(result)

        return categorized


class RecurringExpenseManager:
    """Manage salary, rent, utilities, and other recurring obligations."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.DB_PATH

    def add_recurring_expense(self, business_id: int, expense_config: Dict) -> int:
        """Create a new recurring expense. Returns expense_id."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO recurring_expense (
              business_id, expense_type, description, amount_minor,
              cadence, day_of_month, party_id, next_due, end_date, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            business_id,
            expense_config["expense_type"],
            expense_config["description"],
            expense_config["amount_minor"],
            expense_config["cadence"],
            expense_config.get("day_of_month"),
            expense_config.get("party_id"),
            expense_config["next_due"],
            expense_config.get("end_date"),
        ))

        conn.commit()
        expense_id = cursor.lastrowid
        conn.close()
        return expense_id

    def generate_schedule(self, business_id: int, months_ahead: int = 12) -> List[Dict]:
        """Generate upcoming obligation schedule for the next N months."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT expense_id, description, amount_minor, cadence,
                   day_of_month, next_due, end_date
            FROM recurring_expense
            WHERE business_id = ? AND active = 1
            ORDER BY next_due
        """, (business_id,))

        expenses = cursor.fetchall()
        conn.close()

        schedule = []

        for exp in expenses:
            amt = exp["amount_minor"]
            cadence = exp["cadence"]
            next_due_str = exp["next_due"]
            end_date_str = exp["end_date"]

            try:
                current = datetime.strptime(next_due_str[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue

            end_date = None
            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
                except (ValueError, TypeError):
                    pass

            months_to_generate = months_ahead
            if cadence == "daily":
                max_instances = months_ahead * 30
            elif cadence == "weekly":
                max_instances = months_ahead * 4
            elif cadence == "biweekly":
                max_instances = months_ahead * 2
            else:
                max_instances = months_ahead

            for _ in range(max_instances):
                if end_date and current > end_date:
                    break

                schedule.append({
                    "expense_id": exp["expense_id"],
                    "description": exp["description"],
                    "amount_minor": amt,
                    "due_date": current.strftime("%Y-%m-%d"),
                    "status": "expected",
                })

                if cadence == "monthly":
                    if current.month == 12:
                        current = current.replace(year=current.year + 1, month=1)
                    else:
                        current = current.replace(month=current.month + 1)
                elif cadence == "weekly":
                    current += timedelta(days=7)
                elif cadence == "biweekly":
                    current += timedelta(days=14)
                elif cadence == "daily":
                    current += timedelta(days=1)
                elif cadence == "quarterly":
                    current = current.replace(month=((current.month - 1 + 3) % 12) + 1)
                    if current.month <= 3:
                        current = current.replace(year=current.year + 1)
                elif cadence == "annual":
                    current = current.replace(year=current.year + 1)

        return sorted(schedule, key=lambda x: x["due_date"])

    def check_obligation_compliance(self, business_id: int) -> Dict:
        """Check whether recurring expenses were paid on time."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
              re.description,
              COUNT(*) as expected_count,
              SUM(CASE WHEN rei.status = 'paid' THEN 1 ELSE 0 END) as paid_count,
              SUM(CASE WHEN rei.status = 'late' THEN 1 ELSE 0 END) as late_count,
              SUM(CASE WHEN rei.status = 'missed' THEN 1 ELSE 0 END) as missed_count
            FROM recurring_expense re
            JOIN recurring_expense_instance rei ON rei.expense_id = re.expense_id
            WHERE re.business_id = ?
            GROUP BY re.expense_id
        """, (business_id,))

        rows = cursor.fetchall()
        conn.close()

        obligations = []
        total_expected = 0
        total_paid = 0

        for row in rows:
            expected = row["expected_count"]
            paid = row["paid_count"]
            total_expected += expected
            total_paid += paid

            obligations.append({
                "description": row["description"],
                "expected": expected,
                "paid_on_time": paid,
                "paid_late": row["late_count"],
                "missed": row["missed_count"],
                "compliance_rate": (paid / expected * 100) if expected > 0 else 0,
            })

        overall_rate = (total_paid / total_expected * 100) if total_expected > 0 else 0

        return {
            "obligations": obligations,
            "overall_rate": overall_rate,
        }

    def get_upcoming_obligations(self, business_id: int, days_ahead: int = 7) -> List[Dict]:
        """Get obligations due in the next N days."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT expense_id, description, amount_minor, cadence, next_due
            FROM recurring_expense
            WHERE business_id = ? AND active = 1
              AND next_due BETWEEN ? AND ?
            ORDER BY next_due
        """, (business_id, today, cutoff))

        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
