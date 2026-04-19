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
| Versioning and promotion decisions (`v1`/`v2_foundations`/`v3_runtime`) | **A/R** | C |
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

---

## Prioritized Claude backlog

### P0 - Conformance baseline (must pass first)

1. Validate all current `v1` runtime behavior still conforms to updated specs in `30`, `33`, and `40`.
2. Report any ambiguities where implementation cannot proceed without a spec clarification.

**Acceptance criteria**
- No unapproved behavior drift from `v1` contracts.
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

---

## Escalation loop

If Claude encounters conflicts, missing semantics, or implementation-impacting ambiguity:

1. Stop scope expansion.
2. Return a focused clarification request that references chapter + section.
3. Resume only after updated spec text is approved.
