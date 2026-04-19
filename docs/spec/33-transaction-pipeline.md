# Transaction Pipeline

**Status:** Draft
**Binding level:** Mixed (`v1` runtime-binding baseline, `v2` spec-only contract surface, `v3` runtime-binding for promoted pipeline scope)

## Purpose

How **aggregate transaction activity** within a simulated **day** (one **tick**) becomes **fees**, **fund transfers**, and **ledger postings**; what is **stored** in **normal** vs **debug** play; and how this ties to UI and reporting.

Prototype sequencing note: Money/Calendar/FX schema work in v2 is documented in **`40-yaml-config.md`** as a spec-only foundation; pipeline implementation expansion is deferred to v3.

**Cross-references:** tick = one day, pause, modes **`30-architecture.md`**; fee rules **`21-fee-economics.md`**; rails and settlement **`20-payment-rails.md`**; institutions and sinks **`01-principles.md`**, **`31-agents.md`**; realtime payloads **`52-realtime-ui-protocol.md`**; config caps **`40-yaml-config.md`**.

---

## Versioning and promotion policy

- `v1` (`prototype_vendor_pop_v1`) remains the authoritative runtime behavior until an explicit promotion decision is recorded.
- `v2` additions in this chapter are normative **schema/contract language** only and are **non-runtime-binding**.
- `v3` is the first target where promoted pipeline stages become runtime-mandatory.
- Promotion from `v2` to `v3` requires:
  - contract parity between this chapter and **`40-yaml-config.md`**,
  - deterministic stage-order statement in **`30-architecture.md`**,
  - explicit acceptance criteria in a handoff backlog for implementation.
- Promotion note: transaction pipeline runtime promotion is approved in **ADR-0002** for profiles/configs that declare `pipeline_schema_version: v3_runtime`.

### Version gates

| Version | Binding | Scope |
|---|---|---|
| `v1` | Runtime-binding | Agent-owned onboarding/transact adjudication and minimal outputs |
| `v2_foundations` | Spec-only | Canonical pipeline objects, routing/posting/transfer/fee schema contracts |
| `v3_runtime` | Runtime-binding | Full transaction-intent -> fees -> postings -> asset transfers execution + invoice-triggered deferred fee collection |

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

## Canonical pipeline artifacts (v2 contract, v3 runtime)

These artifacts formalize the unstructured transaction-pipeline notes and are not runtime-mandatory until promoted:

- `TransactionIntent`
  - aggregate instruction emitted by onboarding/transact adjudication.
  - may route to one or more destinations by `destination_role` (or `local` sink), once routed to external destination will generate another `TransactionIntent` by making respective Transact() call to resolved destination agent
  - supports deterministic value-date policy tokens (`same_day`, `next_day_plus_x`, `next_working_day_plus_x`, `next_month_day_plus_x`).
  - when a policy contains `plus_x`, an explicit integer offset parameter is required (`value_date_offset_days`).
- `FeeResult`
  - fee computed in configured sequence order.
  - may be triggered by transaction intents or prior fee results.
  - includes deterministic trigger filters and amount basis (`count_cost`, `amount_percentage`, or declared formula mode).
  - supports explicit settlement policy, including `next_month_day_plus_x` with required `value_date_offset_days`.
- `PostingEntry`
  - dual-entry accounting record with required `source` and `destination`.
  - source and destination must be role-resolved ledger references, not hardcoded product IDs or agent IDs.
  - amount must resolve to a single currency before posting.
  - value-date policy follows the same deterministic token set.
- `AssetTransfer`
  - movement between concrete value containers (not ledger accounts).
  - source and destination must be role-resolved container references, not hardcoded product IDs or agent IDs.
  - supports source/destination container refs, amount basis, and deterministic value-date policy.
- `ValueContainerMap`
  - reconciliation map linking ledger nodes to value containers.
  - supports aggregate mappings (for example, settlement-funds ledgers mapping to per-agent settlement containers).

### Role-based reference resolution (v2 contract, v3 runtime)

- Pipeline configuration must be reusable across product instances; therefore pipeline rules must reference roles rather than concrete `agent_id` or `product_id`.
- Resolution of roles to concrete IDs is owned by product-instance config in **`40-yaml-config.md`**.
- Role resolution must occur before generating `PostingEntry` and `AssetTransfer` artifacts for a tick.
- Ledger path construction for posting is defined by config-level ledger construction contracts in **`40-yaml-config.md`** (not only by ledger-to-container mapping).

### Product-owned pipelines and inter-product handoff (v2 contract, v3 runtime)

- Pipeline execution is attached **per product instance**. Each product owns one pipeline profile.
- A pipeline profile can be reused by multiple products, but execution context is always the owning product.
- When Product A emits outgoing `TransactionIntent` to Product B (via resolved destination role), Product B's attached pipeline becomes responsible for downstream fee and settlement logic for that intent.
- This preserves the agent-owned principle: each agent/product computes and executes its own obligations.
- Destination-product handoff contract:
  - destination product receives `Transact()` call with originating `vendor_id` in `client_id`,
  - remaining parameters carry the routed transaction-intent details (intent id, amounts, currency, value-date policy/offset, and other required metadata),
  - destination product pipeline executes from that received context.

### Invoice-triggered fee settlement (v2 contract, v3 runtime)

- For fee contracts that settle on `next_month_day_plus_x`, beneficiary side emits an `InvoiceTransactionEvent` on the due date.
- The invoice event triggers payer-side settlement handling in one of two modes:
  - pay invoice directly.
- Fee accrual and fee collection are separate lifecycle steps:
  - accrual occurs when fee is computed,
  - collection occurs when invoice event is generated/reconciled at due date.

### Iteration fee sinks profile (v2 spec-only)

- Introduce two sink-type vendor roles in pipeline contracts:
  - `payment_scheme` (with `scheme_access_product`)
  - `payment_processor` (with `processor_services_product`)
- Fee contracts for this iteration:
  - `processor_services`: fixed fee per transaction (`count_cost`)
  - `scheme_access`: fixed fee per transaction (`count_cost`) plus percent of transaction amount (`amount_percentage`)
- Settlement requirement for both fee contracts:
  - `settlement_value_date_policy = next_month_day_plus_x`
  - `settlement_value_date_offset_days = 5`

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
- Multi-destination transaction-intent routing and aggregation rules from `v2_foundations`.
- Full posting and asset-transfer contracts from `v2_foundations`.

---

## Contents still to detail (later)

- Named stages (authorization, clearing, settlement) as implemented in v1; decline reasons and propagation; failure modes vs P&L; exact bucket dimension list per scenario profile.
