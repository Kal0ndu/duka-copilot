"""
settings.py - each business's own settings, controlled by the OWNER
=====================================================================

One file per business in settings/ (e.g. settings/amina_grocery.json):
  sector              what kind of business it is (tells the AI)
  payday              the day staff are paid ("Sat", or null): helps tell wages
                      from family transfers
  per_transaction_cap, daily_cap, loan_cap, verified_payees   (the guard's rules)
  safety_buffer       KES the owner wants to keep (default KES 1,000; any value
                      from 0 up). Forecast alerts fire below it.
  learned_rules       categories the owner taught once ("teach it once")

Only the owner changes these, in the app's Settings tab. Changing caps or
payees needs the owner PIN. The AI can never change them (T3 forbidden).
Tests use defaults(), never the saved files, so test results can't drift.

HOW TO RUN (writes the default files if they don't exist yet)
    py settings.py
"""

import json
import re
from pathlib import Path

from analytics import WEEKDAYS
from categoriser import CATEGORIES, payee_key
from security import POLICIES, Policy

SETTINGS_DIR = Path(__file__).parent / "settings"
DEFAULT_BUFFER = 1000       # KES: the safety buffer until the owner changes it
SENSITIVE = ("per_transaction_cap", "daily_cap", "loan_cap", "verified_payees")
PAYEE_ID = re.compile(r"^[A-Z]{2,6}-\d{2}$")         # e.g. SUP-01, RENT-01

SECTORS = {"amina_grocery": "grocery shop in Nairobi",
           "grace_salon": "beauty salon in Kisumu",
           "otieno_transport": "motorbike-taxi (boda boda) business in Nakuru"}
PAYDAYS = {"grace_salon": "Sat"}


def defaults(business):
    """The built-in settings (also what the tests use)."""
    p = POLICIES[business]
    return {"sector": SECTORS[business], "payday": PAYDAYS.get(business),
            "per_transaction_cap": p.per_transaction_cap, "daily_cap": p.daily_cap,
            "loan_cap": p.loan_cap, "verified_payees": dict(p.verified_payees),
            "safety_buffer": DEFAULT_BUFFER, "learned_rules": []}


def path_for(business):
    return SETTINGS_DIR / f"{business}.json"


def load_settings(business):
    cfg = defaults(business)
    if path_for(business).exists():
        cfg.update(json.loads(path_for(business).read_text(encoding="utf-8")))
    return cfg


def validate(cfg):
    """A list of problems (empty = fine)."""
    problems = []
    for key in ("per_transaction_cap", "daily_cap", "loan_cap"):
        if not isinstance(cfg[key], (int, float)) or cfg[key] <= 0:
            problems.append(f"{key} must be a positive amount")
    if not problems and cfg["daily_cap"] < cfg["per_transaction_cap"]:
        problems.append("the daily cap can't be smaller than the per-payment cap")
    if cfg["payday"] not in (None, *WEEKDAYS):
        problems.append(f"payday must be one of {WEEKDAYS} or empty")
    if cfg["safety_buffer"] is not None and not (isinstance(cfg["safety_buffer"], (int, float))
                                                 and cfg["safety_buffer"] >= 0):
        problems.append("the safety buffer must be 0 or more")
    for pid, name in cfg["verified_payees"].items():
        if not PAYEE_ID.match(pid):
            problems.append(f"payee ID {pid!r} must look like SUP-01")
        if not str(name).strip() or len(str(name)) > 40:
            problems.append(f"payee {pid} needs a name of up to 40 characters")
    for rule in cfg["learned_rules"]:
        if rule.get("category") not in CATEGORIES or len(rule.get("match", "")) < 3:
            problems.append(f"bad learned rule {rule!r}")
    return problems


def save_settings(business, cfg):
    problems = validate(cfg)
    if problems:
        raise ValueError("; ".join(problems))
    SETTINGS_DIR.mkdir(exist_ok=True)
    path_for(business).write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")


def changes(old, new):
    """{field: (old value, new value)} for every field that changed."""
    return {k: (old.get(k), new[k]) for k in new if old.get(k) != new[k]}


def needs_pin(old, new):
    """Changing caps or payees needs the owner PIN."""
    return any(k in SENSITIVE for k in changes(old, new))


def policy_from(cfg):
    """The guard's rules, from these settings."""
    return Policy(verified_payees=dict(cfg["verified_payees"]),
                  per_transaction_cap=cfg["per_transaction_cap"], daily_cap=cfg["daily_cap"],
                  loan_cap=cfg["loan_cap"], loan_products=("sacco", "bank", "micro_loan"))


def profile_from(cfg):
    """What the categoriser needs to know about the owner."""
    return {"wage_weekday": WEEKDAYS.index(cfg["payday"]) if cfg["payday"] else None}


def safety_buffer(cfg):
    """The owner's buffer (0 is allowed); KES 1,000 if none is set."""
    value = cfg.get("safety_buffer")
    return float(DEFAULT_BUFFER if value is None else value)


def learn(cfg, description_or_key, category):
    """'Teach it once': remember this payee's category for this business.
    Returns new settings (the old ones are unchanged)."""
    key = payee_key(description_or_key)
    if len(key) < 3:
        raise ValueError("can't learn a rule from this description")
    rules = [r for r in cfg["learned_rules"] if r["match"] != key]
    return dict(cfg, learned_rules=rules + [{"match": key, "category": category}])


def forget(cfg, key):
    return dict(cfg, learned_rules=[r for r in cfg["learned_rules"] if r["match"] != key])


if __name__ == "__main__":
    for business in POLICIES:
        if not path_for(business).exists():
            save_settings(business, defaults(business))
        print(f"{path_for(business)}")
