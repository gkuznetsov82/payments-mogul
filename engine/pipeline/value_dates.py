"""Deterministic value-date resolution per spec 33 / 40 §value-date policies.

Policies:
  same_day                 -> origin_date (offset must be omitted or 0)
  next_day_plus_x          -> origin_date + (offset + 1) calendar days
  next_working_day_plus_x  -> next working day after origin, plus `offset` further
                              working days (calendar-aware via Calendar.is_working_day)
  next_month_day_plus_x    -> first day of next month + offset days
"""

from __future__ import annotations

from datetime import date as _date_t, timedelta
from typing import Optional

from engine.calendars.calendar import Calendar


class ValueDateError(Exception):
    pass


def resolve_value_date(origin_date: _date_t,
                       policy: str,
                       offset_days: Optional[int] = None,
                       calendar: Optional[Calendar] = None) -> _date_t:
    """Resolve a value/settlement date for a given policy + offset."""
    if policy == "same_day":
        return origin_date

    if offset_days is None:
        raise ValueDateError(
            f"value_date_policy='{policy}' requires offset_days (spec 40 §value-date offset rules)"
        )

    if policy == "next_day_plus_x":
        return origin_date + timedelta(days=offset_days + 1)

    if policy == "next_working_day_plus_x":
        if calendar is None:
            # Without a calendar, fall back to calendar-day arithmetic; behavior is
            # documented in tests so determinism is preserved.
            return origin_date + timedelta(days=offset_days + 1)
        # Find the next working day strictly after origin, then advance offset more.
        d = origin_date + timedelta(days=1)
        while not calendar.is_working_day(d):
            d += timedelta(days=1)
        remaining = offset_days
        while remaining > 0:
            d += timedelta(days=1)
            if calendar.is_working_day(d):
                remaining -= 1
        return d

    if policy == "next_month_day_plus_x":
        # First of next month + offset days.
        if origin_date.month == 12:
            first_next = _date_t(origin_date.year + 1, 1, 1)
        else:
            first_next = _date_t(origin_date.year, origin_date.month + 1, 1)
        return first_next + timedelta(days=offset_days)

    raise ValueDateError(f"unknown value_date_policy: {policy!r}")
