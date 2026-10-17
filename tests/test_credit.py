import pytest

from credit import (SACCO_ANNUAL_RATE, compare_options, effective_annual_cost, instalment_loan,
                    micro_loan, overdraft, weekly_personal, with_personal_cap)
from forecast import build_model


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


def test_personal_cap_scales_personal_money(amina_rows):
    model = build_model(amina_rows)
    assert weekly_personal(with_personal_cap(model, 5_000)) == pytest.approx(5_000)
