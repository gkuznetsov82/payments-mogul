"""Pydantic config models for prototype_vendor_pop_v1 (v0) plus v2 foundations
(Money / Currency Catalog / FX / Calendar / Region) per spec 40.

v2 sections are all optional at the top level so existing v0 configs continue
to load unchanged.
"""

from __future__ import annotations

import re
from datetime import date as _date_t
from typing import Literal, Optional
from pydantic import BaseModel, field_validator, model_validator


# Rounding modes allowed by simulation.count_rounding_mode / amount_rounding_mode (spec 40).
# v0 default is "half_up"; other Python-native modes accepted for forward-compat.
_ROUNDING_MODES = ("half_up", "half_even", "down", "up", "floor", "ceiling")


class FrictionRange(BaseModel):
    min: float
    max: float

    @model_validator(mode="after")
    def check_range(self) -> FrictionRange:
        if not (0 <= self.min <= 1):
            raise ValueError("E_FRICTION_RANGE_INVALID: min must be in [0, 1]")
        if not (0 <= self.max <= 1):
            raise ValueError("E_FRICTION_RANGE_INVALID: max must be in [0, 1]")
        if self.min > self.max:
            raise ValueError("E_FRICTION_RANGE_INVALID: min must be <= max")
        return self


class ProductConfig(BaseModel):
    product_id: str
    product_label: str
    product_class: str
    onboarding_friction: Optional[FrictionRange] = None
    transaction_friction: Optional[FrictionRange] = None


class VendorAgentConfig(BaseModel):
    vendor_id: str
    vendor_label: str
    operational: bool
    products: list[ProductConfig]
    # v2 foundations: optional region binding for calendar resolution (spec 40 §world).
    region_id: Optional[str] = None

    @field_validator("products")
    @classmethod
    def at_least_one_product(cls, v: list) -> list:
        if len(v) < 1:
            raise ValueError("E_WORLD_MISSING_VENDOR: vendor must have at least one product")
        return v


class ProductLinkConfig(BaseModel):
    vendor_id: str
    product_id: str
    known: bool
    # onboarded_count is a whole-person count per spec 40 (integer).
    onboarded_count: int

    @field_validator("onboarded_count")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("E_ONBOARDED_COUNT_INVALID: onboarded_count must be >= 0")
        return v


class PopConfig(BaseModel):
    pop_id: str
    pop_label: str
    # pop_count is a whole-person count per spec 40 (integer).
    pop_count: int
    daily_onboard: float
    daily_active: float
    daily_transact_count: float
    daily_transact_amount: float
    product_links: list[ProductLinkConfig]
    # v2 foundations: optional region binding (spec 40 §world); fallback to scenario default.
    region_id: Optional[str] = None
    # If authoring used a money-object form for daily_transact_amount in v2 YAML,
    # carry the currency through for cross-validation against money.default_currency.
    daily_transact_amount_currency: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def coerce_daily_transact_amount(cls, data):
        """Accept either scalar `daily_transact_amount: 22.5` or money-object
        form `daily_transact_amount: {amount: 22.5, currency: USD}` per spec 40
        v2 §critical contract decision #1 (authoring symmetry with output).

        Internal type stays float for agent rate arithmetic; the currency tag
        is captured separately and cross-validated by the loader against
        money.default_currency."""
        if isinstance(data, dict):
            amt = data.get("daily_transact_amount")
            if isinstance(amt, dict) and "amount" in amt:
                data = dict(data)
                data["daily_transact_amount"] = float(amt["amount"])
                if "currency" in amt:
                    data["daily_transact_amount_currency"] = amt["currency"]
        return data

    @field_validator("pop_count")
    @classmethod
    def positive_pop_count(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("E_POP_COUNT_INVALID: pop_count must be > 0")
        return v

    @field_validator("daily_onboard", "daily_active")
    @classmethod
    def rate_0_to_1(cls, v: float) -> float:
        if not (0 <= v <= 1):
            raise ValueError("E_RATE_OUT_OF_RANGE: rate must be in [0, 1]")
        return v

    @field_validator("daily_transact_count", "daily_transact_amount")
    @classmethod
    def non_negative_txn(cls, v: float) -> float:
        if v < 0:
            raise ValueError("E_TXN_PARAM_INVALID: transact params must be >= 0")
        return v


class WorldConfig(BaseModel):
    vendor_agents: list[VendorAgentConfig]
    pops: list[PopConfig]


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ScenarioConfig(BaseModel):
    id: str
    seed: int
    market_id: str
    # v2 foundations: optional start_date — "today" or YYYY-MM-DD (spec 40 §scenario).
    start_date: Optional[str] = None

    @field_validator("id")
    @classmethod
    def must_be_prototype(cls, v: str) -> str:
        if v != "prototype_vendor_pop_v1":
            raise ValueError(
                f"E_SCENARIO_ID_UNSUPPORTED: expected 'prototype_vendor_pop_v1', got '{v}'"
            )
        return v

    @field_validator("start_date")
    @classmethod
    def valid_start_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v == "today":
            return v
        if not _ISO_DATE.match(v):
            raise ValueError(
                f"E_START_DATE_INVALID: start_date must be 'today' or YYYY-MM-DD, got '{v}'"
            )
        try:
            _date_t.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"E_START_DATE_INVALID: {exc}")
        return v


class SimulationConfig(BaseModel):
    tick_wall_clock_base_ms: int
    debug_history_max_ticks: int
    debug_history_default_ticks: int
    intake_window_ms: int
    agent_method_order: list[str]
    agent_iteration_policy: str
    # Numeric typing policy (spec 40, 51 §Numeric typing contract, 52).
    # v0 defaults preserve the existing behavior for configs written pre-spec.
    count_rounding_mode: str = "half_up"
    amount_scale_dp: int = 2
    amount_rounding_mode: str = "half_up"

    @field_validator("agent_method_order")
    @classmethod
    def must_be_onboard_transact(cls, v: list) -> list:
        if v != ["Onboard", "Transact"]:
            raise ValueError(
                f"E_METHOD_ORDER_INVALID: must be ['Onboard', 'Transact'], got {v}"
            )
        return v

    @field_validator("count_rounding_mode", "amount_rounding_mode")
    @classmethod
    def known_rounding_mode(cls, v: str) -> str:
        if v not in _ROUNDING_MODES:
            raise ValueError(
                f"E_ROUNDING_MODE_INVALID: rounding mode must be one of {_ROUNDING_MODES}, got '{v}'"
            )
        return v

    @field_validator("amount_scale_dp")
    @classmethod
    def amount_scale_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"E_AMOUNT_SCALE_INVALID: amount_scale_dp must be >= 0, got {v}")
        return v

    @field_validator("tick_wall_clock_base_ms")
    @classmethod
    def tick_wall_clock_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                f"E_TICK_WALL_CLOCK_INVALID: tick_wall_clock_base_ms must be >= 0, got {v}"
            )
        return v

    @field_validator("intake_window_ms")
    @classmethod
    def intake_window_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"E_INTAKE_WINDOW_INVALID: intake_window_ms must be >= 1, got {v}"
            )
        return v

    @field_validator("debug_history_max_ticks", "debug_history_default_ticks")
    @classmethod
    def debug_window_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"E_DEBUG_WINDOW_INVALID: debug_history_* must be >= 1, got {v}"
            )
        return v

    @model_validator(mode="after")
    def intake_within_tick_total(self) -> SimulationConfig:
        """tick_wall_clock_base_ms is the TOTAL tick wall-clock duration; intake
        is the portion at the start of the tick reserved for command intake.
        Intake therefore cannot exceed the total. tick_wall_clock_base_ms=0 is a
        legacy 'no pacing' mode that disables this constraint (intake still runs
        on its own timer; ticks proceed back-to-back with no inter-tick wait)."""
        if (self.tick_wall_clock_base_ms > 0
                and self.intake_window_ms > self.tick_wall_clock_base_ms):
            raise ValueError(
                f"E_INTAKE_EXCEEDS_TICK: intake_window_ms ({self.intake_window_ms}) "
                f"must be <= tick_wall_clock_base_ms ({self.tick_wall_clock_base_ms})"
            )
        return self


class ControlDefaultsConfig(BaseModel):
    accepting_onboard: bool
    accepting_transact: bool


# =============================================================================
# v2 foundations: Money / Currency Catalog / FX / Calendar / Region (spec 40)
# =============================================================================


_WEEKEND_PROFILES = ("sat_sun", "fri_sat")
_FX_SOURCE_POLICIES = ("local_only", "frankfurter_only", "local_override_then_frankfurter")
_HOLIDAY_SOURCE_POLICIES = ("local_only", "nager_only", "local_override_then_nager")
_CURRENCY_CATALOG_FORMATS = ("yaml", "json")
_FX_LOCAL_FORMATS = ("yaml", "json", "csv")
_ISO_3166_ALPHA2 = re.compile(r"^[A-Z]{2}$")
_ISO_4217_ALPHA3 = re.compile(r"^[A-Z]{3}$")


class MoneyConfig(BaseModel):
    """Money typing/rounding defaults (spec 40 §money)."""
    amount_rounding_mode: str = "half_up"
    default_currency: str
    enforce_money_object: bool = True

    @field_validator("amount_rounding_mode")
    @classmethod
    def known_mode(cls, v: str) -> str:
        if v not in _ROUNDING_MODES:
            raise ValueError(
                f"E_ROUNDING_MODE_INVALID: amount_rounding_mode must be one of {_ROUNDING_MODES}, got '{v}'"
            )
        return v

    @field_validator("default_currency")
    @classmethod
    def iso_alpha3(cls, v: str) -> str:
        if not _ISO_4217_ALPHA3.match(v):
            raise ValueError(
                f"E_DEFAULT_CURRENCY_INVALID: default_currency must be ISO 4217 alpha-3, got '{v}'"
            )
        return v


class CurrencyCatalogLocalFile(BaseModel):
    path: str
    format: str = "yaml"

    @field_validator("format")
    @classmethod
    def known_format(cls, v: str) -> str:
        if v not in _CURRENCY_CATALOG_FORMATS:
            raise ValueError(
                f"E_CURRENCY_CATALOG_FORMAT_INVALID: must be one of {_CURRENCY_CATALOG_FORMATS}, got '{v}'"
            )
        return v


class CurrencyCatalogConfig(BaseModel):
    """Currency catalog source (spec 40 §currency_catalog). v2 supports local_file only."""
    source_type: Literal["local_file"]
    local_file: CurrencyCatalogLocalFile
    allow_local_overrides: bool = False


class FXLocalFileSource(BaseModel):
    enabled: bool = True
    path: str
    format: str = "yaml"

    @field_validator("format")
    @classmethod
    def known_format(cls, v: str) -> str:
        if v not in _FX_LOCAL_FORMATS:
            raise ValueError(
                f"E_FX_LOCAL_FORMAT_INVALID: must be one of {_FX_LOCAL_FORMATS}, got '{v}'"
            )
        return v


class FXSources(BaseModel):
    """The `fx.sources` sub-object — currently only local_file is first-class."""
    local_file: Optional[FXLocalFileSource] = None


class FrankfurterSourceConfig(BaseModel):
    """A configured Frankfurter endpoint (spec 40 §fx). Multiple instances allowed."""
    source_id: str
    enabled: bool = True
    base_url: str = "https://api.frankfurter.dev/v2"
    base_country: str
    country_provider_map: Optional[dict[str, str]] = None
    default_provider: Optional[str] = None

    @field_validator("base_country")
    @classmethod
    def iso_alpha2(cls, v: str) -> str:
        if not _ISO_3166_ALPHA2.match(v):
            raise ValueError(
                f"E_COUNTRY_CODE_INVALID: base_country must be ISO 3166-1 alpha-2, got '{v}'"
            )
        return v

    @model_validator(mode="after")
    def must_be_resolvable(self) -> FrankfurterSourceConfig:
        """Spec 40 §fx: missing country_provider_map only allowed if explicit
        default_provider exists. No implicit silent fallback."""
        has_map = bool(self.country_provider_map)
        has_default = bool(self.default_provider)
        if not has_map and not has_default:
            raise ValueError(
                "E_FRANKFURTER_PROVIDER_UNRESOLVED: source must define either "
                "country_provider_map or default_provider"
            )
        return self


class FXConfig(BaseModel):
    """FX selection and source list (spec 40 §fx)."""
    source_policy: str
    sources: Optional[FXSources] = None
    frankfurter_sources: list[FrankfurterSourceConfig] = []
    source_refs: Optional[list[str]] = None

    @field_validator("source_policy")
    @classmethod
    def known_policy(cls, v: str) -> str:
        if v not in _FX_SOURCE_POLICIES:
            raise ValueError(
                f"E_FX_POLICY_INVALID: source_policy must be one of {_FX_SOURCE_POLICIES}, got '{v}'"
            )
        return v


class LocalHolidaySource(BaseModel):
    enabled: bool = True
    path: str


class NagerDateSource(BaseModel):
    enabled: bool = True
    base_url: str = "https://date.nager.at/api/v3"
    country_code: Optional[str] = None
    types: Optional[list[str]] = None

    @field_validator("country_code")
    @classmethod
    def iso_alpha2(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _ISO_3166_ALPHA2.match(v):
            raise ValueError(
                f"E_COUNTRY_CODE_INVALID: country_code must be ISO 3166-1 alpha-2, got '{v}'"
            )
        return v


class HolidaySources(BaseModel):
    local_file: Optional[LocalHolidaySource] = None
    nager_date: Optional[NagerDateSource] = None


class CalendarConfig(BaseModel):
    calendar_id: str
    weekend_profile: str = "sat_sun"
    non_working_overrides: list[str] = []
    holiday_source_policy: str = "local_only"
    holiday_sources: Optional[HolidaySources] = None

    @field_validator("weekend_profile")
    @classmethod
    def known_weekend(cls, v: str) -> str:
        if v not in _WEEKEND_PROFILES:
            raise ValueError(
                f"E_WEEKEND_PROFILE_INVALID: must be one of {_WEEKEND_PROFILES}, got '{v}'"
            )
        return v

    @field_validator("holiday_source_policy")
    @classmethod
    def known_policy(cls, v: str) -> str:
        if v not in _HOLIDAY_SOURCE_POLICIES:
            raise ValueError(
                f"E_HOLIDAY_POLICY_INVALID: must be one of {_HOLIDAY_SOURCE_POLICIES}, got '{v}'"
            )
        return v

    @field_validator("non_working_overrides")
    @classmethod
    def valid_dates(cls, v: list[str]) -> list[str]:
        for d in v:
            try:
                _date_t.fromisoformat(d)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"E_NON_WORKING_DATE_INVALID: '{d}' is not a valid YYYY-MM-DD date: {exc}"
                )
        return v


class RegionConfig(BaseModel):
    region_id: str
    calendar_id: str
    label: Optional[str] = None


class PrototypeConfig(BaseModel):
    config_version: str
    scenario: ScenarioConfig
    simulation: SimulationConfig
    world: WorldConfig
    control_defaults: ControlDefaultsConfig
    # v2 foundations (spec 40). All optional so v0 configs continue to load.
    money: Optional[MoneyConfig] = None
    currency_catalog: Optional[CurrencyCatalogConfig] = None
    fx: Optional[FXConfig] = None
    calendars: list[CalendarConfig] = []
    regions: list[RegionConfig] = []
