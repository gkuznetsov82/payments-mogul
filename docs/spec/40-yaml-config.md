# YAML Configuration

**Status:** Draft

## Purpose

Config file layout, anchors/aliases patterns, mapping to Pydantic models, and **runtime simulation controls** (tick pacing, debug retention caps) that must be validated at load time.

**Cross-references:** balance defaults **`41-balance-knobs.md`**; architecture **`30-architecture.md`**; pipeline **`33-transaction-pipeline.md`**.

---

## Simulation and observability (required keys / sections)

These belong in **base** or **scenario** config (exact shape is implementation-defined but must be **validated**):

- **`tick_wall_clock_base_ms`** (or equivalent) — Total wall-clock **duration budget per tick** at **1x** speed (intake + processing within one budget). Tunable; default TBD after stress testing (**`30-architecture.md`**).
- **`debug_history_max_ticks`** — **Hard cap** on the user-selectable **rolling window** length for **debug** detailed history. Must reject or clamp invalid values (**`33-transaction-pipeline.md`**).
- Optional: **`debug_history_default_ticks`** — Suggested default when enabling debug mode.

For the current prototype phase, these `debug_history_*` keys are **validated/reserved** but runtime enforcement and UI/API controls are deferred until transaction-pipeline detailed data retention is implemented (**`33-transaction-pipeline.md`**).

Implementation may store **debug bucket history** in an embedded **database** path or URI (**`30-architecture.md`**); if so, surface **path**, **size limits**, and **cleanup** policy in config or ADR.

---

## Prototype v0 config contract (`prototype_vendor_pop_v1`)

This section locks a **minimal YAML contract** for the first runnable vertical slice. It is intentionally small and should be implemented before broader schema generalization.

### Top-level structure (required)

- `config_version` (`string`) - Schema version tag for compatibility checks.
- `scenario` (`object`) - Scenario identity and deterministic seed.
- `simulation` (`object`) - Tick and intake-window runtime controls.
- `world` (`object`) - Minimal agent/product/pop world definition.
- `control_defaults` (`object`) - Initial control-state gates for product actions.

### `scenario` section

- `id` (`string`) - Must be `prototype_vendor_pop_v1` for this slice.
- `seed` (`integer`) - Deterministic run seed.
- `market_id` (`string`) - Logical market label (single market in v0).

### `simulation` section

- `tick_wall_clock_base_ms` (`integer`, `>= 0`)
- `debug_history_max_ticks` (`integer`, `>= 1`)
- `debug_history_default_ticks` (`integer`, `>= 1`, `<= debug_history_max_ticks`)
- `intake_window_ms` (`integer`, `>= 1`) - Duration of command intake before close for a tick.
- `agent_method_order` (`array[string]`) - Must be `["Onboard", "Transact"]` in v0.
- `agent_iteration_policy` (`string`) - `stable_sorted_ids` for deterministic traversal.
- `count_rounding_mode` (`string`) - Rounding mode for discrete counts; v0 default/recommended: `half_up`.
- `amount_scale_dp` (`integer`, `>= 0`) - Decimal places for amount emission/persistence.
- `amount_rounding_mode` (`string`) - Rounding mode for amounts; v0 default/recommended: `half_up`.

### `world.vendor_agents[]` item

- `vendor_id` (`string`)
- `vendor_label` (`string`)
- `operational` (`boolean`)
- `products` (`array[object]`, min length 1)

`products[]` item:

- `product_id` (`string`)
- `product_label` (`string`)
- `product_class` (`string`) - For v0, allow `GenericProduct` or `RetailPayment-Card-Prepaid`.
- `onboarding_friction` (`object`, optional for non-friction class):
  - `min` (`float`, `0..1`)
  - `max` (`float`, `0..1`, `>= min`)
- `transaction_friction` (`object`, optional for non-friction class):
  - `min` (`float`, `0..1`)
  - `max` (`float`, `0..1`, `>= min`)

### `world.pops[]` item

- `pop_id` (`string`)
- `pop_label` (`string`)
- `pop_count` (`integer`, `> 0`)
- `daily_onboard` (`float`, `0..1`)
- `daily_active` (`float`, `0..1`)
- `daily_transact_count` (`number`, `>= 0`)
- `daily_transact_amount` (`number`, `>= 0`)
- `product_links` (`array[object]`, min length 1)

`product_links[]` item:

- `vendor_id` (`string`)
- `product_id` (`string`)
- `known` (`boolean`)
- `onboarded_count` (`integer`, `>= 0`, `<= pop_count`)

`daily_transact_count` and `daily_transact_amount` may remain non-integer rates/intensities in v0, but all derived **transaction counts** and **population counts** must be rounded to integers using `simulation.count_rounding_mode` before becoming externally visible outputs (events, snapshots, persistence).

`intake_window_ms` must be `<= tick_wall_clock_base_ms` for non-overrun pacing semantics; intake is a subset of total tick time budget, never an additive second budget.

### `control_defaults` section

- `accepting_onboard` (`boolean`)
- `accepting_transact` (`boolean`)

These gates seed initial product control state before runtime control commands (`Open/CloseOnboarding`, `Open/CloseTransacting`) are applied in `tick_user_inputs_processed` (**`30-architecture.md`**, **`51-api-contract.md`**).

### v0 example file

```yaml
config_version: "v0"

scenario:
  id: "prototype_vendor_pop_v1"
  seed: 424242
  market_id: "market_local_v0"

simulation:
  tick_wall_clock_base_ms: 1000
  debug_history_max_ticks: 30
  debug_history_default_ticks: 7
  intake_window_ms: 500
  agent_method_order: ["Onboard", "Transact"]
  agent_iteration_policy: "stable_sorted_ids"
  count_rounding_mode: "half_up"
  amount_scale_dp: 2
  amount_rounding_mode: "half_up"

world:
  vendor_agents:
    - vendor_id: "vendor_alpha"
      vendor_label: "Vendor Alpha"
      operational: true
      products:
        - product_id: "prod_prepaid_alpha"
          product_label: "Alpha Prepaid Card"
          product_class: "RetailPayment-Card-Prepaid"
          onboarding_friction:
            min: 0.05
            max: 0.10
          transaction_friction:
            min: 0.02
            max: 0.08

  pops:
    - pop_id: "pop_main"
      pop_label: "Main Pop Segment"
      pop_count: 10000
      daily_onboard: 0.03
      daily_active: 0.40
      daily_transact_count: 1.2
      daily_transact_amount: 22.5
      product_links:
        - vendor_id: "vendor_alpha"
          product_id: "prod_prepaid_alpha"
          known: true
          onboarded_count: 0

control_defaults:
  accepting_onboard: true
  accepting_transact: true
```

### Deferred beyond v0

- Multi-market and ROW topologies in config.
- Rich institution catalogs beyond the single-vendor slice.
- Deep override layering and anchor/alias conventions.
- Full command-auth configuration for Person/PiC authority.

---

## Contents (to complete)

- Directory structure (e.g., scenarios/, agents/, rails/)
- Anchor/alias conventions for portfolios
- Override order (scenario vs base)
- Validation errors: path reporting for authors
