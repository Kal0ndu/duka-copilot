"""E2E test: full flow through sandbox without real LLM calls."""
import pytest
from sandbox.account import SandboxAccount, LoanRecord
from sandbox.mock_lender import MockLender
from core.cost_engine import CostEngine
from datetime import date


class TestSandboxE2E:
    """End-to-end flow: upload -> categorise -> analyse -> forecast -> compare."""

    def test_full_happy_path(self):
        # 1. Create account with some history
        acct = SandboxAccount(msisdn="0712345678")
        acct.deposit(5000, category="sales")
        acct.deposit(3000, category="sales")
        acct.withdraw(2000, category="stock_purchase")
        acct.withdraw(500, category="transport")

        # 2. Snapshot
        snap = acct.daily_snapshot()
        assert snap["balance_minor"] == 5500
        assert snap["total_credits"] == 8000
        assert snap["total_debits"] == 2500
        assert snap["net"] == 5500

        # 3. Compare financing
        offers = MockLender.compare_all(5000, 30)
        assert len(offers) >= 4
        best = offers[0]

        # 4. Affordability check
        engine = CostEngine()
        check = engine.affordability_check(
            daily_repayment=best.daily_repayment_minor,
            avg_daily_profit=300,
            buffer_minor=1000,
        )
        assert isinstance(check["affordable"], bool)

        # 5. Shortfall detection on simulated forecast
        balances = [5500, 5200, 4800, 4400, 4000, 3500, 3000, 2500]
        shortfalls = engine.detect_shortfalls(balances, buffer=500)
        assert len(shortfalls) == 0  # no shortfalls in this range

    def test_loan_repayment_flow(self):
        acct = SandboxAccount(msisdn="0712345678", balance_minor=10000)
        loan = LoanRecord(
            loan_id="L001", principal_minor=5000, disbursed=4800,
            rate_monthly_pct=7.5, term_days=30, start_date=date.today(),
            daily_repayment_minor=200,
        )
        acct.take_loan(loan)
        assert acct.balance_minor == 14800

        # Repay fully
        for _ in range(25):
            acct.service_loan("L001", 200)
        assert loan.status == "paid"
        assert acct.balance_minor == 9800
