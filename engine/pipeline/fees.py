"""FeeAccrual — fee computed by sequence (spec 33)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_t
from typing import Optional


@dataclass(frozen=True)
class FeeAccrual:
    fee_id: str
    sequence_id: str
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str
    product_id: str               # the product whose pipeline computed this fee (beneficiary)
    trigger_id: str               # intent or upstream fee that triggered this fee
    beneficiary_role: str
    beneficiary_agent_id: str
    beneficiary_product_id: Optional[str]
    payer_role: Optional[str]     # source product role (if resolvable)
    payer_agent_id: Optional[str]
    txn_count_basis: int          # number of transactions the fee was computed against
    amount_basis: float           # currency-amount basis the fee was computed against
    fixed_component: float        # count_cost * txn_count
    percent_component: float      # amount_percentage * amount_basis
    fee_amount: float             # fixed + percent
    currency: str
    settlement_value_date_policy: str
    settlement_value_date_offset_days: Optional[int]
    settlement_due_date: _date_t
    settlement_trigger_event: Optional[str]
    status: str                   # "accrued" at construction
