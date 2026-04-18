# Validation Rules (Pydantic)

**Status:** Draft

## Purpose

Sanity checks: hard errors vs warnings; codes and UI surfacing.

---

## Prototype v0 validation set (required)

These validations are the minimum required to load and run `prototype_vendor_pop_v1` from YAML (**`40-yaml-config.md`**).

### Hard errors (must block run start)

- `scenario.id` must equal `prototype_vendor_pop_v1` for this profile.
- `simulation.agent_method_order` must be exactly `["Onboard", "Transact"]`.
- `simulation.debug_history_default_ticks <= simulation.debug_history_max_ticks`.
- At least one `world.vendor_agents[]` and at least one `world.pops[]` must exist.
- Every `product_links[]` reference must resolve to an existing `(vendor_id, product_id)` pair.
- `pop_count > 0`.
- `0 <= daily_onboard <= 1`.
- `0 <= daily_active <= 1`.
- `daily_transact_count >= 0`.
- `daily_transact_amount >= 0`.
- For each link, `0 <= onboarded_count <= pop_count`.
- If friction ranges are provided:
  - `0 <= min <= 1`
  - `0 <= max <= 1`
  - `min <= max`

### Warnings (allow run start)

- `intake_window_ms` very low (for example `< 50`) may make manual command timing difficult.
- `tick_wall_clock_base_ms == 0` disables pacing and may reduce observability in text UI.
- `known: false` on all links for a pop means no onboarding/transact requests will ever be generated.

### Suggested stable error codes (v0)

- `E_SCENARIO_ID_UNSUPPORTED`
- `E_METHOD_ORDER_INVALID`
- `E_DEBUG_WINDOW_INVALID`
- `E_WORLD_MISSING_VENDOR`
- `E_WORLD_MISSING_POP`
- `E_LINK_TARGET_MISSING`
- `E_POP_COUNT_INVALID`
- `E_RATE_OUT_OF_RANGE`
- `E_TXN_PARAM_INVALID`
- `E_ONBOARDED_COUNT_INVALID`
- `E_FRICTION_RANGE_INVALID`

## Contents (to complete)

- Constraint catalog (e.g., interchange vs MDR)
- Error taxonomy and stable codes
- Warning vs block policy
- Cross-field and cross-entity validation
