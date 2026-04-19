# Simulation Architecture

**Status:** Draft
**Binding level:** Mixed (`v1` runtime-binding baseline, `v2` spec-only extensions, `v3` runtime-binding for promoted pipeline scope)

## Purpose

Engine boundaries: Mesa scheduling, **tick semantics** (one tick = one simulated day), **play modes** (normal vs debug retention), **wall-clock pacing**, **pause** behavior, **determinism**, persistence of aggregates and optional detailed history, and tech stack alignment.

**Cross-references:** transaction materialization and retention **`33-transaction-pipeline.md`**; fees and postings **`21-fee-economics.md`**; rails transfers **`20-payment-rails.md`**; player pause and decisions **`10-player-journey.md`**; control authority **`31-agents.md`**; realtime control messages **`52-realtime-ui-protocol.md`**; caps and defaults **`40-yaml-config.md`**, **`41-balance-knobs.md`**.

---

## Versioning and promotion policy

- `v1` remains the active runtime architecture contract for `prototype_vendor_pop_v1`.
- `v2_foundations` additions are architecture/spec contracts that may reserve fields and sequencing language but do not require runtime behavior change.
- `v3_runtime` is the target where promoted pipeline stages become execution requirements.
- Promotion note: transaction pipeline runtime promotion is approved in **ADR-0002** when `pipeline_schema_version == v3_runtime`.
- Promotion criteria for any pipeline stage:
  - stage semantics are specified in **`33-transaction-pipeline.md`**,
  - config surface is locked in **`40-yaml-config.md`**,
  - determinism impact is documented in this chapter and accepted by architecture review.

### Binding matrix

| Area | `v1` | `v2_foundations` | `v3_runtime` |
|---|---|---|---|
| Tick lifecycle | Runtime-binding | Runtime-binding | Runtime-binding |
| Agent `Onboard`/`Transact` order | Runtime-binding | Runtime-binding | Runtime-binding |
| Full intent->fee->posting->transfer pipeline | Deferred | Spec-only contract | Runtime-binding |
| Debug detailed retention controls | Reserved/validated | Spec-level retention contract | Runtime-binding (queryable store required) |

---

## Tick semantics

- **One tick = one simulated day.** Intra-day mechanics (authorization, clearing, settlement as modeled) run **within** that tick and produce **economic outcomes** for the day: volumes, fees, fund transfers, and **aggregated accounting postings** to institutional P&L/balance sheet and pop sinks (**`01-principles.md`** accounting boundary).
- **Process order (conceptual):** world state at start of day → agent steps and exogenous inputs → aggregate transaction intents and pipeline stages (**`33-transaction-pipeline.md`**) → fee calculations (**`21-fee-economics.md`**) → fund movement per rails (**`20-payment-rails.md`**) → ledger postings → events/shocks (**`34-events-scheduler.md`**) → end-of-day snapshots and optional detailed logging (mode-dependent). Exact ordering for determinism must be **fixed and documented** in implementation; any parallelization must preserve bitwise or documented equivalence to a serial reference order.
- Deterministic stage order for `v3_runtime` is fixed as: intents -> fees -> postings -> asset transfers -> retention.

### Start date and calendar boundary (v2 foundations spec)

- Scenario start date is configuration-driven (`scenario.start_date` in **`40-yaml-config.md`**) and accepts either `"today"` (resolved once at run start) or explicit `YYYY-MM-DD`.
- Tick-to-date mapping after start-date resolution is deterministic (`date(T) = start_date + T days`).
- Region-to-calendar assignment is configuration-driven; regions reference calendar objects and do not define weekend/holiday rules directly.
- World entities may carry `region_id` mapping so vendors/pops resolve calendar context through region assignment.
- In v2 foundations, this is a schema/spec boundary only; runtime adoption is deferred.

### Numeric type and rounding policy (required)

- Counts that represent **people** or **transaction cardinality** are discrete and must be emitted/stored as **integers** (for example: requested onboard count, accepted onboard count, requested txns, successful txns, failed txns, onboarded population stock).
- Fractional intermediate math is allowed internally, but values crossing contract boundaries (state, events, API, snapshots, persisted aggregates) must apply deterministic rounding first.
- Default rounding for discrete counts is **round half up** (`x.5 -> ceil`, otherwise nearest integer), with floor at zero unless a scenario explicitly allows signed deltas.
- Monetary amounts remain numeric but must use a declared scale/rounding policy from config (`40-yaml-config.md`) before emission/persistence.

---

## Play modes: normal vs debug (retention only)

Modes differ by **what is stored after each tick**, not by different economic rules. Same **seed** and configuration should yield the **same** simulated trajectory (**Determinism** below).

### Normal play-through

- The engine **simulates** within-day transaction activity to drive fees, transfers, and postings.
- For **ongoing play and statistics**, persist **end-of-day summary snapshots** only (aggregates, ledger balances, KPI buckets)—not a durable per-intent or per-microscopic-event row store for the full run. Exact snapshot schema **`23-metrics-kpis.md`**, **`42-fixtures-and-snapshots.md`**.

### Debug play-through

- The user configures a **rolling window** of **N ticks** (simulated days) for which **detailed** simulation history is retained (**full per-aggregate / per-bucket log** for those days—see **`33-transaction-pipeline.md`**). Older ticks **drop out** of the window as the run advances.
- **N** is **capped** by configuration (**`40-yaml-config.md`**) to bound memory and storage.

---

## Persistence of detailed history (debug)

- Detailed retention should use a **queryable store** (e.g. embedded **SQLite** or equivalent) so the UI and tools can **filter, aggregate, and drill down** without loading everything into memory. Schema and migration strategy are implementation details; the spec requires **effective querying** for debug workflows, not a specific SQL dialect.
- Normal-mode EOD snapshots may use the same engine or lighter storage; **authoritative** long-run history for normal play remains **aggregate-level**, not full debug detail.

---

## Wall-clock pacing and speed multipliers

- `tick_wall_clock_base_ms` defines the **total wall-clock budget for one tick** at **1x** speed.
- `intake_window_ms` defines the intake sub-window **within that same tick budget** (not an additional delay after/before tick budget).
- Tick timing at speed `S` follows one budget model:
  - `tick_budget_ms = tick_wall_clock_base_ms / S`
  - `intake_budget_ms = intake_window_ms / S`
  - `processing_budget_ms = max(0, tick_budget_ms - intake_budget_ms)`
- Intake and processing are contiguous phases of a single tick. Do **not** add intake and base tick as separate waits; doing so would overrun intended tick length.
- If simulation processing finishes earlier than remaining processing budget, engine may wait out the remainder to preserve pacing. If processing exceeds budget, tick overruns and next tick starts immediately (no extra compensating wait).
- The base interval and intake sub-window are **configurable** via **`40-yaml-config.md`** / **`41-balance-knobs.md`** and may be tuned after performance testing—not hard-coded in this spec.

---

## Pause

- When the user requests **pause**, the run **always stops at the end of the current tick** (after that tick’s simulation and persistence for that mode are complete). There is **no** mid-tick interactive pause.
- While paused, the user may inspect state and issue **decisions**; **all decisions take effect starting the next tick** the engine executes (**`10-player-journey.md`**, **`31-agents.md`**).

## Next Day (single-step advance)

- When the user requests **Next Day** (single tick forward) while **paused**, the engine runs **exactly one** tick, then returns to **paused**. No **continuous** run is started.
- **Wall-clock pacing** (**1× / 2× / 3×**) applies to **wait between ticks** in **continuous** mode only (**Resume**). After a **Next Day** step, the run is **idle** again: there is **no** mandatory extra wait before the user can issue another **Next Day**, control-panel edit, or **Resume** (optional UI animation may use wall time without affecting simulation state).
- **Determinism:** stepping with **Next Day** vs **Resume** for the **same** number of ticks must yield the **same** simulation outcomes **given the same decisions** committed before each tick (**`10-player-journey.md`**).

---

## Determinism

- Runs with the same **seed**, **configuration**, and **decision inputs** (including timing of decisions relative to tick boundaries) must produce the **same** trajectory under the engine’s **determinism policy** (same pseudo-random stream usage, no reliance on wall-clock for simulation logic). Wall-clock pacing must **not** change simulation outcomes.

---

## Prototype v1 execution profile (vertical slice)

For the bare-bones prototype (`prototype_vendor_pop_v1`), define an explicit minimal runtime profile:

- **Single-process authoritative simulation loop** (no distributed scheduling assumptions).
- **Tick-boundary command intake window** with explicit close and processing phases.
- **Deterministic command ordering** per tick:
  - commands targeted to tick `T` are ordered by stable ingest order (or equivalent deterministic tie-breaker)
  - commands arriving after intake close for `T` are deferred to `T+1`
- **Agent-owned action execution:** simulation logic calls agent methods; external commands modify control state and do not directly execute counterpart actions.

### Prototype tick cycle (minimum contract)

1. Emit/open **intake window** for tick `T`.
2. Receive and validate user commands while intake is open.
3. Close intake window for `T`.
4. Run **`tick_user_inputs_processed`** phase for `T`:
   - apply accepted intake commands for tick `T` to control/world state.
5. Start simulation loop for `T` with fixed method order:
   - call `Onboard()` on all agent classes (noop allowed by class contract),
   - then call `Transact()` on all agent classes.
6. Run pipeline adjudication and aggregate outputs (see **`33-transaction-pipeline.md`**).
7. Commit world-state changes atomically for tick close (`tick_committed`).
8. Emit tick lifecycle and outcome events for clients (see **`52-realtime-ui-protocol.md`**).

### Timing semantics for user inputs

- If a command is accepted **before** tick `T` intake closes, its effects are applied in **`tick_user_inputs_processed`** for `T`, and therefore can affect simulation outcomes in the **same tick**.
- If a command arrives **after** intake close for `T`, it is queued for processing in `T+1`.

### Prototype persistence minimum

- World state may be maintained in memory for this slice.
- At each committed tick, produce a lightweight snapshot payload sufficient for:
  - API state query (`51`)
  - realtime `state_snapshot` updates (`52`)
  - deterministic integration-test assertions.

Durable full-history storage is not required for this prototype beyond existing normal/debug chapter commitments.

---

## Performance and implementation notes (non-binding)

- **Single vs multi-process**, threading, and batching are implementation choices subject to the determinism policy and observable outcomes above.
- Target machine assumptions and scale notes (pop slices, institutions) may be recorded in **`41-balance-knobs.md`** or ADRs as needed.
