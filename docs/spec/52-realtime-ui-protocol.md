# Realtime UI Protocol

**Status:** Draft

## Purpose

Streaming contract between engine and dashboard: snapshots, deltas, throttling, and **simulation control** events (pause, speed, debug settings).

**Cross-references:** API control plane **`51-api-contract.md`**; tick and pause semantics **`30-architecture.md`**; player UX **`12-ui-ux-spec.md`**.

---

## Control messages (outline)

- **Pause requested** — If intake is still open for tick `T`, server enters **pause_pending** and freezes intake countdown; otherwise server pauses after current tick commit.
- **Resume** — If intake countdown is frozen by pause-pending, resume unfreezes that countdown from remaining time; otherwise it resumes continuous play between ticks.
- **Next day** — Client requests **single** tick while **paused**; server runs **one** tick, emits **paused** again with updated tick id (**no** inter-tick speed wait after the step—**`30-architecture.md`**).
- **Set speed** — **1×**, **2×**, **3×** (or multiplier); affects **wait only** between ticks in **continuous** mode, not simulation math.
- **Set debug rolling window** — **Deferred for prototype runtime** until transaction-pipeline detailed bucket history exists; current scope keeps config keys and does not require runtime control messages for this yet (**`33-transaction-pipeline.md`**).
- **Decision submitted** — Acknowledge with target/processing tick metadata; same-tick vs next-tick processing follows intake-close timing rules (**`30-architecture.md`**, **`31-agents.md`**).
- **Config reload + world restart** — Client can request server config re-read and world restart; stream emits restart lifecycle events and fresh snapshot boundary.
- **Server shutdown request** — Client can request graceful shutdown via control API; stream emits `server_shutdown` before close.

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

Tick time model semantics for clients:

- `tick_wall_clock_base_ms` is total tick budget at 1x; `intake_window_ms` is contained within that budget.
- Client countdowns must treat intake and processing as phases of one tick timeline, not two additive timelines.

Count and quantity fields inside lifecycle/outcome/snapshot payloads must follow numeric typing policy:

- Person and transaction counts are emitted as integers.
- Amount fields use configured amount scale/rounding from **`40-yaml-config.md`**.

Date and currency visibility fields are required for TUI/operator readability:

- `simulation_date` (`YYYY-MM-DD`) should be present in `tick_committed` and `state_snapshot`.
- `default_currency` (ISO 4217 alpha-3) should be present in `state_snapshot` (or nested config block).
- Amount-bearing events should include explicit currency context via money objects.

### Additional prototype events

- `command_ack` (accepted/rejected + target tick metadata)
- `action_outcome` (request/decision outcomes for onboard/transact)
- `state_snapshot` (post-commit state for text UI and tests)
- `intake_countdown_paused` (pause requested while intake is open; includes remaining ms)
- `intake_countdown_resumed` (resume during frozen intake; includes remaining ms at resume)
- `world_restarting` (reload requested and accepted; old world draining)
- `world_restarted` (new world initialized; includes new baseline tick/snapshot generation id)
- `server_shutdown` (server is intentionally going down; includes reason, reconnect hint, and restart intent)

### Pipeline observability event family (required for TUI operator views)

To support pipeline/ledger observability sections in **`60-screen-specs.md`**, stream must expose compact events (or equivalent snapshot substructures) for:

- `transaction_intent_event`
  - intent creation/routing details, source product, destination role/product, value date policy + resolved date.
  - must include `intent_stage` (`original_incoming` or `routed_outgoing`) so operators can see both original and derivative intents in logs.
  - must include a stable correlation reference (`root_intent_id`) shared by the original intent and all routed derivatives.
  - for routed intents, payload should include:
    - `routing_completion_mode` (`synchronous` | `asynchronous`)
    - execution status (`pending` | `executed` | `rejected`)
    - reason code for non-success paths.
- `fee_accrual_event`
  - fee id, beneficiary role/product, amount components (`count_cost`, `amount_percentage`), accrual status.
- `value_transfer_event`
  - source/destination container refs, amount, value date policy + resolved date, execution status.
- `posting_entry_event`
  - source/destination ledger refs, debit/credit amount, posting date/status.
- `invoice_transaction_event`
  - emitted on due-date lifecycle transition from accrued fee to invoiced artifact, representing aggregated fees due on the same date.
- `settlement_resolution_event`
  - emitted after invoice handling with final settlement outcome (`paid` or `failed`) and residual amount.

Event payloads should include consistent correlation keys for cross-view drill-down:

- `tick_id`
- `simulation_date`
- `pipeline_profile_id`
- `product_id`
- one or more of `intent_id`, `trigger_id`, `fee_id`, `invoice_id`
- `root_intent_id` when intent fan-out/routing occurs

For async fan-out paths, `transaction_intent_event` resolution emissions should reuse the same `intent_id` + `root_intent_id` as the original pending routed emission.

### Payload minimums for date/currency visibility

- `tick_committed` minimum extension:
  - `tick_id`
  - `simulation_date`
  - amount-bearing fields with explicit currency context
- `state_snapshot` minimum extension:
  - `tick_id`
  - `simulation_date`
  - `scenario_start_date_resolved`
  - `default_currency`
  - `config.amount_scale_dp`
  - `config.amount_rounding_mode`

### Ordering requirement

For a given tick `T`, lifecycle events must preserve order:

1. `tick_intake_window_opened`
2. `tick_intake_window_closed`
3. `tick_user_inputs_processed`
4. `tick_committed`

Command and outcome events may interleave by phase, but must not violate this lifecycle order.

For asynchronous routed legs, cross-tick ordering should follow:

1. origin tick emits routed intent as `pending`,
2. resolution tick emits routed intent as `executed` or `rejected`,
3. if resolved `executed`, destination-side fee/posting/transfer events may follow in that same resolution tick.

When pause is requested during intake-open for tick `T`:

1. `tick_intake_window_opened`
2. `intake_countdown_paused`
3. (optional idle interval while frozen)
4. `intake_countdown_resumed` (after resume)
5. `tick_intake_window_closed`
6. `tick_user_inputs_processed`
7. `tick_committed`

If pause-pending is still active at step 7, next state snapshot must indicate `paused`.

---

## Shutdown and reconnect contract (prototype requirement)

- Server must emit `server_shutdown` to SSE subscribers before intentionally closing event streams.
- `server_shutdown` payload should include at least:
  - `reason` (for example: `manual_shutdown`, `config_reload_restart`, `deploy`)
  - `grace_period_ms` (time before stream termination when possible)
  - `reconnect_after_ms` (recommended client retry delay)
  - `will_restart` (boolean)
- After emitting `server_shutdown`, server may close SSE connections.
- Clients should treat stream close without prior `server_shutdown` as unexpected failure and apply exponential backoff reconnect.
- Clients should treat stream close after `server_shutdown` as expected transition and reconnect using provided delay hint.
- Clients should not surface a transport-error banner for expected close after `server_shutdown`; UI should show an expected lifecycle transition instead.
- `server_shutdown.will_restart == true` is required for reload-driven restarts (`reason=config_reload_restart`).
- When `server_shutdown.will_restart == false`, clients may switch from reconnect loop to explicit "server offline" state after bounded retries.

---

## Contents (to complete)

- Channel(s): WebSocket vs SSE
- Message types: full snapshot vs patch (including post-tick snapshots)
- Throttling / coalescing rules
- Client reconnection and resume (must recover tick id, paused state, speed, debug **N**)
