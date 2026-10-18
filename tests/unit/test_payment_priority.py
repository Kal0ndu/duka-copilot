"""Tests for core/payment_priority.py"""
from datetime import date, timedelta

from core.payment_priority import PaymentCandidate, band_for, rank_payments

TODAY = date(2026, 10, 18)


def _c(pid, kind="other", days=5, amount=1_000_00, essential=True, penalty=0):
    return PaymentCandidate(pid, f"p{pid}", kind, amount, TODAY + timedelta(days=days), essential, penalty)


def test_overdue_rent_outranks_future_savings():
    ranked = rank_payments([_c(1, "savings", days=10, essential=False), _c(2, "rent", days=-2)], TODAY)
    assert [p.payment_id for p in ranked] == [2, 1]
    assert ranked[0].band == "critical"
    assert ranked[0].reasons[0] == "Overdue by 2 days"


def test_late_fee_raises_priority():
    ranked = rank_payments([_c(1), _c(2, penalty=200_00)], TODAY)
    assert ranked[0].payment_id == 2
    assert any("Late fee" in r for r in ranked[0].reasons)


def test_cash_shortfall_demotes_non_essential_and_flags_essential():
    ranked = rank_payments(
        [_c(1, "rent", days=1, amount=8_000_00), _c(2, "supplier_standing", days=1, amount=5_000_00, essential=False)],
        TODAY, balance_minor=10_000_00, buffer_minor=1_000_00,
    )
    by_id = {p.payment_id: p for p in ranked}
    assert by_id[1].covered is True
    assert by_id[2].covered is False
    assert any("Can wait" in r for r in by_id[2].reasons)


def test_unknown_balance_skips_affordability():
    ranked = rank_payments([_c(1)], TODAY, balance_minor=None)
    assert ranked[0].covered is None


def test_scores_are_clamped_and_banded():
    top = rank_payments([_c(1, "loan_repayment", days=-30, penalty=10**9)], TODAY)[0]
    assert top.score == 90  # max: 40 urgency + 25 kind + 10 essential + 15 penalty
    bottom = rank_payments([_c(1, "savings", days=30, essential=False)], TODAY, balance_minor=0)[0]
    assert bottom.score == 0  # 5 + 5 - 10, clamped at 0
    assert band_for(69) == "high" and band_for(70) == "critical" and band_for(29) == "low"
