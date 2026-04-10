# API Contract (FastAPI)

**Status:** Draft

## Purpose

HTTP/WebSocket surface: runs, control plane, and exports.

**Cross-references:** realtime messages **`52-realtime-ui-protocol.md`**; pause and pacing **`30-architecture.md`**.

---

## Control plane (outline)

The API must support at minimum:

- **Run lifecycle** — Start, stop, save/load run state (details TBD).
- **Pause / resume** — Request pause (completes current tick, then idle); **resume** advances ticks **continuously**, subject to **speed** pacing between ticks.
- **Next day** (single step) — While **paused**, advances **one** tick then remains **paused**; no inter-tick speed wait applied after the step (**`30-architecture.md`**).
- **Speed** — Set **1× / 2× / 3×** (or scalar multiplier) relative to configured base interval for **continuous** advance only.
- **Debug window** — Set **rolling history length** in ticks, clamped to **`debug_history_max_ticks`** (**`40-yaml-config.md`**).
- **Decisions** — Submit **entity decisions** for **next tick** (scoped by auth and control graph—**`31-agents.md`**); validate and echo effective tick.

Exact routes, request bodies, and OpenAPI embedding strategy: **to complete**.

---

## Contents (to complete)

- Resources and routes outline (full catalog)
- Request/response shapes (reference or embed OpenAPI strategy)
- Auth (if any) and versioning
- Pagination and export formats
- **Query** endpoints or export for **debug** bucket history (filter by time, institution, dimensions) if not solely over realtime
