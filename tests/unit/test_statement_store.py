"""Uploaded statements stay saved with the business, and auto-detect finds
recurring expenses in them."""
import sqlite3

import pytest

from core.business_setup import BusinessSetup
from core.expense_tracker import ExpenseTracker
from core.statement_store import ledger_version, list_statements, load_ledger_records, remove_statement
from tests.fixtures_duka import DATA, build_world


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path)


def test_statement_is_listed_and_loaded_from_the_database(world):
    files = list_statements(world.db, world.amina)
    assert [f["filename"] for f in files] == ["amina_grocery_statement.csv"]
    assert files[0]["active_rows"] > 1000 and files[0]["period_end"] == "2026-10-15"

    # A brand-new "session" reads the same records straight from the DB.
    records = load_ledger_records(world.db, world.amina)
    assert len(records) == files[0]["active_rows"]
    r = records[0]
    assert r["date"] == "2026-10-15" and r["direction"] in ("in", "out")
    assert r["amount"] == (r["amount_minor"] / 100 if r["direction"] == "in" else -r["amount_minor"] / 100)
    assert {"category", "category_kind", "counterparty", "channel", "balance"} <= set(r)


def test_statements_are_per_business(world):
    assert all(f["filename"] == "grace_salon_statement.csv" for f in list_statements(world.db, world.other))
    amina_ids = {r["txn_id"] for r in load_ledger_records(world.db, world.amina)}
    assert amina_ids.isdisjoint(r["txn_id"] for r in load_ledger_records(world.db, world.other))


def test_analytics_on_saved_ledger(world):
    from core.analytics import BusinessAnalytics
    kpi = BusinessAnalytics(load_ledger_records(world.db, world.amina)).kpi_summary()
    assert kpi["total_revenue"] > 0 and kpi["txn_count"] > 1000


def test_remove_and_upload_again(world):
    from core.ingestion import StatementIngestor
    v0 = ledger_version(world.db, world.amina)
    n = remove_statement(world.db, world.amina, world.file_id)
    assert n > 1000 and load_ledger_records(world.db, world.amina) == []
    assert ledger_version(world.db, world.amina) != v0
    with pytest.raises(LookupError):
        remove_statement(world.db, world.other, world.file_id)   # not Grace's statement

    raw = (DATA / "amina_grocery_statement.csv").read_bytes()
    report = StatementIngestor(world.db).ingest(raw, "amina_grocery_statement.csv", world.amina, world.amina_user)
    assert report.status != "duplicate" and len(load_ledger_records(world.db, world.amina)) == n


def test_auto_detect_scans_the_saved_statement(world):
    found = {p["payee"]: p for p in ExpenseTracker(world.db).detect_recurring_expenses(world.amina)}
    rent = found["MWANGI PROPERTIES"]
    assert (rent["cadence"], rent["interval_count"], rent["amount_minor"], rent["is_variable"]) == \
        ("monthly", 1, 1_500_000, False)
    assert (rent["last_paid_date"], rent["next_due"], rent["suggested_type"]) == \
        ("2026-10-05", "2026-11-05", "rent")
    stock = found["UNGA DISTRIBUTORS LTD"]
    assert stock["is_variable"] and stock["frequency_label"] == "Weekly"
    # Overdraft repayments and fees are not bills.
    assert not any("overdraft" in (p["payee"] or "").lower() for p in found.values())


def test_scan_one_statement_and_mark_tracked(world):
    tracker = ExpenseTracker(world.db)
    only_this = tracker.detect_recurring_expenses(world.amina, file_id=world.file_id)
    assert only_this and tracker.detect_recurring_expenses(world.amina, file_id=999) == []

    rent = next(p for p in only_this if p["payee"] == "MWANGI PROPERTIES")
    BusinessSetup(world.db).add_recurring_expense(
        world.amina, rent["suggested_type"], "Shop rent", rent["amount_minor"], rent["cadence"],
        party_id=rent["party_id"], last_paid_date=rent["last_paid_date"])
    again = next(p for p in tracker.detect_recurring_expenses(world.amina) if p["payee"] == "MWANGI PROPERTIES")
    assert again["already_tracked"]
    e = BusinessSetup(world.db).get_recurring_expenses(world.amina)[0]
    assert (e["last_paid_date"], e["next_due"]) == ("2026-10-05", "2026-11-05")
