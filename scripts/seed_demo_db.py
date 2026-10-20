"""Build a ready-to-demo Duka database: three owners you can log in as, each
with their business, a real statement loaded, an approval PIN, verified
payees, recurring bills, standing orders, owner limits and a funded sandbox.

    python scripts/seed_demo_db.py                  # writes data/duka.db (old one backed up)
    python scripts/seed_demo_db.py --db other.db    # somewhere else

Everything goes through the app's own code (migrations, BusinessSetup,
StatementIngestor, OwnerPin, add_payee, StandingOrderService), so the result
is exactly what the app would have produced. All people and money are FAKE.

Demo logins (password login; OTP also works and prints in the terminal):
    Amina  0711000001  password Duka2026!  PIN 2468   (also the admin)
    Grace  0711000002  password Duka2026!  PIN 1357
    Otieno 0711000003  password Duka2026!  PIN 3579
"""
import argparse
import contextlib
import io
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auth.password_utils import hash_password  # noqa: E402
from auth.phone_utils import hash_phone, normalise_phone  # noqa: E402

DATA = ROOT / "data" / "mock_data"
PASSWORD = "Duka2026!"

OWNERS = [
    {
        "name": "Amina", "phone": "0711000001", "pin": "2468", "admin": True,
        "business": ("Amina's Fresh Grocery", "grocery", "fresh produce & kiosk"),
        "statement": "amina_grocery_statement.csv",
        "payees": ["Soko Supplies", "Freshfarm Wholesalers", "Unga Distributors Ltd",
                   "Mwangi Properties", "Power Co Tokens"],
        "limits": dict(per_txn=35_000, daily=60_000, loan=60_000, buffer=5_000),
        "bills": [("rent", "Shop rent - Mwangi Properties", 15_000, "monthly", 1),
                  ("utilities", "KPLC electricity tokens", 2_500, "monthly", 10),
                  ("salary", "Shop assistant wages", 1_500, "weekly", None)],
        "orders": [("Shop rent", "rent", "paybill", "522522", "MWANGI-RENT", 15_000, "monthly", 1),
                   ("KPLC tokens", "utility", "paybill", "888880", "AMINA-SHOP", 2_500, "monthly", 10)],
        "employees": 2, "revenue": 300_000,
    },
    {
        "name": "Grace", "phone": "0711000002", "pin": "1357", "admin": False,
        "business": ("Grace Beauty Salon", "salon", "hair & beauty"),
        "statement": "grace_salon_statement.csv",
        "payees": ["Style Supplies Ltd", "Beauty Hub Wholesale", "Lakeside Plaza Mgmt",
                   "Power Co Tokens"],
        "limits": dict(per_txn=25_000, daily=40_000, loan=50_000, buffer=3_000),
        "bills": [("rent", "Salon rent - Lakeside Plaza", 12_000, "monthly", 5),
                  ("salary", "Stylists' wages", 6_000, "weekly", None)],
        "orders": [("Salon rent", "rent", "paybill", "400200", "LAKESIDE-G12", 12_000, "monthly", 5)],
        "employees": 3, "revenue": 150_000,
    },
    {
        "name": "Otieno", "phone": "0711000003", "pin": "3579", "admin": False,
        "business": ("Otieno Boda Services", "transport", "motorbike taxi"),
        "statement": "otieno_transport_statement.csv",
        "payees": ["Highway Fuel Point", "City Petrol Station", "Bike Finance Ltd",
                   "Riders Sacco", "Kariuki Housing"],
        "limits": dict(per_txn=10_000, daily=15_000, loan=30_000, buffer=1_000),
        "bills": [("loan_repayment", "Bike loan - Bike Finance Ltd", 2_500, "weekly", None),
                  ("rent", "Room rent - Kariuki Housing", 6_000, "monthly", 1)],
        "orders": [("Bike loan", "loan_repayment", "paybill", "247247", "BIKE-OT-77", 2_500, "weekly", None)],
        "employees": 0, "revenue": 60_000,
    },
]


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


def build(db_path: str) -> list:
    from core.business_setup import BusinessSetup
    from core.ingestion import StatementIngestor
    from core.owner_settings import OwnerPin, OwnerSettings, add_payee, save_settings
    from core.standing_orders import StandingOrderService
    from db.migrate import MigrationRunner, ensure_006

    with _quiet():
        MigrationRunner(db_path).run_pending()
    ensure_006(db_path)

    setup = BusinessSetup(db_path)
    ingestor = StatementIngestor(db_path)
    pins = OwnerPin(db_path)
    orders = StandingOrderService(db_path)
    summary = []

    for o in OWNERS:
        phone = normalise_phone(o["phone"])
        pw_hash, pw_salt = hash_password(PASSWORD)
        with sqlite3.connect(db_path) as conn:
            uid = conn.execute(
                """INSERT INTO app_user (phone_hash, phone_verified, display_name, display_token,
                       password_hash, password_salt, status)
                   VALUES (?, 1, ?, ?, ?, ?, 'active')""",
                (hash_phone(phone), o["name"], o["name"], pw_hash, pw_salt),
            ).lastrowid

        name, sector, sub = o["business"]
        bid = setup.register_business(name, sector, sub_sector=sub, employee_count=o["employees"],
                                      revenue_estimate_minor=o["revenue"] * 100, owner_user_id=uid)

        csv = DATA / o["statement"]
        with _quiet():
            report = ingestor.ingest(csv.read_bytes(), csv.name, bid, uid)

        pins.set_pin(bid, o["pin"])
        lim = o["limits"]
        save_settings(db_path, OwnerSettings(
            business_id=bid, per_txn_cap_minor=lim["per_txn"] * 100, daily_cap_minor=lim["daily"] * 100,
            loan_cap_minor=lim["loan"] * 100, safety_buffer_minor=lim["buffer"] * 100,
            payday_weekday=5 if sector == "salon" else None, language="en"), user_id=uid, pin=o["pin"])
        for p in o["payees"]:
            add_payee(db_path, bid, p, o["pin"], user_id=uid)

        today = date.today()
        for etype, desc, amount, cadence, dom in o["bills"]:
            nxt = (today.replace(day=dom) if dom and dom >= today.day else
                   (today.replace(day=1) + timedelta(days=32)).replace(day=dom) if dom else
                   today + timedelta(days=(4 - today.weekday()) % 7 or 7))
            setup.add_recurring_expense(bid, etype, desc, amount * 100, cadence, day_of_month=dom,
                                        next_due=nxt.isoformat())
        for label, kind, dtype, number, ref, amount, cadence, dom in o["orders"]:
            start = today.replace(day=dom) if dom else today
            orders.create_order(bid, uid, label, kind, dtype, number, amount, cadence,
                                start_date=start, account_reference=ref)

        with sqlite3.connect(db_path) as conn:      # sandbox money so approved payments can run
            conn.execute("DELETE FROM sandbox_account WHERE business_id = ?", (bid,))
            conn.execute("INSERT INTO sandbox_account (business_id, balance_minor) VALUES (?, ?)",
                         (bid, 100_000 * 100))
        if o["admin"]:
            from auth.rbac import assign_admin
            assign_admin(db_path, uid)

        summary.append((o["name"], o["phone"], o["pin"], name, bid, report.rows_loaded))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "duka.db"))
    a = ap.parse_args()
    db = Path(a.db)
    if db.exists():
        backup = db.with_name(f"{db.stem}-backup-{datetime.now():%Y%m%d-%H%M%S}{db.suffix}")
        shutil.move(str(db), str(backup))
        print(f"Old database moved to {backup.name}")
    db.parent.mkdir(parents=True, exist_ok=True)

    rows = build(str(db))
    print(f"\nDemo database ready: {db}\n")
    print(f"{'Owner':8} {'Phone':12} {'Password':10} {'PIN':5} {'Business':26} Transactions")
    for name, phone, pin, biz, bid, n in rows:
        print(f"{name:8} {phone:12} {PASSWORD:10} {pin:5} {biz:26} {n:,}")
    print("\nAmina is also the admin (Admin & Security page). Sandbox balance: KES 100,000 each.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
