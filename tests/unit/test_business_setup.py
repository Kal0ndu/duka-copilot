"""Tests for core/business_setup.py"""
import pytest
import sqlite3
import tempfile
import os
from core.business_setup import BusinessSetup


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
          sub_sector TEXT,
          country_code TEXT NOT NULL,
          currency_code TEXT NOT NULL,
          timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi',
          registration_type TEXT NOT NULL DEFAULT 'informal',
          tax_pin_token TEXT,
          start_date TEXT,
          employee_count INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'active',
          is_synthetic INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
          updated_at TEXT
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
          is_business_related INTEGER,
          first_seen TEXT,
          last_seen TEXT,
          note TEXT,
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
        INSERT OR IGNORE INTO category(category_id, code, name, kind, sort_order) VALUES
         (1, 'RENT', 'Rent', 'opex', 10),
         (2, 'SALES_TILL', 'Sales (till)', 'income', 5),
         (3, 'STOCK_PURCHASES', 'Stock purchases', 'cogs', 20);
    """)
    conn.commit()
    conn.close()
    yield path
    # Cleanup
    try:
        os.unlink(path)
    except OSError:
        pass


class TestBusinessSetup:
    def test_ensure_schema_creates_tables(self, db_path):
        setup = BusinessSetup(db_path)
        setup.ensure_schema()

        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('recurring_expense','financial_goal','business_category_config','chart_of_accounts')"
        ).fetchall()
        conn.close()

        table_names = [t[0] for t in tables]
        assert "recurring_expense" in table_names
        assert "financial_goal" in table_names
        assert "business_category_config" in table_names
        assert "chart_of_accounts" in table_names

    def test_register_business_creates_record(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(
            name="Test Kiosk",
            sector="kiosk",
            country_code="KE",
            employee_count=2,
        )

        assert biz_id > 0

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT name_token, sector, country_code, employee_count FROM business WHERE business_id = ?",
            (biz_id,)
        ).fetchone()
        conn.close()

        assert row[0] == "Test Kiosk"
        assert row[1] == "kiosk"
        assert row[2] == "KE"
        assert row[3] == 2

    def test_register_business_defaults(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="Defaults Co", sector="services")

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT currency_code, timezone, registration_type, status FROM business WHERE business_id = ?",
            (biz_id,)
        ).fetchone()
        conn.close()

        assert row[0] == "KES"
        assert row[1] == "Africa/Nairobi"
        assert row[2] == "informal"
        assert row[3] == "active"

    def test_add_recurring_expense_monthly(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="Rent Tracker", sector="retail")

        exp_id = setup.add_recurring_expense(
            business_id=biz_id,
            expense_type="rent",
            description="Monthly shop rent",
            amount_minor=5000000,
            cadence="monthly",
            day_of_month=1,
            next_due="2026-11-01",
        )

        assert exp_id > 0

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT description, amount_minor, cadence, day_of_month FROM recurring_expense WHERE expense_id = ?",
            (exp_id,)
        ).fetchone()
        conn.close()

        assert row[0] == "Monthly shop rent"
        assert row[1] == 5000000
        assert row[2] == "monthly"
        assert row[3] == 1

    def test_add_recurring_expense_weekly(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="Salary Tracker", sector="salon")

        exp_id = setup.add_recurring_expense(
            business_id=biz_id,
            expense_type="salary",
            description="Weekly staff pay",
            amount_minor=3000000,
            cadence="weekly",
        )

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT cadence, is_variable FROM recurring_expense WHERE expense_id = ?",
            (exp_id,)
        ).fetchone()
        conn.close()

        assert row[0] == "weekly"
        assert row[1] == 0

    def test_add_recurring_expense_variable(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="Variable Co", sector="agri")

        exp_id = setup.add_recurring_expense(
            business_id=biz_id,
            expense_type="utilities",
            description="Electricity bill",
            amount_minor=2000000,
            cadence="monthly",
            is_variable=True,
            variable_formula="avg of last 3 months",
        )

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT is_variable, variable_formula FROM recurring_expense WHERE expense_id = ?",
            (exp_id,)
        ).fetchone()
        conn.close()

        assert row[0] == 1
        assert row[1] == "avg of last 3 months"

    def test_get_recurring_expenses_empty(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="No Expenses", sector="transport")

        expenses = setup.get_recurring_expenses(biz_id)
        assert expenses == []

    def test_get_recurring_expenses_multiple(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="Many Expenses", sector="grocery")

        setup.add_recurring_expense(biz_id, "rent", "Rent", 5000000, "monthly", day_of_month=1)
        setup.add_recurring_expense(biz_id, "salary", "Salary", 3000000, "monthly", day_of_month=25)
        setup.add_recurring_expense(biz_id, "utilities", "Power", 1500000, "monthly", day_of_month=15)

        expenses = setup.get_recurring_expenses(biz_id)
        assert len(expenses) == 3

        descriptions = [e["description"] for e in expenses]
        assert "Rent" in descriptions
        assert "Salary" in descriptions
        assert "Power" in descriptions

    def test_set_financial_goals(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="Goals Co", sector="services")

        goal_ids = setup.set_financial_goals(
            business_id=biz_id,
            revenue_target=100000000,
            margin_target=35,
            buffer_target=20000000,
        )

        assert len(goal_ids) == 3

        goals = setup.get_financial_goals(biz_id)
        assert len(goals) == 3

        goal_types = {g["goal_type"] for g in goals}
        assert "revenue_target" in goal_types
        assert "margin_target" in goal_types
        assert "cash_buffer" in goal_types

    def test_get_financial_goals_empty(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="No Goals", sector="kiosk")

        goals = setup.get_financial_goals(biz_id)
        assert goals == []

    def test_configure_category_upsert(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="Cat Config", sector="grocery")

        config_id = setup.configure_category(
            business_id=biz_id,
            global_category_id=1,
            display_name="Shop Rent",
            monthly_budget_minor=5000000,
            auto_categorize_keywords="rent,landlord,premises",
        )

        assert config_id > 0

        configs = setup.get_category_configs(biz_id)
        assert len(configs) == 1
        assert configs[0]["display_name"] == "Shop Rent"
        assert configs[0]["monthly_budget_minor"] == 5000000

        config_id2 = setup.configure_category(
            business_id=biz_id,
            global_category_id=1,
            display_name="Updated Rent",
        )

        configs = setup.get_category_configs(biz_id)
        assert len(configs) == 1
        assert configs[0]["display_name"] == "Updated Rent"

    def test_get_business_profile_exists(self, db_path):
        setup = BusinessSetup(db_path)
        biz_id = setup.register_business(name="Profile Co", sector="restaurant", employee_count=5)

        profile = setup.get_business_profile(biz_id)
        assert profile is not None
        assert profile.name_token == "Profile Co"
        assert profile.sector == "restaurant"
        assert profile.employee_count == 5

    def test_get_business_profile_not_found(self, db_path):
        setup = BusinessSetup(db_path)
        profile = setup.get_business_profile(99999)
        assert profile is None
