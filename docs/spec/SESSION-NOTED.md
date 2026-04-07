# Session notes (handoff / context)

**IMPORTANT — FOR HUMANS AND TOOLING CONFIG**

- **Claude Code and other spec-driven agents must NOT treat this file as part of the product specification.** Do not use it to infer requirements, conflict resolution, or implementation behavior when “reading the spec.”
- **Purpose:** conversational handoff, decisions discussed in chat, and backlog hints. The authoritative spec remains the numbered `*.md` files and `72-adr/`.
- If your agent has an ignore list (e.g. `.cursorignore`, project rules), add this path so routine “read all specs” passes skip it.

---

## Repo / spec state (as of this save)

### Already written into numbered specs

- **`00-overview.md`** — Purpose, elevator pitch (Dwarf Fortress of payments vibe), non-goals, glossary placeholder, document map (list format, not tables), conflict rules, implementation lock order. Spec root: `docs/spec/`.
- **`01-principles.md`** — Sterman-style feedback-first; institutions vs pops; accounting boundary; Markets vs ROW; procgen + curated/data scenarios; legends/burn-in vision; agentic vs global solver (ADR caveat); determinism/audit pointers; planning tool vs game; phasing; employees as possible future pop (one line).
- **`10-player-journey.md`** — Natural-person player; session loop; RPG traits mid-term; diplomacy/agreements; license-as-agreement with regulator, revocation pivots (BIN sponsor, M&A/sell); VCs/exec/board; employee pops mid/long; Vic3-style “buildings” / outsourcing / reliability long-term; phasing.
- **`11-scenarios.md`** — Scenario types (authored, data-informed, procedural); Markets vs ROW; pointers to architecture/events/config validation; “contents to complete” backlog.
- **`20-payment-rails.md`** — Contents list + bullet: commercial rails ≠ corporate control; consolidation in `31`/`21`.
- **`31-agents.md`** — Capitalism Lab–style corporate graph; institution types; person agents; agreements/diplomacy/regulatory license; stances; legal-entity books vs group consolidation; BIN sponsor in-group vs third-party example; M&A long-term; interaction matrix + phasing updates.

### Typo / style hygiene (optional)

- Overview elevator pitch: **“Its ultimate goal”** (not “It’d”).
- Pick **US vs UK** spelling consistently (e.g. behavior vs behaviour).

---

## Discussed but not yet fully written into specs (backlog)

### Transaction backbone and logging

- Ticks produce **aggregate transaction intents** (pop slice × counterparty institutions × key dimensions), not individual cardholders. These drive **fees, fraud, BS movements, P&L**.
- **Tiered observability:** (1) always tick/GL summaries for UI and scoring; (2) often per-tick aggregate bucket log or sketch; (3) debug: embedded DB / Parquet for full trail; (4) perf mode: trim storage.
- Consider **posting-first** vs **transaction-as-object**; **replay** (seed + inputs vs log); **drill-down** P&L → posting → bucket; **retention windows**; **per-tick checksum** for reproducibility.
- **Target files when editing:** `33-transaction-pipeline.md`, `30-architecture.md`, `23-metrics-kpis.md`, `42-fixtures-and-snapshots.md`; optional principle line in `01`.

### Scale assumptions (user machine as dev baseline)

- Tick **1 day**; possible **weekly rollup** for storage or game pacing tradeoffs.
- **~1k–100k** pop slices, **~50–100** institutions; real cost ~**K links per pop per tick**, not necessarily full **P×I** dense mesh.
- **Ultra 9 + 64 GB RAM:** vectorized math fine at large tensors; **Python loops** at 10⁷ scale risky; **GPU** often unused unless explicitly GPU numerics.

### Phase 0 / vertical slice strategy

- Lock **one** end-to-end path in spec before or parallel to MVP: single scenario spine, minimal `20`–`23`, `30`+`33`, stub `40`, stub `51`/`60`.
- **`71-implementation-roadmap.md`** should get an explicit Phase 0 “done” checklist.
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
