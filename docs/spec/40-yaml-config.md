# YAML Configuration

**Status:** Draft
**Binding level:** Mixed (`v0/v1` runtime-binding core, `v2_foundations` spec-only extensions, `v3_runtime` runtime-binding for promoted pipeline scope)

## Purpose

Config file layout, anchors/aliases patterns, mapping to Pydantic models, and **runtime simulation controls** (tick pacing, debug retention caps) that must be validated at load time.

This chapter also defines the **Prototype v2 foundations schema surface** for Money, Calendar, and FX as a **spec-only deliverable**. Runtime software integration for these v2 fields is intentionally deferred.

**Cross-references:** balance defaults **`41-balance-knobs.md`**; architecture **`30-architecture.md`**; pipeline **`33-transaction-pipeline.md`**.

---

## Versioning and promotion policy

- `config_version` remains the top-level compatibility gate for overall config shape.
- Introduce `pipeline_schema_version` under the pipeline section when pipeline config contracts are used.
- Allowed pipeline schema values:
  - `v2_foundations` (spec-only, non-runtime-binding)
  - `v3_runtime` (runtime-binding)
- Promotion of pipeline fields from reserved/spec-only to runtime-binding requires aligned updates in:
  - **`33-transaction-pipeline.md`** (behavior contract),
  - **`30-architecture.md`** (determinism/ordering contract),
  - this chapter (YAML contract and validation expectations).
- Promotion note: transaction pipeline runtime promotion is approved in **ADR-0002** for configs declaring `pipeline_schema_version: v3_runtime`.

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

## Prototype v2 foundations extension (+ v3 pipeline promotion)

This section defines config contracts and YAML examples for v2 foundations and promoted v3 pipeline runtime contracts.

- Deliverables include schema contracts and YAML examples.
- Runtime implementation remains out of scope for v2 foundations fields unless explicitly promoted.
- Transaction pipeline contracts are runtime-binding when `pipeline_schema_version: v3_runtime`.

### Additive top-level structure for v2

The following keys are additive to the current shape:

- `scenario.start_date` (`string`) - either `"today"` or `YYYY-MM-DD`.
- `money` (`object`) - money typing and rounding defaults.
- `currency_catalog` (`object`) - ISO 4217-backed catalog source and overrides.
- `fx` (`object`) - first-class FX sources and selection policy.
- `calendars` (`array[object]`) - named calendar objects.
- `regions` (`array[object]`) - named regions assigned to calendars.
- `pipeline` (`object`) - transaction pipeline profile registry (spec-only in v2).

### `scenario.start_date` semantics

- `"today"` resolves to server-local current date at run start and is then fixed for that run.
- Explicit date accepts past or future `YYYY-MM-DD`.
- After start date is resolved, tick-date mapping is deterministic (`date(T) = start_date + T days`).

### `money` section

- `amount_rounding_mode` (`string`) - default deterministic mode; recommended `half_up`.
- `default_currency` (`string`, ISO 4217 alpha-3) - default for scenarios that omit explicit currency at authoring time.
- `enforce_money_object` (`boolean`) - must be `true` for v2 foundations; amount-bearing domain objects must carry `{amount, currency}`.
- Transitional scalar-amount compatibility is intentionally out of scope until Production v1.

### `currency_catalog` section

- `source_type` (`string`) - `local_file` only in v2.
- `local_file.path` (`string`) - path to a project file containing currency definitions.
- `local_file.format` (`string`) - `yaml` or `json`.
- `allow_local_overrides` (`boolean`) - allows additive/override entries for world changes.

#### Full ISO 4217 ingestion plan (spec-level)

- The full current and historical ISO list is expected to be generated from SIX List One and List Three artifacts.
- Delivery mechanism is an explicit sync script (for example `tools/sync_iso4217.py`) that:
  - downloads/parses authoritative SIX files,
  - normalizes to project schema,
  - writes deterministic output under `configs/reference/`,
  - is run manually or in CI as an explicit update step.

`currency_catalog` entries should include:

- `code` (ISO 4217 alpha-3)
- `numeric_code`
- `name`
- `minor_unit` (0..3 in common practice; historical edge values allowed if source data requires)
- Optional `active_from` / `active_to`

### `fx` section

#### First-class sources

- `local_file` source:
  - `enabled` (`boolean`)
  - `path` (`string`)
  - `format` (`string`, `yaml|json|csv`)
- `frankfurter_sources` (`array[object]`) for multiple configured endpoints:
  - `source_id` (`string`, unique; e.g. `frankfurter_ecb`, `frankfurter_usfrb`)
  - `enabled` (`boolean`)
  - `base_url` (`string`, default `https://api.frankfurter.dev/v2`)
  - `base_country` (`string`, ISO 3166-1 alpha-2)
  - `country_provider_map` (`object`) - explicit map of country code to provider code (central-bank/source selection)
  - `default_provider` (`string`, optional fallback when map lookup misses)

#### Selection policy

- `source_policy` (`string`) one of:
  - `local_only`
  - `frankfurter_only`
  - `local_override_then_frankfurter`
- `source_refs` (`array[string]`, optional) - constrained list of `frankfurter_sources[].source_id` eligible for this scenario/context.
- Missing `country_provider_map` entry behavior must be explicit:
  - either validation error, or
  - use configured `default_provider`
- No implicit silent fallback is allowed.

#### Normalized FX record shape

- `date` (`YYYY-MM-DD`, UTC day)
- `base_currency` (ISO 4217 alpha-3)
- `quote_currency` (ISO 4217 alpha-3)
- `rate` (decimal)
- `provider_id` (string)
- `retrieved_at` (UTC timestamp)

### `calendars` section

Each calendar object:

- `calendar_id` (`string`, unique)
- `weekend_profile` (`string`) - `sat_sun` (default) or `fri_sat` (initial allowed set for v2)
- `non_working_overrides` (`array[date]`, optional) - additive specific dates
- `holiday_sources` (`array[object]`) - first-class source list:
  - `local_file`:
    - `enabled` (`boolean`)
    - `path` (`string`)
  - `nager_date`:
    - `enabled` (`boolean`)
    - `base_url` (`string`, default `https://date.nager.at/api/v3`)
    - `country_code` (`string`, ISO 3166-1 alpha-2, optional query parameter only for Nager lookup)
    - `types` (`array[string]`, optional filter such as `Public`, `Bank`)
- `holiday_source_policy` (`string`) one of:
  - `local_only`
  - `nager_only`
  - `local_override_then_nager`

### `regions` section

Each region object:

- `region_id` (`string`, unique)
- `calendar_id` (`string`) - required reference to `calendars[].calendar_id`
- Optional `label` (`string`)

`regions` do not define working days directly; working-day rules are owned by the assigned calendar object.

### `world` region assignment (v2 extension)

World entities can be mapped to regions to select the calendar context used by default:

- `world.vendor_agents[].region_id` (`string`, required in region-aware scenarios)
- `world.pops[].region_id` (`string`, optional; if omitted, scenario default region applies)

These fields reference `regions[].region_id`.

### Agent calendar inheritance (config contract)

- Agents spawned in a region inherit the region's assigned calendar by default.
- An agent may override inherited calendar assignment via explicit config reference.

### `pipeline` section (v2 foundations + v3 runtime)

This section formalizes transaction-pipeline config contracts. Binding depends on `pipeline_schema_version`.

- `pipeline_schema_version` (`string`) - `v2_foundations` or `v3_runtime`.
- `pipeline_profiles` (`array[object]`) - reusable per-product pipeline definitions:
  - `pipeline_profile_id` (`string`, unique)
  - `transaction_intents` (`array[object]`) - incoming intent contract definitions:
  - `intent_id` (`string`, unique)
  - `destinations` (`array[object]`)
    - `destination_role` (`string`) - symbolic role resolved at product instance level (or `local`)
    - `outgoing_intent_id` (`string`)
    - `value_date_policy` (`string`) - one of:
      - `same_day`
      - `next_day_plus_x`
      - `next_working_day_plus_x`
      - `next_month_day_plus_x`
    - `value_date_offset_days` (`integer`, `>= 0`) - required when `value_date_policy` contains `plus_x`
    - `amount_basis` (`string`) - reference token (for example `transaction_intent_amount`)
    - `currency_mode` (`string`) - `inherit`, `fixed_currency`, or `fx_convert`
  - `ledger_construction` (`array[object]`) - posting ledger construction contracts:
  - `ledger_ref` (`string`, unique) - symbolic reference used by posting rules
  - `path_pattern` (`string`) - ledger path template that may include role placeholders, e.g. `{product_role}` / `{counterparty_role}`
  - optional `normal_side` (`string`) - `debit` or `credit`
  - `posting_rules` (`array[object]`) - dual-entry posting generation contracts:
  - `trigger_id` (`string`) - transaction intent ID or fee ID
  - `source_ledger_ref` (`string`) - reference to `ledger_construction[].ledger_ref`
  - `destination_ledger_ref` (`string`) - reference to `ledger_construction[].ledger_ref`
  - `amount_basis` (`string`)
  - `value_date_policy` (`string`) - same allowed set as above
  - `value_date_offset_days` (`integer`, `>= 0`) - required when `value_date_policy` contains `plus_x`
  - `value_container_construction` (`array[object]`) - value-container construction contracts:
  - `container_ref` (`string`, unique) - symbolic reference used by asset-transfer rules
  - `path_pattern` (`string`) - container path template that may include role placeholders
  - `asset_transfer_rules` (`array[object]`) - value-container movement contracts:
  - `trigger_id` (`string`) - transaction intent ID or fee ID
  - `source_container_ref` (`string`) - reference to `value_container_construction[].container_ref`
  - `destination_container_ref` (`string`) - reference to `value_container_construction[].container_ref`
  - `amount_basis` (`string`)
  - `value_date_policy` (`string`) - same allowed set as above
  - `value_date_offset_days` (`integer`, `>= 0`) - required when `value_date_policy` contains `plus_x`
  - `fee_sequences` (`array[object]`) - ordered fee execution:
  - `sequence_id` (`string`)
  - `fees` (`array[object]`)
    - `fee_id` (`string`)
    - `trigger_ids` (`array[string]`) - transaction intent IDs and/or prior fee IDs
    - `beneficiary_role` (`string`) - role of fee beneficiary agent
    - optional `beneficiary_product_role` (`string`) - role of beneficiary product when beneficiary has more than one product and target product must be unambiguous
    - `settlement_value_date_policy` (`string`) - same allowed set as `value_date_policy`
    - `settlement_value_date_offset_days` (`integer`, `>= 0`) - required when settlement policy contains `plus_x`
    - `settlement_trigger_event` (`string`) - `invoice_transaction_event` for deferred fee collection
    - optional `filter` (`object`) - future transaction-detail selectors
    - one or more amount drivers:
      - `count_cost`
      - `amount_percentage`
      - `formula_ref`
  - `ledger_value_container_map` (`array[object]`) - reconciliation mapping:
  - `ledger_ref` (`string`) - reference to `ledger_construction[].ledger_ref`
  - `container_ref` (`string`) - reference to `value_container_construction[].container_ref`
  - `mapping_mode` (`string`) - `one_to_one` or `aggregate`

#### Intent of `beneficiary_product_role`

- `beneficiary_role` identifies **which agent** receives the fee economics.
- `beneficiary_product_role` identifies **which product of that beneficiary agent** owns the fee contract and downstream settlement behavior.
- Use `beneficiary_product_role` when:
  - beneficiary agent has multiple products, or
  - product-specific fee contracts differ within the same beneficiary agent.
- It may be omitted only when beneficiary product is unambiguous from role bindings.

#### Product-level role resolution (required for pipeline role references)

Role resolution is owned by the product instance so the same pipeline profile can be reused across multiple product instances.

- `world.vendor_agents[].products[]` binds pipeline execution with:
  - `pipeline_profile_id` (`string`) - required reference to `pipeline.pipeline_profiles[].pipeline_profile_id`
  - `pipeline_role_bindings` (`object`) defines concrete role mapping:
  - `entity_roles` (`object`)
    - key = role name (for example `upstream_processor`, `issuing_product`)
    - value = selector object, one of:
      - `{ agent_id: "<id>" }`
      - `{ product_id: "<id>" }`
      - `{ local: true }`
  - optional `default_product_role` (`string`) - role to use when a path pattern requires product role and no explicit override is provided

All role placeholders in pipeline path patterns and routing destinations must be resolvable from this mapping.

#### Inter-product `Transact()` handoff contract

When a transaction intent routes from Product A to Product B:

- Product B receives `Transact()` with:
  - `client_id` = upstream originating `vendor_id`,
  - remaining parameters carrying routed transaction details (at minimum `intent_id`, amount/currency context, and value-date policy/offset).
- Product B then executes its own attached `pipeline_profile_id` from that handoff context.

#### Value-date offset rules (required)

- If `value_date_policy` or `settlement_value_date_policy` contains `plus_x`, corresponding offset field is mandatory:
  - `value_date_offset_days`
  - `settlement_value_date_offset_days`
- For `same_day`, offset should be omitted or set to `0`.
- For this iteration's sink-fee contracts (scheme and processor), settlement policy is `next_month_day_plus_x` with offset `5`.
- For sink-fee settlement in this iteration, `settlement_trigger_event` must be `invoice_transaction_event` and collection uses direct payment after invoice issuance.

#### Pipeline binding by schema version

| `pipeline_schema_version` | Binding | Expected use |
|---|---|---|
| `v2_foundations` | Spec-only | Authoring, review, and fixture documentation |
| `v3_runtime` | Runtime-binding | Executable behavior |

### v3 runtime schema example (illustrative)

```yaml
config_version: "v0"

scenario:
  id: "prototype_vendor_pop_v1"
  seed: 424242
  market_id: "market_local_v0"
  start_date: "today" # or "2026-01-01"

money:
  amount_rounding_mode: "half_up"
  default_currency: "USD"
  enforce_money_object: true

currency_catalog:
  source_type: "local_file"
  local_file:
    path: "configs/reference/currency_catalog_iso4217_sample.yaml"
    format: "yaml"
  allow_local_overrides: true

fx:
  source_policy: "local_override_then_frankfurter"
  sources:
    local_file:
      enabled: true
      path: "configs/reference/fx_rates_local_example.yaml"
      format: "yaml"
  frankfurter_sources:
    - source_id: "frankfurter_ecb"
      enabled: true
      base_url: "https://api.frankfurter.dev/v2"
      base_country: "DE"
      country_provider_map:
        DE: "ECB"
      default_provider: "ECB"
    - source_id: "frankfurter_usfrb"
      enabled: true
      base_url: "https://api.frankfurter.dev/v2"
      base_country: "US"
      country_provider_map:
        US: "FED"
      default_provider: "FED"
  source_refs: ["frankfurter_ecb", "frankfurter_usfrb"]

calendars:
  - calendar_id: "cal_global_default"
    weekend_profile: "sat_sun"
    non_working_overrides:
      - "2026-12-31"
    holiday_source_policy: "local_override_then_nager"
    holiday_sources:
      local_file:
        enabled: true
        path: "configs/reference/calendar_local_example.yaml"
      nager_date:
        enabled: true
        base_url: "https://date.nager.at/api/v3"
        country_code: "US"
        types: ["Public", "Bank"]

regions:
  - region_id: "region_main"
    calendar_id: "cal_global_default"
    label: "Main Region"

pipeline:
  pipeline_schema_version: "v3_runtime"
  pipeline_profiles:
    - pipeline_profile_id: "prepaid_card_pipeline"
      transaction_intents:
        - intent_id: "Transact-Purchase-Clearing"
          destinations:
            - destination_role: "upstream_processor"
              outgoing_intent_id: "Transact-Purchase-Clearing-Upstream"
              value_date_policy: "same_day"
              value_date_offset_days: 0
              amount_basis: "transaction_intent_amount"
              currency_mode: "inherit"
      ledger_construction:
        - ledger_ref: "customer_funds"
          path_pattern: "[Managed-Funds][{product_role}][Customer-Funds]"
        - ledger_ref: "settlement_funds_by_counterparty"
          path_pattern: "[Managed-Funds][{product_role}][Settlement-Funds][{counterparty_role}]"
      posting_rules:
        - trigger_id: "Transact-Purchase-Clearing-Upstream"
          source_ledger_ref: "customer_funds"
          destination_ledger_ref: "settlement_funds_by_counterparty"
          amount_basis: "transaction_intent_amount"
          value_date_policy: "next_working_day_plus_x"
          value_date_offset_days: 0
      value_container_construction:
        - container_ref: "customer_funds_container"
          path_pattern: "[Managed-Funds][Customer-Funds][{product_role}]"
        - container_ref: "settlement_funds_container_by_counterparty"
          path_pattern: "[Managed-Funds][Settlement-Funds][{counterparty_role}]"
      asset_transfer_rules:
        - trigger_id: "Transact-Purchase-Clearing-Upstream"
          source_container_ref: "customer_funds_container"
          destination_container_ref: "settlement_funds_container_by_counterparty"
          amount_basis: "transaction_intent_amount"
          value_date_policy: "next_working_day_plus_x"
          value_date_offset_days: 0
      fee_sequences: []
      ledger_value_container_map:
        - ledger_ref: "settlement_funds_by_counterparty"
          container_ref: "settlement_funds_container_by_counterparty"
          mapping_mode: "aggregate"
    - pipeline_profile_id: "scheme_access_pipeline"
      transaction_intents: []
      ledger_construction:
        - ledger_ref: "scheme_fee_receivable"
          path_pattern: "[Managed-Funds][{product_role}][Settlement-Funds][{payer_role}]"
      posting_rules:
        - trigger_id: "fee_scheme_access"
          source_ledger_ref: "scheme_fee_receivable"
          destination_ledger_ref: "scheme_fee_receivable"
          amount_basis: "fee_amount"
          value_date_policy: "next_month_day_plus_x"
          value_date_offset_days: 5
      value_container_construction: []
      asset_transfer_rules: []
      fee_sequences:
        - sequence_id: "scheme_fee_sequence"
          fees:
            - fee_id: "fee_scheme_access"
              trigger_ids: ["Transact-Purchase-Clearing-Upstream"]
              beneficiary_role: "self_agent"
              beneficiary_product_role: "self_product"
              settlement_value_date_policy: "next_month_day_plus_x"
              settlement_value_date_offset_days: 5
              settlement_trigger_event: "invoice_transaction_event"
              count_cost:
                amount: 0.01
                currency: "USD"
              amount_percentage: 0.0015
      ledger_value_container_map: []
    - pipeline_profile_id: "processor_services_pipeline"
      transaction_intents: []
      ledger_construction:
        - ledger_ref: "processor_fee_receivable"
          path_pattern: "[Managed-Funds][{product_role}][Settlement-Funds][{payer_role}]"
      posting_rules:
        - trigger_id: "fee_processor_services"
          source_ledger_ref: "processor_fee_receivable"
          destination_ledger_ref: "processor_fee_receivable"
          amount_basis: "fee_amount"
          value_date_policy: "next_month_day_plus_x"
          value_date_offset_days: 5
      value_container_construction: []
      asset_transfer_rules: []
      fee_sequences:
        - sequence_id: "processor_fee_sequence"
          fees:
            - fee_id: "fee_processor_services"
              trigger_ids: ["Transact-Purchase-Clearing-Upstream"]
              beneficiary_role: "self_agent"
              beneficiary_product_role: "self_product"
              settlement_value_date_policy: "next_month_day_plus_x"
              settlement_value_date_offset_days: 5
              settlement_trigger_event: "invoice_transaction_event"
              count_cost:
                amount: 0.03
                currency: "USD"
      ledger_value_container_map: []

world:
  vendor_agents:
    - vendor_id: "vendor_alpha"
      region_id: "region_main"
      vendor_label: "Vendor Alpha"
      operational: true
      products:
        - product_id: "prod_prepaid_alpha"
          product_label: "Alpha Prepaid Card"
          product_class: "RetailPayment-Card-Prepaid"
          pipeline_profile_id: "prepaid_card_pipeline"
          pipeline_role_bindings:
            entity_roles:
              issuing_product: { product_id: "prod_prepaid_alpha" }
              product_role: { product_id: "prod_prepaid_alpha" }
              upstream_processor: { agent_id: "upstream_agent_alpha" }
              payment_scheme: { agent_id: "vendor_scheme" }
              payment_processor: { agent_id: "vendor_processor" }
              scheme_access_product: { product_id: "prod_scheme_access" }
              processor_services_product: { product_id: "prod_processor_services" }
              counterparty_role: { agent_id: "upstream_agent_alpha" }
              local: { local: true }
            default_product_role: "product_role"
    - vendor_id: "vendor_scheme"
      region_id: "region_main"
      vendor_label: "Global Payment Scheme (Sink)"
      operational: true
      products:
        - product_id: "prod_scheme_access"
          product_label: "Scheme-Access Product"
          product_class: "SinkProduct"
          pipeline_profile_id: "scheme_access_pipeline"
          pipeline_role_bindings:
            entity_roles:
              self_agent: { agent_id: "vendor_scheme" }
              self_product: { product_id: "prod_scheme_access" }
              payer_role: { agent_id: "vendor_alpha" }
            default_product_role: "self_product"
    - vendor_id: "vendor_processor"
      region_id: "region_main"
      vendor_label: "Payment Processor (Sink)"
      operational: true
      products:
        - product_id: "prod_processor_services"
          product_label: "Processor-Services Product"
          product_class: "SinkProduct"
          pipeline_profile_id: "processor_services_pipeline"
          pipeline_role_bindings:
            entity_roles:
              self_agent: { agent_id: "vendor_processor" }
              self_product: { product_id: "prod_processor_services" }
              payer_role: { agent_id: "vendor_alpha" }
            default_product_role: "self_product"
  pops:
    - pop_id: "pop_main"
      region_id: "region_main"
      pop_label: "Main Pop Segment"
      pop_count: 10000
      daily_onboard: 0.03
      daily_active: 0.40
      daily_transact_count: 1.2
      daily_transact_amount:
        amount: 22.5
        currency: "USD"
      product_links:
        - vendor_id: "vendor_alpha"
          product_id: "prod_prepaid_alpha"
          known: true
          onboarded_count: 0
```

### Spec-level acceptance checklist for this phase

- YAML schema defines Money, Currency Catalog, FX, Calendar, and Region contracts without requiring runtime implementation in this phase.
- Pipeline contracts are defined as reusable `pipeline_profiles` and attached per product via `pipeline_profile_id`.
- FX supports both first-class sources (`local_file`, `frankfurter_sources[]`) and explicit selection policy.
- Multiple Frankfurter source instances are supported via `source_id` and `source_refs`.
- Frankfurter selection is configurable via `base_country` and explicit `country_provider_map`.
- Calendar supports both first-class holiday sources (`local_file`, `nager_date`) and explicit selection policy.
- Region references calendar object; working-day rules remain in calendar object.
- World entities may map to regions via `region_id`, enabling region-specific calendar context.
- Fee settlement supports `invoice_transaction_event` for deferred collection via direct payment.
- Example YAML files exist for currency catalog, local FX rates, and local calendar holiday overlays.

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
