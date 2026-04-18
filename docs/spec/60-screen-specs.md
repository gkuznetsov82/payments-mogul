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
  - `intake_window_closed`
  - `user_inputs_processed`
  - `tick_committed`
- **Text command input panel** — submit control commands such as `CloseOnboarding(vendor_id, product_id)` / `OpenOnboarding(vendor_id, product_id)`.
- **Text command log** — append `command_ack` events with accepted/rejected and target tick fields.
- **Text outcome log** — append `action_outcome` lines for onboarding/transact request/decision results.
- **Text snapshot block** — latest post-commit values for key pop/vendor/product counters and gates.

This prototype UI is intentionally text-first and non-visual; no chart/dashboard requirements are needed for the phase gate.
