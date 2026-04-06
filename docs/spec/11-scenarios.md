# Scenarios

**Status:** Draft

## Purpose

Scenario catalog, **world construction** (resolved markets vs ROW), and how runs are parameterized from configuration. For *why* worlds are layered, how pops vs institutions work, and procedural vs authored philosophy, see **`01-principles.md`**.

---

## Scenario types (overview)

Scenarios differ by **what is resolved at full fidelity**, **what ROW supplies**, and **how the initial world is produced**:

- **Authored / curated** — Hand-tuned starting graphs, pops, and parameters (closest to a fixed “historical” or designer scenario). Use when you want exact reproducibility and narrative control.
- **Data-informed** — Starting aggregates (or partial institution lists) imported or copied from real-world summaries; remainder filled by generators or defaults. Roadmap item; depends on data pipeline and validation rules.
- **Procedural (seed + constraints)** — **Seed-based** generation that satisfies a **constraint profile** (schemes, concentration, population/macro proxies, penetration, tourism/seasonality, etc.) without listing every entity by hand. Primary path for “impossible to fully observe” markets.

Pre-play **world history** (burn-in / legends) is specified in principle in **`01-principles.md`**; schedule and mechanics belong in **`30-architecture.md`** and **`34-events-scheduler.md`** when implemented.

---

## Markets vs Rest-of-World

Each scenario declares one or more **Markets** (fully simulated slices) and an optional **ROW** aggregate. Definitions and rationale: **`01-principles.md`** (Markets and Rest-of-World).

- **Market** — Closure of institutions, pops, rails, and local rules simulated in detail for that run. May be geographic (e.g. country, region) or **logical** (e.g. addressable user universe for a global platform).
- **ROW** — Boundary conditions and aggregate counterparties; not individual foreign issuers/acquirers unless promoted into a market for that scenario.

Scenario YAML (or equivalent) should make **market boundaries and ROW linkage** explicit so configs do not silently imply “one country = whole world.”

---

## Contents (to complete)

- Scenario list: names, intent, default markets, default player role
- Competitors, regulation hooks, and seed data references per scenario
- **Constraint profiles** for procedural scenarios (schema lives in **`40-yaml-config.md`**; validation in **`50-validation-rules.md`**)
- YAML (or config) entry points per scenario
- Unlock / progression (if any)
- Reproducibility: seeds, fixed vs random components (**`30-architecture.md`** for determinism policy)
