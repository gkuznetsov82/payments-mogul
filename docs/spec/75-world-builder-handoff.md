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
4. Build UI shell on React stack (no long-term vanilla-static substitute for `v0_viewer`).

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
2. Build interactive graph views and diagnostics-to-node linking in UI.
3. Support degraded visualization for partially valid documents when parseable.
4. Provide node/edge detail panel and config section navigation/filtering.
5. Ensure graph readability at moderate graph size with deterministic layout strategy.
6. Add user-controlled node rearrangement with reset-to-auto-layout behavior.
7. Add dedicated pipeline drill-down view (per profile) with stage/interconnection visibility.
8. Extend diagnostic graph-target hints for robust focus routing (node + optional edge + view hint).
9. Add explicit pipeline scope UX: default `All profiles (aggregate)` plus per-profile selection.
10. Implement cross-pipeline connectivity edges and click-through navigation between pipeline contexts.
11. Ensure posting/transfer trigger lineage is fully visible (trigger -> rule -> source/destination refs).
12. Upgrade default layout strategy to hierarchical crossing-minimized auto-layout (ELK layered or equivalent), with deterministic fallback.
13. Add readability controls for dense graphs: collapsed aggregate view, expand-on-demand internals, edge-class visibility filters, and k-hop focus mode.
14. Preserve mental map across scope/filter/expand interactions for unchanged subgraphs.
15. Add hybrid focus layout option (mindmap/radial local context around selected node) while retaining deterministic global layout baseline.
16. Ensure minimap and graph controls are themed for dark UI and remain legible (no bright white default artifacts).

**Acceptance criteria**

- User can inspect topology for representative complex config fixtures.
- Unresolved references are highlighted in graph and diagnostics panel.
- Visualization remains usable without requiring full edit mode.
- Graph is an interactive canvas (pan/zoom/select) rather than textual rows.
- Selecting a node/edge shows structured details (`id`, `kind`, `label`, `attrs`).
- Selecting a diagnostic focuses/highlights related graph elements when resolvable.
- For `tests/fixtures/v3_pipeline_full.yaml`, user can follow at least one visual chain:
  `pop -> product_link -> product -> pipeline_profile`.
- For medium-size graphs (>=100 nodes), navigation remains practical (zoom + search/filter + fit-to-view).
- Users can drag/rearrange nodes and reset to deterministic auto-layout without losing graph integrity.
- Pipeline drill-down view exists and supports profile selection with stage/interconnection inspection.
- Diagnostic focus routing can target node and, when available, specific edge/view context.
- Pipeline aggregate scope is the default entry and clearly indicated in UI.
- Aggregate scope shows union of fees/postings/transfers/demands across all profiles in fixture config.
- Cross-pipeline route/payment/trigger links are rendered and clickable.
- Clicking a cross-pipeline link switches to correct target context/profile and focuses target node/details.
- For configured posting/transfer rules, users can trace full lineage:
  trigger source -> posting/transfer rule -> ledger/container endpoints.
- Default aggregate pipeline view for `configs/prototype_v3_runtime_example.yaml` is readable without manual drag cleanup.
- Users can isolate a local subgraph (k-hop and/or edge-class filter) within <= 3 interactions from selected node.
- Layout continuity is preserved: unchanged subgraphs keep stable relative positioning across scope/filter toggles.
- Focus-mode local layout (mindmap/radial) is available and produces visibly clearer selected-node context than full-graph baseline.
- Minimap and control widgets are dark-theme compliant and visually integrated with the canvas.

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
