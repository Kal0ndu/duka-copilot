"""
key_numbers.py - every headline figure we quote, generated from the code
==========================================================================

Writes docs/key_numbers.md. The deck, docs and demo script should quote ONLY
these figures, so they always match the code. Everything uses the built-in
default settings (settings.defaults()), so demo changes in the app can't move them.

HOW TO RUN
    py run_tests.py      (runs all tests, then writes this file with the test results)
    py key_numbers.py    (business figures only; test results say "run py run_tests.py")
"""

from datetime import datetime
from pathlib import Path

from agent import BUSINESSES
from analytics import DATA, load_ledger, summarise, true_positions
from build_ledger import check_accuracy
from categoriser import categorise_all
from credit import headline
from forecast import backtest, build_model, forecast, shortfall_alert
from parser import parse_statement
from settings import defaults, safety_buffer

OUT = Path(__file__).parent / "docs" / "key_numbers.md"


def kes(x):
    return f"KES {x:,.0f}"


def business_rows():
    """One table row per business, per figure."""
    table = []
    for b in BUSINESSES:
        rows = load_ledger(DATA / f"{b}_ledger.csv")
        s = summarise(rows)
        cfg = defaults(b)
        buffer = safety_buffer(cfg)
        last = rows[-1]["date"]
        position = true_positions(rows, [last])[last]
        alert = shortfall_alert(forecast(build_model(rows), last, position), buffer)
        bt = backtest(rows)
        txns, report = parse_statement(DATA / f"{b}_statement.csv")
        categorise_all(txns, b)
        accuracy, _ = check_accuracy(txns, DATA / f"{b}_labels.csv")
        share = s["personal"]["share_of_profit"]
        table.append((b, [
            ("Statement period", f"{s['period']['start']} to {s['period']['end']} "
                                 f"({s['period']['days']} days)", "analytics.summarise"),
            ("Transactions (clean)", f"{len(txns):,}", "parser.parse_statement"),
            ("Balance mismatches", f"{report['balance_mismatches']}", "parser.parse_statement"),
            ("Categorisation accuracy", f"{accuracy:.1%}", "build_ledger.check_accuracy"),
            ("Sales", kes(s["sales"]["total"]), "analytics.summarise"),
            ("Cash profit (sales minus business costs)", kes(s["profit"]), "analytics.summarise"),
            ("Personal money taken out", kes(s["personal"]["total"])
             + (f" ({share:.0%} of cash profit)" if share is not None else ""),
             "analytics.summarise"),
            ("Mobile-money balance (15 Oct)", kes(s["cash"]["closing_balance"]),
             "analytics.summarise"),
            ("Overdraft owed", kes(s["cash"]["overdraft_owed"]), "analytics.overdraft_owed_by_day"),
            ("True position (balance minus overdraft owed)", kes(s["cash"]["true_position"]),
             "analytics.true_positions"),
            ("Overdraft fees in the period", kes(s["credit"]["overdraft_fees"]),
             "analytics.summarise"),
            ("Overdraft used", f"{s['credit']['overdraft_times_used']} times",
             "analytics.summarise"),
            ("Safety buffer (default)", kes(buffer), "settings.safety_buffer"),
            ("Caps: per payment / per day / loan",
             f"{kes(cfg['per_transaction_cap'])} / {kes(cfg['daily_cap'])} / "
             f"{kes(cfg['loan_cap'])}", "settings.defaults"),
            ("14-day forecast",
             f"ALERT on {alert['risky_days']} of 14 days; worst {alert['worst_date']:%a %d %b} "
             f"at {kes(alert['worst_low'])}; needs {kes(alert['amount_needed'])}"
             if alert else "OK: low estimate stays above the buffer",
             "forecast.forecast + shortfall_alert"),
            ("Forecast backtest (last 14 days hidden)",
             f"sales {bt['sales_error_pct']:+.1%}; last day {kes(abs(bt['final_error']))} "
             f"{'too high' if bt['final_error'] > 0 else 'too low'}; "
             f"{bt['days_inside_range']}/{bt['days']} days inside range", "forecast.backtest"),
        ]))
    return table


def headline_rows():
    h = headline(cfg=defaults("amina_grocery"))
    best = h["best"]
    options = {o["name"]: o for o in h["options"]}
    rows = [
        ("Money needed to stay above the buffer (14 days)", kes(h["needed"]),
         "forecast.shortfall_alert"),
        ("Loan cap", kes(h["loan_cap"]), "settings.defaults"),
        ("Recommended loan (within the cap)",
         f"{best['name']} of {kes(h['amount'])} over {h['days']} days" if best else "none",
         "credit.recommend"),
        ("Need above the loan cap?", "yes" if h["over_cap"] else "no", "credit.headline"),
    ]
    rows += [(f"Effective annual cost: {name}", f"{o['annual_cost']:.0%}",
              "credit.effective_annual_cost") for name, o in options.items()]
    if best:
        cut = h["current"] - best["cap"]
        rows += [
            ("Overdraft fees per year (habit)", kes(h["habit_per_year"]), "credit.headline"),
            (f"{best['name']} cost per year", kes(h["best_per_year"]), "credit.headline"),
            ("**Yearly saving**", f"**{kes(h['saving_per_year'])}**", "credit.headline"),
            ("Personal money now (per week)", kes(h["current"]), "credit.weekly_personal"),
            ("**Weekly withdrawal cap**",
             f"**{kes(best['cap'])}** (down {kes(cut)}, {cut / h['current']:.0%})"
             if not best["fits_now"] else "not needed", "credit.personal_cap"),
        ]
    return rows


def test_rows(tests):
    if tests is None:
        return [("Test results", "not refreshed: run `py run_tests.py`", "run_tests.py")]
    return [
        ("Unit tests", f"{tests['passed']} passed, {tests['failed']} failed", "pytest"),
        ("Attack scorecard", f"{tests['blocked']} of {tests['attacks']} blocked", "attacks.py"),
        ("Task success, scripted mock AI", f"{tests['scripted'][0]}/{tests['scripted'][1]} = "
         f"{tests['scripted'][0] / tests['scripted'][1]:.0%}", "evaluation.py"),
        ("Task success, offline keyword planner", f"{tests['planner'][0]}/{tests['planner'][1]} = "
         f"{tests['planner'][0] / tests['planner'][1]:.0%}", "evaluation.py"),
        ("Number verification", tests["numbers"], "agent.unverified_numbers"),
    ]


def table(rows):
    return (["| Figure | Value | Source |", "|---|---|---|"]
            + [f"| {name} | {value} | `{source}` |" for name, value, source in rows])


def write(tests=None):
    lines = ["# Duka Copilot - key numbers", "",
             f"Generated from the code on {datetime.now():%Y-%m-%d %H:%M} with the **default "
             "settings**. Quote only these figures in the deck, docs and demo. Regenerate with "
             "`py run_tests.py`.", "",
             "All data is synthetic (fixed seed). SACCO and bank rates are illustrative, not "
             "real quotes. Categorisation rules were written knowing the data generator, so "
             "real-world accuracy would be lower.", "",
             "## Headline: Amina's credit", ""]
    lines += table(headline_rows())
    lines += ["", "## Tests and evidence", ""] + table(test_rows(tests))
    for b, rows in business_rows():
        lines += ["", f"## {BUSINESSES[b]['label']}", ""] + table(rows)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(f"Saved: {write()}")
