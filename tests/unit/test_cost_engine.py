"""Tests for core/cost_engine.py"""
import pytest
from core.cost_engine import CostEngine, CreditProduct, FeeComponent


class TestCostEngine:
    def test_ear_single(self):
        engine = CostEngine()
        periodic_rate, ear = engine.compute_ear_single(
            principal=30000, total_repayable=33000, term_days=30
        )
        assert isinstance(periodic_rate, float)
        assert isinstance(ear, float)
        assert ear > 0  # positive rate

    def test_ear_installments(self):
        engine = CostEngine()
        periodic_rate, ear = engine.compute_ear_installments(
            principal=100000, installment_amount=12000,
            n_installments=10, period_days=30
        )
        assert isinstance(ear, float)
        assert ear > 0

    def test_price_product(self):
        engine = CostEngine()
        product = CreditProduct(
            product_id=1, code="M-SHWARI", type="digital",
            name="M-Shwari", repayment_style="single",
            min_amount_minor=50000, max_amount_minor=5000000,
            min_term_days=7, max_term_days=30,
            fees=[FeeComponent(kind="upfront_pct", basis="principal", rate_bp=750)]
        )
        result = engine.price_product(product, principal_minor=100000, term_days=30)
        assert result.product_code == "M-SHWARI"
        assert result.tcc_minor > 0

    def test_compare_products(self):
        engine = CostEngine()
        p1 = CreditProduct(
            product_id=1, code="M-SHWARI", type="digital",
            name="M-Shwari", repayment_style="single",
            min_amount_minor=50000, max_amount_minor=5000000,
            min_term_days=7, max_term_days=30,
            fees=[FeeComponent(kind="upfront_pct", basis="principal", rate_bp=750)]
        )
        results = engine.compare_products([p1], principal_minor=100000, term_days=30)
        assert len(results) == 1
        assert results[0].product_code == "M-SHWARI"

    def test_check_affordability_affordable(self):
        engine = CostEngine()
        product = CreditProduct(
            product_id=1, code="M-SHWARI", type="digital",
            name="M-Shwari", repayment_style="single",
            min_amount_minor=50000, max_amount_minor=5000000,
            min_term_days=7, max_term_days=30,
            fees=[FeeComponent(kind="upfront_pct", basis="principal", rate_bp=750)]
        )
        result = engine.check_affordability(
            product, principal_minor=100000, term_days=30,
            daily_surplus_minor=20000
        )
        assert isinstance(result, bool)

    def test_ear_zero_case(self):
        engine = CostEngine()
        periodic_rate, ear = engine.compute_ear_single(
            principal=50000, total_repayable=50000, term_days=30
        )
        assert ear == 0.0
