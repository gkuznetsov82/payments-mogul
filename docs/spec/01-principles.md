# Design Principles

**Status:** Draft

## Purpose

Rules that constrain modeling depth, feedback design, world construction, and implementation tradeoffs. Aligned with Sterman-style system dynamics: **feedback first**, explicit stocks and flows, delays where reality has delays, and **just enough** detail to support decisions and P&L—not a closed-form optimization of the whole economy.

For document map, conflict rules, and implementation order, see **`00-overview.md`**. Scenario shapes and config entry points live in **`11-scenarios.md`**.

---

## Feedback loops over static spreadsheets

The product is valuable when users can see **causal chains and second-order effects** (pricing, routing, fraud, regulation, competition), not when outputs are arbitrary tables. Prefer mechanisms that create **observable loops** (e.g. fee → volume → fraud → loss → repricing) over one-shot calculators.

---

## “Just enough” modeling

Simulate agents and aggregates that **move institutional P&L** or **change strategic constraints**. Omit detail that does not change decisions, reports, or scenario outcomes in a material way. When in doubt, default to **coarser** representation first; split pops or add institution types only when a scenario requires it.

---

## Two tiers of actors: institutions vs pops

**Institutions (“big” agents)** — Program managers, issuers, acquirers, PSPs, payment schemes, regulators, and similar. They are **finite** in count (often on the order of tens to a few hundred per resolved market; larger geographies still have a bounded set of *meaningful* named players). They are modeled with **state, behavior per tick, and persistent balance sheets / P&L** where the spec calls for it.

**Populations (“pops”)** — Consumers and merchants in aggregate. They appear in **large counts** and are **not** simulated as individual units. They are grouped by **segment axes** (e.g. geography, age band, social tier, risk or affiliation buckets—exact axes are scenario- and market-dependent). Pops **live inside addressable markets** (see below). **Mid- / long-term**, **employees** may be modeled the same way (labor supply, payroll mass, poaching between employers)—see **`10-player-journey.md`**.

**Migration between segments** is modeled as **mass moving between pop buckets** (conservation-aware rebalancing), not as per-unit agents relocating. Institutions read pops through **summaries and response surfaces** (rates, elasticities, fraud intensity, adoption), not by iterating microscopic populations.

---

## Accounting boundary

**Institutions** carry the **authoritative ledger** for the simulation: persistent **P&L and balance sheet** (or equivalent accounting snapshots per tick) where specified.

**Pops** do **not** require per-segment P&L/BS as first-class persisted state. They act as **sources and sinks of postings**—one-way or flow-level accounting into institutional books (e.g. spend volume, fees allocated, chargebacks attributed) unless a later scenario explicitly requires richer pop-level economics.

---

## Markets and Rest-of-World (layered world)

**Market** (capital M) means a **fully resolved slice of the world** for a given run: institutions, pops, rails, and rules the engine simulates at full fidelity. A market is **not always a country**. Examples:

- A **national** bank may use Markets as **regions or states** within one country.
- A **cross-border or internet-scale** platform may use a Market as the **universe of addressable users and counterparties** for that business, not a single jurisdiction.

**Rest-of-World (ROW)** is everything outside the resolved Markets. ROW is modeled **similarly to pops and aggregate pressures**: cross-border flows, scheme or regulatory spillovers, and “foreign” institutions **without** individual ABM unless explicitly promoted into a market for that scenario. The **interface** from ROW to markets should stay as small as possible: only the signals needed for credible competition and reporting (exact surface is specified in domain and sim chapters).

---

## World origin: authored, data-informed, and procedural

**Curated scenarios** (e.g. Victoria 3–style historical or hand-tuned starting points) are valuable where **real aggregated data** exists. The roadmap may include **importing production-shaped aggregates** (issuer/acquirer-level summaries) to seed a world.

**Procedural generation** is required for the general case: **full observability of every player in a Market is impossible**. Worlds should be **seed-based** and driven by **constraints** (e.g. scheme presence, concentration of acquirers/issuers, population and macro proxies, card penetration, tourism or seasonality). The intent is to **fill** institutions, pops, and topology without hand-authoring endless entity lists—Dwarf Fortress–style **depth from generators**, not from typing every balance sheet.

**Pre-simulation history (“legends” / burn-in)** — The world does not notionally begin on tick zero of play. Mid- and long-term vision includes **generating or simulating prior years** (or an abstract equivalent) so that **path-dependent** structure—concentration, relationships, installed base, regulatory scars—exists before the player’s scenario clock. Early versions may approximate this with **calibrated priors** instead of full multi-year simulation; the principle is that **starting state should feel lived-in**, not empty.

---

## Agentic interaction vs closed-form optimization

Institutions should **interact through rules, schedules, and limited information**, producing **emergent** market outcomes where possible. Avoid a single global solver that replaces all strategic tension unless an ADR explicitly chooses that shortcut for performance or v1 scope.

---

## Determinism, explainability, auditability

Runs with the same **seed and configuration** should yield the same trajectory under the **determinism policy** defined in **`30-architecture.md`**. Users and implementers should be able to trace **why** balances moved: postings link to mechanisms (pipeline, events, agent actions) described in **`33-transaction-pipeline.md`**, **`34-events-scheduler.md`**, and **`31-agents.md`**.

---

## Success metrics: planning tool vs game

The product is **game-shaped** (session loop, scenarios, readability) but serves **education, modeling, and what-if analysis**. Success is not “maximum realism”; it is **useful counterfactuals** and **trustworthy accounting** at the institutional layer. Exact session metrics and win/lose framing live in **`10-player-journey.md`** and **`23-metrics-kpis.md`**.

---

## Phasing (intent, not a promise of v1 scope)

1. **Early** — One or few markets, coarse pops, simple institution sets; procgen may be templates or lightly constrained.
2. **Mid** — Constraint-driven procedural worlds, explicit ROW layer, richer pop axes and scenario profiles (see **`11-scenarios.md`**, **`40-yaml-config.md`**).
3. **Long** — Data-seeded scenarios where available; **legends / burn-in** or equivalent depth; deeper ABM only where justified by P&L and design goals.
