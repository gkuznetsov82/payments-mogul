"""Working-day calendar resolver (spec 40 §calendars).

A Calendar object answers `is_working_day(date)` by combining:
  - weekend profile (`sat_sun` or `fri_sat`)
  - inline `non_working_overrides` from the calendar config
  - holidays from configured sources subject to `holiday_source_policy`:
      * local_only — only inline + local file
      * nager_only — only inline + Nager.Date
      * local_override_then_nager — inline + local UNION + Nager.Date

(Inline `non_working_overrides` always apply regardless of policy — they are
authoring-time absolutes per spec.)
"""

from __future__ import annotations

from datetime import date as _date_t
from typing import Optional

from engine.config.models import CalendarConfig
from engine.calendars.local import LocalHolidaySource
from engine.calendars.nager import NagerDateHolidaySource


class CalendarError(Exception):
    pass


# Python date.weekday(): Monday=0..Sunday=6. Spec: sat_sun → {Sat=5, Sun=6}; fri_sat → {Fri=4, Sat=5}.
_WEEKEND_DAYS = {
    "sat_sun": {5, 6},
    "fri_sat": {4, 5},
}


class Calendar:
    def __init__(self,
                 cfg: CalendarConfig,
                 local_source: Optional[LocalHolidaySource] = None,
                 nager_source: Optional[NagerDateHolidaySource] = None) -> None:
        self.cfg = cfg
        self.calendar_id = cfg.calendar_id
        self.weekend_profile = cfg.weekend_profile
        self._inline_non_working: set[_date_t] = {
            _date_t.fromisoformat(d) for d in (cfg.non_working_overrides or [])
        }
        self.local_source = local_source
        self.nager_source = nager_source

    def is_weekend(self, on_date: _date_t) -> bool:
        return on_date.weekday() in _WEEKEND_DAYS[self.weekend_profile]

    def is_holiday(self, on_date: _date_t) -> bool:
        if on_date in self._inline_non_working:
            return True
        policy = self.cfg.holiday_source_policy
        # Local file: always considered (when source exists), regardless of nager presence.
        if policy in ("local_only", "local_override_then_nager") and self.local_source is not None:
            if on_date in self.local_source.holidays_for(self.calendar_id):
                return True
        # Nager: considered when policy allows.
        if policy in ("nager_only", "local_override_then_nager") and self.nager_source is not None:
            try:
                if on_date in self.nager_source.holidays_for_year(on_date.year):
                    return True
            except Exception:
                # Don't fail working-day lookup on remote source error; treat as no Nager hit.
                # (Tests should seed_year() to make Nager deterministic.)
                pass
        return False

    def is_working_day(self, on_date: _date_t) -> bool:
        if self.is_weekend(on_date):
            return False
        if self.is_holiday(on_date):
            return False
        return True
