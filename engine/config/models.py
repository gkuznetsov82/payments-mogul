"""Pydantic v0 config models for prototype_vendor_pop_v1."""

from __future__ import annotations

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


class ScenarioConfig(BaseModel):
    id: str
    seed: int
    market_id: str

    @field_validator("id")
    @classmethod
    def must_be_prototype(cls, v: str) -> str:
        if v != "prototype_vendor_pop_v1":
            raise ValueError(
                f"E_SCENARIO_ID_UNSUPPORTED: expected 'prototype_vendor_pop_v1', got '{v}'"
            )
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


class PrototypeConfig(BaseModel):
    config_version: str
    scenario: ScenarioConfig
    simulation: SimulationConfig
    world: WorldConfig
    control_defaults: ControlDefaultsConfig
