"""GenericPop — Mesa agent representing a stock-flow pop segment."""

from __future__ import annotations

from dataclasses import dataclass

import mesa

from engine.config.models import PopConfig
from engine.numeric import round_amount, round_count


@dataclass
class ProductLinkState:
    vendor_id: str
    product_id: str
    known: bool
    onboarded_count: float


@dataclass
class ActionOutcome:
    tick_id: int
    action_type: str      # "Onboard" or "Transact"
    pop_id: str
    vendor_id: str
    product_id: str
    status: str           # "accepted", "rejected", "success", "failure"
    reason_code: str
    accepted_pop_count: float = 0.0
    rejected_pop_count: float = 0.0
    successful_txn_count: float = 0.0
    failed_txn_count: float = 0.0
    successful_total_amount: float = 0.0
    failed_total_amount: float = 0.0

    def as_dict(self,
                count_mode: str = "half_up",
                amount_scale_dp: int = 2,
                amount_mode: str = "half_up") -> dict:
        """Emit outcome per spec 40/51/52 numeric typing: counts as integers,
        amounts scaled to configured decimal places."""
        return {
            "tick_id": self.tick_id,
            "action_type": self.action_type,
            "pop_id": self.pop_id,
            "vendor_id": self.vendor_id,
            "product_id": self.product_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "accepted_pop_count": round_count(self.accepted_pop_count, count_mode),
            "rejected_pop_count": round_count(self.rejected_pop_count, count_mode),
            "successful_txn_count": round_count(self.successful_txn_count, count_mode),
            "failed_txn_count": round_count(self.failed_txn_count, count_mode),
            "successful_total_amount": round_amount(self.successful_total_amount, amount_scale_dp, amount_mode),
            "failed_total_amount": round_amount(self.failed_total_amount, amount_scale_dp, amount_mode),
        }


class GenericPop(mesa.Agent):
    def __init__(self, model: mesa.Model, cfg: PopConfig) -> None:
        super().__init__(model)
        self.pop_id = cfg.pop_id
        self.pop_label = cfg.pop_label
        self.pop_count = cfg.pop_count
        self.daily_onboard = cfg.daily_onboard
        self.daily_active = cfg.daily_active
        self.daily_transact_count = cfg.daily_transact_count
        self.daily_transact_amount = cfg.daily_transact_amount
        # vendor_id -> product_id -> ProductLinkState
        self.products: dict[str, dict[str, ProductLinkState]] = {}
        for link in cfg.product_links:
            self.products.setdefault(link.vendor_id, {})[link.product_id] = ProductLinkState(
                vendor_id=link.vendor_id,
                product_id=link.product_id,
                known=link.known,
                onboarded_count=link.onboarded_count,
            )

    def Onboard(self) -> None:
        """Mesa step entrypoint: generate onboarding requests for known product links."""
        tick_id = self.model.steps
        vendors = self.model.vendors
        for vendor_id in sorted(self.products.keys()):
            vendor = vendors.get(vendor_id)
            if vendor is None:
                continue
            for product_id in sorted(self.products[vendor_id].keys()):
                link = self.products[vendor_id][product_id]
                if not link.known:
                    continue
                requested = self.pop_count * self.daily_onboard
                result = vendor.handle_onboard_from_pop(self.pop_id, product_id, requested)
                link.onboarded_count += result.accepted_pop_count
                status = "accepted" if result.accepted_pop_count > 0 else "rejected"
                self.model.record_outcome(ActionOutcome(
                    tick_id=tick_id,
                    action_type="Onboard",
                    pop_id=self.pop_id,
                    vendor_id=vendor_id,
                    product_id=product_id,
                    status=status,
                    reason_code=result.reason_code,
                    accepted_pop_count=result.accepted_pop_count,
                    rejected_pop_count=result.rejected_pop_count,
                ))

    def Transact(self) -> None:
        """Mesa step entrypoint: generate transact requests for links with onboarded stock."""
        tick_id = self.model.steps
        vendors = self.model.vendors
        for vendor_id in sorted(self.products.keys()):
            vendor = vendors.get(vendor_id)
            if vendor is None:
                continue
            for product_id in sorted(self.products[vendor_id].keys()):
                link = self.products[vendor_id][product_id]
                if not link.known or link.onboarded_count <= 0:
                    continue
                active_count = link.onboarded_count * self.daily_active
                requested_txn = active_count * self.daily_transact_count
                requested_amt = active_count * self.daily_transact_amount
                result = vendor.handle_transact_from_pop(
                    self.pop_id, product_id, active_count, requested_txn, requested_amt
                )
                status = "success" if result.successful_txn_count > 0 else "failure"
                self.model.record_outcome(ActionOutcome(
                    tick_id=tick_id,
                    action_type="Transact",
                    pop_id=self.pop_id,
                    vendor_id=vendor_id,
                    product_id=product_id,
                    status=status,
                    reason_code=result.reason_code,
                    successful_txn_count=result.successful_txn_count,
                    failed_txn_count=result.failed_txn_count,
                    successful_total_amount=result.successful_total_amount,
                    failed_total_amount=result.failed_total_amount,
                ))

    def snapshot(self,
                 count_mode: str = "half_up",
                 amount_scale_dp: int = 2,
                 amount_mode: str = "half_up") -> dict:
        """Emit pop snapshot per spec 40/52 numeric typing."""
        links = [
            {
                "vendor_id": link.vendor_id,
                "product_id": link.product_id,
                "known": link.known,
                "onboarded_count": round_count(link.onboarded_count, count_mode),
            }
            for products in self.products.values()
            for link in products.values()
        ]
        return {
            "pop_id": self.pop_id,
            "pop_label": self.pop_label,
            "pop_count": int(self.pop_count),
            "product_links": links,
        }
