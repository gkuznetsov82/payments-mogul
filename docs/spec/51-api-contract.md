# API Contract (FastAPI)

**Status:** Draft

## Purpose

HTTP/WebSocket surface: runs, control plane, and exports.

**Cross-references:** realtime messages **`52-realtime-ui-protocol.md`**; pause and pacing **`30-architecture.md`**.

---

## Control plane (outline)

The API must support at minimum:

- **Run lifecycle** — Start, stop, save/load run state (details TBD).
- **Pause / resume** — Request pause (details below); **resume** advances ticks **continuously**, subject to **speed** pacing between ticks.
- **Next day** (single step) — While **paused**, advances **one** tick then remains **paused**; no inter-tick speed wait applied after the step (**`30-architecture.md`**).
- **Speed** — Set **1× / 2× / 3×** (or scalar multiplier) relative to configured base interval for **continuous** advance only.
- **Debug window** — **Deferred for prototype runtime** until transaction pipeline emits compactable debug data; for now, keep `debug_history_*` as validated config/reserved controls only (**`33-transaction-pipeline.md`**, **`40-yaml-config.md`**).
- **Decisions / controls** — Submit intake-window control commands for entities (scoped by auth/control graph policy—**`31-agents.md`**); processing tick depends on intake-close timing (**`30-architecture.md`**).
- **Config reload + world restart** — Command to re-read server config and restart world state from tick 0 (details below).
- **Server shutdown** — Command to request graceful server shutdown with pre-close SSE notification (details below).

Exact routes, request bodies, and OpenAPI embedding strategy: **to complete**.

---

## Prototype v1 intake-window control APIs

For `prototype_vendor_pop_v1`, API inputs are treated as **control-state commands** during the tick intake window. They do not directly execute agent transaction actions.

### Pause/resume semantics for long intake windows

- If **Pause** is requested while tick `T` intake is still open, server enters **pause-pending** and **freezes intake countdown** at remaining duration.
- While intake countdown is frozen, no intake-close transition occurs until **Resume**.
- If **Resume** is requested during this frozen intake, server **unfreezes** intake countdown and continues tick `T` from remaining intake time.
- If pause-pending remains active through intake close and tick processing, server pauses after `tick_T_committed`.
- If **Pause** is requested after intake already closed for tick `T`, behavior remains "pause after `tick_T_committed`" (no countdown freeze because intake is already closed).
- API responses should expose whether pause is immediate, pause-pending, or resumed-from-pause-pending so UI can reflect true control state.

### Config reload + world restart command

- Add a control endpoint for **config re-read + world restart** (for example, `POST /control/reload_config`).
- On acceptance, server must:
  1. Re-read scenario YAML from configured source.
  2. Re-validate config using standard validation rules.
  3. Replace simulation world with a new initialized world if validation succeeds.
  4. Reset run state to startup baseline (at minimum: tick id to initial value, fresh agent state, cleared transient command queues).
- If validation fails, server returns validation failure details and keeps current world running.
- Response should include a structured result (`accepted`, `reloaded`, `error_codes`/`rejection_reason`, and world generation identifier if used).

### Server shutdown command

- Add a control endpoint for graceful shutdown (for example, `POST /control/shutdown`).
- On acceptance, server must emit `server_shutdown` to subscribers before closing streams/process.
- Response should include accepted/rejected status and shutdown timing hints (`grace_period_ms`, optional `reconnect_after_ms`).
- If shutdown command is rejected (for policy/authorization reasons), return explicit `rejection_reason`.

### Example prototype commands

- `CloseOnboarding(vendor_id, product_id)`
- `OpenOnboarding(vendor_id, product_id)`
- (optional extension) `CloseTransacting(vendor_id, product_id)` / `OpenTransacting(vendor_id, product_id)`

### Timing semantics

- If a command is accepted before tick `T` intake closes, it is applied in `tick_T_user_inputs_processed`, so tick `T` simulation can already be affected.
- If a command arrives after intake close for `T`, it is scheduled for processing in `T+1`.
- API acknowledgement should indicate which tick the command will be processed in.
- Tick pacing uses a single budget model: `tick_wall_clock_base_ms` is total tick duration at 1x, and `intake_window_ms` is its intake subset. API/control behavior must not treat them as additive waits.

### Numeric typing contract

- API payloads that represent people or transaction counts must be integers (no fractional counts).
- Amount fields remain numeric and follow configured scale/rounding policy from **`40-yaml-config.md`**.

### Date and currency visibility contract (TUI/API requirement)

To support operator clarity in TUI and other clients, API responses that expose simulation state must include:

- `simulation_date` (`YYYY-MM-DD`) - current tick-resolved business date.
- `scenario_start_date_resolved` (`YYYY-MM-DD`) - resolved value after `"today"` evaluation.
- `default_currency` (ISO 4217 alpha-3) - active default currency from config.

Amount-bearing payloads should expose currency context via one of:

- **Required:** money object form `{ amount, currency }`.

For v2 foundations spec, legacy scalar amount compatibility is intentionally not included.

### Minimum state query/snapshot fields (prototype extension)

`GET /snapshot` (or equivalent state query) should include at minimum:

- `tick_id`
- `run_mode`
- `simulation_date`
- `scenario_start_date_resolved`
- `default_currency`
- `config.amount_scale_dp`
- `config.amount_rounding_mode`

When returning aggregates/outcomes with amounts, include money objects so TUI can label units explicitly.

### Minimum command acknowledgement envelope

- `command_id`
- `accepted` (boolean)
- `target_tick`
- `processed_in_tick` (when available after processing)
- `rejection_reason` (when rejected)

For control-plane actions (`pause`, `resume`, `reload_config`, `shutdown`), provide equivalent explicit status fields so clients can distinguish:

- accepted vs rejected
- immediate effect vs pending effect
- resulting run mode (`running`, `pause_pending`, `paused`, `restarting`, `shutting_down`)

### Authority model (phased)

- **Prototype now:** control commands may target any agent/product in scope of the run.
- **Future:** command authorization is constrained by in-game Person authority (for example, Person-in-Charge scope).

---

## Contents (to complete)

- Resources and routes outline (full catalog)
- Request/response shapes (reference or embed OpenAPI strategy)
- Auth (if any) and versioning
- Pagination and export formats
- **Query** endpoints or export for **debug** bucket history (filter by time, institution, dimensions) once transaction-pipeline detailed history is implemented
- Lifecycle notification endpoint/event mapping for graceful server shutdown and reconnect behavior (see **`52-realtime-ui-protocol.md`**)
