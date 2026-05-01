"""AssetTransfer — value-container movement (spec 33).

v4 (spec 52 §value_transfer_event + spec 73 §7):
- Explicit source/destination ownership fields so UIs can attribute both sides
  correctly (Accounts view uses destination ownership, not payer-only).
- `status` may be `executed` | `failed`. Failed transfers carry a
  `reason_code` (e.g. INSUFFICIENT_FUNDS, CONTAINER_NOT_REGISTERED).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_t
from typing import Optional


@dataclass(frozen=True)
class AssetTransfer:
    transfer_id: str
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str
    # `product_id` is kept as a back-compat alias (owning product / audit lens).
    # Split ownership fields below are authoritative for Accounts attribution.
    product_id: str
    trigger_id: str
    source_container_ref: str
    destination_container_ref: str
    source_container_path: str
    destination_container_path: str
    amount: float
    currency: str
    value_date_policy: str
    resolved_value_date: _date_t
    status: str                # "executed" | "failed"
    # Spec 52 §value_transfer_event: explicit source/destination ownership for
    # correct Accounts attribution. For same-profile transfers these match;
    # for cross-product payment transfers they differ (payer vs creditor).
    source_product_id: str = ""
    source_agent_id: Optional[str] = None
    destination_product_id: str = ""
    destination_agent_id: Optional[str] = None
    # Failure reason when status == "failed" (spec 73 §7 / spec 52
    # §value_transfer_event "must indicate failed execution status and include
    # failure reason"). None on successful execution.
    reason_code: Optional[str] = None
