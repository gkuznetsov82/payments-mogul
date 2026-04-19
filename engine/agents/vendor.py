"""VendorAgent — Mesa agent that routes pop requests to owned product decision methods."""

from __future__ import annotations

import mesa

from engine.agents.product import (
    GenericProduct,
    OnboardDecisionResult,
    TransactDecisionResult,
    TransactionDetails,
    build_product,
)
from engine.config.models import ControlDefaultsConfig, VendorAgentConfig


class VendorAgent(mesa.Agent):
    def __init__(
        self,
        model: mesa.Model,
        cfg: VendorAgentConfig,
        defaults: ControlDefaultsConfig,
    ) -> None:
        super().__init__(model)
        self.vendor_id = cfg.vendor_id
        self.vendor_label = cfg.vendor_label
        self.operational = cfg.operational
        self.region_id = cfg.region_id  # v2 foundations: drives calendar lookup
        self.products: dict[str, GenericProduct] = {
            p.product_id: build_product(
                p,
                cfg.vendor_id,
                defaults.accepting_onboard,
                defaults.accepting_transact,
            )
            for p in cfg.products
        }

    # Mesa tick entrypoints — noop for VendorAgent in prototype
    def Onboard(self) -> None:
        pass

    def Transact(self) -> None:
        pass

    # Request handlers — called by GenericPop during its Onboard/Transact steps
    def handle_onboard_from_pop(
        self,
        pop_id: str,
        product_id: str,
        requested_pop_count: float,
    ) -> OnboardDecisionResult:
        if not self.operational:
            return OnboardDecisionResult(0.0, requested_pop_count, "VENDOR_NOT_OPERATIONAL")
        product = self.products.get(product_id)
        if product is None:
            return OnboardDecisionResult(0.0, requested_pop_count, "PRODUCT_NOT_FOUND")
        return product.onboard_product(pop_id, requested_pop_count, self.model.random)

    def handle_transact_from_pop(
        self,
        pop_id: str,
        product_id: str,
        requested_pop_count: float,
        requested_txn_count: float,
        requested_total_amount: float,
    ) -> TransactDecisionResult:
        if not self.operational:
            return TransactDecisionResult(
                0.0, requested_txn_count, 0.0, requested_total_amount, "VENDOR_NOT_OPERATIONAL"
            )
        product = self.products.get(product_id)
        if product is None:
            return TransactDecisionResult(
                0.0, requested_txn_count, 0.0, requested_total_amount, "PRODUCT_NOT_FOUND"
            )
        return product.transact_product(
            pop_id, requested_pop_count, requested_txn_count, requested_total_amount,
            self.model.random,
        )

    def handle_transact_from_vendor(
        self,
        client_id: str,
        product_id: str,
        details: TransactionDetails,
    ) -> TransactDecisionResult:
        """Per ADR-0002: route an upstream-vendor-originated transaction intent
        to the owned destination product. `client_id` is the originating
        upstream vendor_id."""
        if not self.operational:
            return TransactDecisionResult(
                0.0, float(details.txn_count), 0.0, float(details.amount),
                "VENDOR_NOT_OPERATIONAL",
            )
        product = self.products.get(product_id)
        if product is None:
            return TransactDecisionResult(
                0.0, float(details.txn_count), 0.0, float(details.amount),
                "PRODUCT_NOT_FOUND",
            )
        return product.transact_product_from_upstream(client_id, details)

    def snapshot(self,
                 count_mode: str = "half_up",
                 amount_scale_dp: int = 2,
                 amount_mode: str = "half_up") -> dict:
        return {
            "vendor_id": self.vendor_id,
            "vendor_label": self.vendor_label,
            "operational": self.operational,
            "products": {
                pid: p.snapshot(count_mode, amount_scale_dp, amount_mode)
                for pid, p in self.products.items()
            },
        }
