"""TransactionIntent — aggregate routed instruction (spec 33 §canonical artifacts).

v4 extensions:
  - `intent_stage` + `root_intent_id` — spec 33 §Transaction-intent log visibility
    (original + routed-derivative observability with shared correlation key).
  - `routing_completion_mode` — spec 40 §Routing completion mode; carried so
    the realtime payload (spec 52 §transaction_intent_event) can surface the
    declared sync/async mode on every routed leg.
  - `status` + `reason_code` — spec 33 §Destination gate-honor contract + v4
    §Fan-out completion semantics. `status` is `pending` for in-flight async
    legs on origin tick, `executed` for successful handoff (or the
    original_incoming root after all synchronous dependencies succeeded), or
    `rejected` when any synchronous dependency failed / destination gate
    refused. `reason_code` carries the decision's reason on non-success.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_t
from typing import Optional


@dataclass(frozen=True)
class TransactionIntent:
    intent_id: str                # for routed_outgoing: the destination's outgoing_intent_id.
                                  # for original_incoming: the source profile's intent_id.
    parent_intent_id: Optional[str]  # the source profile's intent_id, or None for origin
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str       # profile that materialized this intent
    source_product_id: str
    destination_role: str           # empty for original_incoming stage
    destination_product_id: str     # resolved; empty for original_incoming stage
    destination_vendor_id: str      # resolved; empty for original_incoming stage
    txn_count: int
    amount: float                   # in default currency
    currency: str
    value_date_policy: str
    value_date_offset_days: Optional[int]
    resolved_value_date: _date_t
    # Spec 33 §Transaction-intent log visibility + spec 52 §transaction_intent_event.
    intent_stage: str = "routed_outgoing"      # "original_incoming" | "routed_outgoing"
    root_intent_id: str = ""                   # stable key shared by original + derivatives
    # Spec 40 §Routing completion mode. Empty-string for original_incoming roots.
    routing_completion_mode: str = "synchronous"
    # Spec 33 §Destination gate-honor + §Fan-out completion semantics.
    status: str = "executed"                   # "pending" | "executed" | "rejected"
    reason_code: str = "OK"                    # OK / OK_UPSTREAM / TRANSACT_CLOSED / ...
