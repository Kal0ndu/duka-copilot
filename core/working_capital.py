"""Working capital intelligence: A/R and A/P aging, DSO/DPO, and credit book management."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import pandas as pd


@dataclass
class CreditEntry:
    entry_id: str
    counterparty: str
    phone_token: str
    kind: str  # 'receivable' (money owed to business) or 'payable' (money business owes)
    amount_kes: float
    issued_date: str
    due_date: str
    days_overdue: int
    bucket: str  # 'Current (0-30d)', '31-60d', '61-90d', '90+d'
    status: str  # 'open', 'partial', 'settled'
    reminder_msg: str


class WorkingCapitalAnalyzer:
    """ILLUSTRATIVE ONLY: estimates a credit book from transaction patterns
    (receivables = 18% and payables = 22% of each top counterparty's volume).
    These are not real debts; never show them as such or send reminders
    from them. Real figures: working_capital_position() / open_invoices()."""

    def __init__(self, transactions=None):
        if isinstance(transactions, pd.DataFrame):
            self.df = transactions.copy()
        elif isinstance(transactions, list):
            self.df = pd.DataFrame(transactions)
        else:
            self.df = pd.DataFrame()
        self._prepare_data()

    def _prepare_data(self):
        if self.df.empty:
            return

        if "amount_kes" not in self.df.columns:
            if "amount_minor" in self.df.columns:
                self.df["amount_kes"] = pd.to_numeric(self.df["amount_minor"], errors="coerce").fillna(0).abs() / 100.0
            elif "amount" in self.df.columns:
                self.df["amount_kes"] = pd.to_numeric(self.df["amount"], errors="coerce").fillna(0).abs()
            else:
                self.df["amount_kes"] = 0.0

        if "direction" not in self.df.columns:
            if "type" in self.df.columns:
                self.df["direction"] = self.df["type"].apply(
                    lambda t: "in" if str(t).lower() in ("credit", "in") else "out"
                )
            else:
                self.df["direction"] = "out"

        if "local_date" not in self.df.columns:
            if "date" in self.df.columns:
                self.df["local_date"] = self.df["date"].astype(str).str.slice(0, 10)
            elif "ts" in self.df.columns:
                self.df["local_date"] = pd.to_datetime(self.df["ts"], errors="coerce").dt.strftime("%Y-%m-%d")
            else:
                self.df["local_date"] = datetime.today().strftime("%Y-%m-%d")

    def generate_credit_book(self) -> Tuple[List[CreditEntry], List[CreditEntry]]:
        """Extract or simulate receivables (customer credit book) and payables based on actual counterparty activity."""
        if self.df.empty:
            return [], []

        max_date_str = str(self.df["local_date"].max())
        try:
            ref_date = datetime.strptime(max_date_str, "%Y-%m-%d")
        except Exception:
            ref_date = datetime.now()

        # Identify regular customers and suppliers from transactions
        inflows = self.df[self.df["direction"] == "in"]
        outflows = self.df[self.df["direction"] == "out"]

        receivables: List[CreditEntry] = []
        payables: List[CreditEntry] = []

        # Generate receivables for top customers (simulating realistic duka informal credit)
        top_customers = inflows.groupby("counterparty").agg(
            total_vol=("amount_kes", "sum"),
            last_date=("local_date", "max"),
            txns=("amount_kes", "count")
        ).sort_values("total_vol", ascending=False).head(8)

        sample_offsets = [5, 14, 28, 42, 65, 80, 105, 15]
        for i, (name, row) in enumerate(top_customers.iterrows()):
            offset = sample_offsets[i % len(sample_offsets)]
            issued = ref_date - timedelta(days=offset)
            due = issued + timedelta(days=14)  # 14-day terms typical in Kenya
            days_overdue = max(0, (ref_date - due).days)

            # Credit amount is roughly 15-25% of their typical transaction volume
            credit_amount = max(350.0, round(float(row["total_vol"]) * 0.18, -1))

            if days_overdue == 0:
                bucket = "Current (0-30d)"
            elif days_overdue <= 30:
                bucket = "1-30 days overdue"
            elif days_overdue <= 60:
                bucket = "31-60 days overdue"
            else:
                bucket = "61+ days overdue"

            phone_tok = f"07** *** {200 + i * 15:03d}"
            reminder = (
                f"Habari {name}, friendly reminder of your outstanding store credit of "
                f"KES {credit_amount:,.0f} due on {due.strftime('%d %b')}. "
                f"Kindly clear via Till or M-Pesa. Asante for your continued support!"
            )

            receivables.append(CreditEntry(
                entry_id=f"REC-{1001 + i}",
                counterparty=str(name),
                phone_token=phone_tok,
                kind="receivable",
                amount_kes=credit_amount,
                issued_date=issued.strftime("%Y-%m-%d"),
                due_date=due.strftime("%Y-%m-%d"),
                days_overdue=days_overdue,
                bucket=bucket,
                status="open",
                reminder_msg=reminder,
            ))

        # Generate payables for suppliers and operational bills
        top_suppliers = outflows.groupby("counterparty").agg(
            total_vol=("amount_kes", "sum"),
            last_date=("local_date", "max")
        ).sort_values("total_vol", ascending=False).head(5)

        pay_offsets = [7, 18, 25, 35, 12]
        for j, (sup_name, row) in enumerate(top_suppliers.iterrows()):
            offset = pay_offsets[j % len(pay_offsets)]
            issued = ref_date - timedelta(days=offset)
            due = issued + timedelta(days=30)  # 30-day supplier credit
            days_overdue = max(0, (ref_date - due).days)

            pay_amount = max(800.0, round(float(row["total_vol"]) * 0.22, -2))

            if days_overdue == 0:
                bucket = "Current (Not Due)"
            elif days_overdue <= 30:
                bucket = "1-30 days overdue"
            else:
                bucket = "30+ days overdue"

            payables.append(CreditEntry(
                entry_id=f"PAY-{2001 + j}",
                counterparty=str(sup_name),
                phone_token="Supplier Office",
                kind="payable",
                amount_kes=pay_amount,
                issued_date=issued.strftime("%Y-%m-%d"),
                due_date=due.strftime("%Y-%m-%d"),
                days_overdue=days_overdue,
                bucket=bucket,
                status="open",
                reminder_msg=f"Pay KES {pay_amount:,.0f} to {sup_name} before {due.strftime('%d %b')}.",
            ))

        return receivables, payables

    def compute_working_capital_metrics(self) -> Dict:
        """Calculate DSO, DPO, CCC and working capital gap."""
        receivables, payables = self.generate_credit_book()

        total_ar = sum(r.amount_kes for r in receivables)
        total_ap = sum(p.amount_kes for p in payables)

        total_revenue = self.df[self.df["direction"] == "in"]["amount_kes"].sum() if not self.df.empty else 1.0
        total_cogs = self.df[self.df["direction"] == "out"]["amount_kes"].sum() if not self.df.empty else 1.0

        days_window = max(1, self.df["local_date"].nunique()) if not self.df.empty else 30

        # Days Sales Outstanding
        dso = int(round((total_ar / max(1.0, total_revenue)) * days_window))
        # Days Payable Outstanding
        dpo = int(round((total_ap / max(1.0, total_cogs)) * days_window))
        # Cash Conversion Cycle (CCC = DSO - DPO)
        ccc = dso - dpo

        # Aging breakdown
        ar_buckets = {
            "Current (0-30d)": sum(r.amount_kes for r in receivables if r.bucket == "Current (0-30d)"),
            "1-30 days overdue": sum(r.amount_kes for r in receivables if r.bucket == "1-30 days overdue"),
            "31-60 days overdue": sum(r.amount_kes for r in receivables if r.bucket == "31-60 days overdue"),
            "61+ days overdue": sum(r.amount_kes for r in receivables if r.bucket == "61+ days overdue"),
        }

        ap_buckets = {
            "Current (Not Due)": sum(p.amount_kes for p in payables if p.bucket == "Current (Not Due)"),
            "1-30 days overdue": sum(p.amount_kes for p in payables if p.bucket == "1-30 days overdue"),
            "30+ days overdue": sum(p.amount_kes for p in payables if p.bucket == "30+ days overdue"),
        }

        return {
            "total_receivables_kes": total_ar,
            "total_payables_kes": total_ap,
            "net_working_capital_kes": total_ar - total_ap,
            "dso_days": dso,
            "dpo_days": dpo,
            "cash_conversion_cycle_days": ccc,
            "ar_buckets": ar_buckets,
            "ap_buckets": ap_buckets,
            "overdue_receivables_kes": sum(r.amount_kes for r in receivables if r.days_overdue > 0),
            "overdue_payables_kes": sum(p.amount_kes for p in payables if p.days_overdue > 0),
            "receivables_list": receivables,
            "payables_list": payables,
        }


# ---- working capital from the business's own records ----

OPEN_PAYMENT_STATES = ("pending", "notified", "authorized", "stk_sent", "failed")


def _scalar(conn, sql: str, params) -> int:
    """One integer from the database; 0 when the table does not exist yet."""
    import sqlite3
    try:
        return int(conn.execute(sql, params).fetchone()[0] or 0)
    except sqlite3.OperationalError:
        return 0


def working_capital_position(db_path: str, business_id: int, today=None,
                             horizon_days: int = 30) -> Dict:
    """Working capital computed only from database records (amounts in minor units).

    Current assets
      cash          ledger balance at the end of the latest statement (if positive)
      receivables   unpaid balances of open invoices
      inventory     stock on hand at cost price
    Current liabilities (owed now)
      overdraft     overdraft owed, with fees (core.forecaster.true_position)
      overdue bills recurring-expense instalments past their due date
      open payments standing-order payments generated but not yet paid
    Next horizon_days
      bills due     recurring-expense instalments falling due
      invoices due  open invoice balances falling due (money expected in)

    net_working_capital = current assets - current liabilities
    liquidity_gap       = cash + invoices due - liabilities - bills due
                          (negative: cash will run short within the horizon)
    """
    import sqlite3
    from datetime import date as _date
    from core.expense_tracker import RecurringExpenseManager
    from core.forecaster import true_position

    today = today or _date.today()
    end = today + timedelta(days=horizon_days)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        pos = true_position(conn, business_id)
        balance = pos["balance_minor"]
        open_inv = ("FROM invoice WHERE business_id = ? AND payment_status NOT IN ('paid','cancelled') "
                    "AND status NOT IN ('cancelled','draft')")
        receivables = _scalar(conn, f"SELECT SUM(balance_due_minor) {open_inv}", (business_id,))
        overdue_receivables = _scalar(conn, f"SELECT SUM(balance_due_minor) {open_inv} AND due_date < ?",
                                      (business_id, today.isoformat()))
        invoices_due = _scalar(conn, f"SELECT SUM(balance_due_minor) {open_inv} AND due_date <= ?",
                               (business_id, end.isoformat()))
        inventory = _scalar(conn, """SELECT SUM(current_stock_qty * cost_price_minor) FROM product
                                     WHERE business_id = ? AND is_active = 1 AND current_stock_qty > 0""",
                            (business_id,))
        marks = ",".join("?" * len(OPEN_PAYMENT_STATES))
        open_payments = _scalar(conn, f"""SELECT SUM(amount_minor) FROM scheduled_payment
                                          WHERE business_id = ? AND status IN ({marks})""",
                                (business_id, *OPEN_PAYMENT_STATES))
    finally:
        conn.close()

    try:
        bills = RecurringExpenseManager(db_path).obligations_between(business_id, today, end)
    except sqlite3.Error:
        bills = []
    overdue_bills = sum(b["amount_minor"] for b in bills if b["days_overdue"] > 0)
    bills_due = sum(b["amount_minor"] for b in bills if b["days_overdue"] == 0)
    # Variable bills are planned at their average; the high case adds 10%.
    bills_due_high = sum(b["amount_high_minor"] for b in bills if b["days_overdue"] == 0)

    cash = max(0, balance)
    overdraft = pos["overdraft_owed_minor"] + max(0, -balance)
    current_assets = cash + receivables + inventory
    current_liabilities = overdraft + overdue_bills + open_payments
    return {
        "as_of_statement": pos["as_of"],
        "today": today.isoformat(),
        "horizon_days": horizon_days,
        "cash_minor": cash,
        "receivables_minor": receivables,
        "overdue_receivables_minor": overdue_receivables,
        "inventory_minor": inventory,
        "current_assets_minor": current_assets,
        "overdraft_minor": overdraft,
        "overdue_bills_minor": overdue_bills,
        "open_payments_minor": open_payments,
        "current_liabilities_minor": current_liabilities,
        "net_working_capital_minor": current_assets - current_liabilities,
        "current_ratio": round(current_assets / current_liabilities, 2) if current_liabilities else None,
        "bills_due_minor": bills_due,
        "bills_due_high_minor": bills_due_high,
        "invoices_due_minor": invoices_due,
        "liquidity_gap_minor": cash + invoices_due - current_liabilities - bills_due,
        "liquidity_gap_low_minor": cash + invoices_due - current_liabilities - bills_due_high,
        "bills": bills,
    }


AGING_BUCKETS = ("Not due", "1-30 days overdue", "31-60 days overdue", "61+ days overdue")


def aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return AGING_BUCKETS[0]
    if days_overdue <= 30:
        return AGING_BUCKETS[1]
    if days_overdue <= 60:
        return AGING_BUCKETS[2]
    return AGING_BUCKETS[3]


def open_invoices(db_path: str, business_id: int, today=None) -> List[Dict]:
    """Unpaid invoices of the business with their real age (from due_date)."""
    import sqlite3
    from datetime import date as _date
    today = today or _date.today()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT invoice_id, invoice_number, invoice_date, due_date, customer_name_token,
                          total_amount_minor, amount_paid_minor, balance_due_minor, payment_status
                   FROM invoice
                   WHERE business_id = ? AND payment_status NOT IN ('paid','cancelled')
                     AND status NOT IN ('cancelled','draft') AND balance_due_minor > 0
                   ORDER BY due_date""",
                (business_id,),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        d = dict(r)
        days = (today - _date.fromisoformat(d["due_date"][:10])).days
        d["days_overdue"] = max(0, days)
        d["bucket"] = aging_bucket(days)
        out.append(d)
    return out
