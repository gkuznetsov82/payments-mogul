# ADR 0002: Promote Transaction Pipeline to v3 Runtime

- **Status:** Accepted
- **Date:** 2026-04-19

## Context

Pipeline contracts were introduced under `v2_foundations` as spec-only. The project now needs runtime implementation for:

- per-product pipeline profile execution,
- role-based inter-product handoff,
- fee accrual and deferred invoice settlement,
- postings/value transfers/reconciliation observability,
- TUI operator visibility for world/pipeline/ledger workflows.

## Decision

Promote the transaction pipeline contract to runtime-binding when config declares:

- `pipeline.pipeline_schema_version: v3_runtime`

Promotion scope includes:

1. Product-owned pipeline profiles (`pipeline_profiles[]`) attached via `pipeline_profile_id`.
2. Inter-product handoff contract where destination product receives `Transact()` with:
   - `client_id` set to originating upstream `vendor_id`,
   - routed transaction details in remaining parameters.
3. Deterministic stage execution after v1 adjudication flow:
   - intents -> fees -> postings -> asset transfers -> retention/invoice lifecycle.
4. Deferred fee settlement via `invoice_transaction_event` for `next_month_day_plus_x`.
5. Queryable debug observability store (SQLite or equivalent embedded relational store).

For this phase, settlement netting is explicitly out of scope; invoice collection resolves via direct payment path.

## Consequences

- **Positive:** Unblocks Claude to implement promoted runtime behavior without violating binding-level rules.
- **Positive:** Keeps backwards compatibility by retaining `v2_foundations` as non-runtime-binding.
- **Positive:** Clarifies gating logic: runtime expansion is schema-version-driven.
- **Tradeoff:** Requires additional validation and tests for mixed-mode configs (`v2_foundations` vs `v3_runtime`).

## Required follow-ups

1. Update examples and implementation handoff docs to reflect `v3_runtime` gating.
2. Add/extend agent contract for sink-style products (`SinkProduct`) and inter-product `Transact()` handoff.
3. Align TUI and realtime event contracts with promoted pipeline observability scope.
