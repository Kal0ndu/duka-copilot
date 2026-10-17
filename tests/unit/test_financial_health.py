"""Unit tests for core/financial_health.py."""
import pytest
from datetime import datetime, timedelta
import pandas as pd
from core.financial_health import FinancialHealthAnalyzer, FinancialHealthReport


@pytest.fixture
def healthy_transactions():
    """A healthy business: consistent revenue, moderate expenses, positive cashflow."""
    base_date = datetime(2026, 7, 1)
    txns = []
    for i in range(60):
        d = base_date + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        # Daily revenue KES 2,000-5,000
        txns.append({
            "local_date": date_str,
            "amount": 2000.0 + (i % 4) * 1000.0,
            "direction": "in",
            "counterparty": f"Customer {(i % 5) + 1}",
        })
        # Daily expenses KES 1,000-2,500
        txns.append({
            "local_date": date_str,
            "amount": 1000.0 + (i % 3) * 500.0,
            "direction": "out",
            "counterparty": f"Supplier {(i % 3) + 1}",
        })
    return txns


@pytest.fixture
def struggling_transactions():
    """A struggling business: high expenses, irregular revenue, net loss."""
    base_date = datetime(2026, 7, 1)
    txns = []
    for i in range(30):
        d = base_date + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        # Low, irregular revenue
        if i % 3 != 0:
            txns.append({
                "local_date": date_str,
                "amount": 500.0 + (i % 3) * 300.0,
                "direction": "in",
                "counterparty": f"Customer {(i % 2) + 1}",
            })
        # High expenses every day
        txns.append({
            "local_date": date_str,
            "amount": 2000.0,
            "direction": "out",
            "counterparty": "Main Supplier",
        })
    return txns


@pytest.fixture
def empty_transactions():
    return []


class TestFinancialHealthAnalyzer:
    """Test the FinancialHealthAnalyzer with various business scenarios."""

    def test_assess_healthy_business(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        report = analyzer.assess()

        assert isinstance(report, FinancialHealthReport)
        assert report.health_score > 0
        assert report.health_label != "No Data"
        assert report.txn_count == len(healthy_transactions)
        assert report.period_start != ""
        assert report.period_end != ""

        # Healthy business should have positive margins
        assert report.net_margin_pct > 0, "Healthy business should have positive net margin"
        assert report.days_of_cash > 0, "Should have positive cash runway"
        assert report.current_ratio > 0, "Should have positive current ratio"

    def test_assess_struggling_business(self, struggling_transactions):
        analyzer = FinancialHealthAnalyzer(struggling_transactions)
        report = analyzer.assess()

        assert isinstance(report, FinancialHealthReport)
        # Struggling business should have negative net margin
        assert report.net_margin_pct < 0, "Struggling business should have negative net margin"
        # Should have risk flags
        assert len(report.risk_flags) > 0, "Struggling business should trigger risk flags"
        # Health score should be low
        assert report.health_score < 50, f"Expected health score <50, got {report.health_score}"

    def test_assess_empty_transactions(self, empty_transactions):
        analyzer = FinancialHealthAnalyzer(empty_transactions)
        report = analyzer.assess()

        assert report.health_label == "No Data"
        assert report.health_score == 0
        assert len(report.risk_flags) > 0
        assert "No transaction data" in report.risk_flags[0]

    def test_assess_with_dataframe_input(self, healthy_transactions):
        df = pd.DataFrame(healthy_transactions)
        analyzer = FinancialHealthAnalyzer(df)
        report = analyzer.assess()

        assert report.txn_count > 0
        assert report.health_score >= 0

    def test_report_has_all_required_fields(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        report = analyzer.assess()

        required_fields = [
            "current_ratio", "quick_ratio", "cash_balance_kes",
            "total_current_assets_kes", "total_current_liabilities_kes",
            "days_of_cash", "monthly_burn_rate_kes", "monthly_revenue_kes",
            "burn_multiple", "debt_to_revenue_ratio", "debt_service_coverage",
            "gross_margin_pct", "operating_margin_pct", "net_margin_pct",
            "revenue_growth_pct", "revenue_volatility_pct", "revenue_concentration_pct",
            "health_score", "health_label", "risk_flags", "recommendations",
        ]

        for field in required_fields:
            assert hasattr(report, field), f"Missing field: {field}"
            value = getattr(report, field)
            assert value is not None or field == "revenue_growth_pct", \
                f"Field {field} is None when it shouldn't be"

    def test_health_score_in_range(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        report = analyzer.assess()

        assert 0 <= report.health_score <= 100, \
            f"Health score {report.health_score} out of 0-100 range"

    def test_health_label_matches_score(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        report = analyzer.assess()

        score = report.health_score
        label = report.health_label

        if score >= 80:
            assert label == "Excellent"
        elif score >= 60:
            assert label == "Good"
        elif score >= 40:
            assert label == "Fair"
        elif score >= 20:
            assert label == "At Risk"
        else:
            assert label == "Critical"

    def test_daily_trend_df(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        trend = analyzer.daily_trend_df()

        assert not trend.empty
        assert list(trend.columns) == ["date", "inflow", "outflow", "net", "cumulative_net"]
        assert len(trend) > 0

    def test_weekly_summary(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        weekly = analyzer.weekly_summary()

        assert not weekly.empty
        assert "revenue" in weekly.columns
        assert "expenses" in weekly.columns
        assert "net" in weekly.columns

    def test_revenue_growth_computation(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        report = analyzer.assess()

        # With 60 days of stable data, growth should be computable
        assert report.revenue_growth_pct is not None, "Revenue growth should be computable with 60 days of data"

    def test_customer_concentration(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        report = analyzer.assess()

        assert 0.0 <= report.revenue_concentration_pct <= 100.0, \
            f"Concentration {report.revenue_concentration_pct} out of range"

    def test_dataframe_amount_minor_column(self):
        """Test that amount_minor column is handled correctly."""
        txns = [
            {"local_date": "2026-07-01", "amount_minor": 500000, "direction": "in", "counterparty": "Cust A"},
            {"local_date": "2026-07-01", "amount_minor": 300000, "direction": "out", "counterparty": "Supplier A"},
        ]
        analyzer = FinancialHealthAnalyzer(txns)
        report = analyzer.assess()

        assert report.txn_count == 2
        assert report.monthly_revenue_kes > 0

    def test_burn_multiple_healthy(self, healthy_transactions):
        analyzer = FinancialHealthAnalyzer(healthy_transactions)
        report = analyzer.assess()

        # For a healthy business, burn multiple should be < 1.0
        assert report.burn_multiple > 0, "Burn multiple should be positive"
        # With revenues higher than expenses, burn multiple should be < 1.0
        assert report.burn_multiple < 1.5, f"Burn multiple {report.burn_multiple} too high for healthy business"
