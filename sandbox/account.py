"""Sandbox account: simulated mobile-money wallet with ledger."""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import random
import hashlib


@dataclass
class Transaction:
    txn_id: str
    timestamp: datetime
    counterparty: str
    amount_minor: int          # positive = credit, negative = debit
    category: str
    balance_after: int
    channel: str = "mpesa"     # mpesa, bank, cash


@dataclass
class LoanRecord:
    loan_id: str
    principal_minor: int
    disbursed: int              # actual received after fees
    rate_monthly_pct: float
    term_days: int
    start_date: date
    daily_repayment_minor: int
    repaid_minor: int = 0
    status: str = "active"      # active, paid, defaulted


@dataclass
class SandboxAccount:
    """Simulated mobile-money account with deterministic behaviour."""

    msisdn: str
    balance_minor: int = 0
    float_minor: int = 0         # agent float
    transactions: List[Transaction] = field(default_factory=list)
    loans: List[LoanRecord] = field(default_factory=list)
    _txn_counter: int = 0

    def _next_txn_id(self) -> str:
        self._txn_counter += 1
        raw = f"{self.msisdn}:{self._txn_counter}:{datetime.utcnow().isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12].upper()

    def deposit(self, amount_minor: int, counterparty: str = "CUSTOMER",
                category: str = "sales") -> Transaction:
        self.float_minor += amount_minor
        self.balance_minor += amount_minor
        txn = Transaction(
            txn_id=self._next_txn_id(),
            timestamp=datetime.now(),
            counterparty=counterparty,
            amount_minor=amount_minor,
            category=category,
            balance_after=self.balance_minor,
        )
        self.transactions.append(txn)
        return txn

    def withdraw(self, amount_minor: int, counterparty: str = "SUPPLIER",
                 category: str = "stock_purchase") -> Transaction:
        if amount_minor > self.balance_minor:
            raise ValueError(f"Insufficient balance: {self.balance_minor} < {amount_minor}")
        self.float_minor -= amount_minor
        self.balance_minor -= amount_minor
        txn = Transaction(
            txn_id=self._next_txn_id(),
            timestamp=datetime.now(),
            counterparty=counterparty,
            amount_minor=-amount_minor,
            category=category,
            balance_after=self.balance_minor,
        )
        self.transactions.append(txn)
        return txn

    def send_to(self, recipient, amount_minor: int,
                category: str = "transfer_out") -> Transaction:
        """Send money to another sandbox account."""
        fee = max(0, min(amount_minor * 0.005, 11000))  # ~0.5% fee, capped
        total = amount_minor + int(fee)
        if total > self.balance_minor:
            raise ValueError(f"Insufficient balance: {self.balance_minor} < {total}")
        self.balance_minor -= total
        recipient.deposit(amount_minor, counterparty=self.msisdn, category="transfer_in")
        txn = Transaction(
            txn_id=self._next_txn_id(),
            timestamp=datetime.now(),
            counterparty=recipient.msisdn,
            amount_minor=-amount_minor,
            category=category,
            balance_after=self.balance_minor,
        )
        self.transactions.append(txn)
        return txn

    def take_loan(self, loan: 'LoanRecord'):
        """Book a loan and credit the disbursed amount."""
        self.balance_minor += loan.disbursed
        self.loans.append(loan)

    def service_loan(self, loan_id: str, amount_minor: int) -> int:
        """Apply a repayment. Returns remaining balance after payment."""
        for loan in self.loans:
            if loan.loan_id == loan_id and loan.status == "active":
                remaining = loan.principal_minor - loan.repaid_minor
                applied = min(amount_minor, remaining)
                loan.repaid_minor += applied
                self.balance_minor -= applied
                if loan.repaid_minor >= loan.principal_minor:
                    loan.status = "paid"
                return loan.principal_minor - loan.repaid_minor
        raise ValueError(f"Loan {loan_id} not found or not active")

    def daily_snapshot(self) -> Dict:
        """Return a summary snapshot for analytics."""
        credits = sum(t.amount_minor for t in self.transactions if t.amount_minor > 0)
        debits = sum(abs(t.amount_minor) for t in self.transactions if t.amount_minor < 0)
        loan_total = sum(l.principal_minor - l.repaid_minor for l in self.loans if l.status == "active")
        return {
            "msisdn": self.msisdn,
            "balance_minor": self.balance_minor,
            "float_minor": self.float_minor,
            "total_credits": credits,
            "total_debits": debits,
            "net": credits - debits,
            "active_loans": sum(1 for l in self.loans if l.status == "active"),
            "loan_exposure_minor": loan_total,
            "txn_count": len(self.transactions),
        }


# ---- Tool wrapper function for agent dispatch ----

def propose_supplier_payment(args, business_id: Optional[int] = None,
                            db_path: Optional[str] = None) -> dict:
    """Create a pending supplier payment proposal (requires owner approval).

    Goes through core.approvals: verified payees only, look-alike names
    refused, per-payment and daily caps enforced. Nothing is paid until the
    owner approves with their PIN on the Approvals page.
    
    Args:
        args: ProposeSupplierPaymentArgs with payee_id or payee_name, amount_minor, scheduled_for
        business_id: Active business ID
        db_path: Database path
    
    Returns:
        dict with action_id with status PENDING_APPROVAL (or BLOCKED and why)
    """
    from core.approvals import ApprovalService
    
    if business_id is None:
        return {"error": "business_id required"}
    
    try:
        result = ApprovalService(db_path).propose_payment(
            business_id,
            amount_minor=args.amount_minor,
            payee_id=args.payee_id,
            payee_name=getattr(args, "payee_name", None),
            scheduled_for=args.scheduled_for,
        )
    except Exception as e:
        return {"error": f"Payment proposal failed: {e}"}
    if result["status"] == "PENDING_APPROVAL":
        result["message"] = ("NOT paid yet. The owner must approve it with their PIN on the "
                             "Approvals page.")
    else:
        result["message"] = f"Refused by the owner's payment rules: {result['reason']}"
    return result
