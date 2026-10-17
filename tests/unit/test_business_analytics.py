"""Unit tests for core/analytics.py BusinessAnalytics engine."""
import pytest
import pandas as pd
from core.analytics import BusinessAnalytics


@pytest.fixture
def sample_transactions():
    return [
        {"date": "2026-07-01", "amount": 1000.0, "type": "credit", "category": "sales", "counterparty": "Customer A"},
        {"date": "2026-07-01", "amount": -400.0, "type": "debit", "category": "stock_purchase", "counterparty": "Supplier B"},
        {"date": "2026-07-02", "amount": 1500.0, "type": "credit", "category": "sales_till", "counterparty": "Walkin"},
        {"date": "2026-07-02", "amount": -200.0, "type": "debit", "category": "rent", "counterparty": "Landlord"},
        {"date": "2026-07-03", "amount": -100.0, "type": "debit", "category": "personal", "counterparty": "Self"},
    ]


def test_business_analytics_kpis(sample_transactions):
    analytics = BusinessAnalytics(sample_transactions)
    kpis = analytics.kpi_summary()

    assert kpis["total_revenue"] == 2500.0
    assert kpis["cogs"] == 400.0
    assert kpis["opex"] == 200.0
    assert kpis["personal_outflow"] == 100.0
    assert kpis["net_profit"] == 1900.0
    assert kpis["txn_count"] == 5
    assert kpis["gross_margin_pct"] == 84.0


def test_business_analytics_breakdown(sample_transactions):
    analytics = BusinessAnalytics(sample_transactions)
    breakdown = analytics.category_breakdown()
    assert "Stock & Inventory" in breakdown
    assert breakdown["Stock & Inventory"] == 400.0


def test_business_analytics_daily_in_out(sample_transactions):
    analytics = BusinessAnalytics(sample_transactions)
    df = analytics.daily_in_out_df()
    assert len(df) == 3
    assert "inflow" in df.columns
    assert "outflow" in df.columns
    assert "net" in df.columns


def test_business_analytics_top_counterparties(sample_transactions):
    analytics = BusinessAnalytics(sample_transactions)
    top_cust = analytics.top_counterparties(direction="in")
    assert len(top_cust) >= 2
    names = [c[0] for c in top_cust]
    assert "Customer A" in names or "Walkin" in names
