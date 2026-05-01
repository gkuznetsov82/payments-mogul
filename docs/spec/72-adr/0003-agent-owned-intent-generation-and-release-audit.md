# ADR 0003: Agent-Owned Transaction-Intent Generation and Release Audit Gate

- **Status:** Accepted
- **Date:** 2026-04-26
- **Supersedes (behavioral drift):** runtime pattern where pipeline derives new economic intent streams from source outcomes

## Context

Payments Mogul's simulation principles require that economic behavior is owned by agents, not by transport/execution infrastructure.

As Pop classes evolve into multiple segment types with distinct behavior models, intent generation (including purchase/refund mixes and future behavior-specific intent families) must remain encapsulated in Pop logic. Pipeline logic should remain deterministic infrastructure: validation, routing, postings, transfers, and settlement lifecycle execution.

Recent runtime behavior introduced source-derived intent synthesis in pipeline execution (for example refund stream derivation from purchase flow ratios). That pattern weakens agency boundaries and risks future hidden behavior drift outside agent contracts.

## Decision

The following rules are mandatory and release-blocking:

1. **Intent generation authority**
   - Only agent classes may generate root transaction intents and their economic payloads.
   - "Generate" includes deciding whether an intent exists and assigning its economic details (counts, amounts, directionality, and behavior-specific metadata).

2. **Pipeline responsibility boundary**
   - Pipeline must not invent or behaviorally derive new economic intents from other intents/outcomes.
   - Pipeline is limited to:
     - schema validation,
     - deterministic routing/handoff of already-generated intents,
     - fee/settlement/posting/value-transfer execution,
     - observability emission.

3. **Refund behavior ownership**
   - Refund generation policy is Pop-owned.
   - `refund_to_purchase_ratio` is a Pop behavior input and must be interpreted by Pop logic (or Pop subtype logic), not by pipeline intent materialization logic.

4. **Config authority split**
   - Pop behavior parameters belong in Pop config surfaces.
   - Pipeline intent sections define transport/routing contracts only and must not encode behavior-generation coefficients.

5. **No future exceptions without ADR**
   - Any attempt to move behavior-generation authority out of agents requires a new explicit ADR and must justify principle deviation.

## Consequences

- **Positive:** Preserves agency as a first-class architectural invariant.
- **Positive:** Enables richer Pop subtype behavior without pipeline coupling.
- **Positive:** Improves auditability: behavior origin is isolated to agent classes.
- **Tradeoff:** Requires migration of any existing pipeline-based intent derivation to Pop-owned logic.
- **Tradeoff:** Requires tighter release governance to prevent regression.

## Mandatory Release Audit (every release)

Every release must include an explicit "Agency Boundary Audit" entry in release notes/checklist. Release is blocked if any check fails.

Required checks:

1. **Static boundary check**
   - Confirm no pipeline module contains intent-generation behavior rules (ratios, synthetic intent creation, behavior branching).
2. **Contract check**
   - Confirm Pop contract/spec sections remain the sole authority for intent generation semantics.
3. **Config check**
   - Confirm behavior-generation knobs are under Pop config; pipeline config has no behavior-generation coefficients.
4. **Test check**
   - Confirm tests demonstrate Pop-originated intent generation and pipeline non-generation behavior.
5. **Regression check**
   - Confirm no newly introduced event stream implies pipeline-authored economic intent creation.

## Required follow-ups

1. Update `31-agents.md` to explicitly define Pop-owned intent generation, including refund policy ownership.
2. Update `33-transaction-pipeline.md` to explicitly prohibit pipeline-side economic intent synthesis.
3. Update `40-yaml-config.md` to place behavior-generation knobs (including `refund_to_purchase_ratio`) under Pop config and remove/forbid equivalent pipeline-side behavior knobs.
4. Update validation rules with stable error code(s) for prohibited pipeline-side behavior-generation fields.
5. Add/adjust tests to ensure behavior remains agent-owned and to fail fast on boundary violations.
