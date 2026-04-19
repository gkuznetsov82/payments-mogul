# Screen Specifications

**Status:** Draft

## Purpose

Per-screen UI blueprint: components, data bindings, states.

**Cross-references:** simulation controls and control panel **`12-ui-ux-spec.md`**; realtime **`52-realtime-ui-protocol.md`**.

---

## Contents (to complete)

- **Text simulation shell** — **Pause**, **Resume**, **Next Day**, speed controls; current tick id and run state in text.
- **Text simulation shell** — must also show current `simulation_date` and active currency context (at minimum `default_currency`).
- **Text intake status line** — show lifecycle phase in text:
  - `intake_window_opened`
  - `intake_countdown_paused` (with remaining time)
  - `intake_countdown_resumed` (countdown restarts from remaining time)
  - `intake_window_closed`
  - `user_inputs_processed`
  - `tick_committed`
- **Text command input panel** — submit control commands such as `CloseOnboarding(vendor_id, product_id)` / `OpenOnboarding(vendor_id, product_id)` and run-level controls such as `ReloadConfigAndRestartWorld` and `ShutdownServer`.
- **Text command log** — append `command_ack` events with accepted/rejected and target tick fields.
- **Text outcome log** — append `action_outcome` lines for onboarding/transact request/decision results.
- **Text snapshot block** — latest post-commit values for key pop/vendor/product counters and gates.
- **Text snapshot block** — must show:
  - `simulation_date`
  - `scenario_start_date_resolved`
  - `default_currency`
  - amount values with explicit currency label (not unlabeled numerics).
- **Numeric presentation rule** — render population/transaction counts as whole numbers (no fractional display); render amounts with configured decimal scale.
- **Text lifecycle banner** — show `world_restarting`, `world_restarted`, and `server_shutdown` transitions so stream disconnect is not surfaced as an unexplained error.
- **Text reconnect status** — display countdown to reconnect using server hint when `server_shutdown.reconnect_after_ms` is provided.
- **Debug window control (deferred)** — no interactive control required in current prototype UI until transaction-pipeline detailed history is implemented.

---

## TUI observability views (required for pipeline readiness)

Text-first presentation remains valid, but operator workflow must include focusable views (tabs or equivalent panes) that expose pipeline and accounting state.

### View A — World overview (comprehensive)

- Purpose: quickly assess world-wide health and per-agent/per-product status.
- Required blocks:
  - world summary totals (population, onboarded, transact requested/succeeded/failed),
  - vendor/agent roster with role labels (issuer, scheme, processor, other),
  - per-product status row (attached `pipeline_profile_id`, control gates, region, operational status),
  - simulation context (`tick_id`, `simulation_date`, mode, speed, default currency).
- Required interactions:
  - keyboard navigation across vendor -> product hierarchy,
  - expand/collapse for per-product detail,
  - quick jump to fee/transaction/ledger views for selected product.

### View B — Pipeline activity (fees / transactions / value transfers)

- Purpose: verify transactional flow and fee lifecycle in execution order.
- Required stream/log groups:
  - transaction intents (incoming/outgoing, source product, destination role/product),
  - fee accrual records (fee id, beneficiary role/product, amount components),
  - value transfer records (source/destination container refs, amount, value date),
  - invoice transaction events for deferred settlement (`next_month_day_plus_x` flows).
- Required columns/fields:
  - `tick_id`, `simulation_date`, `product_id`, `pipeline_profile_id`,
  - `trigger_id` / `intent_id` / `fee_id`,
  - `value_date_policy` + offset and resolved due date,
  - status (`accrued`, `invoiced`, `paid`, `netted`, `failed`).
- Required interactions:
  - filter by product, counterparty role, fee id, date range,
  - phase-order sort (intent -> fee -> posting -> transfer -> invoice/settlement),
  - drill from one row into linked downstream records.

### View C — Ledger and value-container reconciliation

- Purpose: confirm postings and actual value movement remain consistent.
- Required blocks:
  - ledger movement table (debit/credit entries by ledger ref/path),
  - value-container movement table (transfers by container ref/path),
  - reconciliation table (`ledger_ref` -> `container_ref`, expected vs actual deltas),
  - open settlement obligations (including invoice-backed fee payables/receivables).
- Required interactions:
  - compare-by-tick and compare-by-date modes,
  - highlight mismatches (`unmapped`, `unbalanced`, `pending_due`, `past_due`),
  - jump from mismatch line to contributing postings/transfers/events.

### Minimum navigation contract

- Views must be keyboard-switchable as primary sections (tabs or equivalent).
- Baseline required sections:
  - `World`
  - `Pipeline`
  - `Ledger`
  - existing controls/events panel(s) remain accessible from all sections.
- If viewport is constrained, section switching may become paged, but all three sections remain reachable.

This prototype UI remains text-first and does not require graphical chart rendering for this phase gate.

---

## TUI layout parameters (required)

- **Baseline target size:** `120x36` (columns x rows).
- **Status/header row:** fixed top row; must always remain visible.
- **Main area split (baseline):**
  - left control pane width: `26-32` columns,
  - right content pane: remaining width,
  - right pane vertical fill: event log receives flexible growth.
- **Recent Events panel sizing:**
  - minimum height: `8` rows,
  - preferred behavior: consume remaining free vertical space after status and essential summary blocks,
  - must be vertically scrollable.

### Responsive behavior by viewport

- `>=120x36`: two-pane layout (controls left, data/log right).
- `100x28` to `119x35`: keep two panes but collapse low-priority blocks and allow control-pane scrolling.
- `80x24` to `99x27`: single-column stacked layout; controls in grouped sections with scroll; event log below state block and still min `8` rows.
- `<80x24`: compact fallback mode with explicit warning; only critical controls and event log shown first, secondary blocks behind a focusable details view.

### Accessibility and operability constraints

- Control pane and event log are both independently focusable scroll regions.
- If any control group overflows, render visible scroll hints (`more above/below` or equivalent indicator).
- Tab order priority: run controls -> world controls -> command controls -> event log -> state/snapshot blocks.
- `ShutdownServer` must be keyboard reachable in all viewport classes.

### Tick timing display contract

- Status line countdown must reflect one tick budget:
  - intake phase countdown: remaining `intake_window_ms` slice (speed-adjusted),
  - processing phase countdown: remaining `tick_wall_clock_base_ms - intake_window_ms` slice (speed-adjusted).
- Do not display intake and full tick as additive independent waits.

### Date/currency display contract (prototype extension)

- Status/header row should include `simulation_date` beside tick id/run mode.
- Amount-bearing lines in event log and state blocks should render either:
  - `<amount> <currency>`, or
  - money-object equivalent formatting.
- Scalar-amount fallback behavior is intentionally not part of v2 foundations; realtime/API payloads must provide money-object currency context.
