"""
analytics.py - Step 4: business health summary from a clean ledger
====================================================================

Reads data/<business>_ledger.csv (made by build_ledger.py) and works out:
  1. sales: total, average per day, average per day of the week
  2. slow days: weekdays well below average, and the worst single dates
  3. business costs and profit (sales minus business costs)
  4. personal money mixed in (cash withdrawals, family, school fees)
  5. credit use (overdraft and loans)
  6. cash position (opening, closing, lowest balance)

summarise() returns a plain dictionary. Later the AI agent gets this
dictionary as a tool result: Python does the maths, the AI only explains it.

HOW TO RUN (after build_ledger.py has created the ledgers)
    py analytics.py
"""

import csv
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent / "data"
BUSINESSES = ["amina_grocery", "grace_salon", "otieno_transport"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Which category belongs to which group.
# Note: airtime counts as a business cost, though some may really be personal.
BUSINESS_COSTS = ["stock_purchase", "rent", "utilities", "wages", "operating_expense",
                  "airtime", "transaction_fee", "other_expense"]
PERSONAL = ["personal_withdrawal", "family_transfer", "personal_payment"]

SLOW_DAY_THRESHOLD = 0.8   # a weekday is "slow" if below 80% of the daily average


def load_ledger(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["date"] = date.fromisoformat(r["Date"])
        r["in"] = float(r["Money In"])
        r["out"] = float(r["Money Out"])
        r["balance"] = float(r["Balance"])
    return rows


def totals_by_category(rows, categories, field):
    totals = {c: 0.0 for c in categories}
    for r in rows:
        if r["Category"] in totals:
            totals[r["Category"]] += r[field]
    return {c: round(v, 2) for c, v in totals.items() if v > 0}


def summarise(rows):
    """Turn a ledger (list of rows) into a business health summary."""
    start, end = rows[0]["date"], rows[-1]["date"]
    all_dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    # --- 1. Sales per day (days with no sales count as 0) ---
    sales_by_date = {d: 0.0 for d in all_dates}
    for r in rows:
        if r["Category"] == "sales":
            sales_by_date[r["date"]] += r["in"]
    sales_total = sum(sales_by_date.values())
    sales_per_day = sales_total / len(all_dates)

    # --- 2. Average sales for each weekday, and slow days ---
    weekday_sum, weekday_count = defaultdict(float), defaultdict(int)
    for d, amount in sales_by_date.items():
        weekday_sum[d.weekday()] += amount
        weekday_count[d.weekday()] += 1
    weekday_avg = {WEEKDAYS[w]: round(weekday_sum[w] / weekday_count[w], 2)
                   for w in sorted(weekday_count)}
    slow_weekdays = [w for w, avg in weekday_avg.items()
                     if avg < SLOW_DAY_THRESHOLD * sales_per_day]
    worst_dates = sorted(sales_by_date.items(), key=lambda kv: kv[1])[:3]

    # --- 3. Business costs and profit ---
    costs = totals_by_category(rows, BUSINESS_COSTS, "out")
    costs_total = sum(costs.values())
    profit = sales_total - costs_total

    # --- 4. Personal money taken out of the business ---
    personal = totals_by_category(rows, PERSONAL, "out")
    personal_total = sum(personal.values())

    # --- 5. Credit use ---
    def total(category, field):
        return round(sum(r[field] for r in rows if r["Category"] == category), 2)

    credit = {
        "overdraft_times_used": sum(1 for r in rows if r["Category"] == "overdraft_drawdown"),
        "overdraft_borrowed": total("overdraft_drawdown", "in"),
        "overdraft_repaid": total("overdraft_repayment", "out"),
        "loans_received": total("loan_disbursement", "in"),
        "loans_repaid": total("loan_repayment", "out"),
    }

    # --- 6. Cash position ---
    first, lowest = rows[0], min(rows, key=lambda r: r["balance"])
    opening = first["balance"] - first["in"] + first["out"]

    return {
        "period": {"start": str(start), "end": str(end), "days": len(all_dates)},
        "sales": {
            "total": round(sales_total, 2),
            "per_day": round(sales_per_day, 2),
            "by_weekday_avg": weekday_avg,
            "slow_weekdays": slow_weekdays,
            "worst_dates": [(str(d), round(v, 2)) for d, v in worst_dates],
        },
        "costs": {"by_category": costs, "total": round(costs_total, 2)},
        "profit": round(profit, 2),
        "personal": {
            "by_category": personal,
            "total": round(personal_total, 2),
            "share_of_profit": round(personal_total / profit, 3) if profit > 0 else None,
        },
        "credit": credit,
        "savings": total("savings_contribution", "out"),
        "cash": {
            "opening_balance": round(opening, 2),
            "closing_balance": rows[-1]["balance"],
            "lowest_balance": lowest["balance"],
            "lowest_balance_date": str(lowest["date"]),
        },
        "needs_owner_review": sum(1 for r in rows if r["Confidence"] in ("medium", "low")),
    }


def kes(amount):
    return f"KES {amount:,.0f}"


def print_summary(name, s):
    p, sales, credit, cash = s["period"], s["sales"], s["credit"], s["cash"]
    print(f"\n{name}  ({p['start']} to {p['end']}, {p['days']} days)")
    print(f"  Sales:   {kes(sales['total'])} total, {kes(sales['per_day'])} per day on average")
    print("  Average sales by weekday: "
          + ", ".join(f"{w} {v:,.0f}" for w, v in sales["by_weekday_avg"].items()))
    print(f"  Slow weekdays (below {SLOW_DAY_THRESHOLD:.0%} of average): "
          f"{', '.join(sales['slow_weekdays']) or 'none'}")
    print("  Worst days: " + ", ".join(f"{d} ({kes(v)})" for d, v in sales["worst_dates"]))

    print(f"  Business costs: {kes(s['costs']['total'])}")
    for cat, v in sorted(s["costs"]["by_category"].items(), key=lambda kv: -kv[1]):
        print(f"    {cat:<18} {kes(v)}")
    print(f"  Profit (sales - business costs): {kes(s['profit'])}")

    share = s["personal"]["share_of_profit"]
    print(f"  Personal money taken out: {kes(s['personal']['total'])}"
          + (f" = {share:.0%} of profit" if share is not None else ""))
    for cat, v in s["personal"]["by_category"].items():
        print(f"    {cat:<18} {kes(v)}")

    print(f"  Overdraft: used {credit['overdraft_times_used']} times, "
          f"borrowed {kes(credit['overdraft_borrowed'])}, repaid {kes(credit['overdraft_repaid'])}")
    if credit["loans_received"] or credit["loans_repaid"]:
        print(f"  Loans: received {kes(credit['loans_received'])}, "
              f"repaid {kes(credit['loans_repaid'])}")
    if s["savings"]:
        print(f"  Savings (SACCO): {kes(s['savings'])}")
    print(f"  Cash: opening {kes(cash['opening_balance'])}, closing {kes(cash['closing_balance'])}, "
          f"lowest {kes(cash['lowest_balance'])} on {cash['lowest_balance_date']}")
    print(f"  Transactions for the owner to confirm: {s['needs_owner_review']}")


def main():
    for name in BUSINESSES:
        rows = load_ledger(DATA / f"{name}_ledger.csv")
        print_summary(name, summarise(rows))


if __name__ == "__main__":
    main()
