"""
build_ledger.py - Step 3: messy statement -> clean, categorised ledger
=======================================================================

For each business this:
  1. parses the messy statement (parser.py)
  2. categorises every transaction (categoriser.py)
  3. saves a clean ledger to data/<business>_ledger.csv
  4. checks the categories against the answer key and prints the ACCURACY

HOW TO RUN (after generate_data.py has created the data folder)
    py build_ledger.py
"""

import csv
from collections import Counter
from pathlib import Path

from parser import parse_statement
from categoriser import categorise_all
from settings import load_settings, profile_from

DATA = Path(__file__).parent / "data"
BUSINESSES = ["amina_grocery", "grace_salon", "otieno_transport"]


def save_ledger(path, transactions):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Time", "Receipt", "Description", "Money In",
                    "Money Out", "Balance", "Category", "Confidence"])
        for t in transactions:
            w.writerow([t["time"].date(), t["time"].strftime("%H:%M"), t["receipt"],
                        t["details"], t["money_in"], t["money_out"], t["balance"],
                        t["category"], t["confidence"]])


def check_accuracy(transactions, labels_path):
    with open(labels_path, newline="", encoding="utf-8") as f:
        truth = {r["Receipt No."]: r["True Category"] for r in csv.DictReader(f)}
    correct, mistakes = 0, Counter()
    for t in transactions:
        expected = truth.get(t["receipt"])
        if t["category"] == expected:
            correct += 1
        else:
            mistakes[(expected, t["category"])] += 1
    return correct / len(transactions), mistakes


def main():
    for name in BUSINESSES:
        txns, report = parse_statement(DATA / f"{name}_statement.csv")
        cfg = load_settings(name)               # staff payday + categories the owner taught
        categorise_all(txns, name, profile_from(cfg), cfg["learned_rules"])
        save_ledger(DATA / f"{name}_ledger.csv", txns)
        accuracy, mistakes = check_accuracy(txns, DATA / f"{name}_labels.csv")

        print(f"\n{name}")
        print(f"  rows read {report['rows_read']}, failed dropped {report['failed_dropped']}, "
              f"duplicates dropped {report['duplicates_dropped']}, "
              f"balance mismatches {report['balance_mismatches']}")
        print(f"  categorisation accuracy: {accuracy:.1%} of {len(txns)} transactions")
        for (expected, got), n in mistakes.most_common(5):
            print(f"    {n} x expected '{expected}' but got '{got}'")

    print(f"\nLedgers saved in: {DATA}")


if __name__ == "__main__":
    main()
