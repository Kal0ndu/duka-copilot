"""Populate a SQLite database with deterministic synthetic Duka data.

The generator uses the complete schema in ``db/schema.sql`` and creates a
small, relationally consistent dataset suitable for local demos and tests.
Money is stored as KES minor units, matching the schema contract.

Examples:
    python data/generate_synthetic.py --db data/synthetic.db --businesses 3
    python data/generate_synthetic.py --db data/synthetic.db --days 180 --seed 7
    python data/generate_synthetic.py --db data/synthetic.db --reset
"""

import argparse
import csv
import hashlib
import json
import random
import sqlite3
import string
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
GENERATOR_VERSION = "2.0.0"
DEFAULT_START = date(2026, 1, 1)

PROFILES = [
    {"name": "Amina Grocery", "sector": "grocery", "sub_sector": "grocery_kiosk", "daily_sales": (1800, 8500), "expenses": {"STOCK_PURCHASES": (700, 3500), "TRANSPORT": (100, 500), "UTILITIES": (1000, 2500)}, "customers": ["WALK-IN CUSTOMER", "NEIGHBOURHOOD CUSTOMER"]},
    {"name": "Grace Salon", "sector": "salon", "sub_sector": "beauty_services", "daily_sales": (1200, 6500), "expenses": {"STOCK_PURCHASES": (300, 1800), "UTILITIES": (500, 1800), "TRANSPORT": (80, 400)}, "customers": ["SALON CUSTOMER", "WALK-IN CUSTOMER"]},
    {"name": "Otieno Transport", "sector": "transport", "sub_sector": "boda_boda", "daily_sales": (900, 4800), "expenses": {"TRANSPORT": (250, 1100), "REPAIRS": (500, 3500)}, "customers": ["PASSENGER", "PASSENGER", "PASSENGER"]},
    {"name": "Wanjiku Food Stall", "sector": "restaurant", "sub_sector": "chapati_stall", "daily_sales": (1500, 7000), "expenses": {"STOCK_PURCHASES": (700, 2800), "UTILITIES": (300, 1200), "TRANSPORT": (100, 450)}, "customers": ["WALK-IN CUSTOMER", "CUSTOMER"]},
    {"name": "Moses Phone Repair", "sector": "services", "sub_sector": "phone_repair", "daily_sales": (800, 6000), "expenses": {"STOCK_PURCHASES": (400, 2600), "TRANSPORT": (100, 500), "UTILITIES": (300, 900)}, "customers": ["CUSTOMER", "CUSTOMER"]},
]

EXPENSE_PARTIES = {
    "STOCK_PURCHASES": ("supplier", ["WHOLESALER", "SUPPLIER A", "DISTRIBUTOR"]),
    "TRANSPORT": ("other_business", ["MATATU", "BODA BODA", "DELIVERY RIDER"]),
    "UTILITIES": ("utility", ["KPLC", "SAFARICOM", "TOKEN VENDOR"]),
    "REPAIRS": ("supplier", ["MECHANIC", "GARAGE"]),
}

CATEGORY_CHANNEL = {
    "SALES_TILL": "till", "STOCK_PURCHASES": "send", "TRANSPORT": "send",
    "UTILITIES": "bill", "REPAIRS": "send",
    "RENT": "send", "WAGES": "send", "LOAN_REPAYMENT": "loan",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def token(value: str) -> str:
    return "tok_" + hashlib.sha256(value.encode()).hexdigest()[:16]


def receipt(rng: random.Random) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(rng.choice(alphabet) for _ in range(10))


def money(kes: int) -> int:
    return int(kes) * 100


def init_database(db_path: Path, reset: bool = False) -> sqlite3.Connection:
    if reset and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return connection


def export_csvs(db_path: Path, output_dir: Path) -> dict[str, int]:
    """Export populated schema tables as CSV files for portable seeding.

    Files are written in table-name order and retain database-generated IDs, so
    they can be loaded into a fresh database in dependency order if needed.
    Views and FTS helper tables are intentionally excluded.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        table_names = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' ORDER BY name"
            )
        ]
        counts = {}
        for table_name in table_names:
            cursor = connection.execute(f'SELECT * FROM "{table_name}"')
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            if not rows:
                continue
            csv_path = output_dir / f"{table_name}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerows(rows)
            counts[table_name] = len(rows)
        return counts
    finally:
        connection.close()


def category_ids(connection: sqlite3.Connection) -> dict[str, int]:
    return {code: category_id for category_id, code in connection.execute("SELECT category_id, code FROM category")}


def create_business(connection: sqlite3.Connection, profile: dict, index: int, start: date, rng: random.Random) -> tuple[int, int, int, int]:
    public_ref = f"SYN-{index:04d}"
    connection.execute(
        "INSERT INTO business (public_ref, name_token, sector, sub_sector, country_code, currency_code, "
        "timezone, registration_type, start_date, employee_count, is_synthetic) VALUES (?, ?, ?, ?, 'KE', 'KES', ?, ?, ?, ?, 1)",
        (public_ref, token(profile["name"]), profile["sector"], profile["sub_sector"], "Africa/Nairobi", "informal", start.isoformat(), rng.randint(0, 4)),
    )
    business_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.execute("INSERT INTO app_user (display_token) VALUES (?)", (token(f"owner-{public_ref}"),))
    user_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.execute("INSERT INTO business_member (business_id, user_id, role) VALUES (?, ?, 'owner')", (business_id, user_id))
    opening_balance = money(rng.randint(8_000, 30_000))
    connection.execute("INSERT INTO financial_account (business_id, platform_id, kind, label, currency_code, opening_balance_minor, opening_date, is_primary) VALUES (?, 1, 'mobile_wallet', ?, 'KES', ?, ?, 1)", (business_id, f"{profile['name']} mobile wallet", opening_balance, start.isoformat()))
    account_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    return business_id, user_id, account_id, opening_balance


def get_or_create_party(connection: sqlite3.Connection, business_id: int, name: str, kind: str, first_seen: str, last_seen: str) -> int:
    display = token(name)
    row = connection.execute("SELECT party_id FROM party WHERE business_id = ? AND display_token = ?", (business_id, display)).fetchone()
    if row:
        connection.execute("UPDATE party SET last_seen = ? WHERE party_id = ?", (last_seen, row[0]))
        return row[0]
    connection.execute("INSERT INTO party (business_id, kind, display_token, is_business_related, first_seen, last_seen) VALUES (?, ?, ?, 1, ?, ?)", (business_id, kind, display, first_seen, last_seen))
    return connection.execute("SELECT last_insert_rowid()").fetchone()[0]


def add_ledger_rows(connection: sqlite3.Connection, business_id: int, account_id: int, profile: dict, start: date, days: int, rng: random.Random, ids: dict[str, int], run_id: int, opening_balance: int) -> tuple[list[tuple], int]:
    balance = opening_balance
    references = []
    current = start
    for offset in range(days):
        current = start + timedelta(days=offset)
        event_index = 0
        factor = 0.55 if current.weekday() == 6 else 1.0
        revenue = int(rng.randint(*profile["daily_sales"]) * factor)
        event_count = max(1, min(10, round(revenue / 900)))
        parts = [revenue // event_count] * event_count
        for position in range(revenue % event_count):
            parts[position] += 1
        for amount_kes in parts:
            category = "SALES_TILL"
            party_name = rng.choice(profile["customers"])
            party_id = get_or_create_party(connection, business_id, party_name, "customer", current.isoformat(), current.isoformat())
            amount = money(amount_kes)
            balance += amount
            reference = receipt(rng)
            references.append((run_id, reference, category))
            hour, minute = divmod(360 + event_index * 20, 60)
            ts = f"{current.isoformat()}T{hour:02d}:{minute:02d}:00+03:00"
            connection.execute("INSERT INTO transaction_ledger (business_id, account_id, reference, ts, local_date, amount_minor, direction, balance_after_minor, party_id, counterparty_token, description_redacted, channel, category_id, category_source, confidence, source) VALUES (?, ?, ?, ?, ?, ?, 'in', ?, ?, ?, ?, 'till', ?, 'rule', 0.98, 'statement')", (business_id, account_id, reference, ts, current.isoformat(), amount, balance, party_id, token(party_name), "Customer sale", ids[category],))
            event_index += 1
        for code, amount_range in profile["expenses"].items():
            due = current.day == 1 if code == "RENT" else rng.random() < 0.22
            if due and current.weekday() != 6:
                amount = money(rng.randint(*amount_range))
                kind, names = EXPENSE_PARTIES.get(code, ("supplier", [code]))
                party_name = rng.choice(names)
                party_id = get_or_create_party(connection, business_id, party_name, kind, current.isoformat(), current.isoformat())
                balance -= amount
                reference = receipt(rng)
                references.append((run_id, reference, code))
                hour, minute = divmod(360 + event_index * 20, 60)
                ts = f"{current.isoformat()}T{hour:02d}:{minute:02d}:00+03:00"
                connection.execute("INSERT INTO transaction_ledger (business_id, account_id, reference, ts, local_date, amount_minor, direction, balance_after_minor, party_id, counterparty_token, description_redacted, channel, category_id, category_source, confidence, source) VALUES (?, ?, ?, ?, ?, ?, 'out', ?, ?, ?, ?, ?, ?, 'rule', 0.93, 'statement')", (business_id, account_id, reference, ts, current.isoformat(), amount, balance, party_id, token(party_name), code.replace("_", " ").title(), CATEGORY_CHANNEL.get(code, "send"), ids[code],))
                event_index += 1
    return references, balance


def add_derived_rows(connection: sqlite3.Connection, business_id: int, account_id: int, start: date, days: int, balance: int, ids: dict[str, int]) -> None:
    connection.execute("INSERT INTO balance_snapshot (account_id, as_of, balance_minor, source) VALUES (?, ?, ?, 'derived')", (account_id, (start + timedelta(days=days - 1)).isoformat(), balance))
    month_totals = defaultdict(lambda: {"revenue": 0, "cogs": 0, "opex": 0, "financing": 0, "count": 0})
    rows = connection.execute("SELECT local_date, amount_minor, direction, c.kind FROM transaction_ledger t JOIN category c ON c.category_id = t.category_id WHERE t.business_id = ?", (business_id,)).fetchall()
    for local_date, amount, direction, kind in rows:
        month = local_date[:7]
        month_totals[month]["count"] += 1
        if direction == "in" and kind == "income":
            month_totals[month]["revenue"] += amount
        elif direction == "out" and kind == "cogs":
            month_totals[month]["cogs"] += amount
        elif direction == "out" and kind == "opex":
            month_totals[month]["opex"] += amount
        elif direction == "out" and kind == "financing":
            month_totals[month]["financing"] += amount
    for month, totals in month_totals.items():
        month_start = f"{month}-01"
        next_month = (date.fromisoformat(month_start).replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = (next_month - timedelta(days=1)).isoformat()
        connection.execute("INSERT INTO metric_snapshot (business_id, period_type, period_start, period_end, calc_version, revenue_minor, cogs_minor, opex_minor, financing_cost_minor, operating_cashflow_minor, txn_count) VALUES (?, 'month', ?, ?, 'synthetic-1', ?, ?, ?, ?, ?, ?)", (business_id, month_start, month_end, totals["revenue"], totals["cogs"], totals["opex"], totals["financing"], totals["revenue"] - totals["cogs"] - totals["opex"] - totals["financing"], totals["count"]))
    connection.execute("INSERT INTO obligation (business_id, label, kind, amount_minor, cadence, day_of_month, next_due, essential, source, confidence) VALUES (?, 'Monthly premises rent', 'rent', ?, 'monthly', 1, ?, 1, 'detected', 0.90)", (business_id, money(8_000), (start + timedelta(days=days)).replace(day=1).isoformat()))
    connection.execute("INSERT INTO forecast_run (business_id, scenario_label, as_of_date, horizon_days, method, seed, n_paths, opening_balance_minor, buffer_minor, data_start, data_end, calc_version) VALUES (?, 'baseline', ?, 14, 'weekday_bootstrap', 42, 100, ?, ?, ?, ?, 'synthetic-1')", (business_id, (start + timedelta(days=days - 1)).isoformat(), balance, money(5_000), start.isoformat(), (start + timedelta(days=days - 1)).isoformat()))
    run_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    for offset in range(15):
        point_date = start + timedelta(days=days + offset)
        expected = balance + offset * money(500)
        connection.execute("INSERT INTO forecast_point (run_id, day_offset, date, expected_minor, p10_minor, p50_minor, p90_minor, inflow_expected_minor, outflow_expected_minor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (run_id, offset, point_date.isoformat(), expected, expected - money(2_000), expected, expected + money(2_000), money(2_000), money(1_500)))


def generate(db_path: Path, businesses: int, days: int, seed: int, start: date, reset: bool, rows_per_table: int = 0) -> dict:
    if businesses < 1:
        raise ValueError("businesses must be at least 1")
    if days < 1:
        raise ValueError("days must be at least 1")
    if rows_per_table < 0:
        raise ValueError("rows_per_table cannot be negative")
    if rows_per_table:
        businesses = max(businesses, rows_per_table)
    rng = random.Random(seed)
    connection = init_database(db_path, reset=reset)
    ids = category_ids(connection)
    required = {"SALES_TILL", "STOCK_PURCHASES", "TRANSPORT", "UTILITIES", "REPAIRS"}
    missing = required - ids.keys()
    if missing:
        raise RuntimeError(f"schema is missing seeded categories: {', '.join(sorted(missing))}")
    summary = {"businesses": 0, "transactions": 0, "database": str(db_path)}
    try:
        for index in range(businesses):
            profile = PROFILES[index % len(PROFILES)]
            business_id, _, account_id, opening_balance = create_business(connection, profile, index + 1, start, rng)
            connection.execute("INSERT INTO synthetic_run (persona, seed, generator_version, params_json) VALUES (?, ?, ?, ?)", (profile["sector"] if profile["sector"] in {"grocery", "salon", "transport"} else "grocery", seed, GENERATOR_VERSION, json.dumps({"days": days, "start": start.isoformat()})))
            run_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            references, balance = add_ledger_rows(connection, business_id, account_id, profile, start, days, rng, ids, run_id, opening_balance)
            connection.executemany("INSERT INTO synthetic_ground_truth (run_id, reference, true_category_code) VALUES (?, ?, ?)", references)
            add_derived_rows(connection, business_id, account_id, start, days, balance, ids)
            summary["businesses"] += 1
            summary["transactions"] += len(references)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Duka's full SQLite schema with synthetic SME data")
    parser.add_argument("--db", type=Path, default=Path("data/synthetic.db"), help="SQLite database path")
    parser.add_argument("--output", choices=("database", "csv", "both"), default="both", help="Write a database, CSV seed files, or both")
    parser.add_argument("--csv-dir", type=Path, default=Path("data/seed_csv"), help="Directory for one CSV per populated schema table")
    parser.add_argument("--businesses", type=int, default=3, help="Number of synthetic businesses")
    parser.add_argument("--rows-per-table", type=int, default=0, help="Scale business-linked relations to at least this many rows, e.g. 1000")
    parser.add_argument("--days", type=int, default=90, help="Transaction history length")
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START, help="History start date (YYYY-MM-DD)")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--reset", action="store_true", help="Delete the target database before creating it")
    args = parser.parse_args()
    db_path = args.db
    temporary_db = None
    if args.output == "csv":
        temporary_db = tempfile.NamedTemporaryFile(prefix="duka-seed-", suffix=".db", delete=False)
        temporary_db.close()
        db_path = Path(temporary_db.name)

    result = generate(db_path, args.businesses, args.days, args.seed, args.start_date, args.reset, args.rows_per_table)
    if args.output in {"csv", "both"}:
        result["csv_tables"] = export_csvs(db_path, args.csv_dir)
        result["csv_directory"] = str(args.csv_dir)
    if temporary_db is not None:
        db_path.unlink(missing_ok=True)
        result["database"] = None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
