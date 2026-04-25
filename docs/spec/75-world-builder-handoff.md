# World Builder Handoff

**Status:** Draft  
**Binding level:** Process-binding for delivery governance; runtime behavior remains governed by chapters `40`, `50`, `51`, and `74`.

## Purpose

Define architecture-to-implementation handoff contract for World Builder:

- Ownership boundaries between spec authority and implementation.
- Prioritized backlog for delivery in small verifiable slices.
- Acceptance criteria at each phase gate.

---

## Role boundaries (RACI-style)

- Requirements and scope boundaries
  - Codex (System Architect / Business Analyst): **A/R**
  - Claude: C
- Spec authoring and refinement (`74`, related updates in `00`, `40`, `50`, `51`, `60`)
  - Codex: **A/R**
  - Claude: C
- Runtime code/config/test changes
  - Codex: C
  - Claude: **A/R**
- Conformance verification against approved specs
  - Codex: A
  - Claude: **R**
- Requirement change requests discovered during coding
  - Codex: **A/R**
  - Claude: C

Legend: `A` = Accountable, `R` = Responsible, `C` = Consulted.

---

## Version gates for implementation

- `v0_viewer`
  - Mandatory first release.
  - Read-first builder: validate, normalize, visualize, export.
- `v0.5_editor`
  - Partial edit capabilities for selected sections.
  - Still anchored to server-authoritative validation/normalization.
- `v1.0_integrated`
  - API-based upload/activation flow to simulation server.
  - Filesystem coupling is no longer required for normal operation.

Promotion between gates requires passing prior acceptance criteria and explicit spec confirmation.

---

## Prioritized Claude backlog

### P0 - Contract alignment and skeleton

1. Create World Builder service shell and UI shell with clean module boundaries.
2. Wire service to existing config load/validation contracts (no duplicate validators).
3. Define response envelopes for validate/normalize/analyze endpoints.

**Acceptance criteria**

- Service starts and responds on all required endpoints.
- Validation responses include stable code and structured location metadata.
- No parallel independent validator implementation exists in UI.

### P1 - Validation + normalization path

1. Implement authoritative `POST /validate`.
2. Implement deterministic `POST /normalize`.
3. Ensure normalized output preserves loader acceptance and semantic equivalence.

**Acceptance criteria**

- Known valid fixtures pass through validate and normalize.
- Known invalid fixtures produce deterministic `E_*` diagnostics.
- Same input produces byte-stable or rule-stable normalized output.

### P2 - Visualization path

1. Implement analysis model generation for world/pipeline relationships.
2. Build graph views and diagnostics-to-node linking in UI.
3. Support degraded visualization for partially valid documents when parseable.

**Acceptance criteria**

- User can inspect topology for representative complex config fixtures.
- Unresolved references are highlighted in graph and diagnostics panel.
- Visualization remains usable without requiring full edit mode.

### P3 - Export and operability

1. Add normalized YAML export workflow.
2. Add regression tests for validate/normalize/analyze envelopes.
3. Add docs for local run and expected user workflow.

**Acceptance criteria**

- Exported normalized YAML is runtime-usable without manual restructuring.
- Integration tests cover successful and failing flows.
- Local workflow is reproducible by fresh contributor setup.

### P4 - Future-facing integration prep (non-blocking for `v0_viewer`)

1. Reserve adapter boundaries for future server upload APIs.
2. Keep schema-version support surfaced in UI and service responses.
3. Define migration placeholder hooks for schema evolution.

**Acceptance criteria**

- No architectural blocker to switching from local-only flow to API upload flow.
- Schema support status is visible and test-covered.

---

## Escalation loop

If implementation encounters ambiguity or conflict:

1. Stop scope expansion in affected area.
2. Return focused clarification request with chapter/section reference.
3. Resume only after updated spec language is approved.
