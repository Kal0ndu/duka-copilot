"""Automated expense detection and recurring expense management."""
from typing import Dict, List, Optional
from datetime import date, datetime, timedelta
import sqlite3
import pandas as pd

from core import recurrence
from core.config import config
from core.adapters.base import StatementAdapter
from core.adapters.mpesa_pdf import MpesaPdfAdapter
from core.adapters.mobile_money_ke import MobileMoneyKeAdapter


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
              COUNT(*) as frequency,
              MAX(local_date) as last_seen
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
            # Same payee, amount and day of the month: a monthly payment.
            cadence = "monthly"

            recurring.append({
                "party_id": row["party_id"],
                "amount_minor": row["amount_minor"],
                "day_of_month": row["day_of_month"],
                "cadence": cadence,
                "frequency": freq,
                "category_id": row["category_id"],
                "confidence": min(100, freq * 10),
                "last_seen": row["last_seen"],
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
        """Create a new recurring expense (validated by BusinessSetup). Returns expense_id."""
        from core.business_setup import BusinessSetup
        keys = ("expense_type", "description", "amount_minor", "cadence", "day_of_month", "party_id",
                "next_due", "end_date", "is_variable", "variable_formula", "last_paid_date", "interval_count")
        return BusinessSetup(self.db_path).add_recurring_expense(
            business_id, **{k: expense_config[k] for k in keys if k in expense_config})

    def _active_expenses(self, business_id: int) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM recurring_expense WHERE business_id = ? AND active = 1 ORDER BY next_due",
            (business_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _instances(self, exp: Dict, until: date):
        """Due dates of one expense from its (unpaid) next_due through until."""
        try:
            yield from recurrence.occurrences(
                exp["next_due"], exp["cadence"], exp.get("interval_count") or 1,
                exp.get("day_of_month"), until=until, end_date=exp.get("end_date"),
            )
        except recurrence.RecurrenceError:
            return

    @staticmethod
    def _amounts(exp: Dict) -> Dict:
        """Per-payment amount; a variable expense's monthly average scaled to
        the period, with its +/-10% range."""
        variable = bool(exp.get("is_variable"))
        expected = recurrence.instalment_amount(
            exp["amount_minor"], exp["cadence"], exp.get("interval_count") or 1, variable)
        low, high = recurrence.amount_range(expected, variable)
        return {"amount_minor": expected, "amount_low_minor": low, "amount_high_minor": high,
                "is_variable": variable,
                "tolerance_pct": int(recurrence.VARIABLE_TOLERANCE * 100) if variable else 0}

    def generate_schedule(self, business_id: int, months_ahead: int = 12,
                          today: Optional[date] = None) -> List[Dict]:
        """Every payment due from now until months_ahead months from today.

        next_due is the first unpaid instalment, so instalments before today
        are still owed: they are listed with status 'overdue' and days_overdue."""
        today = today or date.today()
        until = recurrence._add_months(today, months_ahead, today.day) - timedelta(days=1)
        schedule = []
        for exp in self._active_expenses(business_id):
            for d in self._instances(exp, until):
                st = recurrence.due_status(d, today)
                schedule.append({
                    "expense_id": exp["expense_id"],
                    "description": exp["description"],
                    **self._amounts(exp),
                    "due_date": d.isoformat(),
                    "status": "overdue" if st.state == "overdue" else "expected",
                    "days_until": st.days_until,
                    "days_overdue": st.days_overdue,
                })
        return sorted(schedule, key=lambda x: x["due_date"])

    def obligations_between(self, business_id: int, start: date, end: date) -> List[Dict]:
        """Recurring-expense payments for a forecast window [start, end].

        Instalments due before start are unpaid, so they are carried to
        start (money still owed), with how many days overdue they are."""
        out = []
        for exp in self._active_expenses(business_id):
            for d in self._instances(exp, end):
                out.append({
                    "due_date": max(d, start).isoformat(),
                    **self._amounts(exp),
                    "label": exp["description"],
                    "source": "recurring_expense",
                    "frequency": recurrence.describe(exp["cadence"], exp.get("interval_count") or 1),
                    "original_due_date": d.isoformat(),
                    "days_overdue": max(0, (start - d).days),
                })
        return sorted(out, key=lambda o: o["due_date"])

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

    def get_upcoming_obligations(self, business_id: int, days_ahead: int = 7,
                                 today: Optional[date] = None) -> List[Dict]:
        """Unpaid instalments that are overdue or due in the next N days."""
        today = today or date.today()
        cutoff = today + timedelta(days=days_ahead)
        out = []
        for exp in self._active_expenses(business_id):
            try:
                st = recurrence.due_status(exp["next_due"], today)
            except recurrence.RecurrenceError:
                continue
            if st.next_due <= cutoff:
                out.append({
                    "expense_id": exp["expense_id"], "description": exp["description"],
                    **self._amounts(exp), "cadence": exp["cadence"],
                    "next_due": st.next_due.isoformat(), "days_until": st.days_until,
                    "days_overdue": st.days_overdue, "due_label": st.label,
                })
        return sorted(out, key=lambda o: o["next_due"])


# ---- Tool wrapper functions for agent dispatch ----

def ingest_statement(args, business_id: Optional[int] = None, 
                     db_path: Optional[str] = None) -> dict:
    """Report on a statement file the owner uploaded.

    The Upload Statement page parses, redacts and loads the file
    (core.ingestion.StatementIngestor); the bytes are not kept, so this
    tool reads back what that run recorded in source_file / ingestion_run.

    Args:
        args: IngestStatementArgs with file_id
        business_id: Active business ID
        db_path: Database path
    
    Returns:
        dict with row count, validation report, risk flag
    """
    import json

    if db_path is None:
        db_path = config.DB_PATH
    if business_id is None:
        return {"error": "business_id required"}
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Scoped to the active business: another business's file_id is "not found".
        cursor.execute(
            """SELECT file_id, filename, status, row_count, period_start, period_end,
                      risk_flag, risk_reason, adapter_name, uploaded_at
               FROM source_file WHERE file_id = ? AND business_id = ?""",
            (args.file_id, business_id)
        )
        file_row = cursor.fetchone()
        if not file_row:
            return {"error": "File not found"}
        
        run = cursor.execute(
            """SELECT status, rows_read, rows_loaded, rows_rejected, validation_json
               FROM ingestion_run WHERE file_id = ? ORDER BY run_id DESC LIMIT 1""",
            (args.file_id,)
        ).fetchone()
        review = cursor.execute(
            """SELECT COUNT(*) FROM transaction_ledger
               WHERE business_id = ? AND file_id = ? AND needs_review = 1 AND voided = 0""",
            (business_id, args.file_id)
        ).fetchone()[0]
        conn.close()
        
        validation_issues = []
        if run and run["validation_json"]:
            try:
                validation_issues = json.loads(run["validation_json"])
            except ValueError:
                validation_issues = []
        
        risk_flags = []
        if file_row["risk_flag"]:
            risk_flags.append(file_row["risk_reason"] or "Statement contains suspicious text")
        if not file_row["row_count"]:
            risk_flags.append("No valid transactions imported")
        
        return {
            "file_id": file_row["file_id"],
            "filename": file_row["filename"],
            "period_start": file_row["period_start"],
            "period_end": file_row["period_end"],
            "rows_parsed": run["rows_read"] if run else None,
            "rows_inserted": file_row["row_count"] or 0,
            "rows_already_on_file": run["rows_rejected"] if run else 0,
            "rows_needing_review": review,
            "adapter": file_row["adapter_name"],
            "validation_issues": validation_issues,
            "risk_flags": risk_flags,
            "status": "success" if file_row["status"] == "loaded" else file_row["status"],
        }
    
    except Exception as e:
        return {"error": f"Ingestion failed: {e}"}


def get_ledger_summary(args, business_id: Optional[int] = None,
                       db_path: Optional[str] = None) -> dict:
    """Get transaction totals by category and period.
    
    Args:
        args: GetLedgerSummaryArgs with period (day/week/month/quarter)
        business_id: Active business ID
        db_path: Database path
    
    Returns:
        dict with totals by category and period
    """
    if db_path is None:
        db_path = config.DB_PATH
    if business_id is None:
        return {"error": "business_id required"}
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Map period to date truncation
        period = args.period or "month"
        if period == "day":
            date_trunc = "strftime('%Y-%m-%d', local_date)"
        elif period == "week":
            date_trunc = "strftime('%Y-W%W', local_date)"
        elif period == "month":
            date_trunc = "strftime('%Y-%m', local_date)"
        elif period == "quarter":
            date_trunc = ("strftime('%Y', local_date) || '-Q' || "
                          "((CAST(strftime('%m', local_date) AS INTEGER) + 2) / 3)")
        else:
            date_trunc = "strftime('%Y-%m', local_date)"
        
        # Query: aggregate by category and period
        # category_id -> category.code; the ledger has no category_code column.
        cursor.execute(f"""
            SELECT 
                {date_trunc} as period,
                c.code as category_code,
                t.direction,
                SUM(t.amount_minor) as total_minor,
                COUNT(*) as txn_count
            FROM transaction_ledger t
            LEFT JOIN category c ON c.category_id = t.category_id
            WHERE t.business_id = ? AND t.voided = 0
            GROUP BY period, c.code, t.direction
            ORDER BY period DESC, total_minor DESC
        """, (business_id,))
        
        results = cursor.fetchall()
        conn.close()
        
        # Restructure
        summary = []
        for row in results:
            summary.append({
                "period": row["period"],
                "category": row["category_code"] or "UNCATEGORIZED",
                "direction": row["direction"],
                "total_kes": row["total_minor"] / 100.0,
                "transaction_count": row["txn_count"],
            })
        
        return {"period_type": period, "summary": summary, "count": len(summary)}
    
    except Exception as e:
        return {"error": f"Ledger summary failed: {e}"}
