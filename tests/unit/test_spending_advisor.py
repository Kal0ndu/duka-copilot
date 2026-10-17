"""Tests for core/spending_advisor.py"""
import pytest
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta
from core.spending_advisor import SpendingAdvisor, PurchaseAdvice, AllocationAdvice


@pytest.fixture
def db_path():
    """Create a temporary file-based DB with minimal schema for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS business (
          business_id INTEGER PRIMARY KEY,
          public_ref TEXT NOT NULL UNIQUE,
          name_token TEXT NOT NULL,
          sector TEXT NOT NULL,
          country_code TEXT NOT NULL,
          currency_code TEXT NOT NULL,
          timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi',
          registration_type TEXT NOT NULL DEFAULT 'informal',
          employee_count INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'active',
          buffer_minor INTEGER,
          is_synthetic INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        CREATE TABLE IF NOT EXISTS category (
          category_id INTEGER PRIMARY KEY,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          kind TEXT NOT NULL,
          is_business INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS party (
          party_id INTEGER PRIMARY KEY,
          business_id INTEGER NOT NULL REFERENCES business(business_id),
          kind TEXT NOT NULL DEFAULT 'unknown',
          display_token TEXT NOT NULL,
          UNIQUE (business_id, display_token)
        );
        CREATE TABLE IF NOT EXISTS transaction_ledger (
          txn_id INTEGER PRIMARY KEY,
          business_id INTEGER NOT NULL REFERENCES business(business_id),
          category_id INTEGER REFERENCES category(category_id),
          party_id INTEGER REFERENCES party(party_id),
          amount_minor INTEGER NOT NULL,
          direction TEXT NOT NULL,
          local_date TEXT NOT NULL,
          voided INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS recurring_expense (
          expense_id INTEGER PRIMARY KEY,
          business_id INTEGER NOT NULL REFERENCES business(business_id),
          party_id INTEGER REFERENCES party(party_id),
          expense_type TEXT NOT NULL,
          description TEXT NOT NULL,
          amount_minor INTEGER NOT NULL,
          cadence TEXT NOT NULL,
          day_of_month INTEGER,
          next_due TEXT NOT NULL,
          end_date TEXT,
          is_variable INTEGER NOT NULL DEFAULT 0,
          variable_formula TEXT,
          times_paid INTEGER NOT NULL DEFAULT 0,
          times_missed INTEGER NOT NULL DEFAULT 0,
          avg_actual_minor INTEGER,
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        INSERT OR IGNORE INTO category(category_id, code, name, kind, sort_order) VALUES
         (1, 'RENT', 'Rent', 'opex', 10),
         (2, 'SALES_TILL', 'Sales (till)', 'income', 5),
         (3, 'STOCK_PURCHASES', 'Stock purchases', 'cogs', 20),
         (4, 'UTILITIES', 'Utilities', 'opex', 11);
    """)
    conn.commit()
    conn.close()
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def biz_with_balance(db_path):
    """Business with positive balance and transaction history."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code, buffer_minor) "
        "VALUES (1, 'abc123', 'Test Shop', 'grocery', 'KE', 'KES', 500000)"
    )
    # Add inflows: 100,000 KES over last 30 days
    for i in range(30):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO transaction_ledger(business_id, category_id, amount_minor, direction, local_date, voided) "
            "VALUES (1, 2, 400000, 'in', ?, 0)", (date,)
        )
    # Add outflows: 70,000 KES over last 30 days
    for i in range(30):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO transaction_ledger(business_id, category_id, amount_minor, direction, local_date, voided) "
            "VALUES (1, 3, 250000, 'out', ?, 0)", (date,)
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def biz_with_low_balance(db_path):
    """Business with barely positive balance and no transactions."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code, buffer_minor) "
        "VALUES (1, 'low123', 'Low Balance Shop', 'kiosk', 'KE', 'KES', 500000)"
    )
    # Only one small inflow
    conn.execute(
        "INSERT INTO transaction_ledger(business_id, category_id, amount_minor, direction, local_date, voided) "
        "VALUES (1, 2, 300000, 'in', ?, 0)",
        (datetime.now().strftime("%Y-%m-%d"),)
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def biz_with_obligations(db_path):
    """Business with cash and upcoming obligations."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code, buffer_minor) "
        "VALUES (1, 'obl123', 'Obligations Shop', 'grocery', 'KE', 'KES', 500000)"
    )
    # Healthy inflows
    for i in range(30):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO transaction_ledger(business_id, category_id, amount_minor, direction, local_date, voided) "
            "VALUES (1, 2, 500000, 'in', ?, 0)", (date,)
        )
    for i in range(30):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO transaction_ledger(business_id, category_id, amount_minor, direction, local_date, voided) "
            "VALUES (1, 3, 300000, 'out', ?, 0)", (date,)
        )
    # Add upcoming obligations
    today = datetime.now()
    for i in range(5):
        due = (today + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO recurring_expense(expense_id, business_id, expense_type, description, amount_minor, cadence, next_due, active) "
            "VALUES (?, 1, 'rent', 'Rent payment', 1000000, 'monthly', ?, 1)",
            (i + 1, due)
        )
    conn.commit()
    conn.close()
    return db_path


class TestSpendingAdvisorPurchase:
    """Tests for advise_on_purchase()."""

    def test_advise_on_purchase_go(self, biz_with_balance):
        """Sufficient balance + good ROI → GO."""
        advisor = SpendingAdvisor(biz_with_balance)
        # Balance should be ~(30*400000 - 30*250000) = 4,500,000 minor
        # Purchase 500,000 → still well above buffer
        result = advisor.advise_on_purchase(
            business_id=1,
            purchase_amount_minor=500000,  # KES 5,000
            purchase_label="New shelves",
            expected_roi_pct=25.0,
        )

        assert result.verdict == "GO"
        assert result.balance_after_minor > result.buffer_minor
        assert result.confidence > 50

    def test_advise_on_purchase_no_insufficient_balance(self, biz_with_low_balance):
        """Purchase exceeds balance → NO."""
        advisor = SpendingAdvisor(biz_with_low_balance)
        # Balance = 300,000 minor (KES 3,000)
        # Purchase 500,000 → exceeds balance
        result = advisor.advise_on_purchase(
            business_id=1,
            purchase_amount_minor=500000,  # KES 5,000 > KES 3,000 balance
        )

        assert result.verdict == "NO"
        assert any("Insufficient balance" in r for r in result.reasons)

    def test_advise_on_purchase_wait_obligations(self, biz_with_obligations):
        """Upcoming obligations force WAIT on large purchase."""
        advisor = SpendingAdvisor(biz_with_obligations)
        # Obligations: 5 x 1,000,000 = 5,000,000 due in next 14 days
        # Balance: ~(30*500000 - 30*300000) = 6,000,000
        # Large purchase (4,000,000) → after obligations, below buffer
        result = advisor.advise_on_purchase(
            business_id=1,
            purchase_amount_minor=4000000,  # KES 40,000
        )

        assert result.verdict in ("WAIT", "NO")
        assert result.upcoming_obligations_minor > 0
        assert len(result.reasons) > 0

    def test_advise_on_purchase_negative_roi(self, biz_with_balance):
        """Negative ROI flagged."""
        advisor = SpendingAdvisor(biz_with_balance)
        result = advisor.advise_on_purchase(
            business_id=1,
            purchase_amount_minor=100000,
            expected_roi_pct=-15.0,
        )

        assert any("Negative" in r for r in result.reasons)
        assert result.confidence < 90

    def test_advise_on_purchase_confidence_range(self, biz_with_balance):
        """Confidence is always 0-100."""
        advisor = SpendingAdvisor(biz_with_balance)
        result = advisor.advise_on_purchase(
            business_id=1,
            purchase_amount_minor=50000,
        )

        assert 0 <= result.confidence <= 100

    def test_advise_on_purchase_impact_analysis(self, biz_with_balance):
        """Returns balance_after, buffer, and days of cash."""
        advisor = SpendingAdvisor(biz_with_balance)
        result = advisor.advise_on_purchase(
            business_id=1,
            purchase_amount_minor=500000,
        )

        assert result.balance_before_minor > 0
        assert result.balance_after_minor == result.balance_before_minor - 500000
        assert result.buffer_minor > 0
        assert result.days_of_cash_after >= 0

    def test_advise_on_purchase_empty_data(self, db_path):
        """Business with no transactions still returns valid advice."""
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'empty1', 'Empty Shop', 'kiosk', 'KE', 'KES')"
        )
        conn.commit()
        conn.close()

        advisor = SpendingAdvisor(db_path)
        result = advisor.advise_on_purchase(
            business_id=1,
            purchase_amount_minor=100000,
        )

        assert result.verdict == "NO"  # No balance
        assert result.balance_before_minor == 0
        assert result.confidence < 70  # Low confidence due to empty data


class TestSpendingAdvisorAllocate:
    """Tests for allocate_spending()."""

    def test_allocate_spending_normal(self, biz_with_balance):
        """Returns priority-ranked allocation when cash > obligations."""
        advisor = SpendingAdvisor(biz_with_balance)
        result = advisor.allocate_spending(business_id=1)

        assert isinstance(result, AllocationAdvice)
        assert len(result.allocations) > 0
        assert result.allocations[0]["priority"] >= 1
        # Priorities should be sequential
        priorities = [a["priority"] for a in result.allocations]
        assert priorities == sorted(priorities)

    def test_allocate_spending_tight(self, biz_with_low_balance):
        """Warns when obligations exceed available cash."""
        advisor = SpendingAdvisor(biz_with_low_balance)
        result = advisor.allocate_spending(business_id=1)

        if result.total_obligations_minor > result.available_cash_minor:
            assert len(result.warnings) > 0
            assert any("exceed" in w.lower() for w in result.warnings)

    def test_allocate_spending_buffer_gap(self, biz_with_low_balance):
        """Allocates to buffer when below target."""
        advisor = SpendingAdvisor(biz_with_low_balance)
        result = advisor.allocate_spending(business_id=1)

        buffer_alloc = [a for a in result.allocations if "buffer" in a["label"].lower()]
        if result.surplus_minor > 0 and result.surplus_minor < result.buffer_target_minor:
            assert len(buffer_alloc) > 0

    def test_allocate_spending_warnings(self, biz_with_balance):
        """Includes warnings array."""
        advisor = SpendingAdvisor(biz_with_balance)
        result = advisor.allocate_spending(business_id=1)

        assert isinstance(result.warnings, list)

    def test_allocate_spending_empty_data(self, db_path):
        """Empty business still returns valid allocation."""
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'empty2', 'Empty Shop', 'kiosk', 'KE', 'KES')"
        )
        conn.commit()
        conn.close()

        advisor = SpendingAdvisor(db_path)
        result = advisor.allocate_spending(business_id=1)

        assert result.available_cash_minor == 0
        assert isinstance(result.allocations, list)

    def test_allocate_spending_with_custom_cash(self, biz_with_balance):
        """Custom available cash amount is respected."""
        advisor = SpendingAdvisor(biz_with_balance)
        result = advisor.allocate_spending(
            business_id=1,
            available_cash_minor=10000000,  # KES 100,000
        )

        assert result.available_cash_minor == 10000000

    def test_allocate_spending_surplus_computation(self, biz_with_obligations):
        """Surplus = available - obligations."""
        advisor = SpendingAdvisor(biz_with_obligations)
        result = advisor.allocate_spending(business_id=1)

        expected_surplus = result.available_cash_minor - result.total_obligations_minor
        assert result.surplus_minor == expected_surplus


class TestSpendingAdvisorForecast:
    """Tests for forecast integration."""

    def test_get_forecast_summary_has_keys(self, biz_with_balance):
        """Forecast summary returns expected structure."""
        advisor = SpendingAdvisor(biz_with_balance)
        summary = advisor.get_forecast_summary(business_id=1, horizon_days=7)

        assert "opening_balance" in summary
        assert "final_p50" in summary
        assert "final_p10" in summary
        assert "buffer_minor" in summary
        assert "shortfall_days" in summary
        assert "points" in summary

    def test_get_forecast_summary_points_count(self, biz_with_balance):
        """Points array matches horizon_days + 1."""
        advisor = SpendingAdvisor(biz_with_balance)
        horizon = 10
        summary = advisor.get_forecast_summary(business_id=1, horizon_days=horizon)

        assert len(summary["points"]) == horizon + 1

    def test_get_forecast_summary_empty_data(self, db_path):
        """Empty business still returns a valid forecast."""
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'empty3', 'Empty Shop', 'kiosk', 'KE', 'KES')"
        )
        conn.commit()
        conn.close()

        advisor = SpendingAdvisor(db_path)
        summary = advisor.get_forecast_summary(business_id=1, horizon_days=7)

        assert summary["opening_balance"] == 0
        assert len(summary["points"]) == 8  # horizon_days + 1
