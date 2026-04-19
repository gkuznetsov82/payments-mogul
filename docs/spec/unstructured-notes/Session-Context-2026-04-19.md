# Session Context — 2026-04-19

This note captures the current architecture/spec context so work can resume quickly.

## Scope covered this session

- Transaction pipeline spec matured from unstructured notes into versioned contracts.
- Runtime promotion decision finalized: pipeline promoted to `v3_runtime` (ADR-0002).
- TUI observability requirements added (World/Pipeline/Ledger + run controls and logs separation).
- Initial implementation was reviewed for risks/regressions.

## Key decisions locked

1. **Role boundaries**
   - Codex: system architect / business analyst / specs only.
   - Claude: code/config/tests/runtime implementation.
   - Persisted in `CLAUDE.md`.

2. **Versioning**
   - `v2_foundations` remains spec-only.
   - `v3_runtime` is runtime-binding for promoted pipeline scope.
   - Promotion recorded in `docs/spec/72-adr/0002-promote-transaction-pipeline-to-v3-runtime.md`.

3. **Pipeline ownership model**
   - Pipelines are attached per product (`pipeline_profile_id`), profile definitions reusable.
   - Role-based references resolve at product instance (`pipeline_role_bindings`).

4. **Inter-product handoff**
   - Destination product receives `Transact()` with upstream identity in `client_id` and routed transaction details in remaining params.

5. **Deferred fee settlement**
   - `next_month_day_plus_x` uses explicit offset.
   - Settlement trigger uses `invoice_transaction_event`.
   - Netting removed for now; direct payment path only.

6. **TUI direction**
   - Timing controls always visible.
   - World/Pipeline/Ledger as primary views.
   - Logs on separate section/tab (not always visible).

7. **Debug observability storage**
   - Queryable store required (SQLite or equivalent embedded relational store).

## Primary files updated (spec/governance)

- `docs/spec/30-architecture.md`
- `docs/spec/31-agents.md`
- `docs/spec/33-transaction-pipeline.md`
- `docs/spec/40-yaml-config.md`
- `docs/spec/52-realtime-ui-protocol.md`
- `docs/spec/60-screen-specs.md`
- `docs/spec/12-ui-ux-spec.md`
- `docs/spec/73-transaction-pipeline-handoff.md`
- `docs/spec/72-adr/0002-promote-transaction-pipeline-to-v3-runtime.md`
- `configs/prototype_v2_foundations_example.yaml`

## Code review status

- Review completed on current implementation.
- Findings saved in:
  - `docs/spec/unstructured-notes/Code-Review-Findings-2026-04-19.md`

Top findings to address next session:

- Handoff `client_id` source reconstruction risk when `product_id` is non-unique across vendors.
- Missing payer context propagation in fee/invoice settlement records.
- Potential overwrites in SQLite observability tables due to coarse keys + `INSERT OR REPLACE`.
- Destination profile processing may skip intent-routing stage for multi-hop flows.
- Pipeline store currently in-memory by default (durability/configuration gap).

## Environment note

- Local test execution in this environment was blocked by missing `pytest` module.
- Review relied on static inspection + spec conformance checks.

## Next-session start checklist

1. Re-open review findings note and prioritize high-severity items first.
2. Decide which findings require spec clarifications vs pure implementation fixes.
3. Prepare a focused Claude patch prompt for the top 2-3 issues.
4. After fixes, run full tests in an environment with pytest available.

## Shutdown-ready checkpoint

- Session context saved.
- Findings saved.
- No pending unsaved architecture decisions in this chat.
