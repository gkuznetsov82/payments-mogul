"""Canonical YAML validation for the World Builder service.

Wraps `engine.config.loader.load_config_from_string` so the builder uses the
same validation rules as runtime startup. Returns a structured envelope with
stable error/warning codes (spec 50, spec 74 §Validation ownership).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import yaml
from pydantic import ValidationError

from engine.config.loader import (
    ConfigValidationError,
    ConfigWarning,
    load_config_from_string,
)
from engine.config.models import PrototypeConfig


@dataclass
class Diagnostic:
    code: str
    message: str
    path: Optional[str] = None
    severity: str = "error"  # "error" | "warning"
    # Optional graph-target hint for the World Builder UI: if set, the UI can
    # focus/highlight this node when the diagnostic is clicked. When unset,
    # the UI must show an explicit "no graph target" fallback (spec 74 §UI
    # diagnostics-to-node linking, spec 75 §P2).
    node_id: Optional[str] = None
    # Optional edge-target hint. Edges in the topology graph use synthetic
    # IDs of the form `e-<idx>-<src>-><tgt>-<kind>` (see frontend layout.ts);
    # in the pipeline drill-down view edges use `pe:<profile_id>:<descriptor>`.
    edge_id: Optional[str] = None
    # Section the diagnostic belongs to (`scenario` | `simulation` | `world`
    # | `pipeline` | `money` | `fx` | `calendars` | `regions` | `control_defaults`).
    # Derived from `path` when not set explicitly. Optional — UI uses it for
    # the section navigator filter.
    section: Optional[str] = None
    # Which graph view this diagnostic targets (`topology` | `pipeline`).
    # When set, clicking the diagnostic flips the UI to that view before
    # focusing the node/edge. Backfilled from `section` when omitted.
    graph_view: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Backfill section from path when caller didn't set it explicitly so
        # the UI section navigator can group/filter consistently.
        if d.get("section") is None:
            d["section"] = _section_from_path(d.get("path"))
        if d.get("graph_view") is None:
            d["graph_view"] = _graph_view_for_section(d.get("section"))
        return d


def _graph_view_for_section(section: Optional[str]) -> Optional[str]:
    """Default mapping of diagnostic section -> preferred graph view.

    Pipeline-section diagnostics route to the pipeline drill-down; world/region/
    calendar diagnostics route to the topology view. Anything else has no
    natural graph view and the UI falls back to its 'no target' state.
    """
    if section is None:
        return None
    if section == "pipeline":
        return "pipeline"
    if section in {"world", "regions", "calendars"}:
        return "topology"
    return None


_KNOWN_SECTIONS = {
    "scenario", "simulation", "world", "pipeline",
    "money", "currency_catalog", "fx",
    "calendars", "regions", "control_defaults",
}


def _section_from_path(path: Optional[str]) -> Optional[str]:
    """Map a dotted config path to its top-level section, when discoverable."""
    if not path:
        return None
    head = path.split(".", 1)[0].split("[", 1)[0]
    return head if head in _KNOWN_SECTIONS else None


@dataclass
class ValidationReport:
    valid: bool
    errors: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)
    schema_version: Optional[str] = None
    pipeline_schema_version: Optional[str] = None
    summary: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [d.to_dict() for d in self.errors],
            "warnings": [d.to_dict() for d in self.warnings],
            "schema_version": self.schema_version,
            "pipeline_schema_version": self.pipeline_schema_version,
            "summary": self.summary,
        }


def _pydantic_diagnostics(exc: ValidationError) -> list[Diagnostic]:
    """Translate pydantic ValidationError into multiple stable-code diagnostics."""
    diags: list[Diagnostic] = []
    for err in exc.errors():
        msg = str(err.get("msg", ""))
        code = _extract_code(msg)
        loc = err.get("loc", ())
        path = ".".join(str(p) for p in loc) if loc else None
        diags.append(Diagnostic(code=code, message=msg, path=path, severity="error"))
    return diags


def _extract_code(msg: str) -> str:
    """Pull E_XXX/W_XXX stable code from a validator message."""
    for token in msg.split():
        stripped = token.rstrip(":,.")
        if stripped.startswith("E_") or stripped.startswith("W_"):
            return stripped
    return "E_CONFIG_INVALID"


def _build_summary(cfg: PrototypeConfig) -> dict[str, Any]:
    pipeline_profiles: list[str] = []
    if cfg.pipeline is not None:
        pipeline_profiles = [p.pipeline_profile_id for p in cfg.pipeline.pipeline_profiles]
    return {
        "scenario_id": cfg.scenario.id,
        "config_version": cfg.config_version,
        "vendor_count": len(cfg.world.vendor_agents),
        "product_count": sum(len(v.products) for v in cfg.world.vendor_agents),
        "pop_count": len(cfg.world.pops),
        "region_count": len(cfg.regions),
        "calendar_count": len(cfg.calendars),
        "pipeline_profile_count": len(pipeline_profiles),
        "pipeline_profile_ids": pipeline_profiles,
    }


def _warning_to_diag(w: ConfigWarning) -> Diagnostic:
    return Diagnostic(code=w.code, message=w.message, path=None, severity="warning")


def validate_yaml_string(yaml_text: str) -> ValidationReport:
    """Run canonical validation over an in-memory YAML document.

    Always returns a ValidationReport; never raises. Parse errors are surfaced
    as `E_YAML_PARSE` diagnostics so the UI can render them deterministically.
    """
    # Step 1: parse safely. Surfaced as a single E_YAML_PARSE diagnostic on failure.
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return ValidationReport(
            valid=False,
            errors=[Diagnostic(code="E_YAML_PARSE", message=str(exc), path=None)],
        )

    if parsed is None:
        return ValidationReport(
            valid=False,
            errors=[Diagnostic(
                code="E_YAML_EMPTY",
                message="YAML document is empty",
                path=None,
            )],
        )
    if not isinstance(parsed, dict):
        return ValidationReport(
            valid=False,
            errors=[Diagnostic(
                code="E_YAML_TOPLEVEL_NOT_MAPPING",
                message=f"Top-level YAML must be a mapping; got {type(parsed).__name__}",
                path=None,
            )],
        )

    # Step 2: Pydantic schema validation (collects multiple errors at once).
    try:
        PrototypeConfig.model_validate(parsed)
    except ValidationError as exc:
        return ValidationReport(
            valid=False,
            errors=_pydantic_diagnostics(exc),
            schema_version=parsed.get("config_version"),
        )

    # Step 3: Cross-entity validation via canonical loader (fail-fast — matches
    # runtime semantics; deterministic single error if any).
    try:
        cfg, warns = load_config_from_string(yaml_text)
    except ConfigValidationError as exc:
        return ValidationReport(
            valid=False,
            errors=[Diagnostic(
                code=exc.code,
                message=exc.message,
                path=exc.field,
                severity="error",
            )],
            schema_version=parsed.get("config_version"),
        )

    pipeline_schema = (
        cfg.pipeline.pipeline_schema_version if cfg.pipeline is not None else None
    )
    return ValidationReport(
        valid=True,
        errors=[],
        warnings=[_warning_to_diag(w) for w in warns],
        schema_version=cfg.config_version,
        pipeline_schema_version=pipeline_schema,
        summary=_build_summary(cfg),
    )
