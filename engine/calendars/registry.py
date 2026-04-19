"""Registries that bind config -> runtime Calendar / Region objects (spec 40).

CalendarRegistry materializes one Calendar per `calendars[]` entry, wiring up
the per-calendar local + Nager.Date sources from the config.

RegionRegistry maps `region_id` to its calendar, and resolves an entity's
calendar from a (possibly omitted) `region_id` plus a default region id."""

from __future__ import annotations

from typing import Optional

from engine.config.models import CalendarConfig, PrototypeConfig, RegionConfig
from engine.calendars.calendar import Calendar, CalendarError
from engine.calendars.local import LocalHolidaySource
from engine.calendars.nager import NagerDateHolidaySource


class CalendarRegistry:
    def __init__(self, calendars: dict[str, Calendar]) -> None:
        self._cals = calendars

    @classmethod
    def from_config(cls,
                    cfg: PrototypeConfig,
                    *,
                    local_holiday_source_factory=None) -> "CalendarRegistry":
        """Build a registry from PrototypeConfig.calendars.

        `local_holiday_source_factory(path) -> LocalHolidaySource | None` allows
        tests to inject in-memory sources without touching the filesystem. By
        default we load from the file path declared in the calendar's config.
        """
        if local_holiday_source_factory is None:
            local_holiday_source_factory = _default_local_factory

        cals: dict[str, Calendar] = {}
        for cal_cfg in cfg.calendars:
            local_src = None
            nager_src = None
            if cal_cfg.holiday_sources:
                lf = cal_cfg.holiday_sources.local_file
                if lf is not None and lf.enabled:
                    local_src = local_holiday_source_factory(lf.path)
                nd = cal_cfg.holiday_sources.nager_date
                if nd is not None and nd.enabled:
                    nager_src = NagerDateHolidaySource(nd)
            cals[cal_cfg.calendar_id] = Calendar(
                cfg=cal_cfg,
                local_source=local_src,
                nager_source=nager_src,
            )
        return cls(cals)

    def get(self, calendar_id: str) -> Calendar:
        cal = self._cals.get(calendar_id)
        if cal is None:
            raise CalendarError(f"unknown calendar_id {calendar_id!r}")
        return cal

    def ids(self) -> list[str]:
        return sorted(self._cals.keys())


def _default_local_factory(path: str) -> Optional[LocalHolidaySource]:
    try:
        return LocalHolidaySource.from_file(path)
    except FileNotFoundError:
        return None


class RegionRegistry:
    def __init__(self,
                 regions: dict[str, RegionConfig],
                 calendar_registry: CalendarRegistry,
                 default_region_id: Optional[str] = None) -> None:
        self._regions = regions
        self._cal = calendar_registry
        self._default_region_id = default_region_id

    @classmethod
    def from_config(cls,
                    cfg: PrototypeConfig,
                    calendar_registry: CalendarRegistry,
                    default_region_id: Optional[str] = None) -> "RegionRegistry":
        regions = {r.region_id: r for r in cfg.regions}
        # If exactly one region exists and no explicit default given, use it as default.
        if default_region_id is None and len(regions) == 1:
            default_region_id = next(iter(regions.keys()))
        return cls(regions, calendar_registry, default_region_id)

    def calendar_for_region(self, region_id: Optional[str]) -> Calendar:
        rid = region_id or self._default_region_id
        if rid is None:
            raise CalendarError(
                "no region_id provided and no default region resolvable; "
                "explicit region_id required"
            )
        region = self._regions.get(rid)
        if region is None:
            raise CalendarError(f"unknown region_id {rid!r}")
        return self._cal.get(region.calendar_id)

    def calendar_for_entity(self,
                            entity_region_id: Optional[str],
                            calendar_override_id: Optional[str] = None) -> Calendar:
        """Resolve calendar for a world entity (vendor / pop). Explicit
        `calendar_override_id` always wins over region inheritance (spec 40
        §Agent calendar inheritance)."""
        if calendar_override_id:
            return self._cal.get(calendar_override_id)
        return self.calendar_for_region(entity_region_id)

    def region_ids(self) -> list[str]:
        return sorted(self._regions.keys())

    @property
    def default_region_id(self) -> Optional[str]:
        return self._default_region_id
