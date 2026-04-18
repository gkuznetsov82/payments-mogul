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

    return cfg, collected


def _extract_code(msg: str) -> str:
    """Pull E_XXX code from validator message, or return generic."""
    for token in msg.split():
        if token.startswith("E_"):
            return token.rstrip(":,.")
    return "E_CONFIG_INVALID"
