# Payments Mogul — Specification Index

Specs in this folder define *what* to build; implementation should match these docs or explicitly supersede them via `72-adr/`.

## Reading order

1. `00-overview.md` → `01-principles.md`
2. Domain: `20-` … `23-`
3. Simulation: `30-` … `34-`
4. Config & fixtures: `40-` … `42-`
5. API & validation: `50-` … `52-`
6. UI: `12-ui-ux-spec.md`, `60-` … `62-`
7. Delivery: `70-`, `71-`, `73-`, `74-`, `75-`

## Stack reference (vision)

| Layer        | Technology        |
|-------------|-------------------|
| Simulation  | Mesa (Python)     |
| Validation  | Pydantic          |
| State       | In-memory         |
| Config      | YAML              |
| API         | FastAPI           |
| UI          | React + Tailwind  |
| Charts      | Recharts          |

## Files

| File | Topic |
|------|--------|
| `00-overview.md` | Project overview, glossary, doc map |
| `01-principles.md` | Sterman-style modeling principles |
| `10-player-journey.md` | Session and progression |
| `11-scenarios.md` | Scenario catalog & parameters |
| `12-ui-ux-spec.md` | UI IA and patterns |
| `13-content-style.md` | Copy and number formatting |
| `20-payment-rails.md` | 4-party domain model |
| `21-fee-economics.md` | Fees and constraints |
| `22-regulatory-pressure.md` | Regulation as dynamics |
| `23-metrics-kpis.md` | KPI definitions |
| `30-architecture.md` | Engine and tick architecture |
| `31-agents.md` | Agent behaviors |
| `32-variables-stocks-flows.md` | Stocks, flows, loops |
| `33-transaction-pipeline.md` | Transaction lifecycle |
| `34-events-scheduler.md` | Shocks and schedules |
| `40-yaml-config.md` | Config layout & Pydantic mapping |
| `41-balance-knobs.md` | Tunables table |
| `42-fixtures-and-snapshots.md` | Golden runs |
| `50-validation-rules.md` | Validation catalog |
| `51-api-contract.md` | FastAPI surface |
| `52-realtime-ui-protocol.md` | Streaming to UI |
| `60-screen-specs.md` | Per-screen specs |
| `61-charts-and-metrics.md` | Recharts mapping |
| `62-design-tokens.md` | Industrial UI tokens |
| `70-test-strategy.md` | Testing approach |
| `71-implementation-roadmap.md` | Phases and done criteria |
| `72-adr/README.md` | How to write ADRs |
| `73-transaction-pipeline-handoff.md` | Pipeline delivery handoff contract |
| `74-world-builder-config-designer.md` | World Builder product and API/UX contract |
| `75-world-builder-handoff.md` | World Builder delivery handoff contract |
