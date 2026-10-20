from datetime import datetime

import pytest

from analytics import DATA
from build_ledger import check_accuracy
from categoriser import categorise, categorise_all
from parser import parse_statement


def txn(details, money_in=0.0, money_out=0.0, when=datetime(2026, 10, 14, 10, 0)):
    return {"details": details, "money_in": money_in, "money_out": money_out, "time": when}


@pytest.mark.parametrize("details, money_in, money_out, expected", [
    ("Overdraft Drawdown", 500, 0, ("overdraft_drawdown", "high")),
    ("Overdraft Repayment", 0, 500, ("overdraft_repayment", "high")),
    ("Pay Bill to 123 - MWANGI PROPERTIES Acc. RENT", 0, 15000, ("rent", "high")),
    ("Pay Bill to 123 - SOKO SUPPLIES Acc. 9", 0, 30000, ("stock_purchase", "high")),
    ("Payment from 0712***345 - JOHN", 300, 0, ("sales", "high")),
    ("Customer Withdrawal At Agent Till 5 - AGENT ABC", 0, 4000, ("personal_withdrawal", "high")),
    ("Customer Transfer to 0712***345 - MARY", 0, 3000, ("family_transfer", "medium")),
    ("Merchant Payment to 9 - SOMETHING NEW", 0, 800, ("other_expense", "low")),
])
def test_rules(details, money_in, money_out, expected):
    assert categorise(txn(details, money_in, money_out)) == expected


def test_grace_saturday_evening_transfer_is_wages():
    saturday_evening = datetime(2026, 10, 10, 19, 0)
    t = txn("Customer Transfer to 0712***345 - PETER", money_out=6000, when=saturday_evening)
    assert categorise(t, "grace_salon") == ("wages", "medium")
    assert categorise(t, "amina_grocery") == ("family_transfer", "medium")


@pytest.mark.parametrize("business", ["amina_grocery", "grace_salon", "otieno_transport"])
def test_accuracy_against_answer_key(business):
    txns, _ = parse_statement(DATA / f"{business}_statement.csv")
    categorise_all(txns, business)
    accuracy, _ = check_accuracy(txns, DATA / f"{business}_labels.csv")
    assert accuracy >= 0.99      # rules were written knowing the generator: see the docs
