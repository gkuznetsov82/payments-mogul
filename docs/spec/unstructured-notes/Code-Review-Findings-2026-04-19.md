# Code Review Findings — 2026-04-19

Scope reviewed: runtime pipeline implementation, config/validation wiring, API + engine integration, TUI integration, tests/fixtures.

## Findings

### High

1. Incorrect `client_id` can be sent on inter-product handoff when `product_id` is not globally unique.
   - `engine/pipeline/executor.py`
   - Handoff reconstructs source vendor by scanning `product_id` instead of carrying source vendor directly.

2. Payer context is dropped for fee/invoice settlement events.
   - `engine/pipeline/executor.py`
   - `payer_role` / `payer_agent_id` are left unset during fee accrual, causing invoice settlement records to emit empty payer identity.

### Medium

3. Observability rows can be overwritten within the same tick (potential data loss).
   - `engine/pipeline/store.py`
   - SQLite schema uses coarse primary keys plus `INSERT OR REPLACE` (for example fees keyed by `tick_id + fee_id + product_id`), so repeated events can replace earlier ones.

4. Destination profile does not re-run intent routing stage (only fees/postings/transfers).
   - `engine/pipeline/executor.py`
   - After handoff, destination processing jumps into `_run_profile_stages(...)` instead of full destination intent-routing pass, limiting multi-hop chains.

### Low / Medium

5. Pipeline SQLite store is always in-memory, not configurable/persistent.
   - `engine/simulation/engine.py`
   - Runtime initializes `PipelineStore(":memory:")` unconditionally.

## Test Gap

- Could not execute tests locally in this environment because `pytest` is unavailable (`python -m pytest` -> `No module named pytest`).

