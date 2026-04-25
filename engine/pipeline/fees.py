"""FeeAccrual — fee computed by sequence (spec 33).

v4 additions (spec 33 §Invoice and settlement lifecycle + spec 40 §Lifecycle
date semantics):
- Explicit separate lifecycle dates: `accrual_date`, `invoice_issue_date`,
  `payment_due_date`. Legacy `settlement_due_date` is retained as an alias
  for `payment_due_date` so v3 callers keep working.
- `payer_product_id` — resolved payer product (spec 40 §Intent of payer_role).
- `non_payable` — spec 33 §Cardholder fee statement rule. When True, the
  invoice emitted for this fee is informational (payable=false) and does not
  emit a settlement_resolution_event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date_t
from typing import Optional


@dataclass(frozen=True)
class FeeAccrual:
    fee_id: str
    sequence_id: str
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str
    product_id: str               # the product whose pipeline computed this fee (beneficiary side)
    trigger_id: str               # intent or upstream fee that triggered this fee
    beneficiary_role: str
    beneficiary_agent_id: str
    beneficiary_product_id: Optional[str]
    payer_role: Optional[str]
    payer_agent_id: Optional[str]
    payer_product_id: Optional[str]
    txn_count_basis: int
    amount_basis: float
    fixed_component: float
    percent_component: float
    fee_amount: float
    currency: str
    settlement_value_date_policy: str
    settlement_value_date_offset_days: Optional[int]
    # v4 lifecycle dates (spec 40 §Lifecycle date semantics):
    accrual_date: _date_t
    invoice_issue_date: _date_t
    payment_due_date: _date_t
    # Spec 33 §Cardholder fee statement rule.
    non_payable: bool = False
    settlement_trigger_event: Optional[str] = None
    status: str = "accrued"

    @property
    def settlement_due_date(self) -> _date_t:
        """Back-compat alias. Spec 40 §Lifecycle date semantics: overdue
        semantics use payment_due_date; this keeps pre-v4 callers working."""
        return self.payment_due_date
