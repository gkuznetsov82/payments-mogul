"""InvoiceEvent + SettlementResolution — deferred fee collection (spec 33).

For fees with `settlement_trigger_event = invoice_transaction_event` and a
deferred policy (`next_month_day_plus_x`), the beneficiary product accrues the
fee at compute time and emits an InvoiceEvent on the resolved due date. Per
ADR-0002, settlement netting is out of scope for this phase — invoice
collection resolves via direct payment only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_t


@dataclass(frozen=True)
class InvoiceEvent:
    invoice_id: str
    tick_id: int                # tick on which the invoice is emitted (due date tick)
    simulation_date: _date_t    # = due date
    pipeline_profile_id: str
    beneficiary_product_id: str
    payer_agent_id: str
    payer_product_id: str | None
    fee_id: str
    accrual_tick_id: int        # tick when the underlying fee was accrued
    accrual_date: _date_t
    amount: float
    currency: str
    status: str                 # "invoiced"


@dataclass(frozen=True)
class SettlementResolution:
    invoice_id: str
    tick_id: int
    simulation_date: _date_t
    pipeline_profile_id: str
    beneficiary_product_id: str
    payer_agent_id: str
    payer_product_id: str | None
    fee_id: str
    settled_amount: float
    residual_amount: float       # 0.0 for direct-payment path
    currency: str
    mode: str                    # "paid" (netting deferred per ADR-0002)
    final_status: str            # "paid"
