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
- **Decisions / controls** — Submit intake-window control commands for entities (scoped by auth/control graph policy—**`31-agents.md`**); processing tick depends on intake-close timing (**`30-architecture.md`**).

Exact routes, request bodies, and OpenAPI embedding strategy: **to complete**.

---

## Prototype v1 intake-window control APIs

For `prototype_vendor_pop_v1`, API inputs are treated as **control-state commands** during the tick intake window. They do not directly execute agent transaction actions.

### Example prototype commands

- `CloseOnboarding(vendor_id, product_id)`
- `OpenOnboarding(vendor_id, product_id)`
- (optional extension) `CloseTransacting(vendor_id, product_id)` / `OpenTransacting(vendor_id, product_id)`

### Timing semantics

- If a command is accepted before tick `T` intake closes, it is applied in `tick_T_user_inputs_processed`, so tick `T` simulation can already be affected.
- If a command arrives after intake close for `T`, it is scheduled for processing in `T+1`.
- API acknowledgement should indicate which tick the command will be processed in.

### Minimum command acknowledgement envelope

- `command_id`
- `accepted` (boolean)
- `target_tick`
- `processed_in_tick` (when available after processing)
- `rejection_reason` (when rejected)

### Authority model (phased)

- **Prototype now:** control commands may target any agent/product in scope of the run.
- **Future:** command authorization is constrained by in-game Person authority (for example, Person-in-Charge scope).

---

## Contents (to complete)

- Resources and routes outline (full catalog)
- Request/response shapes (reference or embed OpenAPI strategy)
- Auth (if any) and versioning
- Pagination and export formats
- **Query** endpoints or export for **debug** bucket history (filter by time, institution, dimensions) if not solely over realtime
