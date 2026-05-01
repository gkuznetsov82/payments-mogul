# Transaction Pipeline

**Status:** Draft
**Binding level:** Mixed (`v1` runtime-binding baseline, `v2` spec-only contract surface, `v3` runtime-binding for promoted pipeline scope; prototype v4 semantics execute under `v3_runtime` until a separate schema gate is introduced by ADR)

## Purpose

How **aggregate transaction activity** within a simulated **day** (one **tick**) becomes **fees**, **fund transfers**, and **ledger postings**; what is **stored** in **normal** vs **debug** play; and how this ties to UI and reporting.

Prototype sequencing note: Money/Calendar/FX schema work in v2 is documented in **`40-yaml-config.md`** as a spec-only foundation; pipeline implementation expansion is deferred to v3.

**Cross-references:** tick = one day, pause, modes **`30-architecture.md`**; fee rules **`21-fee-economics.md`**; rails and settlement **`20-payment-rails.md`**; institutions and sinks **`01-principles.md`**, **`31-agents.md`**; realtime payloads **`52-realtime-ui-protocol.md`**; config caps **`40-yaml-config.md`**.

---

## Versioning and promotion policy

- `v1` (`prototype_vendor_pop_v1`) remains the authoritative runtime behavior until an explicit promotion decision is recorded.
- `v2` additions in this chapter are normative **schema/contract language** only and are **non-runtime-binding**.
- `v3` is the first target where promoted pipeline stages become runtime-mandatory.
- V3 final-touch scope includes observability and contract clarity updates only.
- Prototype `v4` semantic scope promotes routed completion semantics (sync/async fan-out), root-intent success-gating, and invoice/settlement lifecycle behavior under current `v3_runtime` gate.
- Promotion from `v2` to `v3` requires:
  - contract parity between this chapter and **`40-yaml-config.md`**,
  - deterministic stage-order statement in **`30-architecture.md`**,
  - explicit acceptance criteria in a handoff backlog for implementation.
- Promotion note: transaction pipeline runtime promotion is approved in **ADR-0002** for profiles/configs that declare `pipeline_schema_version: v3_runtime`.
- Agency boundary note: economic intent generation authority is locked by **ADR-0003**.

### Version gates

| Version | Binding | Scope |
|---|---|---|
| `v1` | Runtime-binding | Agent-owned onboarding/transact adjudication and minimal outputs |
| `v2_foundations` | Spec-only | Canonical pipeline objects, routing/posting/transfer/fee schema contracts |
| `v3_runtime` | Runtime-binding | Full transaction-intent -> fees -> postings -> asset transfers execution + invoice-triggered deferred fee collection |

---

## What gets simulated (all modes)

- **Within a tick**, Pop agents materialize **aggregate transaction intents** (e.g. pop slice × counterparty institutions × key dimensions—not individual cardholder-level rows unless a scenario explicitly requires that granularity). Pipeline then executes these intents deterministically. These intents drive:
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

### Transaction-intent log visibility contract (v3 final touch)

- For routed flows, logs/stream output must include both:
  - the original incoming transaction intent (pre-routing),
  - each routed outgoing derivative intent.
- Original and derivative records must be correlatable via a shared stable key (for example `root_intent_id`).
- This visibility requirement is observability-only for v3 and does not change execution semantics.

---

## Canonical pipeline artifacts (v2 contract, v3 runtime)

These artifacts formalize the unstructured transaction-pipeline notes and are not runtime-mandatory until promoted:

- `TransactionIntent`
  - aggregate instruction emitted from Pop-owned behavior execution.
  - may route to one or more destinations by `destination_role` (or `local` sink); routed derivatives are transport/handoff artifacts of an existing Pop-generated root intent.
  - supports deterministic value-date policy tokens (`same_day`, `next_day_plus_x`, `next_working_day_plus_x`, `next_month_day_plus_x`).
  - when a policy contains `plus_x`, an explicit integer offset parameter is required (`value_date_offset_days`).
- `FeeResult`
  - fee computed in configured sequence order.
  - may be triggered by transaction intents or prior fee results.
  - includes deterministic trigger filters and amount basis (`count_cost`, `amount_percentage`, or declared formula mode).
  - supports explicit settlement policy, including `next_month_day_plus_x` with required `value_date_offset_days`.
  - directionality is explicit and can flow either way between counterparties (`creditor`/`debtor` are runtime-resolved per rule outcome); example: interchange reimbursement can be payable to issuer or payable by issuer depending on net context.
- `SettlementDemandResult` (v4 runtime)
  - settlement claim accrual separate from fee economics.
  - may be triggered by configured settlement-demand rules and can reverse creditor/debtor direction based on net flow.
  - carries explicit creditor and debtor role resolution and amount basis.
  - feeds advisement/invoice envelope with category `settlement_demand`.
  - settlement policy/date primitives must use the same policy token family used elsewhere (`same_day`, `next_day_plus_x`, `next_working_day_plus_x`, `next_month_day_plus_x` with required offsets when `plus_x`).
  - opposing-direction accruals (for example purchase vs refund) net naturally by directional aggregation; special formula semantics are not required for this default path.
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

### Agency boundary: generation vs execution (v4 runtime, normative)

- Per **ADR-0003**, pipeline does not own economic behavior generation.
- Pipeline must not synthesize new behavior intents (for example refund streams) from prior outcomes using pipeline-authored behavior coefficients.
- Pipeline may only:
  - validate and route already-generated intents,
  - run downstream stages (fees, postings, transfers, settlement lifecycle),
  - emit observability artifacts.
- Distinct intent families (purchase, refund, and future behavior-specific types) must be generated by Pop classes before pipeline execution.

### Destination gate-honor contract (v3 runtime)

- Destination handoff must honor destination vendor/product transact gates before running downstream stages.
- If destination adjudication returns non-success (`VENDOR_NOT_OPERATIONAL`, `PRODUCT_NOT_FOUND`, `TRANSACT_CLOSED`, or equivalent failure), destination-side downstream stages for that routed intent must not run.
- In that failure path:
  - the routed intent remains visible in observability output,
  - routed intent status/reason must indicate failure,
  - destination fees/postings/transfers for that failed routed intent must not be emitted.
- This is a gate-honor correctness requirement for current runtime behavior, not a v4 redesign of multi-provider routing semantics.

### Fan-out completion semantics (v4 runtime)

- Every routed destination leg should explicitly declare `routing_completion_mode`; if omitted, default is `synchronous`:
  - `synchronous`
  - `asynchronous`
- `synchronous` leg semantics:
  - the source/root intent may succeed only if all required synchronous legs (and any fanning out synchronous legs that it may have in turn - recursively to the end of the graph) succeed within the same tick execution boundary,
  - if a synchronous leg is value-dated beyond current tick it will result in config validation error and such model will not be loaded.
- `asynchronous` leg semantics:
  - root intent resolution does not wait across ticks for that leg,
  - routed leg is emitted as pending at origin tick and resolved on/after its value date,
  - destination-side downstream stages (fees, postings, transfers) run only after resolved successful handoff.
- Root intent success-gating:
  - evaluate only synchronous required legs for blocking success,
  - asynchronous leg outcomes do not retroactively flip already-resolved root outcome.
- Correlation requirements:
  - root and all routed derivatives keep a shared `root_intent_id`,
  - async resolution events for routed legs must preserve the same `root_intent_id` + `intent_id`.

### Invoice-triggered fee settlement (v2 contract, v3 runtime)

- For fee contracts that settle on `next_month_day_plus_x`, beneficiary side emits an `InvoiceTransactionEvent` on the due date.
- The invoice event triggers payer-side settlement handling in one of two modes:
  - pay invoice directly.
- Fee accrual and fee collection are separate lifecycle steps:
  - accrual occurs when fee is computed,
  - collection occurs when invoice event is generated/reconciled at due date.

### Invoice and settlement lifecycle (v4 runtime)

- Minimum lifecycle states:
  - fee: `accrued`
  - settlement demand: `accrued`
  - invoice: `invoiced`
  - settlement resolution: `paid` or `failed` (with residual when non-zero)
- Lifecycle date fields are explicit and non-interchangeable:
  - `accrual_date`: when fee or settlement-demand economics are recognized,
  - `invoice_issue_date`: when advisement/invoice is emitted,
  - `payment_due_date`: when payment is contractually due.
- Fee contracts and settlement-demand contracts both must define explicit issue-date and due-date policy behavior.
- Lifecycle ordering:
  1. fee/settlement-demand accrual at pipeline stages,
  2. invoice/advisement emission at `invoice_issue_date` (aggregating by category, recipient, and issue date),
  3. payment attempts up to/after `payment_due_date`,
  4. settlement resolution emitted after payment handling.
- Transfer-backed settlement rule:
  - `settlement_resolution_event.final_status = paid` is valid only if corresponding value transfer execution succeeds for settled amount.
  - If transfer fails or is partial, resolution must be non-paid with non-zero residual.
- Cardholder fee statement rule:
  - cardholder-facing fee disclosure should use the invoice/advisement envelope with `invoice_category=fee`, but may be marked non-payable when issuer self-serves from customer funds.
  - non-payable cardholder statements are informational (for cost visibility) and must not require payer-side payment action.
  - recommended status semantics: `payable=false` and settlement status `netted`/`netted_internal`.
- Settlement-demand issuer/obligor rule:
  - settlement demand is initiated by the issuing vendor/product, but creditor/debtor direction is determined by resolved roles.
  - when issuer is debtor (owes funds), recipient records receivable expectation and payment execution remains the issuer/debtor responsibility.
- Container-balance execution rule:
  - payment and transfer execution is balance-aware against payer-side source container balances.
  - transfer application to balances occurs on resolved value date (not on accrual date).
  - container balances are hard non-negative for non-sink agents; sink-agent negative balances remain scenario-governed.
- Insufficient-funds rule:
  - transfer execution is all-or-nothing in this phase (no partial transfer execution), including settlement-payment and pipeline asset-transfer paths,
  - insufficient funds results in failed payment attempt and unchanged source/destination balances,
  - residual remains full unsettled amount for the affected invoice/demand item.
- Transfer observability rule:
  - transfer events must expose both source and destination ownership context so Accounts view can attribute movements to actual owner products/agents.
  - failed transfer attempts must emit explicit failed transfer event payloads with reason code.
- Auto-pay deterministic ordering rule:
  - when multiple payable items compete for the same source container on the same processing date, apply in deterministic order:
    1. earliest `payment_due_date`,
    2. earliest `invoice_issue_date`,
    3. lexical entity ID (`invoice_id` / `settlement_demand_id`).
- Operator action binding:
  - operator commands (`pay_now`, `hold`, `release_hold`) target underlying `invoice_id` or `settlement_demand_id`,
  - message records are informational and do not own action execution state.
- For prototype v4 scope, direct-payment settlement remains allowed as the default path; settlement netting remains optional/deferred unless explicitly enabled by a later spec update.

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
- Rail-level settlement-netting and dispute workflows beyond direct-payment settlement path.

---

## Contents still to detail (later)

- Named stages (authorization, clearing, settlement) as implemented in v1; decline reasons and propagation; failure modes vs P&L; exact bucket dimension list per scenario profile.
