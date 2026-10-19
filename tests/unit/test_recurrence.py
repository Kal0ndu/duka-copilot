"""Payment schedule maths: next due, countdowns, month ends, variable amounts."""
from datetime import date

import pytest

from core import recurrence as r


@pytest.mark.parametrize("last, cadence, n, dom, expected", [
    ("2026-10-01", "monthly", 1, None, "2026-11-01"),
    ("2026-01-31", "monthly", 1, None, "2026-02-28"),     # clamps to month end
    ("2028-01-31", "monthly", 1, None, "2028-02-29"),     # leap year
    ("2026-10-03", "monthly", 1, 1, "2026-11-01"),        # anchored to the 1st
    ("2026-10-19", "weekly", 1, None, "2026-10-26"),
    ("2026-10-19", "weekly", 2, None, "2026-11-02"),      # every two weeks
    ("2026-10-19", "daily", 3, None, "2026-10-22"),
    ("2026-11-15", "monthly", 3, None, "2027-02-15"),     # quarterly as monthly x 3
    ("2026-11-15", "quarterly", 1, None, "2027-02-15"),   # legacy cadence
    ("2026-11-15", "biweekly", 1, None, "2026-11-29"),
    ("2028-02-29", "annual", 1, None, "2029-02-28"),
])
def test_next_due_after_payment(last, cadence, n, dom, expected):
    assert r.next_due_after_payment(last, cadence, n, dom).isoformat() == expected


def test_month_end_does_not_drift():
    dates = [d.isoformat() for d in r.occurrences("2026-01-31", "monthly", until="2026-05-31")]
    assert dates == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31"]


def test_quarterly_over_a_year_is_four_payments():
    assert len(list(r.occurrences("2026-01-15", "monthly", 3, until="2026-12-31"))) == 4


def test_occurrences_stop_at_end_date():
    got = list(r.occurrences("2026-11-15", "monthly", until="2027-12-31", end_date="2027-01-15"))
    assert [d.isoformat() for d in got] == ["2026-11-15", "2026-12-15", "2027-01-15"]


@pytest.mark.parametrize("due, state, days, label", [
    ("2026-10-24", "upcoming", 5, "Due in 5 days"),
    ("2026-10-20", "upcoming", 1, "Due in 1 day"),
    ("2026-10-19", "due_today", 0, "Due today"),
    ("2026-10-16", "overdue", -3, "Overdue by 3 days"),
])
def test_due_status_is_relative_to_today(due, state, days, label):
    st = r.due_status(due, today=date(2026, 10, 19))
    assert (st.state, st.days_until, st.label) == (state, days, label)
    assert st.days_overdue == max(0, -days)


@pytest.mark.parametrize("cadence, n, bad_dom", [("fortnightly", 1, None), ("monthly", 0, None),
                                                  ("monthly", 400, None), ("monthly", 1, 32)])
def test_invalid_schedules_are_rejected(cadence, n, bad_dom):
    with pytest.raises(r.RecurrenceError):
        r.validate(cadence, n, bad_dom)


def test_describe():
    assert r.describe("weekly", 2) == "Every 2 weeks"
    assert r.describe("monthly", 3) == "Every 3 months"
    assert r.describe("annual") == "Yearly"


def test_variable_amount_is_a_monthly_average_with_ten_percent_band():
    # Monthly bill: the average is the payment.
    assert r.instalment_amount(300_000, "monthly", 1, True) == 300_000
    assert r.amount_range(300_000, True) == (270_000, 330_000)
    # Weekly variable bill: a week's share of the monthly average.
    weekly = r.instalment_amount(300_000, "weekly", 1, True)
    assert weekly == round(300_000 * 7 / (365.25 / 12))
    # Fixed amounts are per payment and exact.
    assert r.instalment_amount(300_000, "weekly", 1, False) == 300_000
    assert r.amount_range(300_000, False) == (300_000, 300_000)
