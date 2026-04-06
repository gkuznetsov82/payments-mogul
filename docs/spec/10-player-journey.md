# Player Journey

**Status:** Draft

## Purpose

Session and meta-loop: **who the player is** (natural-person representation), how a run progresses from **character creation → world/scenario start → decisions → ticks → reports**, and how **difficulty, scoring, and long-term systems** (traits, diplomacy, capital stock) phase in over time.

**Cross-references:** principles and pops vs institutions **`01-principles.md`**; institution and **person** agents, agreements **`31-agents.md`**; scenario entry **`11-scenarios.md`**; regulatory events **`22-regulatory-pressure.md`**; KPIs and scoreboard **`23-metrics-kpis.md`**; shocks and audits **`34-events-scheduler.md`**.

---

## Player representation (natural person)

The player is a **named natural person**, not an abstract cursor. At run start (or profile creation), they configure at minimum:

- **Name**
- **Gender** (presentation / record-keeping for copy and UI; keep inclusive options)
- **Age** (may affect narrative or scenario gates where relevant; avoid shallow stereotypes—use only where mechanics justify it)
- **Portrait** (face pic or avatar)

This identity anchors **role-play**, **diplomacy**, and later **trait** systems. The player **controls** one or more institutions (scenario-dependent); the person is the **decision-maker** (CEO, founder, etc.) unless the scenario says otherwise.

---

## Session loop (core)

1. **Create or load** player profile and scenario.
2. **World / scenario start** — Resolved markets, institutions, pops, and initial books (authored, procedural, or hybrid per **`11-scenarios.md`**).
3. **Decision phases** — Player sets policies, pricing, hiring (when modeled), agreements (when unlocked), and responses to prompts between ticks or on a schedule (exact UX in **`12-ui-ux-spec.md`**).
4. **Tick advance** — Simulation updates volumes, ledgers, events, and AI institution actions.
5. **Reports** — P&L, KPIs, alerts, narrative log; optional drill-down (**`23-metrics-kpis.md`**).
6. **End condition or save** — Scenario goal, bankruptcy, time limit, or player exit; **save/load** and run history for comparison runs.

_To complete:_ explicit **win / lose / score** rules per scenario template; **difficulty knobs** (starting capital, AI aggression, regulatory strictness).

---

## RPG-style traits (mid-term)

When **other person agents** exist (see **`31-agents.md`**), the player may also choose **traits** (buffs and debuffs)—Victoria 3–style **modifiers to event and ongoing outcomes**, not combat stats (unless your board likes to sort it out the old-school way).

Illustrative examples (numbers are placeholders until **`41-balance-knobs.md`** locks them):

- **Charismatic leadership** — e.g. **+10%** staff retention (when **employee** populations are modeled).
- **Regulatory reputation** — e.g. **+20%** to favorable resolution of **regulatory audit** outcomes (conditional on scenario).
- **Arrogant** — e.g. **−20%** to **negotiation** event outcomes (schemes, sponsors, partners).

Traits apply to the **player person** and interact with **diplomacy** and **agreement** systems when those exist. Early versions may **omit** trait selection or use a **fixed** default persona.

---

## Diplomacy and agreements (mid-term)

**Victoria 3–style diplomacy** here means: **institutions (and later key persons)** can **negotiate**, form **deals**, and suffer **relationship** consequences—not a map-paint minigame.

### Early versions

What institutions **may** and **may not** do can be **hardcoded** per scenario (allowed action lists, fixed sponsor rails). Faster to ship; less emergence.

### Mid-term and beyond

**“Big” agents** should **interact** and enter **agreements** implemented as first-class state:

- **Commercial** — processing, BIN sponsorship, scheme participation, referral, co-marketing (ties to **`20-payment-rails.md`**, **`21-fee-economics.md`**).
- **Regulatory / license** — e.g. invest in compliance and obtain a **license** modeled as an **agreement with the Regulator agent**. Licenses can be **revoked** or **suspended** after events (e.g. **failed audit**, severe conduct breach—**`22-regulatory-pressure.md`**, **`34-events-scheduler.md`**). Revocation forces **pivots**: seek **BIN sponsorship** or another license path, **sell the business**, or exit the scenario objective (long-term **M&A** per **`31-agents.md`**).

Agreement **templates**, **negotiation rolls** or **deterministic checks**, and **breach / renegotiation** belong in **`31-agents.md`** and **`50-validation-rules.md`** once designed.

---

## Other person agents (VCs, shareholders, prominent execs)

Mid-term, add **named person agents** (finite count) distinct from anonymous pops:

- **VCs / investors** — Capital vs dilution, pressure on growth or margins.
- **Shareholders** (when separate from abstract cap table) — Expectations, votes, crises.
- **Prominent executives** — Recruited as **employees** (full salary and effects) or **board members** (lower cash cost, **stronger ideology / stance influence** on the institution—see **`31-agents.md`**).

**Person traits** (buffs/debuffs) attach to the **person**; when employed or seated, **apply modifiers to the controlled or employing institution** (retention, negotiation, audit odds, etc.).

**Strategic tension:** Stacking an expensive **C-suite** and **influence-heavy board** early can accelerate licenses and deals but **burns cash**; if volume does not follow, **liquidity or covenant** events can end the run. Scenarios should allow **heroic** early spends but not guarantee they are optimal.

---

## Employee populations (mid / long-term)

**Employees** are a **pop-style** aggregate (not individual HR sim): capacity for **onboarding**, **customer service**, **in-house ops and systems** (unless **outsourced**). They:

- Require **payroll** (flows into institutional P&L).
- Face **labor market tightness** per **Market** (scarcity axes in scenario config).
- Can **lose mass to competitors** if rivals **poach** with higher wages or better reputation—modeled as **inter-bucket migration** between employer-associated segments (consistent with **`01-principles.md`** pop migration).

Early versions may use a **single “headcount” stock** or fixed overhead instead of full labor pops.

---

## Company “buildings” and operating assets (long-term vision)

Victoria 3’s **buildings** analogue: **durable company stock**—owned or licensed **software**, **platforms**, **equipment** (e.g. **POS estate** policy: own vs lease vs partner-distribute), **in-house vs outsourced processing**, **data centers**, fraud stacks, etc.

Long-term goals:

- **Ownership vs outsource** — Issuer: processing in-house or outsourced? Is a capable vendor **present in the market**? **Owned by a competitor** (strategic risk)? **Unreliable** (uptime / **out-of-service** events affecting authorization or settlement—**`34-events-scheduler.md`**, **`33-transaction-pipeline.md`**)?
- **Merchant acquirer** — Who owns terminals on the street? Capital intensity vs asset-light.
- **Valuation and M&A** — Asset base and contracts feed **enterprise value** and **due diligence** outcomes (**`31-agents.md`** long-term).

This layer is **vision** for roadmap; v1 may omit or represent as **scalar “tech level”** or fixed scenario assumptions.

---

## Phasing summary (player-facing systems)

- **Early** — Person **cosmetics** only; **hardcoded** institution capabilities; simple session loop; minimal or no traits, diplomacy, employees, or capital stock.
- **Mid** — **Traits** for player and key persons; **agreements** and **diplomacy** between institutions; **execs / board**; **employee** pops or structured labor market; richer **regulatory license** lifecycle.
- **Long** — **Operating asset** depth, outsourcing and reliability shocks, **M&A** and sale-of-business paths tied to person and institution state.
