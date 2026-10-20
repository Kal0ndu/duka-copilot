"""
categoriser.py - sorts each clean transaction into a business category
=======================================================================

We use clear RULES (keyword matching) rather than the AI, because rules are
fast, free, predictable and easy to test. Each result gets a confidence level:
  high   -> a rule matched exactly
  medium -> a reasonable guess from patterns (e.g. day of the week)
  low    -> no rule matched; the owner (or later the AI) should confirm it
  owner  -> the owner taught this payee's category once ("teach it once")

Later, the agent can ask the owner about "low" confidence items only.
"""

import re

# Business profile: facts the owner tells the app once, during setup.
# (e.g. "I pay my staff on Saturday evenings")
BUSINESS_PROFILES = {
    "amina_grocery": {"wage_weekday": None},
    "grace_salon": {"wage_weekday": 5},        # 5 = Saturday
    "otieno_transport": {"wage_weekday": None},
}

# Keyword rules, checked in order. First match wins.
# Each rule: (words to look for, category)
RULES = [
    (["overdraft drawdown"], "overdraft_drawdown"),
    (["overdraft repayment"], "overdraft_repayment"),
    (["loan disbursement"], "loan_disbursement"),
    (["loan repayment"], "loan_repayment"),
    (["charge"], "transaction_fee"),
    (["airtime"], "airtime"),
    (["withdrawal at agent"], "personal_withdrawal"),
    (["acc. rent"], "rent"),
    (["power co", "tokens", "water co"], "utilities"),
    (["sacco"], "savings_contribution"),
    (["finance ltd"], "loan_repayment"),
    (["school", "academy", "college"], "personal_payment"),
    (["distributor", "wholesal", "supplies", "supply"], "stock_purchase"),
    (["petrol", "fuel", "spares", "repairs", "equipment"], "operating_expense"),
]


CATEGORIES = sorted({c for _, c in RULES} | {
    "sales", "wages", "family_transfer", "other_expense", "other_income"})


def payee_key(details):
    """The part of a description that names who was paid or who paid:
    'Pay Bill to 123 - SOKO SUPPLIES Acc. 9' -> 'soko supplies'."""
    text = " ".join(str(details).lower().split())
    if " - " in text:
        text = text.split(" - ", 1)[1]
    text = re.split(r"\s+acc\.", text)[0]
    return " ".join(re.sub(r"[\d*]", " ", text).split())


def categorise(txn, business=None, profile=None, learned=()):
    """Return (category, confidence) for one transaction.
    profile: the owner's settings (e.g. staff payday); learned: rules the owner
    taught ("teach it once"), which win over the built-in rules."""
    text = txn["details"].lower()
    if profile is None:
        profile = BUSINESS_PROFILES.get(business, {})

    key = payee_key(txn["details"])
    for rule in learned:
        if rule["match"] == key:
            return rule["category"], "owner"

    for keywords, category in RULES:
        if any(k in text for k in keywords):
            return category, "high"

    # Money coming in from a customer
    if text.startswith("payment from") and txn["money_in"] > 0:
        return "sales", "high"

    # Transfers to a person: staff wages or family? Use the owner's profile.
    if text.startswith("customer transfer to"):
        wage_day = profile.get("wage_weekday")
        if wage_day is not None and txn["time"].weekday() == wage_day and txn["time"].hour >= 18:
            return "wages", "medium"
        return "family_transfer", "medium"

    # Paid a business we don't recognise yet
    if txn["money_out"] > 0:
        return "other_expense", "low"
    return "other_income", "low"


def categorise_all(transactions, business=None, profile=None, learned=()):
    """Add 'category' and 'confidence' to every transaction (in place)."""
    for t in transactions:
        t["category"], t["confidence"] = categorise(t, business, profile, learned)
    return transactions
