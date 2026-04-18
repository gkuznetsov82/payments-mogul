# Implementation Roadmap

**Status:** Draft

## Purpose

Phased delivery for Claude Code / teams: vertical slices and explicit "done" criteria.

## Contents (to complete)

- Phase 0: repo, CI, stub engine + API + UI shell; **tick = one simulated day**; **normal** vs **debug** retention (**`30-architecture.md`**, **`33-transaction-pipeline.md`**); **pause** at tick boundary; **Resume** vs **Next Day** (single-step); **intake-window command processing semantics**; **1×/2×/3×** pacing for **continuous** play vs configurable base interval; **queryable** store for debug rolling window (**`40-yaml-config.md`** cap)
- Phase 1: vertical slice (one scenario, one loop end-to-end)
- Phase 2: full agent set + regulation + charts
- Phase 3: polish, performance, content pass
- Exit criteria per phase

---

## Phase 1 vertical slice gate (prototype timing model)

Phase 1 is complete when all items below are true for `prototype_vendor_pop_v1`:

- Engine runs explicit tick phases in order:
  - intake window open
  - intake window closed
  - user inputs processed
  - simulation run
  - tick committed
- Simulation loop calls `Onboard()` and `Transact()` on all agent classes in fixed deterministic order each tick.
- A control command submitted before intake close for tick `T` (for example `CloseOnboarding`) changes outcomes in tick `T`.
- A control command submitted after intake close for tick `T` applies in tick `T+1`.
- Realtime emits `tick_user_inputs_processed` before `tick_committed` for each tick.
- Text UI can display lifecycle phases, command acknowledgements, and resulting action outcomes without charts.
- Determinism holds for same seed and same ordered command stream.

Future authority tightening (Person/PiC command scoping) is planned but not required to pass this phase gate.
