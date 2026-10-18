"""AI Sales Assistant: follow-up tasks, payment reminders, win-back suggestions."""
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3


@dataclass
class AIFollowUpTask:
    task_id: Optional[int] = None
    business_id: int = 0
    entity_type: str = "invoice"  # invoice, quotation
    entity_id: int = 0
    customer_id: int = 0
    customer_contact_token: Optional[str] = None
    task_type: str = "payment_reminder"
    status: str = "pending"
    scheduled_for_date: str = ""
    attempted_at: Optional[str] = None
    completed_at: Optional[str] = None
    message_template: Optional[str] = None
    ai_suggested_action: Optional[str] = None
    outcome: Optional[str] = None
    outcome_recorded_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = ""


@dataclass
class CustomerInsight:
    """AI-generated customer insight for sales actions."""
    customer_id: int
    customer_name_token: str
    total_purchases_minor: int
    invoice_count: int
    overdue_count: int
    overdue_amount_minor: int
    last_purchase_date: Optional[str]
    days_since_last_purchase: Optional[int]
    suggested_action: str
    priority: str  # high, medium, low


class AISalesAssistant:
    """Generate follow-up tasks, payment reminders, and customer insights."""

    def __init__(self, db_path: str = "data/duka.db"):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # Task Generation
    # ------------------------------------------------------------------

    def generate_payment_reminders(self, business_id: int) -> List[AIFollowUpTask]:
        """Generate follow-up tasks for overdue/unpaid invoices."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        new_tasks: List[AIFollowUpTask] = []

        with self._get_conn() as conn:
            # Find overdue invoices without recent follow-up
            overdue = conn.execute(
                """SELECT * FROM invoice
                WHERE business_id = ?
                  AND status = 'active'
                  AND payment_status IN ('unpaid','partial','overdue')
                  AND due_date < ?
                  AND (last_follow_up_date IS NULL OR last_follow_up_date < date('now', '-3 days'))
                ORDER BY due_date ASC""",
                (business_id, today),
            ).fetchall()

            for inv in overdue:
                # Check if a pending task already exists
                existing = conn.execute(
                    """SELECT task_id FROM ai_follow_up_task
                    WHERE entity_type = 'invoice' AND entity_id = ? AND status = 'pending'""",
                    (inv["invoice_id"],),
                ).fetchone()
                if existing:
                    continue

                days_overdue = (now - datetime.strptime(inv["due_date"][:10], "%Y-%m-%d")).days

                if days_overdue <= 7:
                    task_type = "payment_reminder"
                    template = (
                        f"Dear {inv['customer_name_token'] or 'Customer'}, "
                        f"this is a friendly reminder that invoice {inv['invoice_number']} "
                        f"for KES {inv['balance_due_minor']/100:,.2f} is now {days_overdue} days overdue. "
                        f"Kindly arrange payment at your earliest convenience. Thank you."
                    )
                elif days_overdue <= 30:
                    task_type = "overdue_notice"
                    template = (
                        f"URGENT: Invoice {inv['invoice_number']} for KES {inv['balance_due_minor']/100:,.2f} "
                        f"is now {days_overdue} days past due. "
                        f"Please remit payment immediately to avoid service disruption."
                    )
                else:
                    task_type = "overdue_notice"
                    template = (
                        f"FINAL NOTICE: Invoice {inv['invoice_number']} for KES {inv['balance_due_minor']/100:,.2f} "
                        f"is {days_overdue} days overdue. This account requires immediate settlement."
                    )

                suggested = (
                    f"Contact via SMS/call. If unreachable after 2 attempts, "
                    f"escalate to formal demand letter."
                )

                cur = conn.execute(
                    """INSERT INTO ai_follow_up_task
                        (business_id, entity_type, entity_id, customer_id,
                         customer_contact_token, task_type, status,
                         scheduled_for_date, message_template,
                         ai_suggested_action, notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        business_id, "invoice", inv["invoice_id"], inv["customer_id"],
                        inv["customer_contact"], task_type, "pending",
                        today, template, suggested,
                        f"Auto-generated: {days_overdue} days overdue",
                    ),
                )

                new_tasks.append(AIFollowUpTask(
                    task_id=cur.lastrowid,
                    business_id=business_id,
                    entity_type="invoice",
                    entity_id=inv["invoice_id"],
                    customer_id=inv["customer_id"],
                    customer_contact_token=inv["customer_contact"],
                    task_type=task_type,
                    status="pending",
                    scheduled_for_date=today,
                    message_template=template,
                    ai_suggested_action=suggested,
                    notes=f"Auto-generated: {days_overdue} days overdue",
                ))

        return new_tasks

    def generate_quotation_follow_ups(self, business_id: int) -> List[AIFollowUpTask]:
        """Generate follow-up tasks for sent quotations not yet accepted."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        with self._get_conn() as conn:
            # Quotations sent > 3 days ago, still in 'sent' status
            pending = conn.execute(
                """SELECT * FROM quotation
                WHERE business_id = ?
                  AND status = 'sent'
                  AND quotation_date < date('now', '-3 days')
                ORDER BY quotation_date ASC""",
                (business_id,),
            ).fetchall()

        new_tasks: List[AIFollowUpTask] = []

        for qt in pending:
            with self._get_conn() as conn:
                existing = conn.execute(
                    """SELECT task_id FROM ai_follow_up_task
                    WHERE entity_type = 'quotation' AND entity_id = ? AND status = 'pending'""",
                    (qt["quotation_id"],),
                ).fetchone()
                if existing:
                    continue

            days_ago = (now - datetime.strptime(qt["quotation_date"][:10], "%Y-%m-%d")).days
            template = (
                f"Hi {qt['customer_name_token'] or 'there'}, "
                f"we're following up on quotation {qt['quotation_number']} "
                f"for KES {qt['total_minor']/100:,.2f} sent {days_ago} days ago. "
                f"Do you have any questions or need adjustments? We'd love to work with you!"
            )
            suggested = "Call to discuss the quotation. Offer a 5% discount if they commit within 7 days."

            with self._get_conn() as conn:
                cur = conn.execute(
                    """INSERT INTO ai_follow_up_task
                        (business_id, entity_type, entity_id, customer_id,
                         customer_name_token, task_type, status,
                         scheduled_for_date, message_template,
                         ai_suggested_action, notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        business_id, "quotation", qt["quotation_id"], qt["customer_id"],
                        qt["customer_name_token"], "quotation_follow_up", "pending",
                        today, template, suggested,
                        f"Auto-generated: sent {days_ago} days ago",
                    ),
                )

                new_tasks.append(AIFollowUpTask(
                    task_id=cur.lastrowid,
                    business_id=business_id,
                    entity_type="quotation",
                    entity_id=qt["quotation_id"],
                    customer_id=qt["customer_id"],
                    customer_contact_token=qt["customer_name_token"],
                    task_type="quotation_follow_up",
                    status="pending",
                    scheduled_for_date=today,
                    message_template=template,
                    ai_suggested_action=suggested,
                    notes=f"Auto-generated: sent {days_ago} days ago",
                ))

        return new_tasks

    def generate_all_tasks(self, business_id: int) -> Dict:
        """Generate all pending follow-up tasks."""
        reminders = self.generate_payment_reminders(business_id)
        follow_ups = self.generate_quotation_follow_ups(business_id)
        return {
            "payment_reminders": len(reminders),
            "quotation_follow_ups": len(follow_ups),
            "total_new_tasks": len(reminders) + len(follow_ups),
        }

    # ------------------------------------------------------------------
    # Task Management
    # ------------------------------------------------------------------

    def get_pending_tasks(
        self, business_id: int, task_type: Optional[str] = None, limit: int = 50
    ) -> List[AIFollowUpTask]:
        """Get pending follow-up tasks."""
        query = "SELECT * FROM ai_follow_up_task WHERE business_id = ? AND status = 'pending'"
        params: list = [business_id]
        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)
        query += " ORDER BY scheduled_for_date ASC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            AIFollowUpTask(
                task_id=r["task_id"],
                business_id=r["business_id"],
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                customer_id=r["customer_id"],
                customer_contact_token=r["customer_contact_token"],
                task_type=r["task_type"],
                status=r["status"],
                scheduled_for_date=r["scheduled_for_date"],
                attempted_at=r["attempted_at"],
                completed_at=r["completed_at"],
                message_template=r["message_template"],
                ai_suggested_action=r["ai_suggested_action"],
                outcome=r["outcome"],
                outcome_recorded_by=r["outcome_recorded_by"],
                notes=r["notes"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def complete_task(
        self, task_id: int, outcome: str, recorded_by: Optional[str] = None
    ) -> bool:
        """Mark a task as completed with outcome."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._get_conn() as conn:
            cur = conn.execute(
                """UPDATE ai_follow_up_task SET
                    status = 'completed', completed_at = ?, outcome = ?,
                    outcome_recorded_by = ?
                WHERE task_id = ? AND status = 'pending'""",
                (now, outcome, recorded_by, task_id),
            )
            if cur.rowcount > 0:
                # Update invoice follow_up fields if linked to invoice
                task = conn.execute(
                    "SELECT entity_type, entity_id FROM ai_follow_up_task WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if task and task["entity_type"] == "invoice":
                    conn.execute(
                        """UPDATE invoice SET
                            follow_up_count = follow_up_count + 1,
                            last_follow_up_date = ?,
                            follow_up_status = CASE
                                WHEN ? LIKE '%paid%' THEN 'payment_received'
                                WHEN ? LIKE '%promised%' THEN 'payment_promised'
                                ELSE 'contacted'
                            END
                        WHERE invoice_id = ?""",
                        (now, outcome, outcome, task["entity_id"]),
                    )
                return True
            return False

    def skip_task(self, task_id: int) -> bool:
        """Skip/ignore a task."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE ai_follow_up_task SET status = 'skipped', attempted_at = ? WHERE task_id = ?",
                (datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"), task_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Customer Insights
    # ------------------------------------------------------------------

    def get_customer_insights(self, business_id: int) -> List[CustomerInsight]:
        """Generate AI-style customer insights for sales actions."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        with self._get_conn() as conn:
            # Get all customers with invoices
            customers = conn.execute(
                """SELECT DISTINCT
                    i.customer_id,
                    i.customer_name_token,
                    COALESCE(SUM(i.total_amount_minor), 0) AS total_purchases,
                    COUNT(i.invoice_id) AS invoice_count,
                    COALESCE(SUM(CASE WHEN i.payment_status IN ('unpaid','partial','overdue')
                        AND i.due_date < ? THEN 1 ELSE 0 END), 0) AS overdue_count,
                    COALESCE(SUM(CASE WHEN i.payment_status IN ('unpaid','partial','overdue')
                        AND i.due_date < ? THEN i.balance_due_minor ELSE 0 END), 0) AS overdue_amount,
                    MAX(i.invoice_date) AS last_purchase_date
                FROM invoice i
                WHERE i.business_id = ? AND i.status = 'active'
                GROUP BY i.customer_id, i.customer_name_token""",
                (today, today, business_id),
            ).fetchall()

        insights: List[CustomerInsight] = []
        for c in customers:
            name = c["customer_name_token"] or f"Customer #{c['customer_id']}"
            days_since = None
            if c["last_purchase_date"]:
                last_date = datetime.strptime(c["last_purchase_date"][:10], "%Y-%m-%d")
                days_since = (now - last_date).days

            # Determine action and priority
            if c["overdue_amount"] > 0 and c["overdue_count"] > 0:
                if c["overdue_amount"] > 500000:  # > KES 5,000
                    suggested = "URGENT: Demand payment immediately. Consider pausing credit terms."
                    priority = "high"
                else:
                    suggested = "Send payment reminder. Offer payment plan if needed."
                    priority = "medium"
            elif days_since and days_since > 60:
                suggested = "Win-back: Offer 10% discount on next purchase. Customer may have churned."
                priority = "medium"
            elif days_since and days_since > 30:
                suggested = "Re-engagement: Send new product catalog or special offer."
                priority = "low"
            elif c["invoice_count"] >= 10:
                suggested = "Loyal customer: Consider VIP discount or early-access offers."
                priority = "low"
            else:
                suggested = "Nurture: Regular follow-up to build relationship."
                priority = "low"

            insights.append(CustomerInsight(
                customer_id=c["customer_id"],
                customer_name_token=name,
                total_purchases_minor=c["total_purchases"],
                invoice_count=c["invoice_count"],
                overdue_count=c["overdue_count"],
                overdue_amount_minor=c["overdue_amount"],
                last_purchase_date=c["last_purchase_date"],
                days_since_last_purchase=days_since,
                suggested_action=suggested,
                priority=priority,
            ))

        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        insights.sort(key=lambda x: (priority_order[x.priority], -x.overdue_amount_minor))

        return insights

    # ------------------------------------------------------------------
    # Dashboard Summary
    # ------------------------------------------------------------------

    def get_ai_dashboard_summary(self, business_id: int) -> Dict:
        """Get AI assistant dashboard KPIs."""
        with self._get_conn() as conn:
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM ai_follow_up_task WHERE business_id = ? AND status = 'pending'",
                (business_id,),
            ).fetchone()[0]

            completed_count = conn.execute(
                """SELECT COUNT(*) FROM ai_follow_up_task
                WHERE business_id = ? AND status = 'completed'
                  AND completed_at >= date('now', '-30 days')""",
                (business_id,),
            ).fetchone()[0]

            overdue_invoices = conn.execute(
                """SELECT COUNT(*) FROM invoice
                WHERE business_id = ? AND status = 'active'
                  AND payment_status IN ('unpaid','partial','overdue')
                  AND due_date < date('now')""",
                (business_id,),
            ).fetchone()[0]

            total_outstanding = conn.execute(
                """SELECT COALESCE(SUM(balance_due_minor), 0) FROM invoice
                WHERE business_id = ? AND status = 'active'
                  AND payment_status IN ('unpaid','partial','overdue')""",
                (business_id,),
            ).fetchone()[0]

        return {
            "pending_tasks": pending_count,
            "completed_last_30d": completed_count,
            "overdue_invoices": overdue_invoices,
            "total_outstanding_minor": total_outstanding,
        }
