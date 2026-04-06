# Agents

**Status:** Draft

## Purpose

Institution and population **behavior contracts**: state, observations, actions, and who interacts with whom (Mesa-oriented). This chapter defines **payment-industry institutions**, the **corporate structure graph** (ownership, control, and group economics), and **stance / ideology** modifiers. Pop agents are summarized here only as interaction endpoints; pop mechanics are anchored in **`01-principles.md`**.

**Cross-references:** player identity, traits, diplomacy phasing **`10-player-journey.md`**; rails topology **`20-payment-rails.md`**; fees and transfer pricing **`21-fee-economics.md`**; KPIs and reporting views **`23-metrics-kpis.md`**; events and M&A timing **`34-events-scheduler.md`**.

---

## Design inspiration: Capitalism-style corporate depth

**Capitalism Lab** (successor to Capitalism II) treats the player’s empire as a **graph of companies** with **equity stakes**, not a single monolith. Useful patterns to echo (not to clone mechanically):

- **Threshold control** — High ownership (in Lab, **75%+** on a subsidiary) unlocks **operating control** distinct from minority investment.
- **Levels of control** — **Corporate** (strategy, capital, structure) vs **operating unit** (day-to-day levers); Payments Mogul may compress this into institution-level decisions per tick.
- **Intra-group commerce** — Trade and money flows **between controlled entities** are modeled as **internal** (special pricing, access, elimination in group views) vs **arm’s-length** deals with outsiders.
- **Structural change** — **Mergers**, absorbing subsidiaries, and **moving businesses** between controlled companies are first-class long-term actions.

Payments Mogul adapts this to **rails, regulation, and ledger truth**: the important parallel is **economic substance**—who actually bears cost and risk— not just UI grouping.

---

## Institution types (payment domain)

The engine recognizes **institution kinds** (extensible by scenario). Initial catalog (names may vary in YAML):

- **Payment scheme / network** (e.g. card network, domestic scheme—if present)
- **Issuer** (bank or licensed issuer of funds/payment credentials)
- **Acquirer** / **PSP** (merchant-facing acceptance, may be bank or non-bank)
- **BIN sponsor** / **sponsor bank** (when non-bank acquirers require a licensed partner—regime-dependent)
- **Program manager** (product/program ownership where modeled separately from issuer)
- **Regulator** (rule changes, audits, enforcement as scenario mechanics)
- **Optional:** processor, fraud vendor, marketplace platform, etc., when a scenario needs them

Each institution is typically a **legal entity** with its own **books** in the sim (see below). Some scenarios may attach **operating divisions** as sub-units without separate legal personality—specify per scenario.

---

## Person agents (player and NPCs)

**Person agents** are **finite**, named actors (the **player character**, **VCs**, **shareholders**, **prominent executives**, board figures). They are **not** pops: they interact through **events, agreements, and governance**, not as millions of identical units.

- **Player person** — Natural-person representation (name, demographics, portrait); may gain **traits** (modifiers) in mid-term versions (**`10-player-journey.md`**).
- **Executives** — Hired as **employees** (higher recurring cost, stronger operational modifiers) or invited to the **board** (lower cash cost, stronger **ideology / stance** pull on the institution).
- **Investors / VCs / notable shareholders** — Capital, expectations, and conflict hooks; may align or clash with player traits and institution stance.

**Modifier stacking:** Traits and person-level effects **aggregate into** the institution(s) they **control, employ, or govern**, subject to caps and scenario rules (document tunables in **`41-balance-knobs.md`**).

---

## Agreements, diplomacy, and regulatory licenses

**Diplomacy** (game-facing term) means **negotiated relationships and contracts** between institutions (and, where modeled, key persons as representatives).

- **Early implementations** may restrict actions with **hardcoded** allow-lists per scenario.
- **Mid-term** introduces **agreement** objects: duration, terms, fees, **termination** and **breach** conditions, **renegotiation** triggers.

**Regulatory license** as agreement:

- Obtaining a license is an **agreement with the Regulator agent** (investment of time/money/compliance capacity—exact costs in **`21-fee-economics.md`** / scenario YAML).
- **Revocation or suspension** follows **events** (e.g. failed audit, enforcement—**`22-regulatory-pressure.md`**, **`34-events-scheduler.md`**), creating **strategic holes** the player must fill via **alternate rails** (e.g. **BIN sponsorship**), **M&A**, or **exit** (**`10-player-journey.md`**, M&A in this chapter).

Commercial rails agreements (sponsor, scheme membership) remain tied to **`20-payment-rails.md`**; **negotiation difficulty** and **relationship scores** live here or in **`41-balance-knobs.md`** until a dedicated diplomacy chapter exists.

---

## Corporate structure: ownership, subsidiaries, investments

### Graph model

Model the corporate world as a **directed graph**:

- **Nodes** — Institutions (legal entities or scenario-defined units).
- **Edges** — **Equity ownership** (percentage of voting or economic stake—pick one convention per scenario or define both), optional **debt / funding** edges if needed later.

Derived concepts:

- **Parent / subsidiary** — Declared or inferred when ownership crosses a scenario’s **control threshold** (default suggestion: align with strong control at **>50%** voting; **effective control** band for gameplay at **≥75%** mirroring Capitalism Lab’s subsidiary DLC—exact numbers live in **`40-yaml-config.md`** / **`41-balance-knobs.md`**).
- **Minority investment** — Non-controlling stake: influences **dividends, board pressure, or ideology alignment** before full control mechanics apply.
- **Conglomerate / group** — Connected component of institutions under a **common ultimate parent** or **player-designated group** (for reporting).

### What relationships affect (near-term → long-term)

- **Investment / stake** — Dividend flows, voting pressure, unlock of “friendly” negotiations, information sharing (scenario-dependent).
- **Subsidiary / control** — Player (or AI) sets aligned strategy; **intercompany pricing** rules; consolidated reporting eligibility.
- **Ideology / stance** (below) — Modifies **trust, cooperation, conflict**, and reaction to **regulatory** or **scheme** pressure—even between non-affiliated institutions.
- **M&A (long-term)** — Create/destroy nodes, merge books or run **purchase accounting** simplifications, migrate portfolios (merchants, BIN ranges, programs).

Exact formulas and event payloads belong in **`21-fee-economics.md`**, **`33-transaction-pipeline.md`**, and **`34-events-scheduler.md`**.

---

## Stances and ideologies

**Ideology** (or **stance**) is orthogonal to equity: it describes **how** an institution prefers to operate—risk appetite, scheme loyalty, merchant aggressiveness, regulatory posture, “growth at all costs” vs “margin discipline,” etc.

Use stances to drive:

- **Negotiation outcomes** (scheme fees, sponsor terms, referral deals)
- **Coalition behavior** (lobbying blocks, joint ventures)
- **Friction** with institutions that have **opposing** stances, even without competitive overlap

Stances can be **discrete enums** (e.g. `conservative`, `aggressive`, `merchant-centric`) or **numeric vectors**; choose per implementation phase. **`41-balance-knobs.md`** should list tunables that map stance → behavior.

---

## Legal-entity books vs group consolidation

### Legal entity (default)

Every resolved institution maintains **its own ledger** (P&L and balance sheet per **`01-principles.md`**). Intercompany flows post as **explicit lines** (sponsor fees, internal processing charges, dividends, capital injections) so audits and scenario debugging remain traceable.

### Consolidated group view (mid-term target)

For a defined **control group** (same economic owner as the player, or AI conglomerate):

- Provide **rollup reporting**: revenue, expense, and balance sheet **aggregated across group members**.
- Apply **intercompany elimination** rules (simplified IFRS-style intent): fees paid **from one group entity to another** are **not** double-counted as external cost at group level—they are **transfer pricing** or **internal service income** that nets out in consolidation.

**Economic substance rule:** consolidation reflects **who bears the economic reality**, not invoice labels. If the player **controls both** payer and payee of a fee, the group view treats that payment as **internal** (eliminated in rollup). If the payer and payee are **not** in the same control group, the fee is **external** and hits group P&L like any third-party cost.

### Example: BIN sponsor inside vs outside the group

- **Player group** includes a **bank (issuer/BIN sponsor)** and a **non-bank acquirer** that uses that bank as **BIN sponsor**. Sponsor fees, reserve requirements, and similar cash flows between acquirer and bank are **intercompany** for consolidation: **not** “left pocket / right pocket” at group level—rollup shows **net** economic effect (subject to elimination rules in **`21-fee-economics.md`**).
- **Player** runs the same non-bank acquirer but the **BIN sponsor is an independent bank** outside the group. Sponsor fees are **third-party expense** (and the sponsor’s revenue). Group P&L for the player **includes** that cost; no elimination.

Commercial **sponsorship agreements** (rails) are specified in **`20-payment-rails.md`**; **which posts eliminate on consolidation** is specified in **`21-fee-economics.md`** and reporting in **`23-metrics-kpis.md`**.

---

## Mergers and acquisitions (long-term)

Target capabilities (phased):

- **Acquisition** of equity stakes up to full control; **delisting** or absorption of subsidiaries into parent **legal** entities (or scenario simplification: merged single node).
- **Portfolio transfer** — Merchant contracts, programs, BIN ranges move between entities with **migration shocks** (churn, compliance review).
- **Antitrust / regulatory** gates as scenario hooks (**`22-regulatory-pressure.md`**).

Each M&A pattern should emit **events** and **ledger adjustments** per **`34-events-scheduler.md`** and **`33-transaction-pipeline.md`**, with ADRs for simplifications (**`72-adr/`**).

---

## Interaction matrix (who touches whom)

_To complete as a compact table or list:_ scheme ↔ issuer ↔ acquirer ↔ sponsor ↔ regulator ↔ program manager; **agreements** and **diplomacy** channels between institutions; **person agents** (player, execs, investors) attached to governance and hiring; pop-facing volume as **aggregate** into acquirer/issuer path; **employee** labor pool (mid-term) affecting capacity and cost.

Emergent outcomes to document when rules exist: price wars, sponsor switching, regulatory cascade, scheme bifurcation, **license loss → sponsor hunt**, board coups or investor crises (when modeled).

---

## Phasing summary

- **Early** — Institutions as nodes; **explicit** sponsor and scheme relationships; **legal-entity** books only; simple stance tags if any; **hardcoded** allowed actions; player **cosmetics** only (**`10-player-journey.md`**).
- **Mid** — **Ownership graph**, control thresholds, **group consolidation**; **agreements** and **diplomacy**; **person agents** with traits; **employee** pops or structured labor; **regulatory license** lifecycle.
- **Long** — **M&A** events, dynamic graph changes, ideology-driven coalitions; **operating assets / outsourcing** depth (**`10-player-journey.md`**); reliability and **out-of-service** shocks tied to vendor and asset choices (**`34-events-scheduler.md`**).
