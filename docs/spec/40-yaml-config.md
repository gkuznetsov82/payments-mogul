# YAML Configuration

**Status:** Draft

## Purpose

Config file layout, anchors/aliases patterns, mapping to Pydantic models, and **runtime simulation controls** (tick pacing, debug retention caps) that must be validated at load time.

**Cross-references:** balance defaults **`41-balance-knobs.md`**; architecture **`30-architecture.md`**; pipeline **`33-transaction-pipeline.md`**.

---

## Simulation and observability (required keys / sections)

These belong in **base** or **scenario** config (exact shape is implementation-defined but must be **validated**):

- **`tick_wall_clock_base_ms`** (or equivalent) — Minimum wall-clock **wait** between ticks at **1×** speed, after simulated work completes. Tunable; default TBD after stress testing (**`30-architecture.md`**).
- **`debug_history_max_ticks`** — **Hard cap** on the user-selectable **rolling window** length for **debug** detailed history. Must reject or clamp invalid values (**`33-transaction-pipeline.md`**).
- Optional: **`debug_history_default_ticks`** — Suggested default when enabling debug mode.

Implementation may store **debug bucket history** in an embedded **database** path or URI (**`30-architecture.md`**); if so, surface **path**, **size limits**, and **cleanup** policy in config or ADR.

---

## Contents (to complete)

- Directory structure (e.g., scenarios/, agents/, rails/)
- Anchor/alias conventions for portfolios
- Override order (scenario vs base)
- Validation errors: path reporting for authors
