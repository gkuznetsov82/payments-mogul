# UI / UX Specification

**Status:** Draft

## Purpose

Information architecture and interaction design for the industrial / command-center experience (no "plastic" UI).

**Cross-references:** player loop, pause, debug mode **`10-player-journey.md`**; simulation pacing **`30-architecture.md`**; control plane **`52-realtime-ui-protocol.md`**.

---

## Simulation controls (required)

- **Pause** — Clearly visible control. If pressed while intake for current tick is open, UI enters **pause pending** and the intake countdown is frozen at remaining time; simulation pauses once current tick processing commits unless user resumes before intake closes. If pressed after intake close, behavior remains "pause after current tick commit" (**`30-architecture.md`**, **`52-realtime-ui-protocol.md`**).
- **Resume** (or **Play**) — From **paused**, runs simulation **continuously**: each completed tick is followed by configured wall-clock wait, then next tick, until **Pause** (**`30-architecture.md`**). If pressed during **pause pending** with frozen intake countdown, **Resume** unfreezes and continues same tick intake from remaining time (must not be ignored). **Speed** (**1×**, **2×**, **3×**) applies only to this **continuous** mode.
- **Next Day** — While **paused**, advances **exactly one tick** (one simulated day), then **returns to paused**. Does **not** start continuous play; **speed** multipliers do **not** apply between **Next Day** presses (**`30-architecture.md`**). Typically **enabled only when paused** (disabled or no-op while continuous play is active—pick one in implementation and document in ADR if needed).
- **Speed** — **1×**, **2×**, **3×** (or equivalent labels) for **continuous** advance after **Resume**; maps to wall-clock pacing **between** ticks; base interval is **configurable** (**`30-architecture.md`**).
- **Debug rolling window** — Runtime control is **deferred** until transaction pipeline provides compactable per-bucket history; current prototype keeps `debug_history_*` as reserved config only (**`33-transaction-pipeline.md`**, **`40-yaml-config.md`**).
- **Reload config + restart world** — Provide explicit control to request server config re-read and world restart; UI should show in-progress restart state and replace displayed world state only after confirmed restart completion event/snapshot.
- **Shutdown server** — Provide explicit control to request graceful server shutdown; UI should show shutdown-pending/offline state after `server_shutdown` event and follow reconnect policy when `will_restart=true`.

---

## Control panel (entity decisions)

- While **paused** (or as allowed between ticks), surface a **control panel** for each institution (or asset) the player may steer under the **control graph** (**`31-agents.md`**). Examples of decision families (exact v1 scope is scenario-dependent): **pricing**, **cashback / rewards**, **risk policy**, **marketing campaigns**, **termination or exclusion of user/merchant categories**, **re-routing payment rails**.
- **Feedback:** Show that submitted changes apply **starting the next tick** after the user **resumes** continuous play or presses **Next Day** (whichever advances the clock first) (**`10-player-journey.md`**).

---

## Realtime robustness (required)

- When receiving `server_shutdown` SSE event, show a non-error notice ("Server restarting/shutting down"), then transition to reconnect mode.
- Distinguish expected stream close (preceded by `server_shutdown`) from unexpected transport failure (no shutdown event).
- Reconnect strategy should follow server-provided `reconnect_after_ms` hint when present; otherwise use bounded exponential backoff.

---

## TUI scaling and accessibility (required)

- TUI must target a **baseline viewport** of at least `120x36` (columns x rows) without clipping critical controls.
- For smaller terminals, controls must remain reachable by one of:
  - scrollable control pane, or
  - responsive reflow (for example, two-column controls -> single-column groups), or
  - paged sections with explicit next/prev focusable controls.
- No primary run control (**Resume / Pause / Next Day / Reload / Shutdown**) may render outside visible bounds with no keyboard-accessible path.
- Layout must reserve the largest flexible area for **Recent Events**; this panel should expand with available height and never stay fixed to a tiny static height when vertical space exists.
- When space is constrained, reduce/stack secondary informational blocks before shrinking event log below usable size.

### Keyboard and focus behavior

- Every actionable control must be operable without mouse.
- Visible focus indicator is required for focused button/list/input and for the active scrollable region.
- Scrolling must support keyboard affordances (arrow keys / page keys or documented equivalents).
- Provide a quick-focus shortcut for event log and for control pane.

### Minimum compact-mode requirements

- At or above `100x28`: full controls and event log available with at most one scrollable panel.
- Below `100x28`: switch to compact layout with grouped sections and explicit scrolling/paging hints.
- Below `80x24`: show unsupported-size warning plus fallback navigation that still exposes run controls and server lifecycle controls.

### Tick countdown interpretation (required)

- UI countdown logic must follow single-budget timing: `tick_wall_clock_base_ms` is total tick length at 1x, and `intake_window_ms` is the intake slice inside that total.
- During intake-open: show time remaining to intake close.
- After intake-close: show remaining processing time budget for the same tick (or overrun state if exceeded), not a second full-tick countdown.

---

## Contents (to complete)

- Screen map and navigation beyond simulation shell
- Density, hierarchy, expert-tool patterns
- Accessibility and keyboard paths
- Relationship to "Victoria 3 industrial" metaphor (concrete UI motifs)
- Debug **query** / drill-down UX against persisted bucket history (tables, filters)
