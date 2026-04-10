# Balance Knobs

**Status:** Draft

## Purpose

Central table of tunables: defaults, ranges, design intent (for scenarios and balancing), including **simulation pacing** and **debug retention** bounds.

**Cross-references:** YAML keys **`40-yaml-config.md`**; pacing semantics **`30-architecture.md`**.

---

## Simulation pacing and debug window (placeholders)

- **`tick_wall_clock_base_ms`** — Default minimum milliseconds between ticks at **1×** after simulated work completes; **min/max** bounds for UI sliders and config validation. Final defaults **after** performance testing.
- **`debug_history_max_ticks`** — Upper bound on rolling **debug** history length; may depend on target machine profile.
- **`debug_history_default_ticks`** — Optional default when enabling debug mode.

_Full knob table (units, linked formulas, sensitivity) still to complete._

---

## Contents (to complete)

- Knob name, unit, default, min/max (broader catalog)
- Linked agents or formulas
- Sensitivity notes and failure modes when extreme
