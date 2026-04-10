# Simulation Architecture

**Status:** Draft

## Purpose

Engine boundaries: Mesa scheduling, **tick semantics** (one tick = one simulated day), **play modes** (normal vs debug retention), **wall-clock pacing**, **pause** behavior, **determinism**, persistence of aggregates and optional detailed history, and tech stack alignment.

**Cross-references:** transaction materialization and retention **`33-transaction-pipeline.md`**; fees and postings **`21-fee-economics.md`**; rails transfers **`20-payment-rails.md`**; player pause and decisions **`10-player-journey.md`**; control authority **`31-agents.md`**; realtime control messages **`52-realtime-ui-protocol.md`**; caps and defaults **`40-yaml-config.md`**, **`41-balance-knobs.md`**.

---

## Tick semantics

- **One tick = one simulated day.** Intra-day mechanics (authorization, clearing, settlement as modeled) run **within** that tick and produce **economic outcomes** for the day: volumes, fees, fund transfers, and **aggregated accounting postings** to institutional P&L/balance sheet and pop sinks (**`01-principles.md`** accounting boundary).
- **Process order (conceptual):** world state at start of day → agent steps and exogenous inputs → aggregate transaction intents and pipeline stages (**`33-transaction-pipeline.md`**) → fee calculations (**`21-fee-economics.md`**) → fund movement per rails (**`20-payment-rails.md`**) → ledger postings → events/shocks (**`34-events-scheduler.md`**) → end-of-day snapshots and optional detailed logging (mode-dependent). Exact ordering for determinism must be **fixed and documented** in implementation; any parallelization must preserve bitwise or documented equivalence to a serial reference order.

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

- Between ticks, the client may enforce a **minimum wall-clock interval** per tick at **1× speed** (e.g. if simulated work finishes in less than that interval, the engine **waits** until the interval elapses before starting the next tick). **2×** and **3×** speeds **proportionally reduce** that wait (e.g. half and one-third of the base interval at 2× and 3×), so perceived pace scales with the multiplier.
- The **base interval** (whether one second or another value) is **configurable** via **`40-yaml-config.md`** / **`41-balance-knobs.md`** and may be tuned after performance testing—not hard-coded in this spec.

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

## Performance and implementation notes (non-binding)

- **Single vs multi-process**, threading, and batching are implementation choices subject to the determinism policy and observable outcomes above.
- Target machine assumptions and scale notes (pop slices, institutions) may be recorded in **`41-balance-knobs.md`** or ADRs as needed.
