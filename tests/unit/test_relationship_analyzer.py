"""Unit tests for core/relationship_analyzer.py."""
import pytest
from core.relationship_analyzer import RelationshipAnalyzer


@pytest.fixture
def party_transactions():
    return [
        {"date": "2026-07-01", "amount": 8000.0, "direction": "in", "counterparty": "VIP Customer", "category": "sales"},
        {"date": "2026-07-02", "amount": 1000.0, "direction": "in", "counterparty": "Small Customer", "category": "sales"},
        {"date": "2026-07-03", "amount": 1000.0, "direction": "in", "counterparty": "VIP Customer", "category": "sales"},
        {"date": "2026-07-04", "amount": 5000.0, "direction": "out", "counterparty": "Main Wholesaler", "category": "stock"},
    ]


def test_customer_supplier_separation(party_transactions):
    analyzer = RelationshipAnalyzer(party_transactions)
    customers = analyzer.get_customers()
    suppliers = analyzer.get_suppliers()

    assert len(customers) == 2
    assert len(suppliers) == 1
    assert customers[0].party_name == "VIP Customer"
    assert suppliers[0].party_name == "Main Wholesaler"


def test_concentration_risk_detection(party_transactions):
    # VIP Customer is 9,000 / 10,000 = 90% of revenue
    analyzer = RelationshipAnalyzer(party_transactions)
    risks = analyzer.get_concentration_risks()
    # At least 1 risk detected if >20%
    vip = [c for c in analyzer.get_customers() if c.party_name == "VIP Customer"][0]
    assert vip.concentration_pct >= 20.0
