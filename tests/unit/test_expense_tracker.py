"""Tests for core/expense_tracker.py"""
import pytest
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta
from core.expense_tracker import ExpenseTracker, RecurringExpenseManager


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
        CREATE TABLE IF NOT EXISTS business_category_config (
          config_id INTEGER PRIMARY KEY,
          business_id INTEGER NOT NULL REFERENCES business(business_id),
          global_category_id INTEGER NOT NULL REFERENCES category(category_id),
          display_name TEXT,
          is_tracking_active INTEGER NOT NULL DEFAULT 1,
          monthly_budget_minor INTEGER,
          alert_threshold_pct INTEGER NOT NULL DEFAULT 80,
          auto_categorize_keywords TEXT,
          UNIQUE (business_id, global_category_id)
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
        CREATE TABLE IF NOT EXISTS recurring_expense_instance (
          instance_id INTEGER PRIMARY KEY,
          expense_id INTEGER NOT NULL REFERENCES recurring_expense(expense_id),
          due_date TEXT NOT NULL,
          expected_amount_minor INTEGER NOT NULL,
          matched_txn_id INTEGER REFERENCES transaction_ledger(txn_id),
          actual_amount_minor INTEGER,
          status TEXT NOT NULL DEFAULT 'expected',
          paid_date TEXT,
          notes TEXT,
          UNIQUE (expense_id, due_date)
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
def biz_with_data(db_path):
    """Create a business with transaction history for pattern detection."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute(
        "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
        "VALUES (1, 'abc123', 'Test Shop', 'grocery', 'KE', 'KES')"
    )
    conn.execute(
        "INSERT INTO party(party_id, business_id, kind, display_token) "
        "VALUES (1, 1, 'landlord', 'Landlord Ltd')"
    )

    # Create 12 monthly payments all on day 1, going backward
    for i in range(12):
        month = 10 - i
        year = 2026
        if month <= 0:
            month += 12
            year = 2025
        date_str = f"{year}-{month:02d}-01"
        conn.execute(
            "INSERT INTO transaction_ledger(business_id, category_id, party_id, amount_minor, direction, local_date) "
            "VALUES (1, 1, 1, 5000000, 'out', ?)", (date_str,)
        )

    conn.commit()
    conn.close()
    return db_path


class TestExpenseTracker:
    def test_detect_recurring_empty_history(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'abc', 'Empty Shop', 'kiosk', 'KE', 'KES')"
        )
        conn.commit()
        conn.close()

        tracker = ExpenseTracker(db_path)
        patterns = tracker.detect_recurring_expenses(1)
        assert patterns == []

    def test_detect_recurring_monthly_pattern(self, biz_with_data):
        tracker = ExpenseTracker(biz_with_data)
        patterns = tracker.detect_recurring_expenses(1)

        assert len(patterns) >= 1
        pattern = patterns[0]
        assert pattern["amount_minor"] == 5000000
        assert pattern["cadence"] == "monthly"
        assert pattern["frequency"] == 12
        assert pattern["confidence"] == 100

    def test_detect_recurring_confidence_scaling(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'def', 'Few Txns', 'salon', 'KE', 'KES')"
        )
        conn.execute(
            "INSERT INTO party(party_id, business_id, kind, display_token) "
            "VALUES (1, 1, 'utility', 'KPLC')"
        )

        # Create 3 monthly payments all on day 15
        for i in range(3):
            month = 10 - i
            year = 2026
            if month <= 0:
                month += 12
                year = 2025
            date_str = f"{year}-{month:02d}-15"
            conn.execute(
                "INSERT INTO transaction_ledger(business_id, category_id, party_id, amount_minor, direction, local_date) "
                "VALUES (1, 4, 1, 2000000, 'out', ?)", (date_str,)
            )
        conn.commit()
        conn.close()

        tracker = ExpenseTracker(db_path)
        patterns = tracker.detect_recurring_expenses(1)

        assert len(patterns) >= 1
        assert patterns[0]["frequency"] == 3
        assert patterns[0]["confidence"] == 30

    def test_auto_categorize_keyword_match(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'ghi', 'Keyword Shop', 'grocery', 'KE', 'KES')"
        )
        conn.execute(
            "INSERT INTO business_category_config(business_id, global_category_id, auto_categorize_keywords) "
            "VALUES (1, 3, 'stock,supplier,wholesale')"
        )
        conn.commit()
        conn.close()

        tracker = ExpenseTracker(db_path)
        cat_id = tracker.auto_categorize_expense(1, "stock purchase from supplier", 5000000)
        assert cat_id == 3

    def test_auto_categorize_no_match(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'jkl', 'No Match Shop', 'retail', 'KE', 'KES')"
        )
        conn.commit()
        conn.close()

        tracker = ExpenseTracker(db_path)
        cat_id = tracker.auto_categorize_expense(1, "blargle flump zanzibar", 10000)
        assert cat_id is None

    def test_categorize_batch_mixed(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'mno', 'Batch Shop', 'grocery', 'KE', 'KES')"
        )
        conn.execute(
            "INSERT INTO business_category_config(business_id, global_category_id, auto_categorize_keywords) "
            "VALUES (1, 3, 'stock')"
        )
        conn.commit()
        conn.close()

        tracker = ExpenseTracker(db_path)
        txns = [
            {"description": "stock purchase", "amount_minor": 500000, "channel": "send"},
            {"description": "random thing", "amount_minor": 10000, "channel": "other"},
        ]

        results = tracker.categorize_batch(1, txns)
        assert len(results) == 2
        assert results[0]["auto_category_id"] == 3
        assert results[0]["needs_review"] is False
        assert results[1]["auto_category_id"] is None
        assert results[1]["needs_review"] is True

    def test_categorize_batch_empty(self, db_path):
        tracker = ExpenseTracker(db_path)
        results = tracker.categorize_batch(1, [])
        assert results == []


class TestRecurringExpenseManager:
    def test_add_recurring_expense_returns_id(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'pqr', 'Manager Shop', 'restaurant', 'KE', 'KES')"
        )
        conn.commit()
        conn.close()

        manager = RecurringExpenseManager(db_path)
        exp_id = manager.add_recurring_expense(1, {
            "expense_type": "rent",
            "description": "Restaurant rent",
            "amount_minor": 8000000,
            "cadence": "monthly",
            "day_of_month": 5,
            "next_due": "2026-11-05",
        })

        assert exp_id > 0

    def test_generate_schedule_monthly_12_months(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'stu', 'Schedule Shop', 'grocery', 'KE', 'KES')"
        )
        conn.execute(
            "INSERT INTO recurring_expense(expense_id, business_id, expense_type, description, amount_minor, cadence, day_of_month, next_due) "
            "VALUES (1, 1, 'rent', 'Monthly rent', 5000000, 'monthly', 1, '2026-11-01')"
        )
        conn.commit()
        conn.close()

        manager = RecurringExpenseManager(db_path)
        schedule = manager.generate_schedule(1, months_ahead=12)

        assert len(schedule) == 12
        assert schedule[0]["amount_minor"] == 5000000
        assert schedule[0]["due_date"] == "2026-11-01"

    def test_generate_schedule_weekly(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'vwx', 'Weekly Shop', 'salon', 'KE', 'KES')"
        )
        conn.execute(
            "INSERT INTO recurring_expense(expense_id, business_id, expense_type, description, amount_minor, cadence, next_due) "
            "VALUES (1, 1, 'salary', 'Weekly pay', 3000000, 'weekly', '2026-11-01')"
        )
        conn.commit()
        conn.close()

        manager = RecurringExpenseManager(db_path)
        schedule = manager.generate_schedule(1, months_ahead=3)

        assert len(schedule) == 12
        for s in schedule:
            assert s["amount_minor"] == 3000000

    def test_generate_schedule_respects_end_date(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'yza', 'EndDate Shop', 'services', 'KE', 'KES')"
        )
        conn.execute(
            "INSERT INTO recurring_expense(expense_id, business_id, expense_type, description, amount_minor, cadence, day_of_month, next_due, end_date) "
            "VALUES (1, 1, 'insurance', 'Annual insurance', 12000000, 'monthly', 15, '2026-11-15', '2027-01-15')"
        )
        conn.commit()
        conn.close()

        manager = RecurringExpenseManager(db_path)
        schedule = manager.generate_schedule(1, months_ahead=12)

        assert len(schedule) == 3
        assert schedule[-1]["due_date"] == "2027-01-15"

    def test_check_obligation_compliance_all_paid(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'bcd', 'Compliant Shop', 'grocery', 'KE', 'KES')"
        )
        conn.execute(
            "INSERT INTO recurring_expense(expense_id, business_id, expense_type, description, amount_minor, cadence, next_due) "
            "VALUES (1, 1, 'rent', 'Rent', 5000000, 'monthly', '2026-10-01')"
        )
        for i in range(3):
            conn.execute(
                "INSERT INTO recurring_expense_instance(expense_id, due_date, expected_amount_minor, status) "
                "VALUES (1, ?, 5000000, 'paid')",
                ((datetime.now() - timedelta(days=30 * i)).strftime("%Y-%m-%d"),)
            )
        conn.commit()
        conn.close()

        manager = RecurringExpenseManager(db_path)
        result = manager.check_obligation_compliance(1)

        assert result["overall_rate"] == 100.0
        assert result["obligations"][0]["compliance_rate"] == 100.0

    def test_check_obligation_compliance_mixed(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'efg', 'Mixed Shop', 'kiosk', 'KE', 'KES')"
        )
        conn.execute(
            "INSERT INTO recurring_expense(expense_id, business_id, expense_type, description, amount_minor, cadence, next_due) "
            "VALUES (1, 1, 'utilities', 'Power', 1500000, 'monthly', '2026-10-01')"
        )
        for i, status in enumerate(["paid", "paid", "late", "missed"]):
            conn.execute(
                "INSERT INTO recurring_expense_instance(expense_id, due_date, expected_amount_minor, status) "
                "VALUES (1, ?, 1500000, ?)",
                ((datetime.now() - timedelta(days=30 * i)).strftime("%Y-%m-%d"), status)
            )
        conn.commit()
        conn.close()

        manager = RecurringExpenseManager(db_path)
        result = manager.check_obligation_compliance(1)

        assert result["overall_rate"] == 50.0
        obl = result["obligations"][0]
        assert obl["paid_on_time"] == 2
        assert obl["paid_late"] == 1
        assert obl["missed"] == 1

    def test_check_obligation_compliance_empty(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'hij', 'Empty Shop', 'transport', 'KE', 'KES')"
        )
        conn.commit()
        conn.close()

        manager = RecurringExpenseManager(db_path)
        result = manager.check_obligation_compliance(1)

        assert result["overall_rate"] == 0
        assert result["obligations"] == []

    def test_get_upcoming_obligations(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO business(business_id, public_ref, name_token, sector, country_code, currency_code) "
            "VALUES (1, 'klm', 'Upcoming Shop', 'grocery', 'KE', 'KES')"
        )
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO recurring_expense(expense_id, business_id, expense_type, description, amount_minor, cadence, next_due) "
            "VALUES (1, 1, 'rent', 'Rent due tomorrow', 5000000, 'monthly', ?)", (tomorrow,)
        )
        conn.commit()
        conn.close()

        manager = RecurringExpenseManager(db_path)
        upcoming = manager.get_upcoming_obligations(1, days_ahead=7)

        assert len(upcoming) == 1
        assert upcoming[0]["description"] == "Rent due tomorrow"
        assert upcoming[0]["amount_minor"] == 5000000
