"""Deterministic canonical YAML normalization for World Builder (spec 74).

Minimum behavior locked by spec 74 §Normalization behavior:
- Canonical ordering of top-level sections and key entity arrays by stable IDs.
- Explicit default insertion only when those defaults are contract-defined
  (we use `exclude_none=True` so the model doesn't emit None placeholders for
  unset optional fields, while contract defaults captured by Pydantic are
  preserved).
- Cross-reference representation consistency (single canonical key order per
  entity).
- Deterministic numeric formatting via PyYAML's safe_dump.

The normalized output must re-validate through the canonical loader (spec 74
§Acceptance criteria: "Normalized output round-trips through loader validation
without semantic drift").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import yaml
from pydantic import ValidationError

from engine.config.loader import (
    ConfigValidationError,
    load_config_from_string,
)
from engine.config.models import PrototypeConfig
from engine.world_builder.validation import (
    Diagnostic,
    _extract_code,
    _pydantic_diagnostics,
    _warning_to_diag,
)


# Canonical top-level key order. Anything not in this list is appended in
# original insertion order at the end so unknown fields don't get silently dropped.
_TOP_LEVEL_ORDER = (
    "config_version",
    "scenario",
    "simulation",
    "money",
    "currency_catalog",
    "fx",
    "calendars",
    "regions",
    "pipeline",
    "world",
    "control_defaults",
)


@dataclass
class NormalizationReport:
    valid: bool
    errors: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)
    normalized_yaml: Optional[str] = None
    normalized_json: Optional[dict[str, Any]] = None
    revalidates: Optional[bool] = None  # whether normalized_yaml passes loader

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [d.to_dict() for d in self.errors],
            "warnings": [d.to_dict() for d in self.warnings],
            "normalized_yaml": self.normalized_yaml,
            "normalized_json": self.normalized_json,
            "revalidates": self.revalidates,
        }


def _ordered_top_level(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _TOP_LEVEL_ORDER:
        if k in d:
            out[k] = d[k]
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


def _sort_world(world: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(world, dict):
        return world
    out = dict(world)
    if "vendor_agents" in out and isinstance(out["vendor_agents"], list):
        vendors = sorted(out["vendor_agents"], key=lambda v: v.get("vendor_id", ""))
        for v in vendors:
            if "products" in v and isinstance(v["products"], list):
                v["products"] = sorted(v["products"], key=lambda p: p.get("product_id", ""))
        out["vendor_agents"] = vendors
    if "pops" in out and isinstance(out["pops"], list):
        pops = sorted(out["pops"], key=lambda p: p.get("pop_id", ""))
        for p in pops:
            if "product_links" in p and isinstance(p["product_links"], list):
                p["product_links"] = sorted(
                    p["product_links"],
                    key=lambda l: (l.get("vendor_id", ""), l.get("product_id", "")),
                )
        out["pops"] = pops
    return out


def _sort_pipeline(pipeline: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(pipeline, dict):
        return pipeline
    out = dict(pipeline)
    if "pipeline_profiles" in out and isinstance(out["pipeline_profiles"], list):
        out["pipeline_profiles"] = sorted(
            out["pipeline_profiles"],
            key=lambda p: p.get("pipeline_profile_id", ""),
        )
    return out


def _canonicalize(data: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic ordering: top-level keys, vendors/products/pops, profiles."""
    result = _ordered_top_level(data)
    if "world" in result:
        result["world"] = _sort_world(result["world"])
    if "pipeline" in result:
        result["pipeline"] = _sort_pipeline(result["pipeline"])
    # Sort calendars and regions by their stable IDs as well (spec 74 §canonical
    # ordering of key entity arrays).
    if "calendars" in result and isinstance(result["calendars"], list):
        result["calendars"] = sorted(
            result["calendars"], key=lambda c: c.get("calendar_id", "")
        )
    if "regions" in result and isinstance(result["regions"], list):
        result["regions"] = sorted(
            result["regions"], key=lambda r: r.get("region_id", "")
        )
    return result


def normalize_yaml_string(yaml_text: str) -> NormalizationReport:
    """Validate then emit deterministic canonical YAML.

    If the input fails validation, normalization is skipped and the report
    carries the validation diagnostics with `normalized_yaml=None`.
    """
    # Parse + validate first; normalization is only meaningful for valid configs.
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return NormalizationReport(
            valid=False,
            errors=[Diagnostic(code="E_YAML_PARSE", message=str(exc))],
        )
    if not isinstance(parsed, dict):
        return NormalizationReport(
            valid=False,
            errors=[Diagnostic(
                code="E_YAML_TOPLEVEL_NOT_MAPPING",
                message=f"Top-level YAML must be a mapping; got {type(parsed).__name__}",
            )],
        )

    try:
        cfg = PrototypeConfig.model_validate(parsed)
    except ValidationError as exc:
        return NormalizationReport(
            valid=False,
            errors=_pydantic_diagnostics(exc),
        )

    try:
        cfg, warns = load_config_from_string(yaml_text)
    except ConfigValidationError as exc:
        return NormalizationReport(
            valid=False,
            errors=[Diagnostic(
                code=exc.code, message=exc.message, path=exc.field
            )],
        )

    # `mode="json"` keeps numeric/string forms YAML-friendly; `exclude_none`
    # drops unset optionals so we don't emit `null` placeholders that the
    # original document didn't author. Pydantic-captured contract defaults
    # are preserved.
    dumped = cfg.model_dump(mode="json", exclude_none=True)
    canonical = _canonicalize(dumped)

    normalized_yaml = yaml.safe_dump(
        canonical,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=1000,
    )

    # Round-trip the normalized YAML through canonical validation to satisfy
    # spec 74 §Acceptance criteria: "Normalized output round-trips through
    # loader validation without semantic drift".
    revalidates = True
    try:
        load_config_from_string(normalized_yaml)
    except ConfigValidationError:
        revalidates = False

    return NormalizationReport(
        valid=True,
        errors=[],
        warnings=[_warning_to_diag(w) for w in warns],
        normalized_yaml=normalized_yaml,
        normalized_json=canonical,
        revalidates=revalidates,
    )
