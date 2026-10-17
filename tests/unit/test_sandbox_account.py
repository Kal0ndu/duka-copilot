"""Tests for sandbox/account.py"""
import pytest
from sandbox.account import SandboxAccount, LoanRecord
from datetime import date


class TestSandboxAccount:
    def setup_method(self):
        self.acct = SandboxAccount(msisdn="0712345678", balance_minor=50000, float_minor=100000)

    def test_deposit(self):
        txn = self.acct.deposit(5000, category="sales")
        assert txn.amount_minor == 5000
        assert self.acct.balance_minor == 55000
        assert self.acct.float_minor == 105000

    def test_withdraw(self):
        txn = self.acct.withdraw(3000, category="stock_purchase")
        assert txn.amount_minor == -3000
        assert self.acct.balance_minor == 47000

    def test_withdraw_insufficient(self):
        with pytest.raises(ValueError, match="Insufficient"):
            self.acct.withdraw(100000)

    def test_send_to(self):
        other = SandboxAccount(msisdn="0798765432")
        txn = self.acct.send_to(other, 5000)
        assert txn.amount_minor == -5000
        assert other.balance_minor == 5000
        assert self.acct.balance_minor < 45000  # fee deducted

    def test_take_and_service_loan(self):
        loan = LoanRecord(
            loan_id="L001", principal_minor=5000, disbursed=5000,
            rate_monthly_pct=7.5, term_days=30, start_date=date.today(),
            daily_repayment_minor=200,
        )
        self.acct.take_loan(loan)
        assert self.acct.balance_minor == 55000

        remaining = self.acct.service_loan("L001", 2000)
        assert remaining == 3000
        assert loan.repaid_minor == 2000

        self.acct.service_loan("L001", 3000)
        assert loan.status == "paid"

    def test_daily_snapshot(self):
        self.acct.deposit(5000, category="sales")
        self.acct.withdraw(2000, category="stock_purchase")
        snap = self.acct.daily_snapshot()
        assert snap["balance_minor"] == 53000
        assert snap["total_credits"] == 5000
        assert snap["total_debits"] == 2000
        assert snap["net"] == 3000

    def test_transaction_history(self):
        self.acct.deposit(1000)
        self.acct.withdraw(500)
        assert len(self.acct.transactions) == 2
        assert self.acct.transactions[0].balance_after == 51000
        assert self.acct.transactions[1].balance_after == 50500
