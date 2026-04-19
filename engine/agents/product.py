"""GenericProduct and RetailPaymentCardPrepaid — product state and decision methods."""

from __future__ import annotations

import random
from dataclasses import dataclass

from engine.config.models import ProductConfig
from engine.numeric import round_amount, round_count


@dataclass
class OnboardDecisionResult:
    accepted_pop_count: float
    rejected_pop_count: float
    reason_code: str


@dataclass
class TransactDecisionResult:
    successful_txn_count: float
    failed_txn_count: float
    successful_total_amount: float
    failed_total_amount: float
    reason_code: str


@dataclass
class TransactionDetails:
    """Routed transaction details delivered by upstream vendor (spec 31, ADR-0002)."""
    intent_id: str
    parent_intent_id: str | None
    txn_count: int
    amount: float
    currency: str
    value_date_policy: str
    value_date_offset_days: int | None


class GenericProduct:
    """Accepts all valid requests under gate checks; no friction."""

    def __init__(
        self,
        cfg: ProductConfig,
        owner_vendor_id: str,
        accepting_onboard: bool,
        accepting_transact: bool,
    ) -> None:
        self.product_id = cfg.product_id
        self.product_label = cfg.product_label
        self.product_class = cfg.product_class
        self.owner_vendor_id = owner_vendor_id
        self.accepting_onboard = accepting_onboard
        self.accepting_transact = accepting_transact
        self.onboarded_pop_count: float = 0.0
        self.successful_transact_count: float = 0.0
        self.successful_transact_amount: float = 0.0
        # v3_runtime pipeline binding (spec 40 §pipeline + product_class).
        self.cfg_profile_id: str | None = cfg.pipeline_profile_id
        self.cfg_role_bindings = cfg.pipeline_role_bindings

    # Control methods — applied during tick_user_inputs_processed
    def close_onboarding(self) -> None:
        self.accepting_onboard = False

    def open_onboarding(self) -> None:
        self.accepting_onboard = True

    def close_transacting(self) -> None:
        self.accepting_transact = False

    def open_transacting(self) -> None:
        self.accepting_transact = True

    # Decision methods — called by VendorAgent on behalf of pop requests
    def onboard_product(
        self,
        pop_id: str,
        requested_pop_count: float,
        rng: random.Random,
    ) -> OnboardDecisionResult:
        if not self.accepting_onboard:
            return OnboardDecisionResult(0.0, requested_pop_count, "ONBOARD_CLOSED")
        accepted = self._apply_onboard_friction(requested_pop_count, rng)
        self.onboarded_pop_count += accepted
        return OnboardDecisionResult(accepted, requested_pop_count - accepted, "OK")

    def transact_product(
        self,
        pop_id: str,
        requested_pop_count: float,
        requested_txn_count: float,
        requested_total_amount: float,
        rng: random.Random,
    ) -> TransactDecisionResult:
        if not self.accepting_transact:
            return TransactDecisionResult(
                0.0, requested_txn_count, 0.0, requested_total_amount, "TRANSACT_CLOSED"
            )
        success_txn, success_amt = self._apply_transact_friction(
            requested_txn_count, requested_total_amount, rng
        )
        self.successful_transact_count += success_txn
        self.successful_transact_amount += success_amt
        return TransactDecisionResult(
            success_txn,
            requested_txn_count - success_txn,
            success_amt,
            requested_total_amount - success_amt,
            "OK",
        )

    def _apply_onboard_friction(self, requested: float, rng: random.Random) -> float:
        return requested

    def _apply_transact_friction(
        self, requested_txn: float, requested_amt: float, rng: random.Random
    ) -> tuple[float, float]:
        return requested_txn, requested_amt

    def transact_product_from_upstream(
        self,
        client_id: str,
        details: "TransactionDetails",
    ) -> "TransactDecisionResult":
        """Per ADR-0002: destination product handler for upstream-routed intents.

        `client_id` is the originating upstream vendor_id (spec 31). Default
        behavior: accept all upstream traffic (no friction), record txn count +
        amount as accepted; fee/posting/transfer logic is then performed by the
        engine's pipeline executor against this product's pipeline profile.
        """
        if not self.accepting_transact:
            return TransactDecisionResult(
                0.0, float(details.txn_count), 0.0, float(details.amount),
                "TRANSACT_CLOSED",
            )
        self.successful_transact_count += details.txn_count
        self.successful_transact_amount += details.amount
        return TransactDecisionResult(
            float(details.txn_count), 0.0, float(details.amount), 0.0, "OK_UPSTREAM",
        )

    def snapshot(self,
                 count_mode: str = "half_up",
                 amount_scale_dp: int = 2,
                 amount_mode: str = "half_up") -> dict:
        """Emit product snapshot per spec 40/52 numeric typing."""
        return {
            "product_id": self.product_id,
            "product_label": self.product_label,
            "accepting_onboard": self.accepting_onboard,
            "accepting_transact": self.accepting_transact,
            "onboarded_pop_count": round_count(self.onboarded_pop_count, count_mode),
            "successful_transact_count": round_count(self.successful_transact_count, count_mode),
            "successful_transact_amount": round_amount(self.successful_transact_amount, amount_scale_dp, amount_mode),
        }


class RetailPaymentCardPrepaid(GenericProduct):
    """Applies per-tick friction sampled from configured ranges via model.random."""

    def __init__(
        self,
        cfg: ProductConfig,
        owner_vendor_id: str,
        accepting_onboard: bool,
        accepting_transact: bool,
    ) -> None:
        super().__init__(cfg, owner_vendor_id, accepting_onboard, accepting_transact)
        ob = cfg.onboarding_friction
        tx = cfg.transaction_friction
        self._ob_min = ob.min if ob else 0.0
        self._ob_max = ob.max if ob else 0.0
        self._tx_min = tx.min if tx else 0.0
        self._tx_max = tx.max if tx else 0.0

    def _apply_onboard_friction(self, requested: float, rng: random.Random) -> float:
        friction = rng.uniform(self._ob_min, self._ob_max)
        return requested * (1.0 - friction)

    def _apply_transact_friction(
        self, requested_txn: float, requested_amt: float, rng: random.Random
    ) -> tuple[float, float]:
        friction = rng.uniform(self._tx_min, self._tx_max)
        rate = 1.0 - friction
        return requested_txn * rate, requested_amt * rate


class SinkProduct(GenericProduct):
    """Sink-style product (spec 31 §SinkProduct, ADR-0002).

    Pop-origin onboard/transact paths return zero-effect results; the operational
    path is `transact_product_from_upstream` (driven by inter-product handoff).
    """

    def onboard_product(
        self,
        pop_id: str,
        requested_pop_count: float,
        rng: random.Random,
    ) -> OnboardDecisionResult:
        return OnboardDecisionResult(0.0, requested_pop_count, "SINK_PRODUCT_NO_POP_TRAFFIC")

    def transact_product(
        self,
        pop_id: str,
        requested_pop_count: float,
        requested_txn_count: float,
        requested_total_amount: float,
        rng: random.Random,
    ) -> TransactDecisionResult:
        return TransactDecisionResult(
            0.0, requested_txn_count, 0.0, requested_total_amount,
            "SINK_PRODUCT_NO_POP_TRAFFIC",
        )


def build_product(
    cfg: ProductConfig,
    owner_vendor_id: str,
    accepting_onboard: bool,
    accepting_transact: bool,
) -> GenericProduct:
    if cfg.product_class == "RetailPayment-Card-Prepaid":
        return RetailPaymentCardPrepaid(cfg, owner_vendor_id, accepting_onboard, accepting_transact)
    if cfg.product_class == "SinkProduct":
        return SinkProduct(cfg, owner_vendor_id, accepting_onboard, accepting_transact)
    return GenericProduct(cfg, owner_vendor_id, accepting_onboard, accepting_transact)
