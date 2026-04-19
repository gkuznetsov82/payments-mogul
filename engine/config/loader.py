"""YAML config loader with cross-entity validation and warnings."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from engine.config.models import PrototypeConfig


@dataclass
class ConfigWarning:
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class ConfigValidationError(Exception):
    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        self.code = code
        self.message = message
        self.field = field
        super().__init__(f"[{code}] {message}")


def load_config(path: str | Path) -> tuple[PrototypeConfig, list[ConfigWarning]]:
    """Load, parse, and validate a v0 prototype config YAML.

    Returns (config, warnings) on success.
    Raises ConfigValidationError on any hard error.
    """
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigValidationError("E_YAML_PARSE", str(exc))

    try:
        cfg = PrototypeConfig.model_validate(data)
    except ValidationError as exc:
        # Surface the first meaningful error code from the message text
        first = exc.errors()[0]
        msg = str(first.get("msg", ""))
        # Extract stable code if embedded
        code = _extract_code(msg)
        field = ".".join(str(p) for p in first.get("loc", []))
        raise ConfigValidationError(code, msg, field) from exc

    collected: list[ConfigWarning] = []

    # Cross-entity validations (hard errors)
    sim = cfg.simulation
    if sim.debug_history_default_ticks > sim.debug_history_max_ticks:
        raise ConfigValidationError(
            "E_DEBUG_WINDOW_INVALID",
            f"debug_history_default_ticks ({sim.debug_history_default_ticks}) "
            f"exceeds debug_history_max_ticks ({sim.debug_history_max_ticks})",
            "simulation.debug_history_default_ticks",
        )

    if len(cfg.world.vendor_agents) == 0:
        raise ConfigValidationError("E_WORLD_MISSING_VENDOR", "At least one vendor_agent is required")

    if len(cfg.world.pops) == 0:
        raise ConfigValidationError("E_WORLD_MISSING_POP", "At least one pop is required")

    # Build product reference set for link resolution
    known_products: set[tuple[str, str]] = set()
    for vendor in cfg.world.vendor_agents:
        for product in vendor.products:
            known_products.add((vendor.vendor_id, product.product_id))

    for pop in cfg.world.pops:
        all_links_unknown = all(not link.known for link in pop.product_links)
        if all_links_unknown:
            collected.append(
                ConfigWarning(
                    "W_ALL_LINKS_UNKNOWN",
                    f"Pop '{pop.pop_id}' has no known=true product links; "
                    "no onboard/transact requests will be generated",
                )
            )

        for link in pop.product_links:
            pair = (link.vendor_id, link.product_id)
            if pair not in known_products:
                raise ConfigValidationError(
                    "E_LINK_TARGET_MISSING",
                    f"Pop '{pop.pop_id}' links to unknown product "
                    f"({link.vendor_id}, {link.product_id})",
                    "world.pops[].product_links",
                )
            if link.onboarded_count > pop.pop_count:
                raise ConfigValidationError(
                    "E_ONBOARDED_COUNT_INVALID",
                    f"Pop '{pop.pop_id}' link to ({link.vendor_id}, {link.product_id}): "
                    f"onboarded_count ({link.onboarded_count}) > pop_count ({pop.pop_count})",
                    "world.pops[].product_links[].onboarded_count",
                )

    # Warnings
    if sim.intake_window_ms < 50:
        collected.append(
            ConfigWarning(
                "W_INTAKE_WINDOW_LOW",
                f"intake_window_ms={sim.intake_window_ms} is very low; "
                "manual command timing may be difficult",
            )
        )
    if sim.tick_wall_clock_base_ms == 0:
        collected.append(
            ConfigWarning(
                "W_NO_PACING",
                "tick_wall_clock_base_ms=0 disables pacing; "
                "ticks will run as fast as possible",
            )
        )

    # v2 foundations cross-entity validation (spec 40 §regions/§fx).
    _validate_v2_foundations(cfg, collected)

    return cfg, collected


def _validate_v2_foundations(cfg: PrototypeConfig, collected: list[ConfigWarning]) -> None:
    """Cross-entity v2 checks for region_id/calendar_id/fx source_refs.

    Backward compat: if v2 sections are absent, skip silently. v2 sections present
    but partially populated must still pass referential integrity checks.
    """
    # 1. calendars: calendar_ids must be unique.
    if cfg.calendars:
        ids: set[str] = set()
        for c in cfg.calendars:
            if c.calendar_id in ids:
                raise ConfigValidationError(
                    "E_CALENDAR_DUPLICATE",
                    f"Duplicate calendar_id '{c.calendar_id}'",
                    "calendars[].calendar_id",
                )
            ids.add(c.calendar_id)

    # 2. regions: region_ids must be unique; calendar_id must reference a defined calendar.
    if cfg.regions:
        rids: set[str] = set()
        cal_ids = {c.calendar_id for c in cfg.calendars}
        for r in cfg.regions:
            if r.region_id in rids:
                raise ConfigValidationError(
                    "E_REGION_DUPLICATE",
                    f"Duplicate region_id '{r.region_id}'",
                    "regions[].region_id",
                )
            rids.add(r.region_id)
            if r.calendar_id not in cal_ids:
                raise ConfigValidationError(
                    "E_CALENDAR_NOT_FOUND",
                    f"Region '{r.region_id}' references unknown calendar '{r.calendar_id}'",
                    "regions[].calendar_id",
                )

    # 3. world entities: region_id (when set) must reference a defined region.
    region_ids = {r.region_id for r in cfg.regions}
    for v in cfg.world.vendor_agents:
        if v.region_id is not None and v.region_id not in region_ids:
            raise ConfigValidationError(
                "E_REGION_NOT_FOUND",
                f"Vendor '{v.vendor_id}' references unknown region '{v.region_id}'",
                "world.vendor_agents[].region_id",
            )
    for p in cfg.world.pops:
        if p.region_id is not None and p.region_id not in region_ids:
            raise ConfigValidationError(
                "E_REGION_NOT_FOUND",
                f"Pop '{p.pop_id}' references unknown region '{p.region_id}'",
                "world.pops[].region_id",
            )

    # 4. fx: source_refs must reference defined frankfurter source_ids.
    if cfg.fx is not None:
        # Frankfurter source_ids must be unique.
        fr_ids: set[str] = set()
        for fs in cfg.fx.frankfurter_sources:
            if fs.source_id in fr_ids:
                raise ConfigValidationError(
                    "E_FX_SOURCE_DUPLICATE",
                    f"Duplicate frankfurter source_id '{fs.source_id}'",
                    "fx.frankfurter_sources[].source_id",
                )
            fr_ids.add(fs.source_id)

        if cfg.fx.source_refs:
            for ref in cfg.fx.source_refs:
                if ref not in fr_ids:
                    raise ConfigValidationError(
                        "E_FX_SOURCE_REF_NOT_FOUND",
                        f"fx.source_refs entry '{ref}' does not match any defined "
                        "frankfurter_sources[].source_id",
                        "fx.source_refs",
                    )

        # Policy <-> source presence consistency.
        policy = cfg.fx.source_policy
        local_enabled = (cfg.fx.sources is not None
                         and cfg.fx.sources.local_file is not None
                         and cfg.fx.sources.local_file.enabled)
        any_frankfurter_enabled = any(s.enabled for s in cfg.fx.frankfurter_sources)
        if policy == "local_only" and not local_enabled:
            raise ConfigValidationError(
                "E_FX_POLICY_SOURCE_MISMATCH",
                "fx.source_policy is 'local_only' but no enabled local_file source is configured",
                "fx.source_policy",
            )
        if policy == "frankfurter_only" and not any_frankfurter_enabled:
            raise ConfigValidationError(
                "E_FX_POLICY_SOURCE_MISMATCH",
                "fx.source_policy is 'frankfurter_only' but no enabled frankfurter_sources entry exists",
                "fx.source_policy",
            )
        if policy == "local_override_then_frankfurter" and not (local_enabled or any_frankfurter_enabled):
            raise ConfigValidationError(
                "E_FX_POLICY_SOURCE_MISMATCH",
                "fx.source_policy is 'local_override_then_frankfurter' but no enabled source exists",
                "fx.source_policy",
            )

    # 5. Authoring currency (when pop daily_transact_amount uses money-object form)
    # must match money.default_currency. Spec 40 §money + critical contract decision #1.
    default_currency = cfg.money.default_currency if cfg.money else None
    for p in cfg.world.pops:
        if p.daily_transact_amount_currency is not None:
            if default_currency is None:
                raise ConfigValidationError(
                    "E_AMOUNT_CURRENCY_WITHOUT_MONEY",
                    f"Pop '{p.pop_id}' authored daily_transact_amount as money-object "
                    "but `money.default_currency` is not set",
                    "world.pops[].daily_transact_amount.currency",
                )
            if p.daily_transact_amount_currency != default_currency:
                raise ConfigValidationError(
                    "E_AMOUNT_CURRENCY_MISMATCH",
                    f"Pop '{p.pop_id}' daily_transact_amount currency "
                    f"'{p.daily_transact_amount_currency}' does not match "
                    f"money.default_currency '{default_currency}'",
                    "world.pops[].daily_transact_amount.currency",
                )


def _extract_code(msg: str) -> str:
    """Pull E_XXX code from validator message, or return generic."""
    for token in msg.split():
        if token.startswith("E_"):
            return token.rstrip(":,.")
    return "E_CONFIG_INVALID"
