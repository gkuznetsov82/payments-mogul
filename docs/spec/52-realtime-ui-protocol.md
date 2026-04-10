# Realtime UI Protocol

**Status:** Draft

## Purpose

Streaming contract between engine and dashboard: snapshots, deltas, throttling, and **simulation control** events (pause, speed, debug settings).

**Cross-references:** API control plane **`51-api-contract.md`**; tick and pause semantics **`30-architecture.md`**; player UX **`12-ui-ux-spec.md`**.

---

## Control messages (outline)

- **Pause requested** — Server completes **current tick**, then emits **paused** with tick id and snapshot boundary.
- **Resume** — Client requests **continuous** play; **next tick** begins after any configured **wall-clock wait** for current speed (**`30-architecture.md`**).
- **Next day** — Client requests **single** tick while **paused**; server runs **one** tick, emits **paused** again with updated tick id (**no** inter-tick speed wait after the step—**`30-architecture.md`**).
- **Set speed** — **1×**, **2×**, **3×** (or multiplier); affects **wait only** between ticks in **continuous** mode, not simulation math.
- **Set debug rolling window** — **N** ticks, clamped to config max; may trigger **storage** resize or prune messages.
- **Decision submitted** — Acknowledge; **effective_tick** = next tick after current boundary (**`10-player-journey.md`**, **`31-agents.md`**).

---

## Contents (to complete)

- Channel(s): WebSocket vs SSE
- Message types: full snapshot vs patch (including post-tick snapshots)
- Throttling / coalescing rules
- Client reconnection and resume (must recover tick id, paused state, speed, debug **N**)
