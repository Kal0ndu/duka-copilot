"""Business 6 (Msafiri / "myplan") test dataset, run through the real app code.

Every expected value comes from tests/test_data/msafiri/ (answer keys written
by generate.py from the scenario design, not by running Duka). A failure here
means the app and the specification disagree.

The dataset's dates end 2026-10-17. Checks that depend on today's date pass
an explicit date (2026-10-19) instead of the clock.
"""
from __future__ import annotations

import contextlib
import csv
import filecmp
import io
import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "tests" / "test_data" / "msafiri"
SUMMARY = json.loads((DATA / "expected_summary.json").read_text())
AS_OF = date.fromisoformat(SUMMARY["obligations_as_of"])
IMPORT_TODAY = datetime(2026, 10, 19, 12, 0)


@dataclass
class World:
    db: str
    business_id: int
    user_id: int
    combined_report: object


def _build(tmp: Path) -> World:
    from core import csv_import
    from core.business_setup import BusinessSetup
    from core.ingestion import StatementIngestor
    from db.migrate import MigrationRunner

    db = str(tmp / "duka.db")
    with contextlib.redirect_stdout(io.StringIO()):
        MigrationRunner(db).run_pending()
    with sqlite3.connect(db) as conn:
        uid = int(conn.execute(
            "INSERT INTO app_user (phone_hash, display_name, display_token) VALUES ('hash-msafiri', 'msafiri', 'TOK')"
        ).lastrowid or 0)
    biz = BusinessSetup(db).register_business("myplan", "services", sub_sector="internet provider",
                                              employee_count=3, owner_user_id=uid)
    report = StatementIngestor(db).ingest((DATA / "statement_combined.csv").read_bytes(),
                                          "statement_combined.csv", biz, uid)
    csv_import.import_products((DATA / "products.csv").read_bytes(), biz, db)
    csv_import.import_customers((DATA / "customers.csv").read_bytes(), biz, db)
    csv_import.import_sales((DATA / "sales.csv").read_bytes(), biz, db, today=IMPORT_TODAY)
    return World(db, biz, uid, report)


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    return _build(tmp_path_factory.mktemp("msafiri"))


@pytest.fixture
def scratch(world, tmp_path) -> World:
    """A private copy of the world for tests that change data."""
    db = str(tmp_path / "duka.db")
    shutil.copy(world.db, db)
    return World(db, world.business_id, world.user_id, world.combined_report)


def _key(file: str):
    return [r for r in csv.DictReader((DATA / "expected_statement_rows.csv").open()) if r["file"] == file]


def _kpis(w: World) -> dict:
    from core.analytics import BusinessAnalytics
    from core.statement_store import load_ledger_records
    return BusinessAnalytics(load_ledger_records(w.db, w.business_id)).kpi_summary()


def _assert_pnl(kpi: dict, exp: dict):
    assert round(kpi["total_revenue"] * 100) == exp["revenue"]
    assert round(kpi["cogs"] * 100) == exp["cogs"]
    assert round(kpi["opex"] * 100) == exp["opex_incl_tax"]
    assert round(kpi["financing_cost"] * 100) == exp["financing_out"]
    assert round(kpi["personal_outflow"] * 100) == exp["personal_out"]
    assert round(kpi["total_costs"] * 100) == exp["total_costs_kpi"]
    assert round(kpi["net_profit"] * 100) == exp["net_profit_kpi"]
    assert round(kpi["operating_cashflow"] * 100) == exp["operating_cashflow"]
    assert kpi["personal_mix_bp"] == exp["personal_mix_bp"]
    assert kpi["gross_margin_pct"] == exp["gross_margin_pct"]
    assert kpi["operating_margin_pct"] == exp["operating_margin_pct"]


# ---- the dataset itself ----

def test_dataset_regenerates_byte_for_byte(tmp_path):
    subprocess.run([sys.executable, str(DATA / "generate.py"), str(tmp_path)], check=True, capture_output=True)
    files = sorted(p.name for p in DATA.iterdir() if p.suffix in (".csv", ".json"))
    _, mismatch, errors = filecmp.cmpfiles(DATA, tmp_path, files, shallow=False)
    assert not mismatch and not errors, f"regenerated files differ: {mismatch or errors}"


# ---- statements ----

def test_combined_statement_ingest_report(world):
    exp = SUMMARY["statement_combined"]
    r = world.combined_report
    assert (r.status, r.rows_read, r.rows_loaded, r.rows_duplicate, r.rows_flagged) == (
        "loaded", exp["rows"], exp["rows"], 0, 0)
    assert r.rows_needs_review == SUMMARY["expected_needs_review_combined"]
    assert (r.period_start, r.period_end) == tuple(SUMMARY["period"])
    assert r.validation_issues == []   # running balance reconciles on every row


def test_every_receipt_is_categorised_as_specified(world):
    with sqlite3.connect(world.db) as conn:
        got = {ref: (code, review, amount, direction) for ref, code, review, amount, direction in conn.execute(
            """SELECT t.reference, c.code, t.needs_review, t.amount_minor, t.direction
               FROM transaction_ledger t JOIN category c USING (category_id) WHERE t.business_id = ?""",
            (world.business_id,))}
    wrong = []
    for row in _key("statement_combined.csv"):
        code, review, amount, direction = got[row["receipt"]]
        want = (row["expected_app_category"], int(row["expected_needs_review"]),
                round(float(row["amount_kes"]) * 100), row["direction"])
        if (code, review, amount, direction) != want:
            wrong.append((row["receipt"], row["scenario"], (code, review, amount, direction), want))
    assert not wrong, f"{len(wrong)} receipt(s) differ, e.g. {wrong[:5]}"


@pytest.mark.parametrize("name", ["statement_income.csv", "statement_expenses.csv"])
def test_partial_statements_of_the_same_wallet_are_duplicates(scratch, name):
    from core.ingestion import StatementIngestor
    expected_rows = SUMMARY[name.replace(".csv", "")]["rows"]
    r = StatementIngestor(scratch.db).ingest((DATA / name).read_bytes(), name, scratch.business_id, scratch.user_id)
    assert (r.rows_read, r.rows_loaded, r.rows_duplicate) == (expected_rows, 0, expected_rows)


def test_reuploading_the_same_file_is_refused(scratch):
    from core.ingestion import StatementIngestor
    r = StatementIngestor(scratch.db).ingest((DATA / "statement_combined.csv").read_bytes(), "again.csv",
                                             scratch.business_id, scratch.user_id)
    assert r.status == "duplicate"


def test_statement_edge_cases(scratch):
    from core.ingestion import StatementIngestor
    exp = SUMMARY["statement_edge_cases"]
    r = StatementIngestor(scratch.db).ingest((DATA / "statement_edge_cases.csv").read_bytes(),
                                             "statement_edge_cases.csv", scratch.business_id, scratch.user_id)
    assert (r.rows_read, r.rows_loaded, r.rows_duplicate, r.rows_flagged) == (
        exp["rows_parsed"], exp["rows_loaded"], exp["rows_duplicate"], exp["rows_flagged"])
    assert "Statement contains duplicate receipt numbers." in r.validation_issues
    with sqlite3.connect(scratch.db) as conn:
        got = {ref: (ts, amt, d, code, review, desc) for ref, ts, amt, d, code, review, desc in conn.execute(
            """SELECT t.reference, t.ts, t.amount_minor, t.direction, c.code, t.needs_review, t.description_redacted
               FROM transaction_ledger t JOIN category c USING (category_id) WHERE t.file_id = ?""", (r.file_id,))}
    for row in _key("statement_edge_cases.csv"):
        if row["expected_ingest"] == "skip":
            assert row["receipt"] not in got, row["scenario"]
            continue
        if row["expected_ingest"] == "duplicate":
            continue
        _, amt, _, code, review, desc = got[row["receipt"]]
        assert (code, review) == (row["expected_app_category"], int(row["expected_needs_review"])), row["scenario"]
        assert amt == round(float(row["amount_kes"].replace(",", "")) * 100), row["scenario"]
        if row["expected_ingest"] == "load_flagged":
            assert desc == "[flagged content removed]"
    # timestamps that are easy to get wrong
    assert got["EDG0000003"][0] == "2026-10-03 09:00:00"     # 03/10/2026 is 3 October
    assert got["EDG0000004"][0] == "2026-10-10 20:32:00"     # 08:32 PM
    assert got["EDG0000021"][2] == "in"                      # Paid In wins over Withdrawn


def test_malformed_statement_is_rejected(scratch):
    from core.ingestion import StatementIngestor
    with pytest.raises(ValueError, match="Unrecognized CSV format"):
        StatementIngestor(scratch.db).ingest((DATA / "statement_malformed.csv").read_bytes(), "bad.csv",
                                             scratch.business_id, scratch.user_id)


# ---- analytics, teaching, party intelligence ----

def test_analytics_kpis_before_teaching(world):
    kpi = _kpis(world)
    _assert_pnl(kpi, SUMMARY["expected_app_pnl_minor_before_teaching"])
    assert kpi["txn_count"] == SUMMARY["statement_combined"]["rows"]


def test_teaching_payees_gives_the_true_pnl(scratch):
    """Owner teaches the salary payees (Wages) and the customer refund (Other
    opex) once; the analytics then match the intended economics."""
    from core.categoriser import teach_category
    teach = {r["party"]: r["intended_category"] for r in _key("statement_combined.csv")
             if r["expected_app_category"] != r["intended_category"] and r["party"]}
    with sqlite3.connect(scratch.db) as conn:
        for party, category in teach.items():
            txn_id = conn.execute(
                """SELECT MIN(t.txn_id) FROM transaction_ledger t JOIN token_vault v
                     ON v.token = t.counterparty_token AND v.business_id = t.business_id
                   WHERE t.business_id = ? AND v.original_value = ? AND t.direction = 'out'""",
                (scratch.business_id, party)).fetchone()[0]
            teach_category(scratch.db, scratch.business_id, txn_id, category)
        # The refund to Baraka Hotel must not relabel Baraka's payments to us.
        baraka_in = conn.execute(
            """SELECT DISTINCT c.code FROM transaction_ledger t JOIN category c USING (category_id)
               JOIN token_vault v ON v.token = t.counterparty_token AND v.business_id = t.business_id
               WHERE v.original_value = 'BARAKA HOTEL' AND t.direction = 'in'""").fetchall()
    assert baraka_in == [("SALES_TRANSFER",)]
    _assert_pnl(_kpis(scratch), SUMMARY["intended_pnl_minor"])


def test_party_intelligence(world):
    from core.relationship_analyzer import RelationshipAnalyzer
    from core.statement_store import load_ledger_records
    exp = SUMMARY["party_intelligence"]
    analyzer = RelationshipAnalyzer(load_ledger_records(world.db, world.business_id))
    customers = analyzer.get_customers()
    assert len(customers) == exp["customers"]
    risks = analyzer.get_concentration_risks()
    assert [c.party_name for c in risks if c.party_type == "customer"] == exp["concentration_risks"]
    assert sorted(c.party_name for c in risks if c.party_type == "supplier") == exp["supplier_dependencies"]
    churn = analyzer.get_churn_risks()
    assert len(churn) == exp["churn_watchlist"]
    assert set(exp["churned_by_design"]) <= {c.party_name for c in churn}
    for want, got in zip(exp["top_10"], customers[:10]):
        assert (got.party_name, round(got.inflow_kes * 100), got.transaction_count, got.concentration_pct,
                got.is_concentration_risk, got.days_since_interaction, got.churn_risk_score, got.segment) == (
            want["customer"], want["inflow_minor"], want["orders"], want["concentration_pct"],
            want["concentration_risk"], want["days_since"], want["churn_risk"], want["segment"])


# ---- regular payments ----

def test_detected_obligations(scratch):
    from core.ingestion import StatementIngestor
    with sqlite3.connect(scratch.db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("DELETE FROM obligation WHERE business_id = ?", (scratch.business_id,))
        StatementIngestor(scratch.db).detect_obligations(conn, scratch.business_id, today=AS_OF)
        got = sorted(tuple(r) for r in conn.execute(
            """SELECT v.original_value, o.label, o.kind, o.amount_minor, o.cadence, o.day_of_month, o.next_due, o.essential
               FROM obligation o JOIN party p USING (party_id)
               JOIN token_vault v ON v.token = p.display_token AND v.business_id = p.business_id
               WHERE o.business_id = ?""", (scratch.business_id,)))
    want = sorted((o["payee"], o["label"], o["kind"], o["amount_minor"], o["cadence"], o["day_of_month"],
                   o["next_due"], o["essential"]) for o in SUMMARY["expected_obligations"])
    assert got == want


def test_auto_detected_recurring_expenses(world):
    from core.expense_tracker import ExpenseTracker
    got = [(p["payee"], p["category_code"], p["amount_minor"], p["is_variable"], p["cadence"], p["interval_count"],
            p["day_of_month"] if p["fixed_day"] else None, p["frequency"], p["last_paid_date"], p["next_due"],
            p["confidence"]) for p in ExpenseTracker(world.db).detect_recurring_expenses(world.business_id)]
    want = [(p["payee"], p["category"], p["amount_minor"], p["is_variable"], p["cadence"], p["interval"],
             p["fixed_day"], p["payments_seen"], p["last_paid"], p["next_due"], p["confidence"])
            for p in SUMMARY["expected_recurring_patterns"]]
    assert got == want


# ---- invoicing imports ----

def test_imports_load_everything(world):
    exp = SUMMARY["sales_import"]
    with sqlite3.connect(world.db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM product WHERE business_id = ?", (world.business_id,)).fetchone()[0] \
            == SUMMARY["products_import"]["created"]
        assert conn.execute(
            "SELECT COUNT(*) FROM party_identifier pi JOIN party p USING (party_id) WHERE p.business_id = ? "
            "AND pi.id_type = 'phone_hash'", (world.business_id,)).fetchone()[0] == SUMMARY["customers_import"]["created"]
        count, sub, vat, total = conn.execute(
            "SELECT COUNT(*), SUM(subtotal_minor), SUM(vat_amount_minor), SUM(total_amount_minor) FROM sale "
            "WHERE business_id = ?", (world.business_id,)).fetchone()
        assert (count, sub, vat, total) == (exp["sales"], exp["subtotal_minor"], exp["vat_minor"], exp["total_minor"])
        by_method = {m: (n, t) for m, n, t in conn.execute(
            "SELECT payment_method, COUNT(*), SUM(total_amount_minor) FROM sale WHERE business_id = ? "
            "GROUP BY payment_method", (world.business_id,))}
        assert by_method == {m: (v["count"], v["total_minor"]) for m, v in exp["by_payment_method"].items()}
        # credit sales are owed, not paid
        assert conn.execute("SELECT DISTINCT payment_status, amount_paid_minor FROM sale WHERE business_id = ? "
                            "AND payment_method = 'credit'", (world.business_id,)).fetchall() == [("pending", 0)]
        stock = dict(conn.execute("SELECT sku, current_stock_qty FROM product WHERE business_id = ?",
                                  (world.business_id,)))
    assert stock == exp["stock_after_import"]
    from core.inventory_manager import InventoryManager
    alerts = sorted(p.sku for p in InventoryManager(world.db).get_reorder_alerts(world.business_id))
    assert alerts == exp["reorder_alerts_after_import"]


def test_monthly_sales_vat_report(world):
    from core.tax_manager import TaxManager
    tax = TaxManager(world.db)
    for month, exp in SUMMARY["sales_import"]["by_month"].items():
        y, m = map(int, month.split("-"))
        assert tax.get_vat_report(world.business_id, y, m)["sales_vat_collected_minor"] == exp["vat_minor"], month


def test_reimporting_adds_nothing(scratch):
    from core import csv_import
    r = csv_import.import_sales((DATA / "sales.csv").read_bytes(), scratch.business_id, scratch.db, today=IMPORT_TODAY)
    assert (r.created, r.skipped, r.errors) == (0, SUMMARY["sales_import"]["sales"], [])
    r = csv_import.import_products((DATA / "products.csv").read_bytes(), scratch.business_id, scratch.db)
    assert (r.created, r.updated) == (0, SUMMARY["products_import"]["rows"])
    r = csv_import.import_customers((DATA / "customers.csv").read_bytes(), scratch.business_id, scratch.db)
    assert (r.created, r.updated) == (0, SUMMARY["customers_import"]["rows"])


@pytest.mark.parametrize("name", ["products_edge_cases.csv", "customers_edge_cases.csv", "sales_edge_cases.csv"])
def test_edge_case_imports(scratch, name):
    from core import csv_import
    importer = {"products": csv_import.import_products, "customers": csv_import.import_customers,
                "sales": csv_import.import_sales}[name.split("_")[0]]
    kwargs = {"today": IMPORT_TODAY} if name.startswith("sales") else {}
    report = importer((DATA / name).read_bytes(), scratch.business_id, scratch.db, **kwargs)
    errors = dict(report.errors)
    for row in csv.DictReader((DATA / "expected_import_errors.csv").open()):
        if row["file"] != name or row["expected_outcome"] == "(same sale as above)":
            continue
        line, want = int(row["line"]), row["expected_outcome"]
        if want in ("created", "updated"):
            assert line not in errors, (line, errors.get(line))
        else:
            assert want.lower() in errors.get(line, "").lower(), (line, want, errors.get(line))
    exp = SUMMARY["edge_imports"][name]
    assert report.created == exp["created"]
    if "updated" in exp:
        assert report.updated == exp["updated"]


# ---- determinism ----

def _fingerprint(w: World) -> dict:
    with sqlite3.connect(w.db) as conn:
        ledger = conn.execute(
            """SELECT reference, ts, amount_minor, direction, channel, category_id, needs_review, confidence,
                      description_redacted, counterparty_token
               FROM transaction_ledger WHERE business_id = ? ORDER BY reference""", (w.business_id,)).fetchall()
        sales = conn.execute(
            """SELECT sale_number, sale_date, subtotal_minor, vat_amount_minor, total_amount_minor, payment_status
               FROM sale WHERE business_id = ? ORDER BY sale_number""", (w.business_id,)).fetchall()
        stock = conn.execute("SELECT sku, current_stock_qty FROM product WHERE business_id = ? ORDER BY sku",
                             (w.business_id,)).fetchall()
    kpi = _kpis(w)
    return {"ledger": ledger, "sales": sales, "stock": stock,
            "kpi": {k: v for k, v in kpi.items() if k not in ("best_day", "worst_day")} | {
                "best_day": kpi["best_day"], "worst_day": kpi["worst_day"]}}


def test_same_input_gives_same_output(world, tmp_path):
    """Build the whole world again from scratch: every stored value and every
    KPI must be identical (the system is deterministic for this input)."""
    again = _build(tmp_path)
    a, b = _fingerprint(world), _fingerprint(again)
    for part in a:
        assert a[part] == b[part], f"{part} differs between two identical runs"
