"""Recurring expenses end to end on a real migrated database: CRUD with
ownership, payment recording, and their effect on the forecast, the AI's
business context and working capital."""
import sqlite3
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from core.business_setup import BusinessSetup, ExpenseError, ExpenseNotFound
from core.expense_tracker import RecurringExpenseManager
from core.forecaster import forecast_balance
from core.working_capital import working_capital_position
from tests.fixtures_duka import build_world

TODAY = date(2026, 10, 19)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("exp"))


@pytest.fixture
def setup(world):
    s = BusinessSetup(world.db)
    yield s
    with sqlite3.connect(world.db) as conn:   # each test starts with no expenses
        conn.execute("DELETE FROM recurring_expense_instance")
        conn.execute("DELETE FROM recurring_expense")


def test_last_payment_sets_next_due_and_countdown(world, setup):
    eid = setup.add_recurring_expense(world.amina, "rent", "Shop rent", 1_500_000, "monthly",
                                      last_paid_date="2026-10-05", today=TODAY)
    e = setup.get_recurring_expenses(world.amina, today=TODAY)[0]
    assert e["expense_id"] == eid
    assert (e["last_paid_date"], e["next_due"]) == ("2026-10-05", "2026-11-05")
    assert (e["due_state"], e["days_until"], e["due_label"]) == ("upcoming", 17, "Due in 17 days")


def test_overdue_is_reported_in_days(world, setup):
    setup.add_recurring_expense(world.amina, "utilities", "Water", 140_000, "monthly",
                                last_paid_date="2026-09-10", today=TODAY)
    e = setup.get_recurring_expenses(world.amina, today=TODAY)[0]
    assert e["next_due"] == "2026-10-10"
    assert (e["due_state"], e["days_overdue"], e["due_label"]) == ("overdue", 9, "Overdue by 9 days")


def test_every_two_weeks(world, setup):
    setup.add_recurring_expense(world.amina, "salary", "Helper wages", 400_000, "weekly",
                                interval_count=2, last_paid_date="2026-10-16", today=TODAY)
    e = setup.get_recurring_expenses(world.amina, today=TODAY)[0]
    assert (e["next_due"], e["frequency_label"]) == ("2026-10-30", "Every 2 weeks")


def test_recording_a_payment_moves_next_due(world, setup):
    eid = setup.add_recurring_expense(world.amina, "rent", "Rent", 1_500_000, "monthly", day_of_month=5,
                                      last_paid_date="2026-09-05", today=TODAY)
    assert setup.get_recurring_expenses(world.amina, today=TODAY)[0]["due_state"] == "overdue"
    e = setup.record_expense_payment(world.amina, eid, "2026-10-07", today=TODAY)
    assert (e["last_paid_date"], e["next_due"], e["times_paid"]) == ("2026-10-07", "2026-11-05", 1)
    with sqlite3.connect(world.db) as conn:
        assert conn.execute("SELECT due_date, status FROM recurring_expense_instance WHERE expense_id = ?",
                            (eid,)).fetchone() == ("2026-10-05", "late")


def test_paying_early_still_moves_past_the_instalment(world, setup):
    eid = setup.add_recurring_expense(world.amina, "rent", "Rent", 1_500_000, "monthly", day_of_month=1,
                                      next_due="2026-11-01", today=TODAY)
    e = setup.record_expense_payment(world.amina, eid, "2026-10-19", today=TODAY)
    assert e["next_due"] == "2026-12-01"


def test_update_recalculates_and_delete_hides(world, setup):
    eid = setup.add_recurring_expense(world.amina, "rent", "Rent", 1_500_000, "monthly",
                                      last_paid_date="2026-10-01", today=TODAY)
    e = setup.update_recurring_expense(world.amina, eid, cadence="weekly", today=TODAY)
    assert e["next_due"] == "2026-10-08"
    e = setup.update_recurring_expense(world.amina, eid, description="Rent (new shop)", today=TODAY)
    assert (e["description"], e["next_due"]) == ("Rent (new shop)", "2026-10-08")
    setup.delete_recurring_expense(world.amina, eid)
    assert setup.get_recurring_expenses(world.amina) == []


def test_another_business_cannot_touch_the_expense(world, setup):
    eid = setup.add_recurring_expense(world.amina, "rent", "Rent", 1_500_000, "monthly", today=TODAY)
    with pytest.raises(ExpenseNotFound):
        setup.update_recurring_expense(world.other, eid, amount_minor=1)
    with pytest.raises(ExpenseNotFound):
        setup.delete_recurring_expense(world.other, eid)
    with pytest.raises(ExpenseNotFound):
        setup.record_expense_payment(world.other, eid)
    assert setup.get_recurring_expenses(world.other) == []
    assert setup.get_recurring_expenses(world.amina)[0]["amount_minor"] == 1_500_000


@pytest.mark.parametrize("kwargs, msg", [
    (dict(amount_minor=0), "more than zero"),
    (dict(description="  "), "describe"),
    (dict(cadence="hourly"), "Unknown frequency"),
    (dict(interval_count=0), "Interval"),
    (dict(last_paid_date="2026-12-01"), "future"),
    (dict(expense_type="bribe"), "Unknown expense type"),
])
def test_invalid_input_is_rejected(world, setup, kwargs, msg):
    args = dict(business_id=world.amina, expense_type="rent", description="Rent",
                amount_minor=100_000, cadence="monthly", today=TODAY)
    args.update(kwargs)
    with pytest.raises(ExpenseError, match=msg):
        setup.add_recurring_expense(**args)


def test_schedule_handles_month_ends_and_lists_overdue(world, setup):
    setup.add_recurring_expense(world.amina, "rent", "Month-end rent", 100_000, "monthly",
                                next_due="2026-08-31", today=TODAY)
    sched = RecurringExpenseManager(world.db).generate_schedule(world.amina, 2, today=TODAY)
    assert [(s["due_date"], s["status"]) for s in sched] == [
        ("2026-08-31", "overdue"), ("2026-09-30", "overdue"),
        ("2026-10-31", "expected"), ("2026-11-30", "expected")]


def _forecast(world):
    return forecast_balance(SimpleNamespace(horizon_days=14), world.amina, world.db)


def test_expense_changes_the_forecast(world, setup):
    base = _forecast(world)
    as_of = date.fromisoformat(base["as_of_date"])
    eid = setup.add_recurring_expense(world.amina, "rent", "Big rent", 5_000_000, "monthly",
                                      next_due=(as_of + timedelta(days=3)).isoformat())
    with_rent = _forecast(world)
    assert [o["label"] for o in with_rent["obligations"] if o["source"] == "recurring_expense"] == ["Big rent"]
    assert with_rent["lowest_low_kes"] <= base["lowest_low_kes"] - 49_000

    setup.update_recurring_expense(world.amina, eid, amount_minor=1_000_000)
    smaller = _forecast(world)
    assert with_rent["lowest_low_kes"] < smaller["lowest_low_kes"] < base["lowest_low_kes"]

    setup.delete_recurring_expense(world.amina, eid)
    assert _forecast(world)["lowest_low_kes"] == base["lowest_low_kes"]


def test_overdue_expense_hits_day_one(world, setup):
    base = _forecast(world)
    as_of = date.fromisoformat(base["as_of_date"])
    setup.add_recurring_expense(world.amina, "rent", "Unpaid rent", 3_000_000, "monthly",
                                next_due=(as_of - timedelta(days=10)).isoformat())
    f = _forecast(world)
    day1 = (as_of + timedelta(days=1)).isoformat()
    assert [o["due_date"] for o in f["obligations"] if o["label"] == "Unpaid rent"] == [day1]
    assert f["points"][0]["expected_kes"] < base["points"][0]["expected_kes"] - 29_000


def test_variable_expense_is_sampled_within_ten_percent(world, setup):
    base = _forecast(world)
    as_of = date.fromisoformat(base["as_of_date"])
    setup.add_recurring_expense(world.amina, "utilities", "Power", 4_000_000, "monthly", is_variable=True,
                                next_due=(as_of + timedelta(days=2)).isoformat())
    o = next(o for o in RecurringExpenseManager(world.db).obligations_between(
        world.amina, as_of, as_of + timedelta(days=14)) if o["label"] == "Power")
    assert (o["amount_low_minor"], o["amount_minor"], o["amount_high_minor"], o["tolerance_pct"]) == \
        (3_600_000, 4_000_000, 4_400_000, 10)
    f = _forecast(world)
    drop = base["points"][-1]["expected_kes"] - f["points"][-1]["expected_kes"]
    assert 36_000 * 0.95 <= drop <= 44_000 * 1.05


def test_ai_context_sees_expenses_with_countdown(world, setup):
    from auth.user_context import UserContext
    setup.add_recurring_expense(world.amina, "rent", "Rent soon", 1_000_000, "monthly",
                                next_due=(date.today() + timedelta(days=4)).isoformat())
    setup.add_recurring_expense(world.amina, "utilities", "Water late", 50_000, "monthly",
                                next_due=(date.today() - timedelta(days=2)).isoformat())
    obl = {o["label"]: o for o in UserContext(world.amina_user, world.amina, world.db).refresh()["obligations"]}
    assert (obl["Rent soon"]["days_until_due"], obl["Rent soon"]["status"]) == (4, "upcoming")
    assert (obl["Water late"]["days_overdue"], obl["Water late"]["status"]) == (2, "overdue")


def test_working_capital_uses_records(world, setup):
    wc0 = working_capital_position(world.db, world.amina, today=TODAY)
    setup.add_recurring_expense(world.amina, "rent", "Overdue rent", 2_000_000, "monthly",
                                next_due="2026-10-10", today=TODAY)
    setup.add_recurring_expense(world.amina, "utilities", "Power", 1_000_000, "monthly", is_variable=True,
                                next_due="2026-10-25", today=TODAY)
    wc = working_capital_position(world.db, world.amina, today=TODAY)
    assert wc["overdue_bills_minor"] - wc0["overdue_bills_minor"] == 2_000_000
    assert wc["current_liabilities_minor"] - wc0["current_liabilities_minor"] == 2_000_000
    assert wc["net_working_capital_minor"] == wc0["net_working_capital_minor"] - 2_000_000
    # Window 19 Oct - 18 Nov: rent's next instalment (10 Nov) and power (25 Oct);
    # the high case adds 10% to the variable power bill only.
    assert wc["bills_due_minor"] - wc0["bills_due_minor"] == 2_000_000 + 1_000_000
    assert wc["bills_due_high_minor"] - wc0["bills_due_high_minor"] == 2_000_000 + 1_100_000
    assert wc["liquidity_gap_minor"] == (wc["cash_minor"] + wc["invoices_due_minor"]
                                         - wc["current_liabilities_minor"] - wc["bills_due_minor"])
