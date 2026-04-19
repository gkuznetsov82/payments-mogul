"""TransactionIntent — aggregate routed instruction (spec 33 §canonical artifacts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date_t
from typing import Optional


@dataclass(frozen=True)
class TransactionIntent:
    intent_id: str                # outgoing_intent_id from the routing destination
    parent_intent_id: Optional[str]  # the source profile's intent_id, or None for origin
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str       # profile that materialized this intent
    source_product_id: str
    destination_role: str
    destination_product_id: str    # resolved
    destination_vendor_id: str     # resolved
    txn_count: int
    amount: float                  # in default currency
    currency: str
    value_date_policy: str
    value_date_offset_days: Optional[int]
    resolved_value_date: _date_t
