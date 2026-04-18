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

## Prototype v1 minimal agent contracts (Vendor + Pop)

This subsection defines the **minimum authoritative contracts** for `prototype_vendor_pop_v1` (**`11-scenarios.md`**). It intentionally excludes broader governance, diplomacy, and multi-entity strategy.

### Contract conventions (prototype section)

- Field and method identifiers are written in monospace.
- All classes in this slice expose `Onboard()` and `Transact()` tick entrypoints.
- Engine method order per tick is fixed: `Onboard()` on all agents, then `Transact()` on all agents (**`30-architecture.md`**).
- External/API commands update control state only; they do not directly execute counterpart transaction actions.

### `VendorAgent` (prototype profile)

#### Properties

- `vendor_id` (`string`) - Stable identifier.
- `vendor_label` (`string`) - Human-readable label for logs/UI.
- `products` (`map<string, GenericProduct>`) - Product registry owned by this vendor, keyed by `product_id`.
- `operational` (`bool`) - High-level gate; if `false`, request handlers reject.

#### Methods

- `Onboard()` - Tick entrypoint. May be noop for this class.
- `Transact()` - Tick entrypoint. May be noop for this class.
- `HandleOnboardFromPop(pop_id, product_id, requested_pop_count)` - Routes pop onboarding request to owned product handler.
- `HandleTransactFromPop(pop_id, product_id, requested_pop_count, requested_txn_count, requested_total_amount)` - Routes pop transact request to owned product handler.

#### Request-handler contract

- Vendor validates ownership (`product_id` belongs to `products`) and `operational == true`.
- Vendor delegates decision to product methods.
- Vendor returns normalized result payloads with counts/reason codes.

### `GenericProduct` (prototype profile)

#### Properties

- `product_id` (`string`) - Stable identifier.
- `product_label` (`string`) - Human-readable label.
- `owner_vendor_id` (`string`) - Owning `VendorAgent` id.
- `accepting_onboard` (`bool`) - Gate checked during onboarding decisions.
- `accepting_transact` (`bool`) - Gate checked during transact decisions.
- `onboarded_pop_count` (`integer`) - Aggregate stock currently onboarded to this product.
- `successful_transact_count` (`integer`) - Aggregate successful transaction count.
- `successful_transact_amount` (`number`) - Aggregate successful transaction amount.
- `last_action_result` (`object|null`) - Last decision summary emitted by this product.

#### Control methods (applied from intake commands)

- `CloseOnboarding()` - Sets `accepting_onboard = false`.
- `OpenOnboarding()` - Sets `accepting_onboard = true`.
- `CloseTransacting()` - Sets `accepting_transact = false`.
- `OpenTransacting()` - Sets `accepting_transact = true`.

Control methods are applied during `tick_user_inputs_processed` for the target tick (**`30-architecture.md`**, **`51-api-contract.md`**).

#### Decision methods (owner-internal)

- `OnboardProduct(pop_id, requested_pop_count)` -> `OnboardDecisionResult`
  - Checks `accepting_onboard`.
  - Returns accepted/rejected counts and reason code.
  - Increments `onboarded_pop_count` by accepted count.
- `TransactProduct(pop_id, requested_pop_count, requested_txn_count, requested_total_amount)` -> `TransactDecisionResult`
  - Checks `accepting_transact`.
  - Checks `requested_pop_count` against onboarded availability for the pop segment.
  - Returns success/failure counts and amounts with reason code.
  - Increments successful counters/amounts.

#### Result payload shapes (normalized)

- `OnboardDecisionResult`:
  - `accepted_pop_count` (`integer`)
  - `rejected_pop_count` (`integer`)
- `TransactDecisionResult`:
  - `successful_txn_count` (`integer`)
  - `failed_txn_count` (`integer`)
  - `successful_total_amount` (`number`)
  - `failed_total_amount` (`number`)

Counts must follow the deterministic rounding policy from **`30-architecture.md`** / **`40-yaml-config.md`** before being returned in result payloads.

### `RetailPayment-Card-Prepaid` (extends `GenericProduct`)

#### Additional properties

- `onboarding_friction` (`range<float>`) - Per-tick conversion friction on requested onboarding population.
- `transaction_friction` (`range<float>`) - Per-tick decline friction on requested transaction flow.

`GenericProduct` accepts all valid requests under gate checks, while this subclass applies friction to reduce acceptance/success outcomes.

### `GenericPop` (prototype profile)

Pops are stock-flow objects representing aggregated segment mass, not individual persons.

#### Properties

- `pop_id` (`string`) - Stable identifier.
- `pop_label` (`string`) - Human-readable label.
- `pop_count` (`integer`) - Total population stock in this segment.
- `products` (`map<vendor_id, map<product_id, ProductLinkState>>`) - Relationship graph to known products.
  - `ProductLinkState.known` (`bool`) - Whether this pop evaluates the product for onboarding/transacting.
  - `ProductLinkState.onboarded_count` (`integer`) - Segment mass currently onboarded to this vendor/product pair.
- `daily_onboard` (`float`) - Share of `pop_count` attempting onboarding per tick.
- `daily_active` (`float`) - Share of onboarded population attempting activity per tick.
- `daily_transact_count` (`number`) - Requested transaction count per active population unit.
- `daily_transact_amount` (`number`) - Requested total amount per active population unit.

#### Methods

- `Onboard()` - Pop-owned onboarding request generation.
  - Iterates known vendor/product links.
  - Computes requested onboarding mass from `daily_onboard`.
  - Calls `VendorAgent.HandleOnboardFromPop(...)`.
  - Updates `ProductLinkState.onboarded_count` with accepted result.
- `Transact()` - Pop-owned transact request generation.
  - Iterates known links with non-zero onboarded stock.
  - Computes requested transacting population and transaction flow from `daily_active`, `daily_transact_count`, `daily_transact_amount`.
  - Calls `VendorAgent.HandleTransactFromPop(...)`.
  - Records outcome summaries for diagnostics/realtime.

### External command boundary (prototype)

- User/API commands in intake windows may modify control state (for example `CloseOnboarding(vendor_id, product_id)`).
- External commands do **not** call `OnboardProduct()` / `TransactProduct()` directly.
- Agent-owned execution path:
  - pops request through `Onboard()` / `Transact()`,
  - vendor/product entities adjudicate through their own methods.

### Prototype scope boundary

For this slice, command authority is limited to accepting valid control commands and enforcing preconditions above. Person traits, diplomacy, board effects, and broader corporate authority logic remain out of scope.

---

## Person agents (player and NPCs)

**Person agents** are **finite**, named actors (the **player character**, **VCs**, **shareholders**, **prominent executives**, board figures). They are **not** pops: they interact through **events, agreements, and governance**, not as millions of identical units.

- **Player person** — Natural-person representation (name, demographics, portrait); may gain **traits** (modifiers) in mid-term versions (**`10-player-journey.md`**).
- **Executives** — Hired as **employees** (higher recurring cost, stronger operational modifiers) or invited to the **board** (lower cash cost, stronger **ideology / stance** pull on the institution).
- **Investors / VCs / notable shareholders** — Capital, expectations, and conflict hooks; may align or clash with player traits and institution stance.

**Modifier stacking:** Traits and person-level effects **aggregate into** the institution(s) they **control, employ, or govern**, subject to caps and scenario rules (document tunables in **`41-balance-knobs.md`**).

---

## Player and AI decisions (control authority and tick boundary)

### Who may decide what

- **Operational and strategic decisions** (e.g. **pricing**, **cashback / rewards**, **risk policy**, **marketing campaigns**, **termination or exclusion of user or merchant categories**, **re-routing** among available **payment rails**) are **scoped** by:
  - The **corporate control graph** (ownership, voting control, and scenario-defined **operating authority**), and
  - **Scenario allowlists** in early versions (**hardcoded** per scenario) expanding to full **validation** rules later (**`50-validation-rules.md`**).
- The **player** may only issue decisions for institutions (or units) they **control** under that graph; **AI institutions** follow their behavior contracts in **`31`** and scenario config.

### When decisions take effect

- Decisions are submitted from the **control panel** while **paused** or during **between-tick** intervals in **continuous** play (**`10-player-journey.md`**, **`12-ui-ux-spec.md`**). They **always take effect starting the next simulated tick** (next simulated day) that the engine runs—after **Next Day** or when **Resume** advances the clock—**never** retroactively altering the tick that just completed.

### Mid-term: scheduled and unattended actions

- **Later**, the same decision types may be **scheduled** for future ticks (e.g. marketing start date, rail migration) so simulations can run **unattended**; scheduling and triggers **`34-events-scheduler.md`**, payloads and validation **`50-validation-rules.md`**.

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
