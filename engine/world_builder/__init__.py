"""World Builder service (spec 74 §v0_viewer, spec 75 §P0/P1/P2).

Standalone slice that exposes authoritative validation, deterministic
normalization, and analysis-graph construction for YAML world configs.

Reuses `engine.config.loader` and `engine.config.models` so validation logic
does not fork between the simulation runtime and the builder.
"""

from engine.world_builder.validation import (
    Diagnostic,
    ValidationReport,
    validate_yaml_string,
)
from engine.world_builder.normalize import NormalizationReport, normalize_yaml_string
from engine.world_builder.analyze import AnalysisReport, analyze_yaml_string

__all__ = [
    "Diagnostic",
    "ValidationReport",
    "validate_yaml_string",
    "NormalizationReport",
    "normalize_yaml_string",
    "AnalysisReport",
    "analyze_yaml_string",
]
