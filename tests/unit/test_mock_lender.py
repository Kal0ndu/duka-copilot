"""Tests for sandbox/mock_lender.py"""
import pytest
from sandbox.mock_lender import MockLender, LoanOffer, compute_ear, compute_tcc


class TestMockLender:
    def test_get_offer_m_shwari(self):
        offer = MockLender.get_offer("mshwari", 10000, 30)
        assert offer.lender == "M-Shwari"
        assert offer.principal_minor == 10000
        assert offer.disbursed_minor == 10000  # no fee
        assert offer.total_repayable_minor > 10000
        assert offer.ear_pct > 0

    def test_get_offer_kcb_mpesa(self):
        offer = MockLender.get_offer("kcb_mpesa", 10000, 30)
        assert offer.lender == "KCB M-Pesa"
        assert offer.processing_fee_pct == 1.0
        assert offer.disbursed_minor < 10000  # fee deducted

    def test_compare_all_returns_sorted_by_ear(self):
        offers = MockLender.compare_all(10000, 30)
        assert len(offers) >= 4
        for i in range(len(offers) - 1):
            assert offers[i].ear_pct <= offers[i + 1].ear_pct

    def test_best_offer_affordability_filter(self):
        offer = MockLender.best_offer(10000, 30, affordability_daily_budget=100)
        assert offer is None or offer.daily_repayment_minor <= 100

    def test_best_offer_no_budget(self):
        offer = MockLender.best_offer(10000, 30)
        assert offer is not None
        assert isinstance(offer, LoanOffer)

    def test_offer_summary(self):
        offers = MockLender.compare_all(10000, 30)
        summary = MockLender.offer_summary(offers)
        assert "M-Shwari" in summary
        assert "EAR" in summary

    def test_invalid_product_key(self):
        with pytest.raises(KeyError):
            MockLender.get_offer("nonexistent", 10000, 30)


class TestEAR:
    def test_ear_zero_term(self):
        assert compute_ear(10000, 11000, 0) == 0.0

    def test_ear_zero_principal(self):
        assert compute_ear(0, 11000, 30) == 0.0

    def test_ear_positive(self):
        ear = compute_ear(10000, 11000, 30)
        assert ear > 10  # should be significant for 10% over 30 days

    def test_tcc(self):
        tcc = compute_tcc(10000, 200, 700)
        assert tcc == 9.0  # (200+700)/10000 * 100
