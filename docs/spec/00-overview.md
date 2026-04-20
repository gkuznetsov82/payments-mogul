# Overview

**Status:** Draft

## Purpose

Payments Mogul is a simulation platform for payments industry. Vision is for it to become a tool that professionals (and wannabes) can use to experiment by building virtual products in the retail payments space, and see how they would perform in a given simulation scenario. This spec sets out descriptions and instructions for agentic AI to implement the actual code, and for any human contributors to understand what was done, and hopefully why.

**Spec root:** `docs/spec/` (flat numbered files plus `72-adr/`).

---

## Elevator pitch & player fantasy

Payments Mogul strives to become the Dwarf Fortress of payments simulation, in a gaming shape. Its ultimate goal is to create simulation environment, combined with procedural generation capability to fill in the world, where users can explore cause and effect loops of the various events and decisions. Backbone of Payments Mogul is the accounting snapshot of the player and other modeled entities recorded every tick. It records the financial status of the world, and can be used to create reports, charts, and analyze behavior. It can be used for educational purposes, financial modeling, and complex what-if analysis. 

## Non-goals

Payments Mogul is the means to an end tool in the shape of the game. It does not strive to simulate the whole world with its infinite complexity. It will prioritize the simulation of relevant behavior in the computationally responsible way. 

## Glossary

_To complete._ (e.g. MDR, interchange, acquirer, issuer, scheme, etc.)

---

## Document map

### Root & framing

- **`00-overview.md`** — This file: pitch, fantasy, non-goals, glossary, doc map, conflict rules.
- **`01-principles.md`** — Sterman-style rules: feedback-first, “just enough” scope, agentic emergence, what is *not* simulated; success metrics (“planning tool” vs “game”).

### Product & game design

- **`10-player-journey.md`** — Session loop: start scenario → decisions → ticks → reports → win/lose or score; save/load; difficulty knobs.
- **`11-scenarios.md`** — Scenario catalog: starting market, competitors, regs, seed data; selection and parameterization (YAML entry points).
- **`12-ui-ux-spec.md`** — Information architecture, screens, density, keyboard paths; industrial/command-center aesthetic (palette, type, no plastic); map vs ledger vs “Victoria 3” industrial vibe.
- **`13-content-style.md`** — Voice for copy, labels, tooltips, error tone; number formatting (currency, basis points).

### Domain model (payments “physics”)

- **`20-payment-rails.md`** — Four-party model and extensions: who pays whom, settlement timing, chargebacks (in/out of scope).
- **`21-fee-economics.md`** — Fee types, caps, pass-through vs markup; constraints (**interchange vs MDR**, etc.); formulas in words + variables.
- **`22-regulatory-pressure.md`** — What regulation *does* in the sim (caps, routing, liability shifts); triggers and delayed effects (feedback loops).
- **`23-metrics-kpis.md`** — P&L lines, network stats, churn definitions; scoreboard vs drill-down.

### Simulation engine (Mesa + dynamics)

- **`30-architecture.md`** — Tick model, random seeds, determinism policy, performance targets, threading/async boundaries.
- **`31-agents.md`** — Agent types: state, behaviors per tick, observations, decisions (rules + tunables); interaction matrix.
- **`32-variables-stocks-flows.md`** — System dynamics: stocks, flows, delays, feedback loops; what is ABM vs aggregate.
- **`33-transaction-pipeline.md`** — Intent → auth → capture → settlement (as simplified as needed); failure modes vs P&L.
- **`34-events-scheduler.md`** — Shocks, calendars, scenario hooks.

### Configuration & data

- **`40-yaml-config.md`** — File layout, anchors/aliases, inheritance, validation ownership (Pydantic ↔ file shape).
- **`41-balance-knobs.md`** — Tunables: name, default, range, design intent, sensitivity notes.
- **`42-fixtures-and-snapshots.md`** — Golden runs, snapshot format for regression.

### Validation & APIs

- **`50-validation-rules.md`** — Hard vs soft constraints; error codes; invalid plans in UI.
- **`51-api-contract.md`** — REST/WebSocket or SSE: subscribe, stream deltas, pause/resume, export; OpenAPI-oriented outline.
- **`52-realtime-ui-protocol.md`** — Dashboard message shapes: throttling, coalescing, snapshot + patch.

### Frontend

- **`60-screen-specs.md`** — Per-screen components, data binding, empty/error states.
- **`61-charts-and-metrics.md`** — Chart ↔ loop mapping; axes, units, alert thresholds.
- **`62-design-tokens.md`** — Colors, spacing, typography (e.g. JetBrains Mono), sharp borders, primitives.

### Quality, ops, ADRs

- **`70-test-strategy.md`** — Property tests on economics, golden scenarios, API contract tests, UI smoke scope.
- **`71-implementation-roadmap.md`** — Phases and explicit “done” per phase.
- **`72-adr/`** — Architecture Decision Records for costly-to-reverse choices only.
- **`73-transaction-pipeline-handoff.md`** — RACI boundaries and prioritized implementation handoff backlog for transaction pipeline delivery.

### Ideation notes (non-authoritative)

- **`unstructured-notes/`** — Scratch and ideation notes only. These files are not implementation-driving specs and do not participate in conflict resolution.

---

## When specs conflict (which file wins)

1. **Numbers and formulas** — `21-fee-economics.md` and `40-yaml-config.md` are authoritative; other docs reference them, not duplicate literals.
2. **Agent behavior** — `31-agents.md` is authoritative for what each agent does; sim mechanics defer to `30`–`34` for mechanics detail.
3. **API and validation** — `50-validation-rules.md` and `51-api-contract.md` over informal mentions elsewhere.
4. **UI look and IA** — `12-ui-ux-spec.md`, `62-design-tokens.md`, and `60-screen-specs.md` over stray UI notes in backend docs.
5. **Recorded architecture choices** — a numbered ADR in `72-adr/` beats older narrative in other specs until those specs are updated.
6. **This overview** — authoritative for *where* topics live; if two non-ADR specs disagree on substance, prefer the more specific doc for that subdomain (see **Document map** above), then reconcile by editing the stale file.
7. **Unstructured notes do not override specs** — `docs/spec/unstructured-notes/` never overrides numbered specs or ADRs.

---

## Implementation lock order (for implementers)

1. `00` → `01`
2. Domain: `20`–`23`
3. Simulation: `31`–`34` (with `30` as cross-cutting architecture)
4. Config: `40`–`42`
5. API / validation: `50`–`52`
6. UI: `12` and `60`–`62`
**Single source of truth:** Put *numbers* and *formulas* in `21` and `40`; reference them from code or generated constants, not scattered READMEs.

**Agent coverage:** Every agent behavior should be traceable to an entry or subsection in `31` (inputs, outputs, tunables) so Mesa code maps 1:1 to spec.
