"""PostingEntry — dual-entry accounting record (spec 33)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_t


@dataclass(frozen=True)
class PostingEntry:
    posting_id: str
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str
    product_id: str
    trigger_id: str             # intent or fee id
    source_ledger_ref: str
    destination_ledger_ref: str
    source_ledger_path: str     # role-expanded path
    destination_ledger_path: str
    amount: float
    currency: str
    value_date_policy: str
    resolved_value_date: _date_t
    status: str                 # "posted"
