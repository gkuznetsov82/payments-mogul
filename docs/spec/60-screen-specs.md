# Screen Specifications

**Status:** Draft

## Purpose

Per-screen UI blueprint: components, data bindings, states.

**Cross-references:** simulation controls and control panel **`12-ui-ux-spec.md`**; realtime **`52-realtime-ui-protocol.md`**.

---

## Contents (to complete)

- **Text simulation shell** — **Pause**, **Resume**, **Next Day**, speed controls; current tick id and run state in text.
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
- **Numeric presentation rule** — render population/transaction counts as whole numbers (no fractional display); render amounts with configured decimal scale.
- **Text lifecycle banner** — show `world_restarting`, `world_restarted`, and `server_shutdown` transitions so stream disconnect is not surfaced as an unexplained error.
- **Text reconnect status** — display countdown to reconnect using server hint when `server_shutdown.reconnect_after_ms` is provided.
- **Debug window control (deferred)** — no interactive control required in current prototype UI until transaction-pipeline detailed history is implemented.

This prototype UI is intentionally text-first and non-visual; no chart/dashboard requirements are needed for the phase gate.

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
