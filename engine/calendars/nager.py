"""Nager.Date holiday provider (spec 40 §calendars §holiday_sources.nager_date).

Per-year HTTP fetch, per-instance in-memory cache, optional `types` filter
(e.g. {"Public", "Bank"}). `country_code` is a query parameter for the lookup
only — calendar identity is not derived from country (spec 40 §calendars).

httpx is imported lazily so test environments without network deps load the
engine cleanly. `seed_year(...)` is provided for tests to bypass HTTP.
"""

from __future__ import annotations

from datetime import date as _date_t

from engine.config.models import NagerDateSource


class NagerDateHolidayError(Exception):
    pass


class NagerDateHolidaySource:
    def __init__(self, cfg: NagerDateSource) -> None:
        self.cfg = cfg
        # year -> set[date]
        self._cache: dict[int, set[_date_t]] = {}

    def holidays_for_year(self, year: int) -> set[_date_t]:
        if not self.cfg.enabled:
            return set()
        if year in self._cache:
            return set(self._cache[year])
        if not self.cfg.country_code:
            raise NagerDateHolidayError(
                "nager_date source has no country_code; either provide one or "
                "disable this source"
            )
        try:
            import httpx
        except ImportError as exc:
            raise NagerDateHolidayError(
                "nager_date source requires httpx; install it to use remote holidays"
            ) from exc
        url = f"{self.cfg.base_url.rstrip('/')}/PublicHolidays/{year}/{self.cfg.country_code}"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise NagerDateHolidayError(f"nager_date HTTP error for {url}: {exc}") from exc

        types_filter = set(self.cfg.types) if self.cfg.types else None
        out: set[_date_t] = set()
        for item in payload or []:
            ds = item.get("date")
            if not ds:
                continue
            if types_filter:
                # Nager exposes "types" array per holiday.
                hol_types = set(item.get("types") or [])
                if not (hol_types & types_filter):
                    continue
            try:
                out.add(_date_t.fromisoformat(ds))
            except ValueError:
                continue
        self._cache[year] = out
        return set(out)

    def seed_year(self, year: int, dates: set[_date_t]) -> None:
        """Inject a year's holidays into the cache (test helper, no network)."""
        self._cache[year] = set(dates)
