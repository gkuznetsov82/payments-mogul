"""InvoiceEvent + SettlementResolution — deferred fee collection (spec 33).

For fees with `settlement_trigger_event = invoice_transaction_event` and a
deferred policy (`next_month_day_plus_x`), the beneficiary product accrues the
fee at compute time and emits an InvoiceEvent on the resolved due date.

v4 aggregation (spec 33 §Invoice and settlement lifecycle): invoices represent
**aggregate** fees of the same fee-type / recipient / payer / due date. Fields
that describe the folded components (tick ids, accrual dates, component count)
support operator traceability without duplicating invoice emissions. Per
ADR-0002, settlement netting remains deferred; direct payment is the default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    fee_id: str                  # fee type aggregated into this invoice
    accrual_tick_id: int         # earliest tick when a component fee accrued
    accrual_date: _date_t        # earliest accrual simulation_date across components
    amount: float                # aggregated amount across components
    currency: str
    status: str                  # "invoiced"
    # v4 §Invoice aggregation: transparency for operators + SQL traceability.
    component_count: int = 1
    component_tick_ids: tuple[int, ...] = field(default_factory=tuple)


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
    final_status: str            # "paid" | "failed"
