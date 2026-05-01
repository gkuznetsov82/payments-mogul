"""Pydantic config models for prototype_vendor_pop_v1 (v0) plus v2 foundations
(Money / Currency Catalog / FX / Calendar / Region) per spec 40.

v2 sections are all optional at the top level so existing v0 configs continue
to load unchanged.
"""

from __future__ import annotations

import re
from datetime import date as _date_t
from typing import ClassVar, Literal, Optional
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


_ALLOWED_PRODUCT_CLASSES = ("GenericProduct", "RetailPayment-Card-Prepaid", "SinkProduct")


class PipelineRoleSelector(BaseModel):
    """Resolves a symbolic role to a concrete agent_id, product_id, or local sink.

    Allowed combinations (spec 40 §pipeline_role_bindings):
    - `{ agent_id: X }`          — role resolves to an agent.
    - `{ product_id: Y }`        — role resolves to a product (agent derivable
                                    via model lookup).
    - `{ agent_id: X, product_id: Y }` — role resolves to a specific product
                                    owned by a specific agent; enables
                                    emission of both identities on directional
                                    events like fee_accrual / settlement_demand.
    - `{ local: true }`          — local sink; mutually exclusive with the others.
    """
    agent_id: Optional[str] = None
    product_id: Optional[str] = None
    local: Optional[bool] = None

    @model_validator(mode="after")
    def must_have_one_target(self) -> "PipelineRoleSelector":
        has_agent = bool(self.agent_id)
        has_product = bool(self.product_id)
        has_local = bool(self.local)
        if not (has_agent or has_product or has_local):
            raise ValueError(
                "E_PIPELINE_ROLE_SELECTOR_INVALID: selector must set at least one of "
                "{agent_id, product_id, local}"
            )
        # `local` is mutually exclusive with agent_id / product_id.
        if has_local and (has_agent or has_product):
            raise ValueError(
                "E_PIPELINE_ROLE_SELECTOR_INVALID: 'local: true' must not be combined "
                "with agent_id or product_id"
            )
        return self


class PipelineRoleBindings(BaseModel):
    """Per-product-instance binding from symbolic role names to concrete refs."""
    entity_roles: dict[str, PipelineRoleSelector] = {}
    default_product_role: Optional[str] = None
    # Spec 40 §Product-level role resolution (v4): opening balances for owned
    # container refs. Non-sink products must have opening_amount >= 0 (enforced
    # in the loader against product_class). Declared here because the bindings
    # object is product-instance-scoped.
    value_container_balances: list["ValueContainerOpeningBalanceConfig"] = []


class ProductConfig(BaseModel):
    product_id: str
    product_label: str
    product_class: str
    onboarding_friction: Optional[FrictionRange] = None
    transaction_friction: Optional[FrictionRange] = None
    # v3_runtime: per-product pipeline binding (spec 40 §pipeline, ADR-0002).
    pipeline_profile_id: Optional[str] = None
    pipeline_role_bindings: Optional[PipelineRoleBindings] = None

    @field_validator("product_class")
    @classmethod
    def known_product_class(cls, v: str) -> str:
        if v not in _ALLOWED_PRODUCT_CLASSES:
            raise ValueError(
                f"E_INVALID_PRODUCT_CLASS: product_class must be one of "
                f"{_ALLOWED_PRODUCT_CLASSES}, got '{v}'"
            )
        return v


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
    # Spec 31 §Pop config + spec 40 §pops + ADR-0003: Pop behavior knob for
    # refund-intent generation as a share of purchase volume. 0 disables
    # refunds. Validated 0..1.
    refund_to_purchase_ratio: float = 0.0
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

    @field_validator("refund_to_purchase_ratio")
    @classmethod
    def refund_ratio_unit_interval(cls, v: float) -> float:
        """Spec 50 §Hard errors + ADR-0003 §3: refund_to_purchase_ratio is a
        share-of-purchase Pop behavior knob and must be in [0, 1]."""
        if not (0 <= v <= 1):
            raise ValueError(
                f"E_REFUND_RATIO_OUT_OF_RANGE: refund_to_purchase_ratio must be in [0, 1], got {v}"
            )
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


# =============================================================================
# v2/v3 pipeline contracts (spec 40 §pipeline, ADR-0002)
# Runtime-binding when pipeline_schema_version == "v3_runtime".
# =============================================================================


_VALUE_DATE_POLICIES = (
    "same_day",
    "next_day_plus_x",
    "next_working_day_plus_x",
    "next_month_day_plus_x",
)
_PIPELINE_SCHEMA_VERSIONS = ("v2_foundations", "v3_runtime")
_CURRENCY_MODES = ("inherit", "fixed_currency", "fx_convert")
# Spec 33 §Fan-out completion semantics + spec 40 §Routing completion mode.
# Default is `synchronous` when omitted.
_ROUTING_COMPLETION_MODES = ("synchronous", "asynchronous")


def _check_offset_for_policy(policy: str, offset: Optional[int], field_label: str) -> None:
    """Spec 40 §Value-date offset rules: when policy contains plus_x, offset is required."""
    requires = "plus_x" in policy
    if requires and offset is None:
        raise ValueError(
            f"E_VALUE_DATE_OFFSET_REQUIRED: {field_label} requires an offset when "
            f"policy is '{policy}'"
        )


class FeeAmountInput(BaseModel):
    """Money-object input form for fee count_cost (spec 40)."""
    amount: float
    currency: str

    @field_validator("currency")
    @classmethod
    def iso_alpha3(cls, v: str) -> str:
        if not _ISO_4217_ALPHA3.match(v):
            raise ValueError(
                f"E_FEE_CURRENCY_INVALID: fee currency must be ISO 4217 alpha-3, got '{v}'"
            )
        return v


class TransactionDestinationConfig(BaseModel):
    destination_role: str
    outgoing_intent_id: str
    value_date_policy: str
    value_date_offset_days: Optional[int] = None
    amount_basis: str = "transaction_intent_amount"
    currency_mode: str = "inherit"
    # Spec 40 §Routing completion mode (v4 semantics): default synchronous when
    # omitted. Synchronous legs block root success within the current tick;
    # asynchronous legs are pending on origin tick and resolve on/after value date
    # (spec 33 §Fan-out completion semantics).
    routing_completion_mode: str = "synchronous"

    @field_validator("value_date_policy")
    @classmethod
    def known_policy(cls, v: str) -> str:
        if v not in _VALUE_DATE_POLICIES:
            raise ValueError(
                f"E_VALUE_DATE_POLICY_INVALID: must be one of {_VALUE_DATE_POLICIES}, got '{v}'"
            )
        return v

    @field_validator("currency_mode")
    @classmethod
    def known_currency_mode(cls, v: str) -> str:
        if v not in _CURRENCY_MODES:
            raise ValueError(
                f"E_CURRENCY_MODE_INVALID: must be one of {_CURRENCY_MODES}, got '{v}'"
            )
        return v

    @field_validator("routing_completion_mode")
    @classmethod
    def known_routing_mode(cls, v: str) -> str:
        if v not in _ROUTING_COMPLETION_MODES:
            raise ValueError(
                f"E_ROUTING_COMPLETION_MODE_INVALID: must be one of "
                f"{_ROUTING_COMPLETION_MODES}, got '{v}'"
            )
        return v

    @model_validator(mode="after")
    def offset_required_for_plus_x(self) -> "TransactionDestinationConfig":
        _check_offset_for_policy(self.value_date_policy, self.value_date_offset_days,
                                  "destination.value_date_offset_days")
        # Spec 33 §Fan-out completion semantics: synchronous legs MUST resolve
        # within the current tick execution boundary. Any non-same_day policy
        # implies a deferred resolution, which is invalid for a synchronous leg
        # and must fail config load.
        if (self.routing_completion_mode == "synchronous"
                and self.value_date_policy != "same_day"):
            raise ValueError(
                f"E_SYNC_LEG_VALUE_DATE_INVALID: synchronous destinations must use "
                f"value_date_policy='same_day' (got '{self.value_date_policy}'); "
                f"deferred resolution is only allowed for routing_completion_mode='asynchronous'"
            )
        return self


class TransactionIntentConfig(BaseModel):
    """Pipeline routing/execution contract for an intent (spec 40 §pipeline).

    Per ADR-0003 §2 + spec 40 §pipeline §"transaction_intents[] is a routing/
    execution contract, not a behavior-generation contract": this object holds
    transport contracts only. Behavior-generation fields (e.g.
    `source_volume_ratio` or any equivalent ratio/coefficient that would
    synthesize new economic intent families from prior outcomes) are
    explicitly forbidden and rejected at config load with
    `E_PIPELINE_BEHAVIOR_FIELD_FORBIDDEN`.

    Refund-intent generation policy lives on Pop (`refund_to_purchase_ratio`).
    """
    # extra="forbid" guarantees Pydantic rejects undeclared keys; the
    # model_validator below issues a stable, spec-aligned error code so
    # operators see the exact policy violation rather than a generic Pydantic
    # "extra inputs are not permitted" message.
    model_config = {"extra": "forbid"}

    intent_id: str
    destinations: list[TransactionDestinationConfig] = []

    # Spec 40 §pipeline + ADR-0003 §4 + spec 50 §Hard errors. Any of these
    # key names appearing on a transaction_intents[] item is a release-blocking
    # boundary violation: pipeline must not encode behavior-generation
    # coefficients. The set is open-ended ("or any equivalent ratio/
    # coefficient") so the validator runs in mode="before" and refuses any
    # non-listed extra key, falling back to the stable code on the canonical
    # examples too.
    _FORBIDDEN_BEHAVIOR_FIELDS: ClassVar[tuple[str, ...]] = (
        "source_volume_ratio",
        # Future-proofing: equivalent coefficients that would smuggle Pop
        # behavior into pipeline contracts. Any new spelling must be added
        # here AND surfaced via E_PIPELINE_BEHAVIOR_FIELD_FORBIDDEN.
        "purchase_to_refund_ratio",
        "refund_ratio",
        "behavior_ratio",
        "intent_volume_ratio",
    )

    @model_validator(mode="before")
    @classmethod
    def reject_pipeline_behavior_fields(cls, data):
        """Spec 50 + ADR-0003 §4: pipeline `transaction_intents[]` must not
        carry behavior-generation knobs. Surface E_PIPELINE_BEHAVIOR_FIELD_FORBIDDEN
        for the canonical names, and also for any unknown extra key (caught by
        extra='forbid' below if this guard misses it)."""
        if not isinstance(data, dict):
            return data
        for field in cls._FORBIDDEN_BEHAVIOR_FIELDS:
            if field in data:
                raise ValueError(
                    f"E_PIPELINE_BEHAVIOR_FIELD_FORBIDDEN: pipeline.transaction_intents[] "
                    f"must not carry behavior-generation field '{field}' — Pop config "
                    f"owns intent-generation knobs (ADR-0003)."
                )
        return data


class LedgerConstructionConfig(BaseModel):
    ledger_ref: str
    path_pattern: str
    normal_side: Optional[str] = None

    @field_validator("normal_side")
    @classmethod
    def known_side(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("debit", "credit"):
            raise ValueError(
                f"E_LEDGER_NORMAL_SIDE_INVALID: normal_side must be debit|credit, got '{v}'"
            )
        return v


class PostingRuleConfig(BaseModel):
    trigger_id: str
    source_ledger_ref: str
    destination_ledger_ref: str
    amount_basis: str = "transaction_intent_amount"
    value_date_policy: str
    value_date_offset_days: Optional[int] = None

    @field_validator("value_date_policy")
    @classmethod
    def known_policy(cls, v: str) -> str:
        if v not in _VALUE_DATE_POLICIES:
            raise ValueError(
                f"E_VALUE_DATE_POLICY_INVALID: must be one of {_VALUE_DATE_POLICIES}, got '{v}'"
            )
        return v

    @model_validator(mode="after")
    def offset_required(self) -> "PostingRuleConfig":
        _check_offset_for_policy(self.value_date_policy, self.value_date_offset_days,
                                  "posting_rules.value_date_offset_days")
        return self


class ValueContainerConstructionConfig(BaseModel):
    container_ref: str
    path_pattern: str


class AssetTransferRuleConfig(BaseModel):
    trigger_id: str
    source_container_ref: str
    destination_container_ref: str
    amount_basis: str = "transaction_intent_amount"
    value_date_policy: str
    value_date_offset_days: Optional[int] = None

    @field_validator("value_date_policy")
    @classmethod
    def known_policy(cls, v: str) -> str:
        if v not in _VALUE_DATE_POLICIES:
            raise ValueError(
                f"E_VALUE_DATE_POLICY_INVALID: must be one of {_VALUE_DATE_POLICIES}, got '{v}'"
            )
        return v

    @model_validator(mode="after")
    def offset_required(self) -> "AssetTransferRuleConfig":
        _check_offset_for_policy(self.value_date_policy, self.value_date_offset_days,
                                  "asset_transfer_rules.value_date_offset_days")
        return self


class FeeConfig(BaseModel):
    fee_id: str
    trigger_ids: list[str] = []
    beneficiary_role: str
    # Spec 40 §Intent of payer_role: optional for one-direction contracts;
    # explicit for bilateral contracts where direction can flip.
    payer_role: Optional[str] = None
    beneficiary_product_role: Optional[str] = None
    # Legacy v3 settlement fields retained for back-compat. When the explicit
    # v4 lifecycle-date fields below are omitted, loader derives
    # invoice_issue_date_policy/offset and payment_due_date_policy/offset from
    # these legacy fields (same policy/offset for both issue and due).
    settlement_value_date_policy: str
    settlement_value_date_offset_days: Optional[int] = None
    # Spec 40 §Lifecycle date semantics (v4): explicit and separate issue/due
    # policies. Aggregation keys use invoice_issue_date; overdue semantics use
    # payment_due_date. Populated from settlement_value_date_* if omitted.
    invoice_issue_date_policy: Optional[str] = None
    invoice_issue_date_offset_days: Optional[int] = None
    payment_due_date_policy: Optional[str] = None
    payment_due_date_offset_days: Optional[int] = None
    settlement_trigger_event: Optional[str] = None
    allow_settlement_netting: Optional[bool] = None
    # Spec 33 §Cardholder fee statement rule + spec 40 §settlement_payment_policies:
    # when true, advisement is informational-only (payable=false, settlement status
    # netted_internal) and must not enter payable queues or expose payment actions.
    non_payable_statement: Optional[bool] = None
    filter: Optional[dict] = None
    count_cost: Optional[FeeAmountInput] = None
    amount_percentage: Optional[float] = None
    # Spec 40 §Refund/purchase netting rule: formula_ref is accepted in schema
    # for forward-compat but runtime execution stays on count_cost / amount_percentage
    # in this iteration (expansion out of scope).
    formula_ref: Optional[str] = None

    @field_validator("settlement_value_date_policy")
    @classmethod
    def known_policy(cls, v: str) -> str:
        if v not in _VALUE_DATE_POLICIES:
            raise ValueError(
                f"E_VALUE_DATE_POLICY_INVALID: must be one of {_VALUE_DATE_POLICIES}, got '{v}'"
            )
        return v

    @field_validator("invoice_issue_date_policy", "payment_due_date_policy")
    @classmethod
    def known_lifecycle_policy(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _VALUE_DATE_POLICIES:
            raise ValueError(
                f"E_VALUE_DATE_POLICY_INVALID: must be one of {_VALUE_DATE_POLICIES}, got '{v}'"
            )
        return v

    @model_validator(mode="after")
    def settlement_offset_required(self) -> "FeeConfig":
        _check_offset_for_policy(self.settlement_value_date_policy,
                                  self.settlement_value_date_offset_days,
                                  "fees.settlement_value_date_offset_days")
        # v4 lifecycle dates: if a policy is specified, its offset must follow
        # the plus_x rule; if omitted, loader will backfill from legacy fields.
        if self.invoice_issue_date_policy is not None:
            _check_offset_for_policy(self.invoice_issue_date_policy,
                                      self.invoice_issue_date_offset_days,
                                      "fees.invoice_issue_date_offset_days")
        if self.payment_due_date_policy is not None:
            _check_offset_for_policy(self.payment_due_date_policy,
                                      self.payment_due_date_offset_days,
                                      "fees.payment_due_date_offset_days")
        # At least one amount driver required (spec 40: count_cost / amount_percentage / formula_ref)
        drivers = [self.count_cost is not None,
                   self.amount_percentage is not None,
                   self.formula_ref is not None]
        if not any(drivers):
            raise ValueError(
                "E_FEE_DRIVER_MISSING: fee must declare at least one of "
                "count_cost / amount_percentage / formula_ref"
            )
        return self

    # ------------------------------------------------------------------ helpers

    def effective_invoice_issue_date_policy(self) -> str:
        """Spec 40 §Lifecycle date semantics: when explicit policy omitted, fall
        back to the legacy settlement_value_date_policy (preserves v3 behavior)."""
        return self.invoice_issue_date_policy or self.settlement_value_date_policy

    def effective_invoice_issue_date_offset_days(self) -> Optional[int]:
        if self.invoice_issue_date_policy is not None:
            return self.invoice_issue_date_offset_days
        return self.settlement_value_date_offset_days

    def effective_payment_due_date_policy(self) -> str:
        return self.payment_due_date_policy or self.settlement_value_date_policy

    def effective_payment_due_date_offset_days(self) -> Optional[int]:
        if self.payment_due_date_policy is not None:
            return self.payment_due_date_offset_days
        return self.settlement_value_date_offset_days


class FeeSequenceConfig(BaseModel):
    sequence_id: str
    fees: list[FeeConfig] = []


# =============================================================================
# Settlement-demand contracts (spec 33 §SettlementDemandResult, spec 40
# §settlement_demand_sequences). Distinct from fees: directionality can flip
# by net outcome and opposing-direction accruals net naturally by aggregation.
# =============================================================================


_INVOICE_CATEGORIES = ("fee", "settlement_demand")


class SettlementDemandConfig(BaseModel):
    settlement_demand_id: str
    trigger_ids: list[str] = []
    creditor_role: str
    debtor_role: str
    invoice_category: str = "settlement_demand"
    invoice_issue_date_policy: str
    invoice_issue_date_offset_days: Optional[int] = None
    payment_due_date_policy: str
    payment_due_date_offset_days: Optional[int] = None
    # Amount drivers (spec 40): amount_percentage primary; formula_ref accepted
    # in schema but not runtime-expanded in this iteration.
    amount_percentage: Optional[float] = None
    count_cost: Optional[FeeAmountInput] = None
    formula_ref: Optional[str] = None

    @field_validator("invoice_category")
    @classmethod
    def must_be_demand(cls, v: str) -> str:
        if v != "settlement_demand":
            raise ValueError(
                f"E_INVOICE_CATEGORY_INVALID: settlement_demand rules must use "
                f"invoice_category='settlement_demand', got '{v}'"
            )
        return v

    @field_validator("invoice_issue_date_policy", "payment_due_date_policy")
    @classmethod
    def known_policy(cls, v: str) -> str:
        if v not in _VALUE_DATE_POLICIES:
            raise ValueError(
                f"E_VALUE_DATE_POLICY_INVALID: must be one of {_VALUE_DATE_POLICIES}, got '{v}'"
            )
        return v

    @model_validator(mode="after")
    def offsets_required(self) -> "SettlementDemandConfig":
        _check_offset_for_policy(self.invoice_issue_date_policy,
                                  self.invoice_issue_date_offset_days,
                                  "settlement_demands.invoice_issue_date_offset_days")
        _check_offset_for_policy(self.payment_due_date_policy,
                                  self.payment_due_date_offset_days,
                                  "settlement_demands.payment_due_date_offset_days")
        # Amount driver required (same principle as FeeConfig).
        drivers = [self.count_cost is not None,
                   self.amount_percentage is not None,
                   self.formula_ref is not None]
        if not any(drivers):
            raise ValueError(
                "E_SETTLEMENT_DEMAND_DRIVER_MISSING: settlement demand must declare "
                "at least one of count_cost / amount_percentage / formula_ref"
            )
        return self


class SettlementDemandSequenceConfig(BaseModel):
    sequence_id: str
    settlement_demands: list[SettlementDemandConfig] = []


# =============================================================================
# Settlement payment policies (spec 40 §settlement_payment_policies) + opening
# balances (spec 40 §Container balance handling).
# =============================================================================


class SettlementPaymentPolicyConfig(BaseModel):
    applies_to_category: str        # "fee" | "settlement_demand"
    source_container_ref: str
    auto_pay_enabled: bool = True
    hold_default: bool = False
    grace_ticks: int = 0
    non_payable_statement: bool = False

    @field_validator("applies_to_category")
    @classmethod
    def known_category(cls, v: str) -> str:
        if v not in _INVOICE_CATEGORIES:
            raise ValueError(
                f"E_INVOICE_CATEGORY_INVALID: applies_to_category must be one of "
                f"{_INVOICE_CATEGORIES}, got '{v}'"
            )
        return v

    @field_validator("grace_ticks")
    @classmethod
    def grace_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                f"E_GRACE_TICKS_INVALID: grace_ticks must be >= 0, got {v}"
            )
        return v


class ValueContainerOpeningBalanceConfig(BaseModel):
    """Spec 40 §Container balance handling (v4 semantics)."""
    container_ref: str
    opening_amount: float
    currency: str

    @field_validator("currency")
    @classmethod
    def iso_alpha3(cls, v: str) -> str:
        if not _ISO_4217_ALPHA3.match(v):
            raise ValueError(
                f"E_OPENING_BALANCE_CURRENCY_INVALID: currency must be ISO 4217 alpha-3, got '{v}'"
            )
        return v


# Resolve the forward reference in PipelineRoleBindings now that the referenced
# class is defined.
PipelineRoleBindings.model_rebuild()


class LedgerValueContainerMapConfig(BaseModel):
    ledger_ref: str
    container_ref: str
    mapping_mode: str = "one_to_one"

    @field_validator("mapping_mode")
    @classmethod
    def known_mode(cls, v: str) -> str:
        if v not in ("one_to_one", "aggregate"):
            raise ValueError(
                f"E_MAPPING_MODE_INVALID: must be one_to_one|aggregate, got '{v}'"
            )
        return v


class PipelineProfileConfig(BaseModel):
    pipeline_profile_id: str
    transaction_intents: list[TransactionIntentConfig] = []
    ledger_construction: list[LedgerConstructionConfig] = []
    posting_rules: list[PostingRuleConfig] = []
    value_container_construction: list[ValueContainerConstructionConfig] = []
    asset_transfer_rules: list[AssetTransferRuleConfig] = []
    fee_sequences: list[FeeSequenceConfig] = []
    # Spec 40 §settlement_demand_sequences (v4): directional settlement claims
    # distinct from fees; net by agent-pair + issue date + category.
    settlement_demand_sequences: list[SettlementDemandSequenceConfig] = []
    # Spec 40 §settlement_payment_policies (v4): payer-side payment execution
    # controls per invoice category.
    settlement_payment_policies: list[SettlementPaymentPolicyConfig] = []
    ledger_value_container_map: list[LedgerValueContainerMapConfig] = []


class PipelineConfig(BaseModel):
    pipeline_schema_version: str
    pipeline_profiles: list[PipelineProfileConfig] = []

    @field_validator("pipeline_schema_version")
    @classmethod
    def known_version(cls, v: str) -> str:
        if v not in _PIPELINE_SCHEMA_VERSIONS:
            raise ValueError(
                f"E_PIPELINE_SCHEMA_VERSION_INVALID: must be one of "
                f"{_PIPELINE_SCHEMA_VERSIONS}, got '{v}'"
            )
        return v

    @property
    def is_runtime(self) -> bool:
        """ADR-0002 gating: runtime-binding only when v3_runtime is declared."""
        return self.pipeline_schema_version == "v3_runtime"


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
    pipeline: Optional[PipelineConfig] = None
