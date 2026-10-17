from datetime import date

import pytest

from analytics import DATA, load_ledger
from forecast import HORIZON, backtest, build_model, forecast, shortfall_alert


@pytest.fixture(scope="module")
def amina_model(amina_rows):
    return build_model(amina_rows)


def flat_model(daily_error=100.0):
    """No sales, no payments: only the overdraft fee can move the balance."""
    return {"sales_avg": {w: 0.0 for w in range(7)}, "patterns": [], "other_per_day": 0.0,
            "outliers": {}, "daily_error": daily_error}


def test_finds_amina_recurring_payments(amina_model):
    found = {(p["category"], p["schedule"], p["slot"]) for p in amina_model["patterns"]}
    assert ("stock_purchase", "weekly", 0) in found      # Mondays
    assert ("stock_purchase", "weekly", 3) in found      # Thursdays
    assert ("rent", "monthly", 5) in found               # the 5th


def test_big_one_offs_are_outliers_not_spread(amina_model):
    categories = {cat for _, cat in amina_model["outliers"]}
    assert "personal_payment" in categories              # the KES 18,000 school fee


def test_range_is_ordered_and_widens(amina_rows, amina_model):
    days = forecast(amina_model, amina_rows[-1]["date"], -37_967)
    assert len(days) == HORIZON
    assert all(d["low"] <= d["expected"] <= d["high"] for d in days)
    widths = [d["high"] - d["low"] for d in days]
    assert widths == sorted(widths)


def test_negative_position_pays_daily_fee():
    days = forecast(flat_model(), date(2026, 10, 15), -1000, days=2)
    assert [d["expected"] for d in days] == [-1005, -1010]


def test_alert_only_when_low_estimate_below_buffer():
    assert shortfall_alert(forecast(flat_model(), date(2026, 10, 15), 50_000)) is None
    alert = shortfall_alert(forecast(flat_model(), date(2026, 10, 15), 1_000))
    assert alert["risky_days"] == HORIZON
    assert alert["amount_needed"] > 2_000


@pytest.mark.parametrize("business", ["amina_grocery", "grace_salon", "otieno_transport"])
def test_backtest_runs_and_sales_are_close(business):
    bt = backtest(load_ledger(DATA / f"{business}_ledger.csv"))
    assert 0 <= bt["days_inside_range"] <= bt["days"] == HORIZON
    assert abs(bt["sales_error_pct"]) < 0.10             # 14-day sales within 10%
