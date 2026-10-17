"""
credit.py - Step 6: compare credit options and find Amina's headline number
=============================================================================

For a loan amount and term this:
  1. prices four options: mobile overdraft, mobile micro-loan, SACCO loan, bank SME loan
  2. shows total repayment, cost, and EFFECTIVE ANNUAL COST (the yearly cost once
     timing and compounding are included - the fair way to compare a 30-day
     loan with a 6-month one)
  3. checks whether the repayments FIT THE FORECAST: with the loan money in and
     the repayments out, the low estimate must stay above the safety buffer
  4. finds the highest WEEKLY PERSONAL MONEY the owner can take while the
     loan still fits - the cap that lets the business stop borrowing
  5. works out the HEADLINE NUMBER: yearly savings from replacing the overdraft
     habit with the cheapest option that fits

The overdraft and micro-loan use the fees from generate_data.py. The SACCO and
bank rates are ILLUSTRATIVE, not real quotes: change them below.

HOW TO RUN (after build_ledger.py has created the ledgers)
    py credit.py               (Amina, amount from her forecast, 6 months)
    py credit.py 50000 90      (any amount in KES and term in days)
"""

import sys
from datetime import timedelta
from math import ceil, sqrt

from analytics import (DATA, OVERDRAFT_ACCESS_FEE, OVERDRAFT_DAILY_FEE, PERSONAL,
                       load_ledger, summarise, true_positions)
from forecast import (HORIZON, RANGE_Z, SAFETY_BUFFER, build_model, forecast,
                      predict_day, shortfall_alert)

BUSINESS = "amina_grocery"
DEFAULT_TERM = 180              # days (6 months)
MONTH = 30                      # days

MICRO_LOAN_FEE = 0.075          # 7.5% flat per 30 days (same as generate_data.py)

# --- ILLUSTRATIVE RATES: not real quotes. Change them here. -------------------
SACCO_ANNUAL_RATE = 0.12        # 1% a month on the reducing balance
SACCO_UPFRONT_FEE = 0.01        # processing fee, taken when the loan is paid out
BANK_ANNUAL_RATE = 0.17         # per year on the reducing balance
BANK_UPFRONT_FEE = 0.03         # arrangement fee
# -----------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. Repayment schedules: each returns (upfront fee, [(day, payment), ...])
# ---------------------------------------------------------------------------

def overdraft(amount, days):
    """Drawn once, repaid in one go at the end; 1% when drawn + 0.5% a day."""
    owed = amount * (1 + OVERDRAFT_ACCESS_FEE) * (1 + OVERDRAFT_DAILY_FEE * days)
    return 0, [(days, owed)]


def micro_loan(amount, days):
    """7.5% per 30 days. For longer terms it is renewed: the fee is paid every
    30 days and the amount itself at the end."""
    periods = max(1, ceil(days / MONTH))
    payments = [(MONTH * p, amount * MICRO_LOAN_FEE) for p in range(1, periods + 1)]
    last_day, last_fee = payments[-1]
    payments[-1] = (last_day, last_fee + amount)
    return 0, payments


def instalment_loan(annual_rate, upfront_fee):
    """Equal monthly instalments on the reducing balance, plus an upfront fee."""
    def schedule(amount, days):
        months = max(1, round(days / MONTH))
        r = annual_rate / 12
        instalment = amount * r / (1 - (1 + r) ** -months)
        return amount * upfront_fee, [(MONTH * m, instalment) for m in range(1, months + 1)]
    return schedule


PRODUCTS = [
    ("Mobile overdraft", overdraft, "1% when drawn + 0.5% a day, repaid in one go"),
    ("Mobile micro-loan", micro_loan, "7.5% per 30 days, renewed every 30 days"),
    ("SACCO loan*", instalment_loan(SACCO_ANNUAL_RATE, SACCO_UPFRONT_FEE),
     f"{SACCO_ANNUAL_RATE:.0%}/yr reducing + {SACCO_UPFRONT_FEE:.0%} fee, monthly; needs membership"),
    ("Bank SME loan*", instalment_loan(BANK_ANNUAL_RATE, BANK_UPFRONT_FEE),
     f"{BANK_ANNUAL_RATE:.0%}/yr reducing + {BANK_UPFRONT_FEE:.0%} fee, monthly; needs records"),
]


# ---------------------------------------------------------------------------
# 2. Cost of each option
# ---------------------------------------------------------------------------

def effective_annual_cost(received, payments):
    """The yearly rate at which the payments are worth exactly what was received
    (an internal rate of return, found by halving the search range each step)."""
    def value_left(daily_rate):
        return received - sum(p / (1 + daily_rate) ** day for day, p in payments)

    low, high = 0.0, 1.0
    for _ in range(100):
        mid = (low + high) / 2
        if value_left(mid) < 0:     # payments still worth more -> rate is higher
            low = mid
        else:
            high = mid
    return (1 + low) ** 365 - 1


def compare_options(amount, days):
    options = []
    for name, schedule, note in PRODUCTS:
        fee, payments = schedule(amount, days)
        total = fee + sum(p for _, p in payments)
        options.append({
            "name": name, "note": note, "upfront_fee": fee, "payments": payments,
            "total_repaid": total, "cost": total - amount,
            "annual_cost": effective_annual_cost(amount - fee, payments),
        })
    return options


# ---------------------------------------------------------------------------
# 3. Does it fit the forecast?
# ---------------------------------------------------------------------------

def weekly_personal(model):
    """Personal money the forecast expects each week (withdrawals, family...)."""
    per_week = {"weekly": 1, "monthly": 12 / 52}
    return -sum(p["amount"] * per_week[p["schedule"]]
                for p in model["patterns"] if p["category"] in PERSONAL)


def with_personal_cap(model, weekly_cap):
    """A copy of the model where personal money is scaled down to the cap."""
    factor = weekly_cap / weekly_personal(model)
    patterns = [dict(p, amount=p["amount"] * factor) if p["category"] in PERSONAL else p
                for p in model["patterns"]]
    return dict(model, patterns=patterns)


def lowest_low(model, option, last_date, position, amount):
    """Lowest LOW estimate of cash over the loan's life. The loan money first
    clears the overdraft (we start from the true position), then each day adds
    expected sales minus payments and loan repayments. The error band grows for
    two weeks, like the forecast, and then stays that wide - we assume a fresh
    forecast every two weeks."""
    due = {}
    for day, p in option["payments"]:
        due[day] = due.get(day, 0) + p
    cash = position + amount - option["upfront_fee"]
    lowest = None
    for k in range(1, max(due) + 1):
        cash += predict_day(model, last_date + timedelta(days=k))["net"] - due.get(k, 0)
        low = cash - RANGE_Z * model["daily_error"] * sqrt(min(k, HORIZON))
        lowest = low if lowest is None else min(lowest, low)
    return lowest


def fits(model, option, last_date, position, amount):
    return lowest_low(model, option, last_date, position, amount) >= SAFETY_BUFFER


def personal_cap(model, option, last_date, position, amount):
    """Highest weekly personal money that still lets this option fit
    (None if it can't fit even with no personal money at all)."""
    current = weekly_personal(model)
    def ok(cap):
        return fits(with_personal_cap(model, cap), option, last_date, position, amount)
    if ok(current):
        return current
    if not ok(0):
        return None
    low, high = 0.0, current
    for _ in range(40):
        mid = (low + high) / 2
        low, high = (mid, high) if ok(mid) else (low, mid)
    return low


# ---------------------------------------------------------------------------
# 4. Report
# ---------------------------------------------------------------------------

def kes(x):
    return f"KES {x:,.0f}"


def main():
    rows = load_ledger(DATA / f"{BUSINESS}_ledger.csv")
    summary = summarise(rows)
    last_date = rows[-1]["date"]
    position = true_positions(rows, [last_date])[last_date]
    model = build_model(rows)

    # Amount: what the forecast says she needs to stay safe, rounded up to 5,000
    alert = shortfall_alert(forecast(model, last_date, position))
    needed = alert["amount_needed"] if alert else 0
    amount = float(sys.argv[1]) if len(sys.argv) > 1 else max(5000, ceil(needed / 5000) * 5000)
    days = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TERM

    print(f"{BUSINESS}: true position {kes(position)}; "
          f"forecast says she needs {kes(needed)} to stay safe")
    print(f"Comparing a loan of {kes(amount)} over {days} days "
          f"(the loan first clears the overdraft)\n")

    options = compare_options(amount, days)
    current = weekly_personal(model)
    print(f"  {'Option':<19}{'Total repaid':>14}{'Cost':>11}{'Annual cost':>13}"
          f"{'Fits now?':>11}   Fits if personal money is at most")
    for o in options:
        o["fits_now"] = fits(model, o, last_date, position, amount)
        o["cap"] = personal_cap(model, o, last_date, position, amount)
        cap = f"{kes(o['cap'])} a week" if o["cap"] is not None else "never"
        print(f"  {o['name']:<19}{o['total_repaid']:>14,.0f}{o['cost']:>11,.0f}"
              f"{o['annual_cost']:>12.0%} {'yes' if o['fits_now'] else 'no':>10}   {cap}")
    for o in options:
        print(f"    {o['name']:<19} {o['note']}")
    print("  * ILLUSTRATIVE rates, not real quotes. Change them at the top of credit.py.")
    print(f"  Personal money now: about {kes(current)} a week "
          f"(withdrawals, family transfers, school fees)")

    # Headline: the overdraft habit vs the cheapest option that can fit
    fitting = [o for o in options if o["cap"] is not None]
    if not fitting:
        print("\nNo option fits, even with no personal money at all.")
        return
    best = min(fitting, key=lambda o: o["cost"])
    habit_per_year = summary["credit"]["overdraft_fees"] * 365 / summary["period"]["days"]
    best_per_year = best["cost"] * 365 / days
    print(f"\nHEADLINE")
    print(f"  Overdraft habit: {kes(summary['credit']['overdraft_fees'])} in fees in "
          f"{summary['period']['days']} days = about {kes(habit_per_year)} a year")
    print(f"  Cheapest option that can fit: {best['name']} at {kes(best['cost'])} per "
          f"{days} days = about {kes(best_per_year)} a year")
    print(f"  Saving: about {kes(habit_per_year - best_per_year)} a year")

    print(f"\nWEEKLY PERSONAL-MONEY CAP")
    if best["fits_now"]:
        print(f"  The {best['name']} fits without changing her personal spending.")
    else:
        cut = current - best["cap"]
        print(f"  Cheaper credit alone is not enough: at {kes(current)} a week no option fits.")
        print(f"  Cap personal money at {kes(best['cap'])} a week (down {kes(cut)}, "
              f"{cut / current:.0%}) so the {best['name']} is repaid on time and the")
        print(f"  low estimate stays above the {kes(SAFETY_BUFFER)} buffer: "
              f"the business stops borrowing.")


if __name__ == "__main__":
    main()
