"""Local holiday source — additive non-working dates from a local YAML file
(spec 40 §calendars §holiday_sources.local_file).

Schema (matches configs/reference/calendar_local_example.yaml):

    calendars:
      - calendar_id: "cal_global_default"
        additional_non_working_dates:
          - date: "2026-12-31"
            reason: "..."
"""

from __future__ import annotations

from datetime import date as _date_t
from pathlib import Path

import yaml


class LocalHolidaySource:
    def __init__(self, dates_by_calendar: dict[str, set[_date_t]]) -> None:
        self._by_calendar = dates_by_calendar

    @classmethod
    def from_file(cls, path: str | Path) -> "LocalHolidaySource":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"local holiday file not found: {p}")
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        by_cal: dict[str, set[_date_t]] = {}
        for entry in data.get("calendars") or []:
            cid = entry.get("calendar_id")
            if not cid:
                continue
            dates: set[_date_t] = set()
            for d in entry.get("additional_non_working_dates") or []:
                ds = d.get("date") if isinstance(d, dict) else d
                if not ds:
                    continue
                if isinstance(ds, _date_t):
                    dates.add(ds)
                else:
                    try:
                        dates.add(_date_t.fromisoformat(str(ds)))
                    except ValueError:
                        continue
            by_cal[cid] = dates
        return cls(by_cal)

    def holidays_for(self, calendar_id: str) -> set[_date_t]:
        return set(self._by_calendar.get(calendar_id, set()))
