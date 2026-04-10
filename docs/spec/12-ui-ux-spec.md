# UI / UX Specification

**Status:** Draft

## Purpose

Information architecture and interaction design for the industrial / command-center experience (no "plastic" UI).

**Cross-references:** player loop, pause, debug mode **`10-player-journey.md`**; simulation pacing **`30-architecture.md`**; control plane **`52-realtime-ui-protocol.md`**.

---

## Simulation controls (required)

- **Pause** — Clearly visible control. **Pause** completes the **current tick** first, then halts the simulation (**`30-architecture.md`**).
- **Resume** (or **Play**) — From **paused**, runs the simulation **continuously**: each completed tick is followed by the configured **wall-clock wait**, then the next tick, until **Pause** (**`30-architecture.md`**). **Speed** (**1×**, **2×**, **3×**) applies only to this **continuous** mode.
- **Next Day** — While **paused**, advances **exactly one tick** (one simulated day), then **returns to paused**. Does **not** start continuous play; **speed** multipliers do **not** apply between **Next Day** presses (**`30-architecture.md`**). Typically **enabled only when paused** (disabled or no-op while continuous play is active—pick one in implementation and document in ADR if needed).
- **Speed** — **1×**, **2×**, **3×** (or equivalent labels) for **continuous** advance after **Resume**; maps to wall-clock pacing **between** ticks; base interval is **configurable** (**`30-architecture.md`**).
- **Debug rolling window** — When debug play-through is enabled, UI to set **N ticks** of retained **bucket-level** history, subject to configured **max** (**`33-transaction-pipeline.md`**, **`40-yaml-config.md`**).

---

## Control panel (entity decisions)

- While **paused** (or as allowed between ticks), surface a **control panel** for each institution (or asset) the player may steer under the **control graph** (**`31-agents.md`**). Examples of decision families (exact v1 scope is scenario-dependent): **pricing**, **cashback / rewards**, **risk policy**, **marketing campaigns**, **termination or exclusion of user/merchant categories**, **re-routing payment rails**.
- **Feedback:** Show that submitted changes apply **starting the next tick** after the user **resumes** continuous play or presses **Next Day** (whichever advances the clock first) (**`10-player-journey.md`**).

---

## Contents (to complete)

- Screen map and navigation beyond simulation shell
- Density, hierarchy, expert-tool patterns
- Accessibility and keyboard paths
- Relationship to "Victoria 3 industrial" metaphor (concrete UI motifs)
- Debug **query** / drill-down UX against persisted bucket history (tables, filters)
