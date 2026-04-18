# Realtime UI Protocol

**Status:** Draft

## Purpose

Streaming contract between engine and dashboard: snapshots, deltas, throttling, and **simulation control** events (pause, speed, debug settings).

**Cross-references:** API control plane **`51-api-contract.md`**; tick and pause semantics **`30-architecture.md`**; player UX **`12-ui-ux-spec.md`**.

---

## Control messages (outline)

- **Pause requested** — Server completes **current tick**, then emits **paused** with tick id and snapshot boundary.
- **Resume** — Client requests **continuous** play; **next tick** begins after any configured **wall-clock wait** for current speed (**`30-architecture.md`**).
- **Next day** — Client requests **single** tick while **paused**; server runs **one** tick, emits **paused** again with updated tick id (**no** inter-tick speed wait after the step—**`30-architecture.md`**).
- **Set speed** — **1×**, **2×**, **3×** (or multiplier); affects **wait only** between ticks in **continuous** mode, not simulation math.
- **Set debug rolling window** — **N** ticks, clamped to config max; may trigger **storage** resize or prune messages.
- **Decision submitted** — Acknowledge with target/processing tick metadata; same-tick vs next-tick processing follows intake-close timing rules (**`30-architecture.md`**, **`31-agents.md`**).

---

## Prototype v1 tick lifecycle events

For `prototype_vendor_pop_v1`, realtime stream should expose the control/simulation boundary explicitly:

- `tick_intake_window_opened`
- `tick_intake_window_closed`
- `tick_user_inputs_processed`
- `tick_committed`

### Event semantics (minimum)

- `tick_intake_window_opened`: server begins accepting control commands for tick `T`.
- `tick_intake_window_closed`: intake for tick `T` is frozen.
- `tick_user_inputs_processed`: accepted commands for tick `T` were applied; simulation run for `T` has not yet committed.
- `tick_committed`: simulation for tick `T` has completed and state changes are committed.

### Additional prototype events

- `command_ack` (accepted/rejected + target tick metadata)
- `action_outcome` (request/decision outcomes for onboard/transact)
- `state_snapshot` (post-commit state for text UI and tests)

### Ordering requirement

For a given tick `T`, lifecycle events must preserve order:

1. `tick_intake_window_opened`
2. `tick_intake_window_closed`
3. `tick_user_inputs_processed`
4. `tick_committed`

Command and outcome events may interleave by phase, but must not violate this lifecycle order.

---

## Contents (to complete)

- Channel(s): WebSocket vs SSE
- Message types: full snapshot vs patch (including post-tick snapshots)
- Throttling / coalescing rules
- Client reconnection and resume (must recover tick id, paused state, speed, debug **N**)
