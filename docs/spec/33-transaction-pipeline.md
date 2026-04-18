# Transaction Pipeline

**Status:** Draft

## Purpose

How **aggregate transaction activity** within a simulated **day** (one **tick**) becomes **fees**, **fund transfers**, and **ledger postings**; what is **stored** in **normal** vs **debug** play; and how this ties to UI and reporting.

**Cross-references:** tick = one day, pause, modes **`30-architecture.md`**; fee rules **`21-fee-economics.md`**; rails and settlement **`20-payment-rails.md`**; institutions and sinks **`01-principles.md`**, **`31-agents.md`**; realtime payloads **`52-realtime-ui-protocol.md`**; config caps **`40-yaml-config.md`**.

---

## What gets simulated (all modes)

- **Within a tick**, the engine materializes **aggregate transaction intents** (e.g. pop slice × counterparty institutions × key dimensions—not individual cardholder-level rows unless a scenario explicitly requires that granularity). These intents drive:
  - **Fee calculations** per **`21-fee-economics.md`** (and scenario knobs).
  - **Fund transfers** and settlement semantics per **`20-payment-rails.md`**.
  - **Aggregated accounting postings** to the **P&L and balance sheet** of relevant **institutions** and to **pop sinks** where the model attributes flows (**`01-principles.md`**).
- **Economic rules do not change** between normal and debug mode; only **retention and inspectability** change (**`30-architecture.md`**).

### Numeric typing and rounding (required)

- Person/population counts and transaction counts are **integers** in all externally visible pipeline outputs.
- Pipeline stages may compute fractional intermediates, but before stage handoff/output they must apply configured deterministic rounding (`simulation.count_rounding_mode` in **`40-yaml-config.md`**).
- Amount fields remain numeric and must be normalized to configured scale/rounding (`amount_scale_dp`, `amount_rounding_mode`) before emission/persistence.

---

## Normal play-through (storage)

- After each tick, persist **end-of-day summary data** sufficient for **statistics**, **reports**, and **KPIs** (**`23-metrics-kpis.md`**): aggregates, closing ledger balances, and scenario-facing counters—not a full durable **per-bucket transaction log** for the entire campaign history unless a separate product requirement is added later.

---

## Debug play-through (rolling window)

- The user configures a **rolling window** of **N ticks** (simulated days). For ticks inside the window, retain a **full per-aggregate / per-bucket log** for that day (Option A: complete bucket-level detail for the dimensions the engine uses—not a statistical sample). Ticks older than **N** **expire** from the detailed store as the simulation advances.
- **N** is **capped** by configuration (**`40-yaml-config.md`**) to protect resources.
- Detailed history should live in a **queryable persistence layer** (e.g. embedded relational store—**`30-architecture.md`**) so debug UIs can query by institution, bucket, time range, and fee line without scanning flat files.
- **Prototype sequencing note:** runtime debug-window controls and retention enforcement are deferred until this pipeline emits compactable detailed data. Before that milestone, `debug_history_*` acts as reserved config only.

---

## Data for UI and charts

- The pipeline defines what **per-tick** and **per-stage** signals exist for **dashboards** and **drill-down** in debug mode; **throttling and coalescing** for realtime delivery **`52-realtime-ui-protocol.md`**.

---

## Prototype v1 pipeline subset (agent-owned flow)

For `prototype_vendor_pop_v1`, pipeline execution starts only **after** `tick_user_inputs_processed` is complete for tick `T` (**`30-architecture.md`**).

### Stage order for tick `T` (fixed)

1. **Pop onboarding requests** generated during `Pop.Onboard()`.
2. **Vendor/Product onboarding decisions** (accept/reject) via vendor-owned methods.
3. **Pop transact requests** generated during `Pop.Transact()`.
4. **Vendor/Product transact decisions** (success/failure) via vendor-owned methods.

This preserves the principle that each agent executes its own logic; external APIs do not execute counterpart transaction actions directly.

### Minimal outputs required for the prototype

- **Action outcomes** for each request/decision path (`accepted`, `rejected`, `success`, `failure` with reason code).
- **Aggregate counters** at tick close:
  - onboard requested / accepted / rejected
  - transact requested / succeeded / failed
  - successful transact amount total
- **Minimal posting placeholder** for successful transact:
  - one simplified posting entry (amount and counterpart identifiers) for integration-test assertions.

For this prototype, all listed counters are integer-valued after rounding policy application.

### Deferred in this slice

- Full fee taxonomy and line-item decomposition.
- Deep clearing/settlement stage modeling by rail.
- Rich decline hierarchies beyond basic reason codes.

---

## Contents still to detail (later)

- Named stages (authorization, clearing, settlement) as implemented in v1; decline reasons and propagation; failure modes vs P&L; exact bucket dimension list per scenario profile.
