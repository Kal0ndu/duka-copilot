"""Write every headline figure and test result into docs/, from the code.

    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python scripts/key_numbers.py

Produces docs/key_numbers.md (figures for the deck and demo) and
docs/test_results.md (test, attack and task-success scorecards), so the deck
can't drift from the code: quote only these files and regenerate after any
change. Uses a fresh database built from the sample statements and the
DEFAULT owner settings, never the live data/duka.db.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tests.fixtures_duka import build_world  # noqa: E402

DOCS = ROOT / "docs"
BUSINESSES = [
    ("Amina's Grocery (Nairobi)", "amina_grocery_statement.csv"),
    ("Grace Beauty Salon (Kisumu)", "grace_salon_statement.csv"),
    ("Otieno Boda Services (Nakuru)", "otieno_transport_statement.csv"),
]


def kes(minor_or_kes, minor=False):
    v = minor_or_kes / 100 if minor else minor_or_kes
    return f"KES {v:,.0f}"


def business_figures(name, statement):
    import sqlite3
    from core.cost_engine import compare_financing, recommend_loan
    from core.financial_health import compute_business_health
    from core.forecaster import detect_shortfalls, forecast_backtest, forecast_balance
    from core.owner_settings import load_settings

    w = build_world(tempfile.mkdtemp(), statement=statement)
    db, bid = w.db, w.amina
    with sqlite3.connect(db) as conn:
        n, start, end = conn.execute(
            "SELECT COUNT(*), MIN(local_date), MAX(local_date) FROM transaction_ledger WHERE business_id = ?",
            (bid,)).fetchone()
        review = conn.execute("SELECT COUNT(*) FROM transaction_ledger WHERE business_id = ? AND needs_review = 1",
                              (bid,)).fetchone()[0]
        flagged = conn.execute("SELECT COUNT(*) FROM injection_finding").fetchone()[0]
    s = load_settings(db, bid)
    health = compute_business_health(SimpleNamespace(period="month"), bid, db)
    f = forecast_balance(SimpleNamespace(horizon_days=14), bid, db)
    sf = detect_shortfalls(SimpleNamespace(forecast_run_id=f["forecast_run_id"]), bid, db)
    bt = forecast_backtest(SimpleNamespace(horizon_days=14), bid, db)
    offers = compare_financing(SimpleNamespace(amount_minor=4_500_000, term_days=180, purpose="stock"),
                               bid, db)["offers"]
    rl = recommend_loan(SimpleNamespace(amount_minor=None, term_days=180, language="en"), bid, db)

    rows = [
        ("Statement period", f"{start} to {end}", "`transaction_ledger`"),
        ("Transactions loaded", f"{n:,}", "`core.ingestion.StatementIngestor`"),
        ("Rows the owner should review (teach once)", f"{review:,} ({review / n:.0%})", "`needs_review`"),
        ("Rows flagged as prompt injection", f"{flagged}", "`injection_finding`"),
        ("Money in, last 30 days", kes(health["revenue_kes"]), "`compute_business_health`"),
        ("Business costs, last 30 days", kes(health["costs_kes"]), "`compute_business_health`"),
        ("Margin, last 30 days", f"{health['margin_pct']}%", "`compute_business_health`"),
        ("Personal spending share of money out", f"{health['personal_mix_pct']}%", "`compute_business_health`"),
        ("Mobile-money balance (last day)", kes(f["balance_kes"]), "`forecaster.true_position`"),
        ("Overdraft owed, with fees", kes(f["overdraft_owed_kes"]), "`forecaster.overdraft_owed_by_day`"),
        ("**True position** (balance minus overdraft owed)", f"**{kes(f['true_position_kes'])}**",
         "`forecaster.true_position`"),
        ("Safety buffer / caps (per payment / day / loan)",
         f"{kes(s.safety_buffer_minor, True)} / {kes(s.per_txn_cap_minor, True)} / "
         f"{kes(s.daily_cap_minor, True)} / {kes(s.loan_cap_minor, True)}", "`owner_settings.defaults`"),
        ("14-day forecast",
         (f"ALERT on {sf['shortfall_count']} of 14 days from {sf['first_date']}; "
          f"needs about {kes(sf['amount_needed_kes'])}") if sf["shortfall_count"] else "stays above the buffer",
         "`forecast_balance + detect_shortfalls`"),
    ]
    if "error" not in bt:
        rows.append(("Forecast backtest (last 14 days hidden)",
                     f"sales {bt['sales_error_pct']:+.1f}%; last day off by {kes(abs(bt['final_balance_error_kes']))}; "
                     f"{bt['days_inside_range']}/14 days inside range", "`forecast_backtest`"))
    for o in offers:
        rows.append((f"KES 45,000 / 180 days: {o['product_name']}",
                     f"cost {kes(o['tcc_minor'], True)}, {o['ear_pct']}% a year", "`compare_financing`"))
    best = rl.get("best")
    rows.append(("Loan fit check (default settings)",
                 (f"{best['product_name']} of {kes(rl['amount_minor'], True)}"
                  + ("" if best["fits_now"] else
                     f", if personal money stays under {kes(best['max_weekly_personal_minor'], True)} a week "
                     f"(now {kes(rl['weekly_personal_now_minor'], True)})"))
                 if best else ("no loan needed" if rl.get("no_need") else "no loan within the cap fits"),
                 "`recommend_loan`"))
    return name, rows


def pytest_counts():
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-W", "ignore"],
                         cwd=ROOT, env=env, capture_output=True, text=True).stdout
    last = [l for l in out.splitlines() if " passed" in l or " failed" in l]
    return last[-1].strip("= ") if last else "pytest did not run"


def main():
    from tests.eval.task_eval import run_offline, run_scripted
    from tests.security.attack_suite import ATTACKS

    import shutil
    from dataclasses import replace
    base = build_world(tempfile.mkdtemp())

    def fresh():
        db = str(Path(tempfile.mkdtemp()) / "duka.db")
        shutil.copy(base.db, db)
        return replace(base, db=db)

    attacks = []
    for name, fn in ATTACKS:
        try:
            blocked, detail = fn(fresh())
        except Exception as e:
            blocked, detail = False, f"crashed: {type(e).__name__}: {e}"
        attacks.append((name, blocked, detail))
    scripted = run_scripted(fresh)
    offline = run_offline()
    tests = pytest_counts()
    when = datetime.now().strftime("%Y-%m-%d %H:%M")

    blocked_n = sum(b for _, b, _ in attacks)
    scripted_n = sum(ok for _, ok, _ in scripted)
    offline_n = sum(ok for _, ok, _ in offline)

    lines = [
        "# Duka Copilot - key numbers", "",
        f"Generated from the code on {when} with the **default owner settings**. Quote only these figures "
        "in the deck, docs and demo. Regenerate with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python "
        "scripts/key_numbers.py`.", "",
        "All data is synthetic. SACCO and bank rates are illustrative, not real quotes. The offline "
        "planner's questions were written alongside it, so real-world accuracy would be lower.", "",
        "## Tests and evidence", "",
        "| Figure | Value | Source |", "|---|---|---|",
        f"| Automated tests | {tests} | `pytest` |",
        f"| Attack scorecard | {blocked_n} of {len(attacks)} blocked | `tests/security/attack_suite.py` |",
        f"| Task success, scripted AI | {scripted_n}/{len(scripted)} = {scripted_n / len(scripted):.0%} | "
        "`tests/eval/task_eval.py` |",
        f"| Task success, offline keyword planner (EN + SW) | {offline_n}/{len(offline)} = "
        f"{offline_n / len(offline):.0%} | `tests/eval/task_eval.py` |", "",
    ]
    for name, statement in BUSINESSES:
        title, rows = business_figures(name, statement)
        lines += [f"## {title}", "", "| Figure | Value | Source |", "|---|---|---|"]
        lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
        lines.append("")
    DOCS.mkdir(exist_ok=True)
    (DOCS / "key_numbers.md").write_text("\n".join(lines), encoding="utf-8")

    res = ["# Duka Copilot - test results", "", f"Generated {when}. {tests}.", "",
           f"## Attack scorecard: {blocked_n} of {len(attacks)} blocked", "",
           "Each attack runs against the real code on its own copy of the database. Where the database's "
           "own triggers already refuse a write, a second variant drops the trigger first (as someone with "
           "the raw file could) to show the signed approval code / hash chain still catches it.", "",
           "| # | Attack | Result | Detail |", "|---|---|---|---|"]
    res += [f"| {i} | {n} | {'BLOCKED' if b else '**NOT BLOCKED**'} | {str(d)[:110]} |"
            for i, (n, b, d) in enumerate(attacks, 1)]
    res += ["", f"## Task success, scripted AI: {scripted_n}/{len(scripted)}", "",
            "| Task | Result |", "|---|---|"]
    res += [f"| {n} | {'pass' if ok else '**FAIL**'} |" for n, ok, _ in scripted]
    res += ["", f"## Offline planner (no AI): {offline_n}/{len(offline)}", "",
            "| Question | Tools chosen | Result |", "|---|---|---|"]
    res += [f"| {q} | {', '.join(t) or '-'} | {'pass' if ok else '**FAIL**'} |" for q, ok, t in offline]
    (DOCS / "test_results.md").write_text("\n".join(res) + "\n", encoding="utf-8")
    print(f"Wrote docs/key_numbers.md and docs/test_results.md: {tests}; attacks {blocked_n}/{len(attacks)}; "
          f"scripted {scripted_n}/{len(scripted)}; offline {offline_n}/{len(offline)}")


if __name__ == "__main__":
    main()
