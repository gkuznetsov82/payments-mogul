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
- **Text command input panel** — split controls into:
  - world controls: `ReloadConfigAndRestartWorld`, `ShutdownServer`,
  - agent controls: onboarding/transacting commands with explicit agent/product target selection.
- **Text command log** — append `command_ack` events with accepted/rejected and target tick fields.
- **Text outcome log** — append `action_outcome` lines for onboarding/transact request/decision results.
- **Text log copyability requirement** — operator-visible logs (command, lifecycle, pipeline, books/accounts movement logs) must be selectable and copyable with standard keyboard flow (including Ctrl+C) so errors can be extracted verbatim.
- **Text log resilience requirement** — rendering of command acknowledgements and lifecycle lines must not raise UI type/runtime errors; log surfaces must keep accepting new lines after command events.
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
  - original incoming intents and routed derivatives shown together with shared correlation key,
  - fee accrual records (fee id, beneficiary role/product, amount components),
  - settlement-demand accrual records (creditor/debtor role, amount, category),
  - value transfer records (source/destination container refs, amount, value date).
- Required columns/fields:
  - `tick_id`, `simulation_date`, `product_id`, `pipeline_profile_id`,
  - `trigger_id` / `intent_id` / `root_intent_id` / `fee_id`,
  - `value_date_policy` + offset and resolved due date,
  - status (`accrued`, `executed`, `failed`).
- Required interactions:
  - filter by product, counterparty role, fee id, date range,
  - phase-order sort (intent -> fee -> posting -> transfer),
  - drill from one row into linked downstream records,
  - selectable log row with detail panel (full event payload) so row text stays compact.

### View C — Books (ledger hierarchy)

- Purpose: accounting-first view of hierarchical ledger balances and movements.
- Required blocks:
  - hierarchical books tree (group -> product -> sub-account),
  - ledger movement table (debit/credit entries by ledger ref/path),
  - aggregate roll-ups converted to default currency for display.
- Required interactions:
  - compare-by-tick and compare-by-date modes,
  - expand/collapse by hierarchy level,
  - jump from aggregate line to contributing posting rows,
  - selectable movement row with detail panel (full posting payload).

### View D — Accounts (value containers)

- Purpose: operational-funds view of container balances and value movement.
- Required blocks:
  - value-container hierarchy by owner/product/counterparty where applicable,
  - value-container movement table (transfers by container ref/path),
  - aggregate roll-ups converted to default currency for display.
- Required interactions:
  - compare-by-tick and compare-by-date modes,
  - highlight mismatches (`unmapped`, `unbalanced`),
  - jump from account line to contributing transfer rows,
  - selectable movement row with detail panel (full transfer payload including source/destination owner context).

### View E — Obligations (invoices and settlement demands)

- Purpose: operational management of payables/receivables and settlement-demand lifecycle.
- Required controls:
  - agent selector dropdown (required scope selector for this view),
  - role-side switch (`creditor` | `debtor`) for selected agent perspective,
  - queue switch (`issued` | `received`) for selected role-side.
- Required blocks:
  - invoice list (category-aware: `fee` vs `settlement_demand`) with lifecycle dates (`accrual_date`, `invoice_issue_date`, `payment_due_date`),
  - settlement-demand list with same date semantics and status/residual fields.
- Required actions (entity-bound):
  - `pay_now`, `hold`, `release_hold` on selected `invoice_id` / `settlement_demand_id`.
- Required interaction behavior:
  - selecting an agent and switching creditor/debtor perspectives must re-scope both invoice and settlement-demand lists,
  - `issued` and `received` lists must be available from both perspectives where data exists,
  - list must be vertically scrollable with consistent styling semantics used in other movement/event views (status color tags, selected-row highlight),
  - if no actionable entity is selected, obligation action controls must be visibly disabled.

### View F — Messages

- Purpose: operator attention queue for informational/warning/critical system messages.
- Required blocks:
  - message list with `message_id`, `severity`, `message_type`, `agent_id`, timestamp, and correlation fields (`invoice_id` / `settlement_demand_id` when present),
  - message detail panel for selected item.
- Required filters:
  - severity,
  - agent,
  - unread/all.
- Required interactions:
  - mark message as read,
  - drill-through from correlated message to Obligations view with referenced entity pre-selected.
- Action boundary:
  - payment/control actions must not execute from message rows,
  - Messages view is informational/navigation-only; actions remain entity-bound in Obligations.
- Control behavior:
  - message controls are selection-scoped (operate only on selected `message_id`),
  - controls requiring correlated entity must be disabled when selected message has no `invoice_id`/`settlement_demand_id`.

### Minimum navigation contract

- Views must be keyboard-switchable as primary sections (tabs or equivalent).
- Baseline required sections:
  - `Run` (timing controls always visible in this section/header region)
  - `World`
  - `Pipeline`
  - `Books`
  - `Accounts`
  - `Obligations` (agent-scoped invoices and settlement demands; issued/received, creditor/debtor views)
  - `Messages` (operator attention queue with correlation drill-through)
  - `Logs` (command/outcome/event stream; not required to be always visible).
- If viewport is constrained, section switching may become paged, but all required sections remain reachable.

This prototype UI remains text-first and does not require graphical chart rendering for this phase gate.

---

## TUI layout parameters (required)

- **Baseline target size:** `120x36` (columns x rows).
- **Status/header row:** fixed top row; must always remain visible.
- **Main area split (baseline):**
  - top run-controls strip remains visible (Pause/Resume/Next Day/speed + tick/date),
  - active section content consumes remaining viewport,
  - logs are hosted in dedicated `Logs` section/tab.
- **Logs section sizing:**
  - minimum visible event list height: `12` rows,
  - must be vertically scrollable.
- **Structured detail pane requirement:**
  - Logs/Pipeline/Books/Accounts event lists must support selected-row detail rendering in a dedicated pane/region.
  - Compact row text should prioritize scanability; full payload should be available only in the detail pane.

### Responsive behavior by viewport

- `>=120x36`: tabbed/sectioned layout with always-visible run-controls strip and full section content.
- `100x28` to `119x35`: keep sectioned layout; collapse low-priority blocks and allow content scrolling.
- `80x24` to `99x27`: compact sectioned layout; prioritize run controls and current section data with explicit paging hints.
- `<80x24`: compact fallback mode with explicit warning; run controls remain visible and sections become paged.

### Accessibility and operability constraints

- Active section content and logs view are independently focusable scroll regions.
- If any control group overflows, render visible scroll hints (`more above/below` or equivalent indicator).
- Tab order priority: run controls -> section switcher -> active section controls -> active section content.
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
