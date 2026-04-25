# World Builder / Config Designer

**Status:** Draft  
**Binding level:** `v0_viewer` runtime-binding for World Builder service/UI contracts; editing workflows are partial and phased.

## Purpose

Define the standalone **World Builder** product slice for near-term delivery:

- Produce and export YAML world configuration files.
- Validate and normalize configurations using authoritative server-side logic.
- Visualize world topology and pipeline connectivity so authored configs are inspectable.

This chapter is a product and contract spec for the builder tool, not the simulation runtime itself.

**Cross-references:** config schema **`40-yaml-config.md`**; validation policy/codes **`50-validation-rules.md`**; control/API contracts **`51-api-contract.md`**; UI screen patterns **`60-screen-specs.md`**; transaction pipeline model **`33-transaction-pipeline.md`**.

---

## Problem statement

YAML authoring complexity is increasing quickly (`world`, `product_links`, `pipeline`, money/calendar/region surfaces). Manual text editing is still acceptable for prototype work, but inspection and confidence degrade as file size and cross-references grow.

Immediate need:

- A visual way to inspect what has been authored.
- Deterministic validation and normalization so users can trust config outputs.
- A path that does not depend on direct server filesystem access.

---

## Product scope and non-goals

### In scope for `v0_viewer`

- Standalone World Builder app (separate process/app surface from simulation TUI).
- YAML import, validation, normalization, and export.
- Read-oriented visualization for world entities and their links.
- Structured diagnostics with stable error/warning codes.
- Local usage mode (file in/file out) without mandatory connection to the game server.

### Explicit non-goals for `v0_viewer`

- Full-featured form editor for all config fields.
- Multi-user collaboration or permissions.
- Runtime world mutation by directly writing into simulation server filesystem.
- Any replacement of simulation runtime validation semantics.

---

## Architecture decision for this chapter (Option A)

Use a **thin web UI + builder backend service** architecture:

- `world-builder-ui` (React) is responsible for authoring surface, visualization, and export UX.
- `world-builder-service` (FastAPI) is responsible for YAML parsing, validation, normalization, and resolver output.
- Validation/normalization is authoritative on the service side (not client-side).

Rationale:

- Prevents logic drift between UI and canonical config contracts.
- Reuses existing config models/validation code paths.
- Keeps migration path open for future upload APIs and server-integrated validation.

---

## Authoritative validation and normalization contract

### Validation ownership

- World Builder service must use the same schema and cross-entity rule logic as simulation startup validation.
- Validation results must preserve stable codes (`E_*`/`W_*`) expected by platform contracts.
- UI may perform syntax sanity checks for ergonomics, but must not be considered authoritative.

### Normalization ownership

- Normalization is performed server-side by World Builder service.
- Normalization must be deterministic: same input document -> same normalized output document.
- Normalized output must preserve semantic equivalence and remain accepted by runtime loader.

### Normalization behavior (minimum)

- Canonical ordering of top-level sections and key entity arrays by stable IDs.
- Explicit default insertion only when those defaults are contract-defined in config schema.
- Cross-reference representation consistency (no mixed alternate forms in output).
- Consistent numeric formatting aligned with configured schema expectations.

---

## Builder service API contract (`v0_viewer`)

The World Builder service provides at minimum:

- `POST /validate`
  - Input: YAML document payload.
  - Output: `valid`, `errors[]`, `warnings[]`, and optional resolved summary metadata.
- `POST /normalize`
  - Input: YAML document payload.
  - Output: normalized YAML (and optional normalized JSON object view).
- `POST /analyze` (or equivalent)
  - Input: YAML document payload.
  - Output: visualization graph model:
    - entities (`vendor`, `product`, `pop`, `region`, `calendar`, pipeline profile),
    - references/edges (`product_links`, profile bindings, role resolutions),
    - unresolved-reference annotations.

Implementation route naming may vary, but these capabilities are mandatory.

---

## Visualization contract (`v0_viewer`)

World Builder UI must provide at least the following visual views:

- **Config structure view**
  - Section navigator for major domains (`scenario`, `simulation`, `world`, `pipeline`, money/FX/calendar/region blocks).
- **World topology graph**
  - Populations, products, vendors, and product link relationships.
- **Pipeline connectivity graph**
  - Product -> pipeline profile binding, role references, and downstream stage references.
- **Diagnostics panel**
  - Error/warning list with stable code, human-readable message, and location reference.
  - Selecting a diagnostic highlights related node/field in view.
- **Output preview**
  - Normalized YAML preview prior to export.

For `v0_viewer`, these views are read-first; direct graph editing is not required.

---

## UX and workflow requirements

- User can load YAML from local disk.
- User can run validate and normalize without starting simulation runtime.
- User can inspect reference topology even when some diagnostics are present.
- User can export normalized YAML back to local disk.
- Diagnostic state is explicit: validation pass/fail is always visible.

Failure behavior:

- Invalid YAML syntax must return parse diagnostics without crashing service.
- Validation failures must still permit visualization of parseable partial structure when possible.
- Service-side errors must return structured failure envelope suitable for UI display.

---

## Phased delivery plan for World Builder

### `v0_viewer` (this chapter's mandatory scope)

- Load -> validate -> visualize -> normalize -> export flow is complete.
- Validation and normalization are server-authoritative.
- Topology and pipeline relationships are inspectable.

### `v0.5_editor` (next scope, non-binding here)

- Partial editing for high-impact sections (`world`, `product_links`, pipeline profile bindings).
- Round-trip safe save with deterministic normalization.

### `v1.0_integrated` (future target)

- Upload world configs to server via API instead of filesystem dependency.
- Server-authoritative compatibility checks before activation.
- Migration/upgrade guidance for schema-version changes.

---

## Compatibility and versioning

- Builder must declare supported config schema versions (initially aligned to active runtime schema gate).
- If input config declares unsupported schema version, validation response must be explicit and non-ambiguous.
- Builder UI should surface schema version status prominently.

---

## Acceptance criteria (`v0_viewer`)

- Any parseable YAML config can be submitted and receives deterministic validation output.
- Validation output uses stable code taxonomy already defined for runtime config checks.
- Normalized output round-trips through loader validation without semantic drift.
- Topology view shows all key entity classes and references from input.
- Unresolved references are visible in both diagnostics and graph context.
- Exported normalized YAML is suitable for runtime usage without manual cleanup.

---

## Deferred decisions / ADR triggers

Record an ADR before implementation if any of the following are required:

- Diverging validation logic between runtime loader and builder service.
- Introducing non-deterministic normalization behavior.
- Replacing service-authoritative validation with client-authoritative checks.
- Changing canonical config serialization semantics in a breaking way.
