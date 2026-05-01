# Transaction Pipeline Handoff

**Status:** Draft
**Binding level:** Process-binding for delivery governance; runtime behavior remains governed by chapters `30`, `33`, and `40`.

## Purpose

Define the architecture-to-implementation handoff contract for transaction pipeline work:

- Who owns specification decisions vs implementation changes.
- What backlog Claude should execute, in what order.
- Which acceptance criteria must be satisfied at each version gate.

---

## Role boundaries (RACI-style)

| Workstream | System Architect / Business Analyst (Codex) | Claude |
|---|---|---|
| Requirements and scope boundaries | **A/R** | C |
| Spec authoring (`30`, `33`, `40`) | **A/R** | C |
| Versioning and promotion decisions (`v1`/`v2_foundations`/`v3_runtime` + v4 semantic scope) | **A/R** | C |
| Runtime code/config/test changes | C | **A/R** |
| Determinism and conformance verification against approved specs | A | **R** |
| Requirement change requests discovered during coding | **A/R** | C |

Legend: `A` = Accountable, `R` = Responsible, `C` = Consulted.

---

## Version gates for implementation

- `v1`
  - Current runtime baseline.
  - No behavior expansion without explicit promotion note.
- `v2_foundations`
  - Spec-only contract expansion.
  - Claude may prepare implementation plans, but must not treat v2 features as runtime-mandatory until promoted.
- `v3_runtime`
  - Runtime-binding profile for full pipeline expansion.
  - Execution order must be deterministic and aligned to chapter `33`.
  - Promotion is approved by ADR-0002 for configs that declare `pipeline_schema_version: v3_runtime`.
- Agency boundary (ADR-0003)
  - Intent generation authority is Pop-owned.
  - Pipeline is restricted to validation/routing/downstream execution and must not synthesize economic behavior intents.
- `v4` semantic scope (prototype)
  - Routing completion semantics (`synchronous`/`asynchronous`) and root success-gating are runtime-mandatory.
  - Invoice/settlement lifecycle events are runtime-mandatory.
  - For current prototype stage, these semantics run under `v3_runtime` config gate unless superseded by ADR.

---

## Prioritized Claude backlog

### P0 - Conformance baseline (must pass first)

1. Validate all current `v1` runtime behavior still conforms to updated specs in `30`, `33`, and `40`.
2. Remove any pipeline-side behavior-intent synthesis and re-home that logic to Pop classes.
3. Report any ambiguities where implementation cannot proceed without a spec clarification.

**Acceptance criteria**
- No unapproved behavior drift from `v1` contracts.
- No pipeline module generates economic intent families from prior outcomes.
- Pop behavior knobs (including `refund_to_purchase_ratio`) are the sole source of refund-intent generation.
- Written ambiguity list returned to spec owner with proposed default interpretations.

### P1 - Pipeline contract implementation (`v3_runtime` promotion scope)

1. Implement transaction-intent routing from role-based pipeline config contracts (`destination_role` resolved at product level).
2. Implement ordered fee sequencing with trigger chains.
3. Implement posting and asset-transfer materialization with role-resolved ledger/container references and ledger construction contracts.
4. Enforce debug-window detailed retention boundaries and EOD aggregate retention separation.

**Acceptance criteria**
- Deterministic outputs under identical seed/config/command stream.
- Stage order observed as intents -> fees -> postings -> asset transfers -> retention.
- Configuration errors are surfaced when referenced IDs/paths are invalid.

### P2 - Operability and evidence

1. Add conformance tests mapped to each acceptance criterion.
2. Provide fixtures covering at least one multi-destination intent and one fee-triggered downstream posting/transfer.
3. Provide evidence pack (test outputs + conformance checklist).

**Acceptance criteria**
- Test suite demonstrates positive and negative cases for new contracts.
- Evidence pack traceably maps implementation behavior back to spec sections.

### P3 - V4 routing + settlement lifecycle semantics

1. Implement `routing_completion_mode` per destination leg with deterministic behavior:
   - synchronous legs are root-blocking within current tick boundary,
   - asynchronous legs resolve in later ticks (or same tick) without blocking root outcome.
2. Implement root-intent success-gating from synchronous legs only.
3. Implement invoice/settlement lifecycle transitions and stream events (`invoice_transaction_event`, `settlement_resolution_event`) with correlation continuity and transfer-backed paid resolution.
4. Add tests/fixtures for:
   - synchronous same-day success,
   - synchronous deferred-leg failure on config loading,
   - asynchronous pending then resolved behavior across ticks.
5. Implement and test settlement-demand accrual/advisement path as distinct from fees, including creditor/debtor direction reversals.
6. Implement message + operator UX contract:
   - messages are informational (severity + correlation),
   - operator actions target entity IDs (`invoice_id` / `settlement_demand_id`), not message IDs,
   - agent-scoped creditor/debtor + issued/received obligations views are supported,
   - dedicated Messages section supports filtering and entity drill-through to Obligations.
7. Fix transfer/balance correctness and ownership observability:
   - enforce balance checks on all transfer execution paths (not only settlement autopay),
   - emit failed transfer events with explicit failure reason for rejected transfer attempts,
   - include source and destination ownership context in transfer events for correct Accounts attribution.
8. Upgrade logs/interaction ergonomics for debugging scale:
   - Pipeline/Books/Accounts rows stay compact and selectable,
   - dedicated detail panel renders full selected-event payload,
   - Obligations list is scrollable and visually consistent with other event/movement views,
   - Messages controls are message-selection-scoped and disabled when correlation target is absent.
9. Upgrade baseline example configs/fixtures to demonstrate the new contracts:
   - `configs/prototype_v3_runtime_example.yaml`
   - `tests/fixtures/v3_pipeline_full.yaml`
   - include (a) Vendor Alpha -> Scheme settlement-demand payable flow with demand issuance in Scheme Access pipeline, and (b) Vendor Alpha 2% cardholder fee flow funding the same payment source container.
   - cardholder fee statement should be modeled as non-payable/netted advisement (no cardholder payment action).
   - demonstrate distinct `invoice_issue_date` and `payment_due_date` behavior for fee statements.
   - ensure refund generation is Pop-owned via `world.pops[].refund_to_purchase_ratio`, not pipeline-derived.

**Acceptance criteria**
- Root intent outcome follows declared routing completion modes deterministically.
- Async routed intents never block root transaction completion across ticks, or within the same tick.
- Invoice and settlement lifecycle events are emitted with stable correlation keys and correct state progression.
- `final_status=paid` must correlate to successful transfer execution for settled amount.
- Invoice/advisement date semantics are explicit and consistent (`accrual_date`, `invoice_issue_date`, `payment_due_date`).
- Settlement-demand behavior is test-covered for direction flips and aggregation semantics.
- Fee behavior is test-covered for bidirectional creditor/debtor directionality.
- Settlement-demand date policies use the same policy/offset primitives as the rest of pipeline contracts.
- Opposing purchase/refund settlement-demand flows are test-covered for natural directional netting without requiring formula-specific behavior.
- Refund intent generation coverage proves Pop-origin generation and pipeline non-generation.
- UI/action contract is test-covered for entity-bound actions and agent-perspective obligations views.
- Non-payable advisement path is test-covered (`payable=false` -> no payment action exposure, informational only).
- Balance handling is test-covered:
  - opening container balances,
  - value-date-applied balance updates,
  - insufficient-funds all-or-nothing failure semantics,
  - deterministic autopay ordering under shared-container contention.
- Messages view is test-covered for informational rendering, filters, and entity drill-through without direct action execution.
- Transfer observability is test-covered:
  - failed transfer emits `value_transfer_event` with explicit failure reason,
  - transfer payload includes both source and destination ownership fields,
  - Accounts attribution matches destination ownership rather than payer-only ownership.
- TUI operability is test-covered:
  - Obligations list scrollability + selection styling,
  - Obligations horizontal overflow handling for long IDs/details,
  - Accounts renders authoritative `current_balance` separately from movement-derived net,
  - message control disable/enable behavior by selected-message correlation,
  - log-row selection plus detail-pane rendering for Pipeline/Books/Accounts.
- Release evidence includes an "Agency Boundary Audit" checklist entry (per ADR-0003).

---

## Escalation loop

If Claude encounters conflicts, missing semantics, or implementation-impacting ambiguity:

1. Stop scope expansion.
2. Return a focused clarification request that references chapter + section.
3. Resume only after updated spec text is approved.
