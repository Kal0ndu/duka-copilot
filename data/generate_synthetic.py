"""Generate synthetic mobile-money transaction data for testing and demos.

Usage:
    python data/generate_synthetic.py --accounts 10 --days 90 --output data/synthetic.csv
"""
import csv
import random
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import Config


# ---- Kenyan micro-business profiles ----

BUSINESS_TYPES = [
    {"name": "grocery_kiosk", "daily_rev_range": (500, 3500), "categories": ["sales", "stock_purchase", "airtime", "rent", "transport"]},
    {"name": "mitumba_clothes", "daily_rev_range": (0, 8000), "categories": ["sales", "stock_purchase", "airtime", "rent", "transport", "bale_purchase"]},
    {"name": "chapati_stall", "daily_rev_range": (300, 2000), "categories": ["sales", "flour_sugar", "charcoal", "rent", "transport"]},
    {"name": "phone_repair", "daily_rev_range": (0, 5000), "categories": ["sales", "parts", "airtime", "rent", "transport"]},
    {"name": "boda_boda", "daily_rev_range": (200, 1500), "categories": ["fares", "fuel", "repairs", "savings"]},
    {"name": "salon", "daily_rev_range": (0, 4000), "categories": ["sales", "products", "rent", "electricity"]},
    {"name": "water_vendor", "daily_rev_range": (100, 2500), "categories": ["sales", "water_bulk", "transport", "rent"]},
    {"name": "mama_mboga", "daily_rev_range": (200, 3000), "categories": ["sales", "stock_purchase", "transport", "rent"]},
    {"name": "cyber_cafe", "daily_rev_range": (0, 2000), "categories": ["printing", "airtime", "internet", "rent", "electricity"]},
    {"name": "fundi_construction", "daily_rev_range": (0, 15000), "categories": ["contracts", "materials", "labour", "transport"]},
]

COUNTERPARTIES = {
    "sales": ["WALKIN", "CUSTOMER", "WALKIN", "CUSTOMER", "WHOLESALE"],
    "stock_purchase": ["SUPPLIER A", "SUPPLIER B", "DISTRIBUTOR", "WHOLESALER"],
    "airtime": ["SAFARICOM", "AIRTEL"],
    "rent": ["LANDLORD"],
    "transport": ["MATATU", "BODA", "FUEL STATION"],
    "flour_sugar": ["MILLER", "WHOLESALER"],
    "charcoal": ["CHARCOAL VENDOR"],
    "parts": ["PARTS SHOP", "DISTRIBUTOR"],
    "fuel": ["FUEL STATION"],
    "repairs": ["GARAGE", "MECHANIC"],
    "savings": ["MPESA SAVINGS"],
    "products": ["BEAUTY SUPPLIER"],
    "electricity": ["KPLC", "TOKEN VENDOR"],
    "water_bulk": ["WATER COMPANY"],
    "bale_purchase": ["MITUMBA WHOLESALE", "GIKOMBA MARKET"],
    "fares": ["PASSENGER", "PASSENGER", "PASSENGER"],
    "printing": ["CUSTOMER", "CUSTOMER"],
    "internet": ["SAFARICOM", "ZUKU"],
    "materials": ["HARDWARE", "TIMBER YARD", "QUARRY"],
    "labour": ["FUNDI", "CASUAL LABOURER"],
    "contracts": ["CLIENT", "CLIENT"],
}

INFLOW_CATEGORIES = {"sales", "fares", "printing", "contracts"}


def generate_accounts(n: int, seed: int = None) -> list:
    rng = random.Random(seed or Config.SYNTHETIC_DATA_SEED)
    accounts = []
    for i in range(n):
        biz = rng.choice(BUSINESS_TYPES)
        phone = f"07{rng.randint(10_000_000, 99_999_999)}"
        accounts.append({
            "msisdn": phone,
            "business": biz["name"],
            "daily_rev_range": biz["daily_rev_range"],
            "categories": biz["categories"],
        })
    return accounts


def generate_transactions(accounts: list, days: int, seed: int = None) -> list:
    rng = random.Random(seed or Config.SYNTHETIC_DATA_SEED)
    rows = []
    start = datetime(2026, 7, 1)
    end = start + timedelta(days=days)

    for acct in accounts:
        d = start
        while d < end:
            rev_range = acct["daily_rev_range"]
            rev = rng.randint(rev_range[0], rev_range[1])
            if rev > 0:
                cat = rng.choice([c for c in acct["categories"] if c in INFLOW_CATEGORIES])
                cpty = rng.choice(COUNTERPARTIES.get(cat, ["UNKNOWN"]))
                rows.append({
                    "msisdn": acct["msisdn"],
                    "date": d.strftime("%Y-%m-%d"),
                    "time": f"{rng.randint(6,21):02d}:{rng.randint(0,59):02d}",
                    "amount": rev,
                    "category": cat,
                    "counterparty": cpty,
                    "type": "credit",
                })

            outflow_cats = [c for c in acct["categories"] if c not in INFLOW_CATEGORIES]
            for cat in outflow_cats:
                if rng.random() < 0.35:
                    amount = rng.randint(50, max(50, rev // 3))
                    cpty = rng.choice(COUNTERPARTIES.get(cat, ["UNKNOWN"]))
                    rows.append({
                        "msisdn": acct["msisdn"],
                        "date": d.strftime("%Y-%m-%d"),
                        "time": f"{rng.randint(6,21):02d}:{rng.randint(0,59):02d}",
                        "amount": -amount,
                        "category": cat,
                        "counterparty": cpty,
                        "type": "debit",
                    })

            d += timedelta(days=1)

    return rows


def write_csv(rows: list, path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["msisdn", "date", "time", "amount", "category", "counterparty", "type"])
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description="Generate synthetic mobile-money data")
    p.add_argument("--accounts", type=int, default=10, help="Number of accounts")
    p.add_argument("--days", type=int, default=90, help="Days of history")
    p.add_argument("--seed", type=int, default=None, help="Random seed")
    p.add_argument("--output", type=str, default="data/synthetic.csv", help="Output CSV path")
    args = p.parse_args()

    seed = args.seed if args.seed is not None else Config.SYNTHETIC_DATA_SEED
    print(f"Generating {args.accounts} accounts × {args.days} days (seed={seed})")

    accounts = generate_accounts(args.accounts, seed=seed)
    rows = generate_transactions(accounts, args.days, seed=seed)
    write_csv(rows, args.output)

    print(f"Wrote {len(rows)} transactions to {args.output}")


if __name__ == "__main__":
    main()
