"""AssetTransfer — value-container movement (spec 33)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_t


@dataclass(frozen=True)
class AssetTransfer:
    transfer_id: str
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str
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
    status: str                # "executed"
