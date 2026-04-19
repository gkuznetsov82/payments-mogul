"""Scenario start date + tick -> date mapping (spec 40 §scenario.start_date).

start_date is "today" (resolves to local server date at run start, then frozen)
or a fixed YYYY-MM-DD literal. Tick→date mapping is deterministic:

    date(tick_id) = start_date + tick_id days
"""

from __future__ import annotations

from datetime import date as _date_t, timedelta


class ScenarioDateError(Exception):
    pass


class ScenarioDates:
    def __init__(self, start_date: _date_t) -> None:
        self.start_date = start_date

    @classmethod
    def from_config(cls, raw: str | None, *, today_fn=None) -> "ScenarioDates":
        """Resolve from the raw scenario.start_date string. `today_fn` is an
        injection point for testing — defaults to date.today()."""
        if today_fn is None:
            today_fn = _date_t.today
        if raw is None:
            # No start_date set: fall back to "today" so v0 configs still work.
            return cls(today_fn())
        if raw == "today":
            return cls(today_fn())
        try:
            return cls(_date_t.fromisoformat(raw))
        except ValueError as exc:
            raise ScenarioDateError(
                f"start_date {raw!r} is not 'today' or YYYY-MM-DD: {exc}"
            ) from exc

    def date_for_tick(self, tick_id: int) -> _date_t:
        if tick_id < 0:
            raise ScenarioDateError(f"tick_id must be >= 0, got {tick_id}")
        return self.start_date + timedelta(days=tick_id)
