import pytest

from analytics import true_positions
from credit import (SACCO_ANNUAL_RATE, compare_options, effective_annual_cost, headline,
                    instalment_loan, micro_loan, overdraft, plain_advice, recommend,
                    weekly_personal, with_personal_cap)
from forecast import build_model
from settings import defaults


def test_overdraft_cost_30_days():
    fee, payments = overdraft(10_000, 30)
    assert fee == 0
    assert payments == [(30, pytest.approx(10_000 * 1.01 * 1.15))]       # KES 11,615


def test_micro_loan_one_period_and_renewed():
    assert sum(p for _, p in micro_loan(10_000, 30)[1]) == pytest.approx(10_750)
    _, payments = micro_loan(10_000, 180)                                # renewed 6 times
    assert len(payments) == 6
    assert sum(p for _, p in payments) == pytest.approx(10_000 + 6 * 750)


def test_instalment_loan_matches_the_textbook_formula():
    fee, payments = instalment_loan(SACCO_ANNUAL_RATE, 0.01)(10_000, 360)
    r = SACCO_ANNUAL_RATE / 12
    assert fee == pytest.approx(100)
    assert len(payments) == 12
    assert payments[0][1] == pytest.approx(10_000 * r / (1 - (1 + r) ** -12))   # ~888.49


def test_effective_annual_cost():
    assert effective_annual_cost(100, [(365, 110)]) == pytest.approx(0.10, abs=1e-4)
    assert effective_annual_cost(100, [(365, 100)]) == pytest.approx(0.0, abs=1e-6)


def test_compare_options_sacco_cheapest():
    options = {o["name"]: o for o in compare_options(45_000, 180)}
    assert min(options.values(), key=lambda o: o["cost"])["name"] == "SACCO loan*"
    assert options["Mobile overdraft"]["annual_cost"] > options["Mobile micro-loan"]["annual_cost"]
    assert all(o["total_repaid"] > 45_000 for o in options.values())


@pytest.fixture(scope="module")
def amina_now(amina_rows):
    last = amina_rows[-1]["date"]
    return build_model(amina_rows), last, true_positions(amina_rows, [last])[last]


def test_need_above_cap_recommends_largest_affordable_within_cap(amina_now):
    model, last, position = amina_now
    amount, options, best = recommend(model, last, position, needed=100_000,
                                      loan_cap=60_000, days=180, buffer=1_000)
    assert amount == 60_000                       # the cap, never more
    assert best["name"] == "SACCO loan*" and best["cap"] is not None
    h = {"best": best, "loan_cap": 60_000, "needed": 100_000, "amount": amount, "days": 180,
         "current": weekly_personal(model), "over_cap": True}
    advice = plain_advice(h)
    assert "more than your loan cap of KES 60,000" in advice
    assert "largest affordable loan within your cap is KES 60,000" in advice
    assert "a week" in advice                     # comes with the weekly withdrawal cap
    assert not any(w in advice.lower() for w in ("raise", "increase", "higher cap"))


def test_cap_too_small_says_so_plainly():
    h = headline(cfg=dict(defaults("amina_grocery"), loan_cap=20_000))
    assert h["amount"] <= 20_000 and h["over_cap"] and h["best"] is None
    advice = plain_advice(h)
    assert "can be repaid safely" in advice and "raise" not in advice.lower()


def test_default_headline_stays_within_cap():
    h = headline(cfg=defaults("amina_grocery"))
    assert h["amount"] <= h["loan_cap"] == 60_000 and not h["over_cap"]
    assert h["buffer"] == 1_000 and h["best"]["name"] == "SACCO loan*"


def test_personal_cap_scales_personal_money(amina_rows):
    model = build_model(amina_rows)
    assert weekly_personal(with_personal_cap(model, 5_000)) == pytest.approx(5_000)
