"""Payment schedules for recurring expenses: next due date, countdown, overdue.

One model, used everywhere a recurring expense is shown or forecast:

  frequency   'daily' | 'weekly' | 'monthly' | 'annual'  (the unit)
  interval    every N units, e.g. weekly x 2 = every two weeks
  last_paid   the date the owner last paid it (optional)
  next_due    the next payment date; derived from last_paid when known

The legacy cadences are the same thing with a fixed multiplier:
'biweekly' = weekly x 2, 'quarterly' = monthly x 3.

Month and year steps keep the anchor day and clamp to the month's end, so a
payment on the 31st falls on 28/29 Feb and returns to the 31st in March.
Countdowns are always computed from today at read time and never stored, so
they cannot go stale.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterator, Optional, Union

FREQUENCIES = ("daily", "weekly", "monthly", "annual")
CADENCES = ("daily", "weekly", "biweekly", "monthly", "quarterly", "annual")
MAX_INTERVAL = 365

# cadence -> (unit, multiplier)
_UNITS = {
    "daily": ("day", 1),
    "weekly": ("day", 7),
    "biweekly": ("day", 14),
    "monthly": ("month", 1),
    "quarterly": ("month", 3),
    "annual": ("month", 12),
}

DateLike = Union[date, datetime, str]


class RecurrenceError(ValueError):
    """An invalid schedule (unknown frequency, bad interval or date)."""


def to_date(value: Optional[DateLike]) -> Optional[date]:
    """Accept a date, datetime or 'YYYY-MM-DD...' string; None stays None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as e:
        raise RecurrenceError(f"Not a valid date: {value!r}") from e


def validate(cadence: str, interval: int = 1, day_of_month: Optional[int] = None) -> None:
    if cadence not in _UNITS:
        raise RecurrenceError(f"Unknown frequency {cadence!r}; use one of {', '.join(CADENCES)}.")
    if not isinstance(interval, int) or isinstance(interval, bool) or not 1 <= interval <= MAX_INTERVAL:
        raise RecurrenceError(f"Interval must be a whole number from 1 to {MAX_INTERVAL}.")
    if day_of_month is not None and not 1 <= int(day_of_month) <= 31:
        raise RecurrenceError("Day of month must be between 1 and 31.")


def _add_months(d: date, months: int, anchor_day: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def step(current: DateLike, cadence: str, interval: int = 1,
         anchor_day: Optional[int] = None, times: int = 1) -> date:
    """The date `times` periods after `current` (negative goes back)."""
    validate(cadence, interval)
    current = to_date(current)
    unit, mult = _UNITS[cadence]
    n = mult * interval * times
    if unit == "day":
        return current + timedelta(days=n)
    return _add_months(current, n, anchor_day or current.day)


def next_due_after_payment(last_paid: DateLike, cadence: str, interval: int = 1,
                           day_of_month: Optional[int] = None) -> date:
    """Next payment date for a payment made on `last_paid`."""
    return step(last_paid, cadence, interval, day_of_month)


def occurrences(next_due: DateLike, cadence: str, interval: int = 1,
                day_of_month: Optional[int] = None, *, until: DateLike,
                end_date: Optional[DateLike] = None) -> Iterator[date]:
    """Every due date from next_due up to and including `until` (and end_date).

    Each date is computed from next_due directly (not from the previous
    date), so month-end clamping never drifts: 31 Jan, 28 Feb, 31 Mar."""
    start = to_date(next_due)
    stop = to_date(until)
    end = to_date(end_date)
    if end is not None and end < stop:
        stop = end
    anchor = day_of_month or start.day
    k = 0
    while True:
        d = step(start, cadence, interval, anchor, times=k)
        if d > stop:
            return
        yield d
        k += 1


@dataclass(frozen=True)
class DueStatus:
    next_due: date
    days_until: int            # negative when overdue
    state: str                 # 'overdue' | 'due_today' | 'upcoming'

    @property
    def days_overdue(self) -> int:
        return max(0, -self.days_until)

    @property
    def label(self) -> str:
        if self.state == "overdue":
            n = self.days_overdue
            return f"Overdue by {n} day{'s' if n != 1 else ''}"
        if self.state == "due_today":
            return "Due today"
        n = self.days_until
        return f"Due in {n} day{'s' if n != 1 else ''}"


def due_status(next_due: DateLike, today: Optional[DateLike] = None) -> DueStatus:
    """Countdown to next_due relative to today (local date)."""
    nd = to_date(next_due)
    today = to_date(today) or date.today()
    days = (nd - today).days
    state = "overdue" if days < 0 else ("due_today" if days == 0 else "upcoming")
    return DueStatus(next_due=nd, days_until=days, state=state)


def describe(cadence: str, interval: int = 1) -> str:
    """Human label: 'Monthly', 'Every 2 weeks', 'Every 3 months'."""
    unit, mult = _UNITS.get(cadence, ("day", 1))
    total = mult * (interval or 1)
    if unit == "day":
        if total == 1:
            return "Daily"
        if total % 7 == 0:
            w = total // 7
            return "Weekly" if w == 1 else f"Every {w} weeks"
        return f"Every {total} days"
    if total == 1:
        return "Monthly"
    if total % 12 == 0:
        y = total // 12
        return "Yearly" if y == 1 else f"Every {y} years"
    return f"Every {total} months"


# ---- variable amounts ----
# For a variable expense the owner enters an approximate MONTHLY AVERAGE;
# each payment is expected within +/-10% of its share of that average.
VARIABLE_TOLERANCE = 0.10
_DAYS_PER_MONTH = 365.25 / 12


def months_per_period(cadence: str, interval: int = 1) -> float:
    unit, mult = _UNITS[cadence]
    n = mult * (interval or 1)
    return n / _DAYS_PER_MONTH if unit == "day" else float(n)


def instalment_amount(amount_minor: int, cadence: str, interval: int = 1,
                      is_variable: bool = False) -> int:
    """Expected amount of one payment. A fixed expense's amount is per
    payment; a variable expense's amount is a monthly average, scaled to
    the payment period (monthly bills are unchanged)."""
    if not is_variable:
        return int(amount_minor)
    return int(round(amount_minor * months_per_period(cadence, interval)))


def amount_range(expected_minor: int, is_variable: bool) -> tuple:
    """(low, high) for one payment: +/-10% when variable, exact otherwise."""
    if not is_variable:
        return int(expected_minor), int(expected_minor)
    return (int(round(expected_minor * (1 - VARIABLE_TOLERANCE))),
            int(round(expected_minor * (1 + VARIABLE_TOLERANCE))))
