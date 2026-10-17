"""
parser.py - reads a messy mobile-money statement and returns clean transactions
================================================================================

Real exported statements are messy. This file fixes:
  - mixed date formats          ("2026-10-15 21:54:47", "15/10/2026 21:54", "Oct 15, 2026 09:54 PM")
  - messy descriptions          (line breaks, double spaces, random lowercase)
  - amounts stored as text      ("1,250.00", "-2680.00", blank)
  - failed transactions         (they never happened, so we drop them)
  - duplicate rows              (same receipt number twice)
  - newest-first ordering       (we sort oldest-first so maths is easier)

It then checks the balances add up, which catches missing or corrupted rows.

Each clean transaction is a dictionary like:
  {"receipt": "OQVCJVV0M9", "time": datetime(...), "details": "Payment from ...",
   "money_in": 1040.0, "money_out": 0.0, "balance": 240240.0}
"""

import csv
from datetime import datetime

DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%b %d, %Y %I:%M %p"]


def parse_time(text):
    """Try each known date format until one works."""
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {text!r}")


def parse_amount(text):
    """'1,250.00' -> 1250.0, '-2,680.00' -> 2680.0, '' -> 0.0"""
    text = (text or "").replace(",", "").replace("-", "").strip()
    return float(text) if text else 0.0


def clean_details(text):
    """Join broken lines and squash repeated spaces."""
    return " ".join((text or "").split())


def parse_statement(path):
    """Read a statement CSV and return (transactions, report)."""
    report = {"rows_read": 0, "failed_dropped": 0, "duplicates_dropped": 0,
              "balance_mismatches": 0}
    seen = set()
    transactions = []

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            report["rows_read"] += 1

            if row["Transaction Status"].strip().lower() != "completed":
                report["failed_dropped"] += 1
                continue
            receipt = row["Receipt No."].strip()
            if receipt in seen:
                report["duplicates_dropped"] += 1
                continue
            seen.add(receipt)

            transactions.append({
                "receipt": receipt,
                "time": parse_time(row["Completion Time"]),
                "details": clean_details(row["Details"]),
                "money_in": parse_amount(row["Paid In"]),
                "money_out": parse_amount(row["Withdrawn"]),
                "balance": parse_amount(row["Balance"]),
            })

    # Statements are already in time order, usually newest first. We flip them
    # to oldest first rather than re-sorting, because some date formats drop
    # the seconds and re-sorting would scramble rows from the same minute.
    if transactions and transactions[0]["time"] > transactions[-1]["time"]:
        transactions.reverse()

    # Balance check: previous balance + money in - money out should equal balance
    for prev, cur in zip(transactions, transactions[1:]):
        expected = prev["balance"] + cur["money_in"] - cur["money_out"]
        if abs(expected - cur["balance"]) > 0.5:
            report["balance_mismatches"] += 1

    report["transactions"] = len(transactions)
    return transactions, report
