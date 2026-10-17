"""Helper to load pre-baked Kenyan SME sample datasets for quick exploration."""
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
from core.adapters.mobile_money_ke import MobileMoneyKeAdapter
from core.redaction import Redactor
from core.categoriser import Categoriser

MOCK_PROFILES = {
    "amina_grocery": {
        "id": "amina_grocery",
        "name": "Amina's Fresh Grocery & Kiosk",
        "sector": "Retail & Grocery (Kibera, Nairobi)",
        "icon": "🏪",
        "file": "amina_grocery_statement.csv",
        "description": "High volume fresh produce, wholesaler purchases, Fuliza overdrafts, and customer credit ledger."
    },
    "otieno_transport": {
        "id": "otieno_transport",
        "name": "Otieno Transport & Boda Services",
        "sector": "Transport & Logistics (Mombasa Rd)",
        "icon": "🚐",
        "file": "otieno_transport_statement.csv",
        "description": "Daily commuter fares, fuel station payments, spare parts, vehicle repairs, and SACCO savings."
    },
    "grace_salon": {
        "id": "grace_salon",
        "name": "Grace Beauty & Hair Salon",
        "sector": "Personal Care & Services (Umoja)",
        "icon": "💇",
        "file": "grace_salon_statement.csv",
        "description": "Hair dressing service revenue, beauty product purchases, commercial rent, KPLC tokens, and casual wages."
    }
}


def load_sample_business(profile_key: str = "amina_grocery") -> List[Dict]:
    """Load and parse sample CSV statement from mock_data."""
    base = Path(__file__).resolve().parent.parent
    profile = MOCK_PROFILES.get(profile_key, MOCK_PROFILES["amina_grocery"])
    file_path = base / "data" / "mock_data" / profile["file"]

    if not file_path.exists():
        return []

    with open(file_path, "rb") as f:
        raw_bytes = f.read()

    adapter = MobileMoneyKeAdapter()
    parsed = adapter.parse(raw_bytes)
    redactor = Redactor()
    redacted = redactor.redact_transactions(parsed)
    categoriser = Categoriser()

    for txn in redacted:
        cur_cat = str(txn.get("category", "")).lower()
        if not cur_cat or cur_cat in ("uncategorised", "unclassified", "other"):
            cat_res = categoriser.categorise(
                description=txn.get("description", txn.get("counterparty", "")),
                channel=txn.get("channel", "other"),
                direction=txn.get("direction", "out"),
                amount_minor=txn.get("amount_minor", int(round(abs(txn.get("amount", 0)) * 100))),
                counterparty=txn.get("counterparty", ""),
            )
            txn["category"] = cat_res.category_code

    return redacted
