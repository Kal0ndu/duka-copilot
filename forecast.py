"""
forecast.py - Step 5: 14-day cash-flow forecast with shortfall alerts
=======================================================================

For each business this:
  1. learns average sales for each day of the week
  2. finds recurring payments by itself (same weekday every week, or same
     date every month), e.g. stock on Mondays, rent on the 5th
  3. rolls the balance forward 14 days: today's balance + sales - payments
  4. gives a LOW / EXPECTED / HIGH range (about 8 in 10 days should land inside)
  5. raises an ALERT if the low estimate falls below the safety buffer
  6. BACKTEST: hides the last 14 days, forecasts them, and reports how close it was

The forecast uses the TRUE POSITION = balance minus overdraft owed (with fees),
because money sitting in the account isn't really the owner's while an
overdraft is unpaid. It assumes NO NEW BORROWING, so a negative forecast shows
the gap the overdraft would have to fill.

HOW TO RUN (after build_ledger.py has created the ledgers)
    py forecast.py
"""

from collections import defaultdict
from datetime import timedelta
from math import sqrt
from statistics import pstdev

from analytics import BUSINESSES, DATA, WEEKDAYS, load_ledger

HORIZON = 14              # days to forecast
SAFETY_BUFFER = 3000      # KES the owner wants to keep; an owner setting
MIN_HIT_RATE = 0.6        # a payment is "recurring" if it happens in 60%+ of its slots
MIN_HITS = 2              # ... and at least twice
RANGE_Z = 1.28            # 1.28 standard deviations each side = about an 80% range

# Borrowing reacts to shortfalls, so the forecast leaves it out.
BORROWING = {"overdraft_drawdown", "overdraft_repayment", "loan_disbursement"}

# Published fees of the generic mobile overdraft (to move to credit.py in Step 6)
OVERDRAFT_ACCESS_FEE = 0.01     # 1% of the amount when drawn
OVERDRAFT_DAILY_FEE = 0.005     # 0.5% of the amount owed per day

SCHEDULES = {
    "weekly": lambda d: d.weekday(),    # slot = day of the week
    "monthly": lambda d: d.day,         # slot = date of the month
}


def date_range(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def daily_flows(rows):
    """date -> {category: net amount that day} (money in +, money out -)."""
    flows = defaultdict(lambda: defaultdict(float))
    for r in rows:
        flows[r["date"]][r["Category"]] += r["in"] - r["out"]
    return flows


def end_of_day_balances(rows, dates):
    """Balance at the end of each date (days with no transactions carry over)."""
    last = {}
    for r in rows:                      # rows are oldest first
        last[r["date"]] = r["balance"]
    balances, bal = {}, rows[0]["balance"] - rows[0]["in"] + rows[0]["out"]
    for d in dates:
        bal = last.get(d, bal)
        balances[d] = bal
    return balances


def detect_recurring(flows, dates):
    """Find payments that repeat on the same weekday or the same date each month."""
    categories = sorted({c for d in dates for c in flows[d]} - BORROWING - {"sales"})
    patterns, explained = [], set()     # explained = (date, category) already covered
    for kind, slot_of in SCHEDULES.items():
        for cat in categories:
            slots = defaultdict(list)   # slot -> [(date, amount)] for every day in that slot
            for d in dates:
                amount = 0 if (d, cat) in explained else flows[d].get(cat, 0)
                slots[slot_of(d)].append((d, amount))
            for slot, days in slots.items():
                hits = [d for d, a in days if a != 0]
                if len(hits) >= MIN_HITS and len(hits) / len(days) >= MIN_HIT_RATE:
                    # Expected amount includes the misses, so it's a fair average
                    amount = sum(a for _, a in days) / len(days)
                    patterns.append({"category": cat, "schedule": kind,
                                     "slot": slot, "amount": amount})
                    explained.update((d, cat) for d in hits)
    return patterns, explained


def build_model(rows):
    """Learn sales rhythm, recurring payments and typical error from history."""
    dates = date_range(rows[0]["date"], rows[-1]["date"])
    flows = daily_flows(rows)

    # Average sales for each weekday (days with no sales count as 0)
    by_weekday = defaultdict(list)
    for d in dates:
        by_weekday[d.weekday()].append(flows[d].get("sales", 0))
    sales_avg = {w: sum(v) / len(v) for w, v in by_weekday.items()}

    patterns, explained = detect_recurring(flows, dates)

    # Everything else (one-off payments etc.) becomes a small daily average
    other = sum(amount for d in dates for cat, amount in flows[d].items()
                if cat not in BORROWING and cat != "sales" and (d, cat) not in explained)
    model = {"sales_avg": sales_avg, "patterns": patterns, "other_per_day": other / len(dates)}

    # How far real days differed from the model -> width of the range
    residuals = []
    for d in dates:
        actual = sum(a for cat, a in flows[d].items() if cat not in BORROWING)
        residuals.append(actual - predict_day(model, d)["net"])
    model["daily_error"] = pstdev(residuals)
    return model


def predict_day(model, d):
    sales = model["sales_avg"][d.weekday()]
    payments = [(p["category"], p["amount"]) for p in model["patterns"]
                if SCHEDULES[p["schedule"]](d) == p["slot"]]
    net = sales + sum(a for _, a in payments) + model["other_per_day"]
    return {"sales": sales, "payments": payments, "net": net}


def forecast(model, last_date, balance, days=HORIZON):
    """Roll the balance forward day by day, with a range that widens over time."""
    result = []
    for k in range(1, days + 1):
        d = last_date + timedelta(days=k)
        day = predict_day(model, d)
        balance += day["net"]
        if balance < 0:         # an unpaid overdraft keeps charging its daily fee
            balance -= round(-balance * OVERDRAFT_DAILY_FEE)
        spread = RANGE_Z * model["daily_error"] * sqrt(k)
        result.append({"date": d, "sales": day["sales"], "payments": day["payments"],
                       "expected": balance, "low": balance - spread, "high": balance + spread})
    return result


def shortfall_alert(days, buffer=SAFETY_BUFFER):
    """None if the low estimate stays above the buffer, else the details."""
    risky = [d for d in days if d["low"] < buffer]
    if not risky:
        return None
    worst = min(risky, key=lambda d: d["low"])
    return {"first_date": risky[0]["date"], "risky_days": len(risky),
            "worst_date": worst["date"], "worst_low": worst["low"],
            "amount_needed": buffer - worst["low"]}


def overdraft_owed_by_day(rows, dates):
    """Overdraft owed (with fees) at the end of each date, worked out from the
    drawdowns and repayments in the statement plus the overdraft's fees.
    Assumes nothing was owed before the statement starts."""
    events = defaultdict(list)
    for r in rows:
        if r["Category"] in ("overdraft_drawdown", "overdraft_repayment"):
            events[r["date"]].append(r)

    owed, fees_until, result = 0.0, None, {}
    for d in dates:
        for r in events[d]:
            if owed > 0:            # add daily fees since they were last added
                owed += round(owed * OVERDRAFT_DAILY_FEE * (d - fees_until).days)
            fees_until = d
            if r["Category"] == "overdraft_drawdown":
                owed += round(r["in"] * (1 + OVERDRAFT_ACCESS_FEE))
            else:
                owed = max(0.0, owed - r["out"])
        pending = round(owed * OVERDRAFT_DAILY_FEE * (d - fees_until).days) if owed else 0
        result[d] = owed + pending
    return result


def true_positions(rows, dates):
    """Balance minus overdraft owed, at the end of each date."""
    balances = end_of_day_balances(rows, dates)
    owed = overdraft_owed_by_day(rows, date_range(rows[0]["date"], dates[-1]))
    return {d: balances[d] - owed[d] for d in dates}


def backtest(rows, days=HORIZON):
    """Hide the last `days` days, forecast them, compare with what really happened."""
    end = rows[-1]["date"]
    cutoff = end - timedelta(days=days)
    history = [r for r in rows if r["date"] <= cutoff]
    hidden = [r for r in rows if r["date"] > cutoff]

    model = build_model(history)
    start_position = true_positions(history, [cutoff])[cutoff]
    predicted = forecast(model, cutoff, start_position, days)

    # Compare with the real true position (balance minus overdraft owed) each day
    actual = true_positions(rows, [p["date"] for p in predicted])
    errors, inside = [], 0
    for p in predicted:
        real = actual[p["date"]]
        errors.append(p["expected"] - real)
        inside += p["low"] <= real <= p["high"]

    sales_forecast = sum(p["sales"] for p in predicted)
    sales_actual = sum(r["in"] for r in hidden if r["Category"] == "sales")
    return {
        "start": cutoff + timedelta(days=1), "end": end,
        "final_error": errors[-1],
        "mean_abs_error": sum(abs(e) for e in errors) / len(errors),
        "avg_daily_sales": sales_actual / days,
        "days_inside_range": inside, "days": days,
        "sales_forecast": sales_forecast, "sales_actual": sales_actual,
        "sales_error_pct": (sales_forecast - sales_actual) / sales_actual,
    }


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def describe_pattern(p):
    if p["schedule"] == "weekly":
        return f"every {WEEKDAYS[p['slot']]}"
    return f"monthly on day {p['slot']}"


def print_forecast(name, rows, model, days, position):
    last = rows[-1]
    owed = last["balance"] - position
    print(f"\n{'=' * 78}\n{name}: {HORIZON}-day forecast from {last['date']} "
          f"(safety buffer KES {SAFETY_BUFFER:,})")
    print(f"  Balance KES {last['balance']:,.0f} - overdraft owed KES {owed:,.0f} "
          f"= true position KES {position:,.0f}")

    print("  Recurring payments found:")
    for p in sorted(model["patterns"], key=lambda p: p["amount"]):
        if abs(p["amount"]) >= 500:
            print(f"    {p['category']:<20} {describe_pattern(p):<17} ~KES {-p['amount']:>8,.0f}")
    print(f"    (smaller and one-off items: ~KES {-model['other_per_day']:,.0f} per day)")

    print(f"\n  {'Date':<11}{'Sales':>8}{'Low':>10}{'Expected':>10}{'High':>10}   Big payments due")
    for d in days:
        flag = "!" if d["low"] < SAFETY_BUFFER else " "
        due = ", ".join(f"{c} {-a:,.0f}" for c, a in d["payments"] if a <= -1000)
        print(f" {flag}{d['date']:%a %d %b} {d['sales']:>8,.0f}{d['low']:>10,.0f}"
              f"{d['expected']:>10,.0f}{d['high']:>10,.0f}   {due}")

    alert = shortfall_alert(days)
    if alert:
        print(f"\n  ALERT: the low estimate drops below KES {SAFETY_BUFFER:,} on "
              f"{alert['risky_days']} of {HORIZON} days, starting {alert['first_date']:%a %d %b}.")
        print(f"         Worst: {alert['worst_date']:%a %d %b}, low estimate "
              f"KES {alert['worst_low']:,.0f}. To stay safe you may need "
              f"KES {alert['amount_needed']:,.0f} more.")
    else:
        print(f"\n  OK: the low estimate stays above KES {SAFETY_BUFFER:,} for all {HORIZON} days.")


def print_backtest(bt):
    print(f"\n  Accuracy test: hid {bt['start']:%d %b} to {bt['end']:%d %b} and forecast it")
    direction = "too high" if bt["final_error"] > 0 else "too low"
    print(f"    Balance on the last day: forecast was KES {abs(bt['final_error']):,.0f} {direction}")
    print(f"    Average daily balance error: KES {bt['mean_abs_error']:,.0f} "
          f"(= {bt['mean_abs_error'] / bt['avg_daily_sales']:.0%} of a typical day's sales)")
    print(f"    Days inside the low-high range: {bt['days_inside_range']} of {bt['days']}")
    print(f"    Sales over the {bt['days']} days: forecast KES {bt['sales_forecast']:,.0f}, "
          f"actual KES {bt['sales_actual']:,.0f} ({bt['sales_error_pct']:+.1%})")


def main():
    for name in BUSINESSES:
        rows = load_ledger(DATA / f"{name}_ledger.csv")
        last_date = rows[-1]["date"]
        position = true_positions(rows, [last_date])[last_date]
        model = build_model(rows)
        days = forecast(model, last_date, position)
        print_forecast(name, rows, model, days, position)
        print_backtest(backtest(rows))


if __name__ == "__main__":
    main()
