# Payments Mogul — Agent Instructions

This file is read automatically by every Claude Code session and subagent.
It contains hard constraints and orientation that must be respected before any code is written or modified.

---

## What this project is

A game-shaped simulation platform for the retail payments industry.
Vision: "Dwarf Fortress of payments." Users build virtual payment companies and observe emergent P&L from strategic decisions.
Full pitch and non-goals: `docs/spec/00-overview.md`.

---

## Role boundaries (persistent)

This project uses a strict separation of responsibilities:

- **Codex agent (this assistant)**
  - Acts as **System Architect + Business Analyst** only.
  - Owns requirements analysis, spec authoring/refinement, versioning strategy, and acceptance criteria definition.
  - Must **not** implement runtime/code/config changes.
  - Must **not** propose implementation task breakdowns unless explicitly requested for Claude handoff.
- **Claude**
  - Owns all software implementation work: code, config wiring, tests, and runtime behavior changes.
  - Executes only against approved numbered specs and explicit handoff notes.

If there is ambiguity between spec intent and implementation detail, route back to spec clarification first.

---

## Read the specs before touching code

Specs live in `docs/spec/` (flat numbered files). Read them in this order for any implementation work:

1. `docs/spec/00-overview.md` — pitch, glossary, doc map, conflict rules
2. `docs/spec/01-principles.md` — Sterman-style modeling rules; what NOT to simulate
3. `docs/spec/30-architecture.md` — tick model, play modes, determinism, pause/resume/next-day
4. `docs/spec/31-agents.md` — agent contracts (VendorAgent, GenericPop, GenericProduct)
5. `docs/spec/33-transaction-pipeline.md` — pipeline phase order within a tick
6. `docs/spec/40-yaml-config.md` — v0 config contract; required sections and fields
7. `docs/spec/50-validation-rules.md` — hard error codes and warnings
8. `docs/spec/51-api-contract.md` — REST control plane and command envelope
9. `docs/spec/52-realtime-ui-protocol.md` — SSE event shapes and delivery rules
10. `docs/spec/60-screen-specs.md` — per-screen UI contracts
11. `docs/spec/71-implementation-roadmap.md` — phases and done criteria
12. `docs/spec/11-scenarios.md` — scenario catalog; prototype_vendor_pop_v1 definition

Domain specs (`20-`–`23-`) for payment rails, fees, regulation, and KPIs as needed.

### Which file wins when specs conflict

1. Numbers and formulas → `21-fee-economics.md` and `40-yaml-config.md`
2. Agent behaviour → `31-agents.md`
3. API and validation → `50-validation-rules.md` and `51-api-contract.md`
4. UI look and IA → `12-ui-ux-spec.md`, `62-design-tokens.md`, `60-screen-specs.md`
5. Recorded architecture choices → a numbered ADR in `docs/spec/72-adr/` beats older narrative
6. `00-overview.md` is authoritative for where topics live

### SESSION-NOTED.md is NOT a spec

`docs/spec/SESSION-NOTED.md` is a conversational handoff file. Do not use it to infer requirements, resolve conflicts, or determine implementation behaviour.

---

## Mandatory tech stack

Every layer must use the prescribed technology. Do not substitute without an ADR.

| Layer | Technology | Notes |
|---|---|---|
| Simulation core | **Mesa** (Python) | `mesa.Model` + `mesa.Agent`; scheduling via explicit sorted iteration with `stable_sorted_ids` policy |
| Validation | **Pydantic v2** | All config models; hard errors raise `ConfigValidationError` with stable codes |
| In-memory state | Python dicts / dataclasses | No external DB for normal play; SQLite for debug history (spec `30`) |
| Config | **YAML** via PyYAML | v0 contract defined in `40-yaml-config.md` |
| API server | **FastAPI** + **Uvicorn** | REST control plane; see `51-api-contract.md` |
| Realtime stream | **SSE** (Server-Sent Events) | ADR-0001 locked this; WebSocket is deferred |
| UI | **React + Tailwind + Recharts** | Industrial / command-center aesthetic; no charting in prototype v1 |
| Text client | **Textual** + **httpx** | TUI for prototype v1; connects to SSE stream |

**Never replace Mesa with a hand-rolled agent loop.** If Mesa's API changes or a limitation is hit, raise it with the user and record the decision in an ADR before deviating.

---

## Tick lifecycle — hard behavioural contract

Every tick `T` must execute exactly these phases in order:

1. `tick_intake_window_opened` — pending commands move to current-tick queue; `intake_open = True`
2. Intake window stays open for `intake_window_ms` (continuous mode) or zero (NextDay mode)
3. `tick_intake_window_closed` — `intake_open = False`; current-tick commands locked
4. `tick_user_inputs_processed` — control commands applied to agent state (gates only; no agent execution)
5. Mesa `model.step()` — `Onboard()` on all agents in stable sorted order, then `Transact()` on all agents in stable sorted order
6. `tick_committed` + `state_snapshot` emitted

Commands received while `intake_open = True` → apply in tick T.
Commands received while `intake_open = False` → apply in tick T+1.

---

## Agent execution rules

- `Onboard()` runs on **all** agents before `Transact()` runs on **any** agent. This is not negotiable.
- Agent iteration order: **stable sorted by domain ID** (`vendor_id`, `pop_id`). Enforced in `PaymentsMogulModel.step()`.
- **External/API commands mutate control state only** (e.g. `CloseOnboarding`, `OpenTransacting`). They never directly call `OnboardProduct()` or `TransactProduct()`.
- Pop methods **generate requests**; Vendor/Product methods **adjudicate** accept/reject/success/failure.
- Pops are **stock-flow aggregates**, not individual persons.

---

## Determinism contract

Same `seed` + same `config` + same ordered command stream → identical trajectory.

- `model.random` (Python `random.Random` seeded via `rng=seed` in Mesa 3.5+) is the **sole RNG source**.
- Do not introduce `numpy` random, `os.urandom`, `time`-based seeds, or any other entropy source into simulation logic.
- Wall-clock pacing (speed multipliers, intake window timing) must **not** affect simulation outcomes.

---

## Config validation — stable error codes

These codes must be returned exactly as written. Do not rename or add prefixes.

| Code | Condition |
|---|---|
| `E_SCENARIO_ID_UNSUPPORTED` | `scenario.id != "prototype_vendor_pop_v1"` |
| `E_METHOD_ORDER_INVALID` | `agent_method_order != ["Onboard", "Transact"]` |
| `E_DEBUG_WINDOW_INVALID` | `debug_history_default_ticks > debug_history_max_ticks` |
| `E_WORLD_MISSING_VENDOR` | no `vendor_agents` entries |
| `E_WORLD_MISSING_POP` | no `pops` entries |
| `E_LINK_TARGET_MISSING` | `product_links[]` references unknown `(vendor_id, product_id)` |
| `E_POP_COUNT_INVALID` | `pop_count <= 0` |
| `E_RATE_OUT_OF_RANGE` | `daily_onboard` or `daily_active` outside `[0, 1]` |
| `E_TXN_PARAM_INVALID` | `daily_transact_count` or `daily_transact_amount < 0` |
| `E_ONBOARDED_COUNT_INVALID` | `onboarded_count < 0` or `> pop_count` |
| `E_FRICTION_RANGE_INVALID` | friction `min > max` or either outside `[0, 1]` |
| `E_INTAKE_WINDOW_INVALID` | `intake_window_ms < 1` |
| `E_TICK_WALL_CLOCK_INVALID` | `tick_wall_clock_base_ms < 0` |
| `E_INTAKE_EXCEEDS_TICK` | `intake_window_ms > tick_wall_clock_base_ms` (when total > 0) |
| `E_ROUNDING_MODE_INVALID` | `count_rounding_mode` or `amount_rounding_mode` not in the allowed set |
| `E_AMOUNT_SCALE_INVALID` | `amount_scale_dp < 0` |
| `E_START_DATE_INVALID` | `scenario.start_date` not `"today"` or `YYYY-MM-DD` |
| `E_DEFAULT_CURRENCY_INVALID` | `money.default_currency` not ISO 4217 alpha-3 |
| `E_CURRENCY_CATALOG_FORMAT_INVALID` | `currency_catalog.local_file.format` not `yaml`/`json` |
| `E_FX_LOCAL_FORMAT_INVALID` | `fx.sources.local_file.format` not `yaml`/`json`/`csv` |
| `E_FX_POLICY_INVALID` | `fx.source_policy` not in allowed set |
| `E_FX_SOURCE_DUPLICATE` | duplicate `fx.frankfurter_sources[].source_id` |
| `E_FX_SOURCE_REF_NOT_FOUND` | `fx.source_refs` entry has no matching `frankfurter_sources[].source_id` |
| `E_FX_POLICY_SOURCE_MISMATCH` | `fx.source_policy` selects sources that aren't enabled/configured |
| `E_FRANKFURTER_PROVIDER_UNRESOLVED` | Frankfurter source has neither `country_provider_map` nor `default_provider` |
| `E_COUNTRY_CODE_INVALID` | ISO 3166-1 alpha-2 expected (`base_country` / `nager_date.country_code`) |
| `E_WEEKEND_PROFILE_INVALID` | `calendars[].weekend_profile` not in `{sat_sun, fri_sat}` |
| `E_HOLIDAY_POLICY_INVALID` | `calendars[].holiday_source_policy` not in allowed set |
| `E_NON_WORKING_DATE_INVALID` | a value in `non_working_overrides` isn't a valid `YYYY-MM-DD` date |
| `E_CALENDAR_DUPLICATE` | duplicate `calendars[].calendar_id` |
| `E_CALENDAR_NOT_FOUND` | `regions[].calendar_id` references unknown calendar |
| `E_REGION_DUPLICATE` | duplicate `regions[].region_id` |
| `E_REGION_NOT_FOUND` | `world.vendor_agents[].region_id` / `world.pops[].region_id` references unknown region |
| `E_AMOUNT_CURRENCY_WITHOUT_MONEY` | pop authored `daily_transact_amount` as money-object but `money.default_currency` not set |
| `E_AMOUNT_CURRENCY_MISMATCH` | pop `daily_transact_amount.currency` ≠ `money.default_currency` |

Warnings (`W_*`) are non-blocking. Hard errors (`E_*`) must prevent run start.

---

## Numeric typing contract (40/51/52)

- **Counts** (persons, transactions) are emitted to all externally-visible channels (events, snapshots, API payloads) as **integers**, rounded from raw rate-derived floats using `simulation.count_rounding_mode` (v0 default `half_up`).
- **Amounts** (money) are emitted as floats at `simulation.amount_scale_dp` decimal places using `simulation.amount_rounding_mode`.
- Agents keep float precision **internally** for determinism and sub-unit accumulation; rounding is applied only at emission boundaries (`ActionOutcome.as_dict`, `GenericProduct.snapshot`, `GenericPop.snapshot`, `SimulationEngine._build_summary`).
- Rounding helpers: `engine.numeric.round_count(value, mode)` / `round_amount(value, scale_dp, mode)`.
- `pop_count` and `onboarded_count` in config are typed as `int` in the Pydantic model and rejected if fractional.

---

## Tick cycle timing contract (40-yaml-config)

- `tick_wall_clock_base_ms` is the **TOTAL** wall-clock duration of one tick at 1× speed.
- `intake_window_ms` is the portion at the **start** of the tick reserved for command intake.
- Inter-tick wait (between `tick_committed` and the next intake open) = `tick_wall_clock_base_ms - elapsed-since-tick-start`. Never additive.
- `tick_wall_clock_base_ms = 0` is "no pacing" mode — ticks proceed back-to-back; the intake<=total constraint is relaxed.
- `tick_committed` event carries `inter_tick_wait_ms` (server-computed) so clients render "next tick in N" countdowns without re-deriving the math.

---

## Dev server (graceful reload)

Do **not** use `uvicorn --reload` on Windows: it kills the worker via `TerminateProcess`, bypassing lifespan shutdown and `server_shutdown` SSE emission. Clients see raw stream errors instead of the spec's graceful shutdown flow (52-realtime-ui-protocol).

Use `python dev.py [--port 8080]` instead. It watches `engine/` and `configs/`, and on changes POSTs `/control/shutdown` (clients receive `server_shutdown` with `will_restart=true`), waits for clean exit, then restarts uvicorn. Equivalent on Unix where reload uses SIGTERM but the wrapper is still preferable for consistent behavior.

---

## Module layout (current)

```
engine/
  config/
    models.py       # Pydantic v0 config schema
    loader.py       # YAML load + cross-entity validation
  agents/
    product.py      # GenericProduct, RetailPaymentCardPrepaid
    vendor.py       # VendorAgent (mesa.Agent)
    pop.py          # GenericPop (mesa.Agent), ActionOutcome
  simulation/
    model.py        # PaymentsMogulModel (mesa.Model) — simulation core
    engine.py       # SimulationEngine — async orchestrator, SSE, intake window
  api/
    server.py       # FastAPI app, REST routes, SSE /events endpoint
configs/
  prototype_v0.yaml           # valid v0 config
  invalid_scenario_id.yaml    # triggers E_SCENARIO_ID_UNSUPPORTED
  invalid_method_order.yaml   # triggers E_METHOD_ORDER_INVALID
client/
  tui.py            # Textual TUI client
tests/
  test_config.py    # 14 config validation tests
  test_engine.py    # 6 engine/determinism tests
```

---

## What is intentionally deferred (do not implement without a spec update)

- Fee calculations and ledger postings (`21-fee-economics.md` later stages)
- SQLite debug history store (spec `30` — normal mode is in-memory only for now)
- Speed multiplier UI (1×/2×/3× hook exists in engine; TUI buttons not wired)
- Multi-scenario support beyond `prototype_vendor_pop_v1`
- Full auth / control-authority graph (`31-agents.md` mid-term)
- Multiplayer tick lifecycle (`SESSION-NOTED.md` 2026-04-16 — not yet in numbered specs)
- Cost perception / PCI model (`SESSION-NOTED.md` 2026-04-16 — not yet in numbered specs)

---

## ADRs

Architecture Decision Records live in `docs/spec/72-adr/`.
Any costly-to-reverse choice that deviates from or extends the specs must be recorded there before implementation.
Current ADRs:
- `0001` — SSE chosen as realtime transport for prototype v1 (WebSocket deferred)
