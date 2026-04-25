"""InvoiceEvent + SettlementResolution + SettlementDemandAccrual (v4 runtime).

Spec 33 §Invoice and settlement lifecycle + spec 52 §invoice_transaction_event:
- Lifecycle dates are explicit and non-interchangeable:
    accrual_date   -> when fee / settlement-demand economics are recognized
    invoice_issue_date -> when the advisement/invoice is emitted (aggregation key)
    payment_due_date   -> when payment is contractually due (overdue / autopay ordering)
- invoice_category: `fee` | `settlement_demand`
- payable: true for actionable invoices, false for informational advisements
  (spec 33 §Cardholder fee statement rule: non-payable items must not expose
  payment actions).
- settlement_status: resolved settlement mode token (`pending` | `paid` | `failed`
  | `netted_internal`). Non-payable statements stay at `netted_internal`.

Transfer-backed paid resolution (spec 33 §Invoice and settlement lifecycle):
SettlementResolution.final_status == "paid" only when an accompanying value
transfer executed successfully for settled_amount; otherwise final_status is
`failed` and residual_amount == invoice amount (all-or-nothing transfer under
spec 40 §Container balance handling).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date_t
from typing import Optional


@dataclass(frozen=True)
class InvoiceEvent:
    invoice_id: str
    tick_id: int                # tick on which the invoice is emitted (issue date tick)
    simulation_date: _date_t    # = invoice_issue_date
    pipeline_profile_id: str
    # Spec 52 §invoice_transaction_event: category is `fee` or `settlement_demand`.
    invoice_category: str
    # Resolved creditor/debtor identities (spec 33 §Directionality). For fee
    # invoices the creditor is the beneficiary; for settlement demands the
    # creditor reflects the net-direction winner after signed aggregation.
    creditor_agent_id: str
    creditor_product_id: Optional[str]
    debtor_agent_id: str
    debtor_product_id: Optional[str]
    # Legacy fee-invoice alias fields (beneficiary/payer) kept for back-compat
    # with existing clients; filled from creditor/debtor resolution.
    beneficiary_product_id: str
    payer_agent_id: str
    payer_product_id: Optional[str]
    # Source reference: fee_id for fee invoices, settlement_demand_id for demand
    # invoices. At least one must be set.
    fee_id: Optional[str]
    settlement_demand_id: Optional[str]
    # Spec 40 §Lifecycle date semantics: three explicit, non-interchangeable dates.
    accrual_date: _date_t        # earliest accrual simulation_date across components
    invoice_issue_date: _date_t  # emission (same as simulation_date on emit tick)
    payment_due_date: _date_t    # overdue + autopay-ordering reference
    accrual_tick_id: int         # earliest tick when a component accrual landed
    amount: float                # aggregated amount across components (signed aggregation for demands)
    currency: str
    status: str                  # "invoiced"
    # Payable flag — spec 33 §Cardholder fee statement rule. When False, item
    # stays informational and is excluded from payment action queues.
    payable: bool = True
    settlement_status: str = "pending"  # "pending" | "paid" | "failed" | "netted_internal"
    # v4 aggregation transparency.
    component_count: int = 1
    component_tick_ids: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SettlementResolution:
    invoice_id: str
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str
    invoice_category: str
    creditor_agent_id: str
    debtor_agent_id: str
    beneficiary_product_id: str
    payer_agent_id: str
    payer_product_id: Optional[str]
    fee_id: Optional[str]
    settlement_demand_id: Optional[str]
    settled_amount: float
    residual_amount: float       # 0.0 on full-paid; = invoice amount on failed
    currency: str
    mode: str                    # "paid" | "failed" (netting deferred per ADR-0002)
    final_status: str            # "paid" | "failed"
    # Transfer correlation — the payment transfer_id that backs a paid
    # resolution. None on failed resolution.
    transfer_id: Optional[str] = None


@dataclass(frozen=True)
class SettlementDemandAccrual:
    """Spec 33 §SettlementDemandResult + spec 40 §settlement_demand_sequences.

    Distinct from FeeAccrual: demands carry an explicit directional axis
    (creditor vs debtor agents) that can flip by net outcome when opposing
    accruals (e.g. purchase vs refund) aggregate into the same invoice group.
    """
    settlement_demand_id: str
    sequence_id: str
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str
    product_id: str                 # issuing product (profile owner)
    trigger_id: str                 # first trigger that matched (observability)
    creditor_role: str
    debtor_role: str
    creditor_agent_id: str
    creditor_product_id: Optional[str]
    debtor_agent_id: str
    debtor_product_id: Optional[str]
    invoice_category: str           # always "settlement_demand"
    txn_count_basis: int
    amount_basis: float             # signed per canonical direction? no — raw, sign derived at emit
    amount: float                   # accrual amount as specified (always >= 0 in spec scope)
    currency: str
    accrual_date: _date_t
    invoice_issue_date: _date_t
    payment_due_date: _date_t
    status: str                     # "accrued"
