# Session notes (handoff / context)

**IMPORTANT — FOR HUMANS AND TOOLING CONFIG**

- **Claude Code and other spec-driven agents must NOT treat this file as part of the product specification.** Do not use it to infer requirements, conflict resolution, or implementation behavior when “reading the spec.”
- **Purpose:** conversational handoff, decisions discussed in chat, and backlog hints. The authoritative spec remains the numbered `*.md` files and `72-adr/`.
- If your agent has an ignore list (e.g. `.cursorignore`, project rules), add this path so routine “read all specs” passes skip it.

---

## Repo / spec state (as of this save)

### Already written into numbered specs

- **`00-overview.md`** — Purpose, elevator pitch (Dwarf Fortress of payments vibe), non-goals, glossary placeholder, document map (list format, not tables), conflict rules, implementation lock order. Spec root: `docs/spec/`.
- **`01-principles.md`** — Sterman-style feedback-first; institutions vs pops; accounting boundary; Markets vs ROW; procgen + curated/data scenarios; legends/burn-in vision; agentic vs global solver (ADR caveat); determinism/audit pointers; **wall-clock pacing must not change simulation outcomes**; planning tool vs game; phasing; employees as possible future pop (one line).
- **`10-player-journey.md`** — Natural-person player; **play modes** (normal vs debug rolling window); **pause / Resume / Next Day / speed**; decisions effective next tick; session loop updated; RPG traits mid-term; diplomacy/agreements; license-as-agreement; VCs/exec/board; employee pops; buildings/outsourcing long-term; phasing.
- **`11-scenarios.md`** — Scenario types (authored, data-informed, procedural); Markets vs ROW; pointers to architecture/events/config validation; “contents to complete” backlog.
- **`12-ui-ux-spec.md`** — Simulation controls: Pause, Resume, Next Day, speed, debug window; control panel; cross-refs.
- **`20-payment-rails.md`** — **Daily** time grain; commercial rails ≠ corporate control; consolidation in `31`/`21`; contents still to complete.
- **`21-fee-economics.md`** — Fees from **aggregate** activity; postings; **intercompany alignment still to complete**; fee taxonomy still to complete.
- **`30-architecture.md`** — Tick = one day; normal vs debug retention; queryable store for debug history; wall-clock pacing 1×/2×/3×; **Next Day** single-step; pause at tick boundary; determinism.
- **`31-agents.md`** — Corporate graph; institution types; person agents; **player/AI decisions** (control authority, next-tick effect); agreements/diplomacy/regulatory license; stances; legal-entity books vs consolidation; BIN sponsor example; M&A long-term; interaction matrix + phasing.
- **`33-transaction-pipeline.md`** — Aggregate intents → fees → transfers → postings; normal EOD vs debug rolling **N** ticks (full bucket log); cross-refs.
- **`40-yaml-config.md`** — `tick_wall_clock_base_ms`, `debug_history_max_ticks`, validation notes; contents still to complete.
- **`41-balance-knobs.md`** — Pacing/debug window placeholders; full table still to complete.
- **`42-fixtures-and-snapshots.md`** — CI compares EOD aggregates; contents still to complete.
- **`51-api-contract.md`** — Control plane outline (pause, resume, **next day**, speed, debug window, decisions).
- **`52-realtime-ui-protocol.md`** — Control messages outline including **next day**.
- **`60-screen-specs.md`** — Simulation shell bullets; contents still to complete.
- **`71-implementation-roadmap.md`** — Phase 0 line expanded (tick, modes, pause/Resume/Next Day, pacing, debug store); phases still loose.

### Typo / style hygiene (optional)

- Overview elevator pitch: **“Its ultimate goal”** (not “It’d”).
- Pick **US vs UK** spelling consistently (e.g. behavior vs behaviour).

---

## Discussed but not yet fully written into specs (backlog)

### Transaction backbone and logging

- **Partially incorporated** into **`30`**, **`33`**, **`42`**, **`01`** (see “Already written” above): tick = day; normal EOD summaries vs debug rolling **N** with queryable store; aggregate intents; CI on EOD aggregates.
- **Still open for future spec work:** posting-first vs transaction-as-object; replay; drill-down chains; **per-tick checksum**; perf trim mode; full **`23-metrics-kpis.md`** snapshot schema.

### Scale assumptions (user machine as dev baseline)

- Tick **1 day**; possible **weekly rollup** for storage or game pacing tradeoffs.
- **~1k–100k** pop slices, **~50–100** institutions; real cost ~**K links per pop per tick**, not necessarily full **P×I** dense mesh.
- **Ultra 9 + 64 GB RAM:** vectorized math fine at large tensors; **Python loops** at 10⁷ scale risky; **GPU** often unused unless explicitly GPU numerics.

### Phase 0 / vertical slice strategy

- Lock **one** end-to-end path in spec before or parallel to MVP: single scenario spine, minimal `20`–`23`, `30`+`33`, stub `40`, stub `51`/`60`.
- **`71-implementation-roadmap.md`** still needs an explicit Phase 0 **“done” checklist** (one-liner exists, not exit criteria).
- **`11-scenarios.md`** should eventually name **one concrete starter scenario** (player role, one Market, ROW, end condition).

### Fee economics gap

- **`21-fee-economics.md`** still needs **intercompany elimination** and numeric/posting alignment with **`31`** (BIN sponsor fees).

### Optional overview tweak

- One sentence in **`00-overview.md`** pointing to **`01`/`11`** for world layering + procgen (if desired).

---

## Meta / workflow

- **Chat threads do not travel with git.** New machine = same files, **new** conversation unless you paste this file or similar.
- **ADR** = Architecture Decision Record; lives in `72-adr/`.
- User preference: **avoid GFM tables** in specs where editor preview is poor; use **headings + bullet lists**.

---

## Open threads from conversation (not spec decisions)

- Relatable games for inspiration: V3, Capitalism Lab, DF, OpenTTD, Democracy 4, Offworld Trading Company, etc. (design reference only.)
- Victoria 3–scale team: ballpark **~100** in credits (all roles), studio ~**150** at one point—not a precise “V3 dev count.”
- Claude/Cursor **Phase 0** wall-clock: often **hours** to first runnable skeleton, **~0.5–2 days** calendar for something you’d build on—with human review and iteration.

---

## Session log — 2026-04-08

### Committed to numbered specs (this session)

- **Transaction aggregation / storage:** `30`, `33`, `10`, `12`, `20`, `21`, `31`, `40`, `41`, `42`, `51`, `52`, `60`, `71`, plus **`01`** (pacing vs determinism). Normal play keeps **EOD summaries**; debug keeps rolling **N** ticks of **full aggregate/bucket** history in a **queryable** store; caps in config.
- **Controls:** **Pause** (end of tick), **Resume** (continuous with **1×/2×/3×** between ticks), **Next Day** (single tick while paused, then paused again). API/realtime outlines updated.
- **Decisions:** Effective **next executed tick** (Next Day or Resume); control graph authority unchanged in substance, wording aligned.

### Discussed; not yet written into numbered specs (next session / backlog)

- **Generic fee & rails engine:** No hardcoded interchange/MDR in core logic—**scenario templates** and validation; optional **code modules** for optimization, **configuration remains driver**.
- **Transaction-intent families (conceptual):** (1) establish relationship, (2) change relationship / share-of-wallet weights, (3) drop relationship, (4) **transact** (richest; **product** as entity joining pop type + institution).
- **Pops:** **Needs** (optional vs mandatory per tick); acquire/use products; **preference** granularity—keep bounded; per–**pop type** logic; scenario seeds for starting configs.
- **Accrual vs cash:** P&L/recognition vs **delayed fund transfers** per rails; receivables before cash; **cashflow** and prefunding as gameplay; staged auth → clearing → settlement; **working days / calendars** (start single calendar, architecture for **multiple** later; holidays, T+n, both legs business day; contrast instant 24×7 rails).
- **Suggested phasing when writing spec:** config-first fees/rails + one calendar + simple transact slice → relationship intents → richer transact → multi-calendar stress.

### Resume prompt (paste in a new chat)

> Read `docs/spec/SESSION-NOTED.md` and continue from the **Session log — 2026-04-08** backlog: generic config-driven fees/rails, four intent types, pops needs/products, accrual vs cash and calendars—promote into `20`, `21`, `33`, `31`, `11`, `40` as appropriate.

---

## Session log — 2026-04-16 (notes archive addendum)

### Cost perception and information asymmetry

- Added concept: product choice is driven by **perceived** cost, not true cost, especially pre-usage.
- Proposed model:
  - **Marketing Rate (`C_m`)**: public sticker claim used in scan/compare.
  - **Realized Friction (`C_r`)**: true effective cost borne after usage.
  - **Perceived Cost Index (`PCI`)**: pop belief, dynamic and pop-specific.
- Experience loop:
  - Onboarding starts with `PCI = C_m`.
  - During usage, each tick computes `delta = C_r - PCI`.
  - Discovery updates `PCI` toward `C_r` with probability based on pop attention/literacy.
  - If `PCI` crosses tolerance threshold, pop enters re-evaluation flow.
- Not all users notice true cost:
  - Attention sensitivity varies by segment.
  - Even without exact fee discovery, cumulative dissatisfaction can raise switching propensity.
- Potential management lever:
  - Pricing disclosure/obfuscation projects may reduce discovery rate.
  - Tradeoff: higher regulatory pressure and consumer-protection downside if audited.
- Open mechanic question captured: discovery mainly driven by **usage time**, **events/news**, or combined trigger.

### Risk and architecture continuity notes

- Reinforced doctrine captured in prior notes:
  - Agents act only within their authority/capability.
  - Dual-entry/accounting-first structure remains core.
  - Aggregate logs and balance-sheet-derived stats remain preferred implementation backbone.
- Human architecture remains a strategic layer:
  - Role-specific leadership/capability upgrades (e.g., risk leadership) should materially affect subsystem efficiency.

### Mapping candidates into numbered specs (backlog)

- `31-agents.md`:
  - Pop attributes for `attention` / `financial_literacy` / tolerance.
  - Product-side state hooks for perceived vs realized cost update path.
- `33-transaction-pipeline.md`:
  - Aggregate cost realization signals that feed `PCI` update each tick (without per-transaction simulation).
- `22-regulatory-pressure.md`:
  - Consumer-protection exposure from persistent information asymmetry.
- `41-balance-knobs.md`:
  - Tuneables for discovery probability, dissatisfaction accumulation, tolerance thresholds.
- `11-scenarios.md`:
  - Scenario-level assumptions for market-wide disclosure norms and consumer sensitivity.

---

## Shutdown handoff — 2026-04-16

### Session outcomes saved

- Unstructured notes ingestion is now feasible via exported PDFs in `docs/spec/unstructured-notes/`.
- Architecture-first synthesis plan was created and stored at:
  - `c:\Users\grigo\.cursor\plans\architecture-first_synthesis_roadmap_34d62d5a.plan.md`
- Notes archive updated with:
  - Cost perception asymmetry model (`C_m`, `C_r`, `PCI`)
  - Discovery/attention dynamics and regulatory implications
  - Mapping targets across numbered specs

### Current source artifacts to preserve context

- `docs/spec/unstructured-notes/GK Notes 2026-04-15.pdf`
- `docs/spec/unstructured-notes/Gemini Notes 2026-04-13.pdf`
- `docs/spec/SESSION-NOTED.md`
- `c:\Users\grigo\.cursor\plans\architecture-first_synthesis_roadmap_34d62d5a.plan.md`

### Recommended first actions on next startup

1. Read the architecture-first plan file above.
2. Read latest addenda in `SESSION-NOTED.md` (2026-04-16 sections).
3. Promote backlog items into numbered specs in this order:
   - `30-architecture.md`
   - `31-agents.md`
   - `33-transaction-pipeline.md`
   - `22-regulatory-pressure.md`
   - `41-balance-knobs.md`
   - `11-scenarios.md`
4. Keep `SESSION-NOTED.md` as context only (not authoritative spec).

### Resume prompt (copy for next chat)

> Read `docs/spec/SESSION-NOTED.md` (including 2026-04-16 sections) and the plan at `c:\Users\grigo\.cursor\plans\architecture-first_synthesis_roadmap_34d62d5a.plan.md`. Continue architecture-first consolidation of numbered specs, preserving all ideas from the two unstructured PDF notes while prioritizing a clean first vertical slice.

---

## Shutdown handoff — 2026-04-16 (multiplayer addendum)

### Multiplayer architecture decisions captured

- New plan created for multiplayer foundations:
  - `c:\Users\grigo\.cursor\plans\multiplayer_foundation_architecture_39b46b1b.plan.md`
- Guiding decision:
  - One deterministic, server-authoritative simulation core.
  - Launch first in session-based synchronous mode.
  - Support async/persistent later via policy/config layer, not engine rewrite.

### Tick-processing contract (agreed direction)

- Wall-clock tick uses phased cycle:
  - command intake window
  - cutoff/lock window
  - deterministic simulation + commit
  - broadcast + next tick open
- Late commands are routed to next tick only.
- Commands use effective-tick semantics (no mid-tick direct state mutation).

### Control-plane/API governance requirements

- Separate business command channel from simulation control channel.
- Core event stream should include lifecycle events:
  - `tick_opened`
  - `tick_cutoff_reached`
  - `tick_committed`
  - `tick_paused`
  - `tick_resumed`
- Session policy must define pause/vote behavior for multiplayer:
  - proposer/voter eligibility
  - quorum rule
  - vote TTL
  - pause duration limits
  - cooldowns
  - host override scope
- Host/server-console controls should be policy-bound and auditable.

### Suggested placement into numbered specs (next pass)

- `30-architecture.md`: tick barrier, commit phases, deterministic ordering, clock/pause policies.
- `51-api-contract.md`: command envelope, effective-tick and idempotency semantics, control actions.
- `52-realtime-ui-protocol.md`: tick/vote lifecycle events and reconnect semantics.
- `34-events-scheduler.md`: timing rules for events relative to tick barrier.
- `71-implementation-roadmap.md`: multiplayer phase gates and explicit phase-1 scope.

### Resume prompt (copy for next chat)

> Read `docs/spec/SESSION-NOTED.md` (including both 2026-04-16 shutdown sections) plus plans at `c:\Users\grigo\.cursor\plans\architecture-first_synthesis_roadmap_34d62d5a.plan.md` and `c:\Users\grigo\.cursor\plans\multiplayer_foundation_architecture_39b46b1b.plan.md`. Continue with architecture-first spec consolidation, then draft API/tick lifecycle schemas for multiplayer control and pause voting.
