"""Pipeline executor — runs after v1 adjudication when pipeline_schema_version='v3_runtime'.

Deterministic stage order per spec 30 §v3_runtime:
    intents -> fees -> postings -> asset transfers -> retention/invoice lifecycle

For each successful Transact outcome whose source product has an attached
v3_runtime pipeline profile:
  1. For each profile.transaction_intents[].destinations[]: route an upstream
     intent to the resolved destination product (via VendorAgent.handle_transact_from_vendor),
     then continue at destination's pipeline.
  2. For each fee_sequence: compute fees in order; trigger ids may reference
     intents or earlier fees in the same sequence. Fees with deferred settlement
     queue an open invoice for the resolved due date.
  3. For each posting_rule: materialize a PostingEntry whose source/destination
     ledger paths are role-expanded.
  4. For each asset_transfer_rule: materialize an AssetTransfer with role-expanded
     container paths.
  5. End-of-tick: check open invoices; any with due_date == simulation_date emit
     invoice_transaction_event + settlement_resolution_event (direct payment per
     ADR-0002; netting deferred).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date as _date_t
from typing import Callable, Optional

from engine.agents.pop import ActionOutcome
from engine.agents.product import GenericProduct, TransactionDetails
from engine.calendars.calendar import Calendar
from engine.config.models import (
    AssetTransferRuleConfig,
    FeeConfig,
    PipelineProfileConfig,
    PostingRuleConfig,
    PrototypeConfig,
    TransactionDestinationConfig,
)
from engine.numeric import round_amount
from engine.pipeline.fees import FeeAccrual
from engine.pipeline.intents import TransactionIntent
from engine.pipeline.invoices import InvoiceEvent, SettlementResolution
from engine.pipeline.postings import PostingEntry
from engine.pipeline.role_resolver import RoleResolutionError, RoleResolver
from engine.pipeline.transfers import AssetTransfer
from engine.pipeline.value_dates import resolve_value_date


# Sentinel for outcomes that should be skipped in pipeline routing.
_INTENT_NS = uuid.UUID("00000000-0000-0000-0000-000000000033")  # spec 33 namespace


@dataclass
class _OpenInvoice:
    """Internal record carrying enough context to emit invoice + resolution at due date."""
    fee: FeeAccrual
    invoice_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.invoice_id:
            self.invoice_id = f"inv_{self.fee.fee_id}_{self.fee.tick_id}"


class PipelineExecutor:
    """Runs pipeline stages for a single tick. Stateless across ticks except for
    the open-invoice queue (settlement is deferred across ticks)."""

    def __init__(self,
                 cfg: PrototypeConfig,
                 model,
                 default_currency: str,
                 calendar_lookup: Callable[[str], Optional[Calendar]],
                 emit: Callable[[str, dict], None]) -> None:
        self.cfg = cfg
        self.model = model
        self.default_currency = default_currency or "USD"
        self.calendar_lookup = calendar_lookup
        self.emit = emit  # (event_type, data) -> None
        self._profile_index = self._index_profiles(cfg)
        self._open_invoices: list[_OpenInvoice] = []

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _index_profiles(cfg: PrototypeConfig) -> dict[str, PipelineProfileConfig]:
        if cfg.pipeline is None:
            return {}
        return {p.pipeline_profile_id: p for p in cfg.pipeline.pipeline_profiles}

    @property
    def is_runtime(self) -> bool:
        return cfg_pipeline_runtime(self.cfg)

    # ------------------------------------------------------------------ per-tick API

    def run_post_adjudication(self,
                              outcomes: list[ActionOutcome],
                              tick_id: int,
                              simulation_date: _date_t) -> None:
        """Entrypoint called by SimulationEngine after v1 adjudication.

        Stage order is fixed (spec 30 §v3_runtime):
            intents -> fees -> postings -> asset transfers -> invoice/settlement.
        """
        if not self.is_runtime:
            return
        # 1. Process each successful Transact outcome from products that have a profile.
        # Stable iteration: outcomes are appended in agent-order; sort by (vendor_id, product_id, pop_id).
        sorted_outcomes = sorted(
            (o for o in outcomes
             if o.action_type == "Transact" and o.successful_txn_count > 0),
            key=lambda o: (o.vendor_id, o.product_id, o.pop_id),
        )
        for o in sorted_outcomes:
            self._process_outcome(o, tick_id, simulation_date)

        # 2. End-of-tick: invoice + settlement for due-today open invoices.
        self._resolve_due_invoices(tick_id, simulation_date)

    # ------------------------------------------------------------------ outcome routing

    def _process_outcome(self,
                         outcome: ActionOutcome,
                         tick_id: int,
                         simulation_date: _date_t) -> None:
        vendor = self.model.vendors.get(outcome.vendor_id)
        if vendor is None:
            return
        product = vendor.products.get(outcome.product_id)
        if product is None or product.cfg_profile_id is None:
            return
        profile = self._profile_index.get(product.cfg_profile_id)
        if profile is None:
            return

        resolver = RoleResolver(product.cfg_role_bindings)
        # Materialize one TransactionIntent per declared destination per declared intent.
        intents_routed: list[TransactionIntent] = []
        for intent_cfg in sorted(profile.transaction_intents, key=lambda i: i.intent_id):
            for dest in sorted(intent_cfg.destinations, key=lambda d: (d.destination_role, d.outgoing_intent_id)):
                intent = self._materialize_intent(
                    profile=profile,
                    source_product=product,
                    source_vendor_id=vendor.vendor_id,
                    parent_intent_id=intent_cfg.intent_id,
                    dest=dest,
                    resolver=resolver,
                    txn_count=int(round(outcome.successful_txn_count)),
                    amount=float(outcome.successful_total_amount),
                    tick_id=tick_id,
                    simulation_date=simulation_date,
                )
                if intent is None:
                    continue
                intents_routed.append(intent)
                self._emit_intent(intent)
                # Hand off to destination product.
                self._dispatch_handoff(intent)

        # Trigger pool for fee/posting/transfer rules: parent intent_id from this profile,
        # any outgoing_intent_id from routed intents.
        local_trigger_amounts: dict[str, tuple[int, float]] = {}
        for intent_cfg in profile.transaction_intents:
            # The "parent" intent itself is also a usable trigger id for fees/postings
            # in the source product's profile (spec 33: intents drive fees + postings).
            local_trigger_amounts[intent_cfg.intent_id] = (
                int(round(outcome.successful_txn_count)),
                float(outcome.successful_total_amount),
            )
        for intent in intents_routed:
            local_trigger_amounts[intent.intent_id] = (intent.txn_count, intent.amount)

        # 2-4. Run fees / postings / asset transfers anchored on the SOURCE product's
        # profile against the local trigger pool. Destination product runs its own
        # profile via _run_profile_stages from the handoff path.
        self._run_profile_stages(
            profile=profile,
            owning_product=product,
            owning_vendor_id=vendor.vendor_id,
            resolver=resolver,
            tick_id=tick_id,
            simulation_date=simulation_date,
            trigger_amounts=local_trigger_amounts,
        )

    # ------------------------------------------------------------------ destination handoff

    def _dispatch_handoff(self, intent: TransactionIntent) -> None:
        dest_vendor = self.model.vendors.get(intent.destination_vendor_id)
        if dest_vendor is None:
            return
        details = TransactionDetails(
            intent_id=intent.intent_id,
            parent_intent_id=intent.parent_intent_id,
            txn_count=intent.txn_count,
            amount=intent.amount,
            currency=intent.currency,
            value_date_policy=intent.value_date_policy,
            value_date_offset_days=intent.value_date_offset_days,
        )
        dest_vendor.handle_transact_from_vendor(
            client_id=intent.source_product_id and getattr(self.model.vendors.get(
                _vendor_of_product(self.model, intent.source_product_id)), "vendor_id", "")
            or "",
            product_id=intent.destination_product_id,
            details=details,
        )
        # Run destination product's profile against this routed intent (its outgoing
        # intent id becomes a trigger inside the destination profile).
        dest_product = dest_vendor.products.get(intent.destination_product_id)
        if dest_product is None or dest_product.cfg_profile_id is None:
            return
        dest_profile = self._profile_index.get(dest_product.cfg_profile_id)
        if dest_profile is None:
            return
        dest_resolver = RoleResolver(dest_product.cfg_role_bindings)
        # Trigger pool at destination: the routed intent_id.
        dest_triggers = {intent.intent_id: (intent.txn_count, intent.amount)}
        self._run_profile_stages(
            profile=dest_profile,
            owning_product=dest_product,
            owning_vendor_id=dest_vendor.vendor_id,
            resolver=dest_resolver,
            tick_id=intent.tick_id,
            simulation_date=intent.simulation_date,
            trigger_amounts=dest_triggers,
        )

    # ------------------------------------------------------------------ profile stages

    def _run_profile_stages(self,
                            profile: PipelineProfileConfig,
                            owning_product: GenericProduct,
                            owning_vendor_id: str,
                            resolver: RoleResolver,
                            tick_id: int,
                            simulation_date: _date_t,
                            trigger_amounts: dict[str, tuple[int, float]]) -> None:
        """Stages 2-4 against the given trigger pool."""
        cal = self._calendar_for_vendor(owning_vendor_id)
        # 2. Fees in declared sequence/fee order (deterministic).
        fee_amounts: dict[str, tuple[int, float]] = {}
        for seq in profile.fee_sequences:
            for fee_cfg in seq.fees:
                # Aggregate across all matched triggers.
                total_count = 0
                total_basis = 0.0
                for tid in fee_cfg.trigger_ids:
                    if tid in trigger_amounts:
                        c, a = trigger_amounts[tid]
                        total_count += c
                        total_basis += a
                    elif tid in fee_amounts:
                        c, a = fee_amounts[tid]
                        total_count += c
                        total_basis += a
                if total_count == 0 and total_basis == 0:
                    continue
                fee = self._compute_fee(
                    fee_cfg=fee_cfg,
                    sequence_id=seq.sequence_id,
                    profile=profile,
                    owning_product=owning_product,
                    owning_vendor_id=owning_vendor_id,
                    resolver=resolver,
                    tick_id=tick_id,
                    simulation_date=simulation_date,
                    txn_count=total_count,
                    amount_basis=total_basis,
                    calendar=cal,
                )
                if fee is None:
                    continue
                fee_amounts[fee_cfg.fee_id] = (total_count, fee.fee_amount)
                self._emit_fee(fee)
                # If deferred settlement, queue invoice.
                if fee.settlement_trigger_event == "invoice_transaction_event":
                    self._open_invoices.append(_OpenInvoice(fee=fee))

        # 3. Postings.
        for rule in profile.posting_rules:
            self._maybe_post(rule, profile, owning_product, resolver, tick_id, simulation_date,
                             trigger_amounts, fee_amounts, cal)

        # 4. Asset transfers.
        for rule in profile.asset_transfer_rules:
            self._maybe_transfer(rule, profile, owning_product, resolver, tick_id, simulation_date,
                                 trigger_amounts, fee_amounts, cal)

    # ------------------------------------------------------------------ fee computation

    def _compute_fee(self,
                     fee_cfg: FeeConfig,
                     sequence_id: str,
                     profile: PipelineProfileConfig,
                     owning_product: GenericProduct,
                     owning_vendor_id: str,
                     resolver: RoleResolver,
                     tick_id: int,
                     simulation_date: _date_t,
                     txn_count: int,
                     amount_basis: float,
                     calendar: Optional[Calendar]) -> Optional[FeeAccrual]:
        sim = self.cfg.simulation
        fixed = 0.0
        if fee_cfg.count_cost is not None:
            fixed = float(fee_cfg.count_cost.amount) * float(txn_count)
        percent = 0.0
        if fee_cfg.amount_percentage is not None:
            percent = float(fee_cfg.amount_percentage) * float(amount_basis)
        total = round_amount(fixed + percent, sim.amount_scale_dp, sim.amount_rounding_mode)

        try:
            beneficiary = resolver.resolve(fee_cfg.beneficiary_role)
        except RoleResolutionError:
            return None
        beneficiary_product_id: Optional[str] = None
        if fee_cfg.beneficiary_product_role:
            try:
                bp = resolver.resolve(fee_cfg.beneficiary_product_role)
                beneficiary_product_id = bp.product_id
            except RoleResolutionError:
                pass

        currency = (fee_cfg.count_cost.currency if fee_cfg.count_cost else self.default_currency)
        try:
            due = resolve_value_date(
                simulation_date,
                fee_cfg.settlement_value_date_policy,
                fee_cfg.settlement_value_date_offset_days,
                calendar=calendar,
            )
        except Exception:
            due = simulation_date

        return FeeAccrual(
            fee_id=fee_cfg.fee_id,
            sequence_id=sequence_id,
            tick_id=tick_id,
            simulation_date=simulation_date,
            pipeline_profile_id=profile.pipeline_profile_id,
            product_id=owning_product.product_id,
            trigger_id=fee_cfg.trigger_ids[0] if fee_cfg.trigger_ids else "",
            beneficiary_role=fee_cfg.beneficiary_role,
            beneficiary_agent_id=beneficiary.agent_id or owning_vendor_id,
            beneficiary_product_id=beneficiary_product_id or owning_product.product_id,
            payer_role=None,
            payer_agent_id=None,
            txn_count_basis=int(txn_count),
            amount_basis=round_amount(amount_basis, sim.amount_scale_dp, sim.amount_rounding_mode),
            fixed_component=round_amount(fixed, sim.amount_scale_dp, sim.amount_rounding_mode),
            percent_component=round_amount(percent, sim.amount_scale_dp, sim.amount_rounding_mode),
            fee_amount=total,
            currency=currency,
            settlement_value_date_policy=fee_cfg.settlement_value_date_policy,
            settlement_value_date_offset_days=fee_cfg.settlement_value_date_offset_days,
            settlement_due_date=due,
            settlement_trigger_event=fee_cfg.settlement_trigger_event,
            status="accrued",
        )

    # ------------------------------------------------------------------ posting / transfer

    def _maybe_post(self,
                    rule: PostingRuleConfig,
                    profile: PipelineProfileConfig,
                    owning_product: GenericProduct,
                    resolver: RoleResolver,
                    tick_id: int,
                    simulation_date: _date_t,
                    trigger_amounts: dict[str, tuple[int, float]],
                    fee_amounts: dict[str, tuple[int, float]],
                    calendar: Optional[Calendar]) -> None:
        amt = self._amount_for_trigger(rule.trigger_id, rule.amount_basis,
                                       trigger_amounts, fee_amounts)
        if amt is None:
            return
        ledger_paths = {l.ledger_ref: l.path_pattern for l in profile.ledger_construction}
        try:
            src = resolver.expand_path(ledger_paths[rule.source_ledger_ref])
            dst = resolver.expand_path(ledger_paths[rule.destination_ledger_ref])
        except (KeyError, RoleResolutionError):
            return
        try:
            v_date = resolve_value_date(simulation_date, rule.value_date_policy,
                                        rule.value_date_offset_days, calendar=calendar)
        except Exception:
            v_date = simulation_date
        sim = self.cfg.simulation
        posting = PostingEntry(
            posting_id=f"post_{profile.pipeline_profile_id}_{rule.trigger_id}_{tick_id}",
            tick_id=tick_id,
            simulation_date=simulation_date,
            pipeline_profile_id=profile.pipeline_profile_id,
            product_id=owning_product.product_id,
            trigger_id=rule.trigger_id,
            source_ledger_ref=rule.source_ledger_ref,
            destination_ledger_ref=rule.destination_ledger_ref,
            source_ledger_path=src,
            destination_ledger_path=dst,
            amount=round_amount(amt, sim.amount_scale_dp, sim.amount_rounding_mode),
            currency=self.default_currency,
            value_date_policy=rule.value_date_policy,
            resolved_value_date=v_date,
            status="posted",
        )
        self._emit_posting(posting)

    def _maybe_transfer(self,
                        rule: AssetTransferRuleConfig,
                        profile: PipelineProfileConfig,
                        owning_product: GenericProduct,
                        resolver: RoleResolver,
                        tick_id: int,
                        simulation_date: _date_t,
                        trigger_amounts: dict[str, tuple[int, float]],
                        fee_amounts: dict[str, tuple[int, float]],
                        calendar: Optional[Calendar]) -> None:
        amt = self._amount_for_trigger(rule.trigger_id, rule.amount_basis,
                                       trigger_amounts, fee_amounts)
        if amt is None:
            return
        container_paths = {c.container_ref: c.path_pattern for c in profile.value_container_construction}
        try:
            src = resolver.expand_path(container_paths[rule.source_container_ref])
            dst = resolver.expand_path(container_paths[rule.destination_container_ref])
        except (KeyError, RoleResolutionError):
            return
        try:
            v_date = resolve_value_date(simulation_date, rule.value_date_policy,
                                        rule.value_date_offset_days, calendar=calendar)
        except Exception:
            v_date = simulation_date
        sim = self.cfg.simulation
        transfer = AssetTransfer(
            transfer_id=f"xfer_{profile.pipeline_profile_id}_{rule.trigger_id}_{tick_id}",
            tick_id=tick_id,
            simulation_date=simulation_date,
            pipeline_profile_id=profile.pipeline_profile_id,
            product_id=owning_product.product_id,
            trigger_id=rule.trigger_id,
            source_container_ref=rule.source_container_ref,
            destination_container_ref=rule.destination_container_ref,
            source_container_path=src,
            destination_container_path=dst,
            amount=round_amount(amt, sim.amount_scale_dp, sim.amount_rounding_mode),
            currency=self.default_currency,
            value_date_policy=rule.value_date_policy,
            resolved_value_date=v_date,
            status="executed",
        )
        self._emit_transfer(transfer)

    @staticmethod
    def _amount_for_trigger(trigger_id: str,
                            amount_basis: str,
                            trigger_amounts: dict[str, tuple[int, float]],
                            fee_amounts: dict[str, tuple[int, float]]) -> Optional[float]:
        if amount_basis == "fee_amount":
            if trigger_id in fee_amounts:
                return fee_amounts[trigger_id][1]
            return None
        # default: transaction_intent_amount
        if trigger_id in trigger_amounts:
            return trigger_amounts[trigger_id][1]
        if trigger_id in fee_amounts:
            return fee_amounts[trigger_id][1]
        return None

    # ------------------------------------------------------------------ invoice resolution

    def _resolve_due_invoices(self, tick_id: int, simulation_date: _date_t) -> None:
        """Emit invoice + direct-payment settlement for each open invoice whose
        due_date == today. Per ADR-0002 netting is out of scope; mode='paid'."""
        still_open: list[_OpenInvoice] = []
        for inv in self._open_invoices:
            if inv.fee.settlement_due_date == simulation_date:
                event = InvoiceEvent(
                    invoice_id=inv.invoice_id,
                    tick_id=tick_id,
                    simulation_date=simulation_date,
                    pipeline_profile_id=inv.fee.pipeline_profile_id,
                    beneficiary_product_id=inv.fee.beneficiary_product_id or inv.fee.product_id,
                    payer_agent_id=inv.fee.payer_agent_id or "",
                    payer_product_id=inv.fee.payer_product_id if hasattr(inv.fee, "payer_product_id") else None,
                    fee_id=inv.fee.fee_id,
                    accrual_tick_id=inv.fee.tick_id,
                    accrual_date=inv.fee.simulation_date,
                    amount=inv.fee.fee_amount,
                    currency=inv.fee.currency,
                    status="invoiced",
                )
                self._emit_invoice(event)
                resolution = SettlementResolution(
                    invoice_id=inv.invoice_id,
                    tick_id=tick_id,
                    simulation_date=simulation_date,
                    pipeline_profile_id=inv.fee.pipeline_profile_id,
                    beneficiary_product_id=event.beneficiary_product_id,
                    payer_agent_id=event.payer_agent_id,
                    payer_product_id=event.payer_product_id,
                    fee_id=event.fee_id,
                    settled_amount=event.amount,
                    residual_amount=0.0,
                    currency=event.currency,
                    mode="paid",
                    final_status="paid",
                )
                self._emit_settlement(resolution)
            else:
                still_open.append(inv)
        self._open_invoices = still_open

    # ------------------------------------------------------------------ intent helpers

    def _materialize_intent(self,
                            profile: PipelineProfileConfig,
                            source_product: GenericProduct,
                            source_vendor_id: str,
                            parent_intent_id: str,
                            dest: TransactionDestinationConfig,
                            resolver: RoleResolver,
                            txn_count: int,
                            amount: float,
                            tick_id: int,
                            simulation_date: _date_t) -> Optional[TransactionIntent]:
        try:
            resolved = resolver.resolve(dest.destination_role)
        except RoleResolutionError:
            return None
        if resolved.local:
            return None  # local sink — no inter-product handoff
        # Determine destination vendor + product.
        dest_product_id = resolved.product_id
        dest_vendor_id = resolved.agent_id
        if dest_product_id is None and dest_vendor_id is not None:
            dest_vendor_id_resolved = dest_vendor_id
        elif dest_product_id is not None:
            dest_vendor_id_resolved = _vendor_of_product(self.model, dest_product_id)
            if dest_vendor_id_resolved is None:
                return None
        else:
            return None
        cal = self._calendar_for_vendor(source_vendor_id)
        try:
            v_date = resolve_value_date(simulation_date, dest.value_date_policy,
                                        dest.value_date_offset_days, calendar=cal)
        except Exception:
            v_date = simulation_date
        sim = self.cfg.simulation
        return TransactionIntent(
            intent_id=dest.outgoing_intent_id,
            parent_intent_id=parent_intent_id,
            tick_id=tick_id,
            simulation_date=simulation_date,
            pipeline_profile_id=profile.pipeline_profile_id,
            source_product_id=source_product.product_id,
            destination_role=dest.destination_role,
            destination_product_id=dest_product_id or "",
            destination_vendor_id=dest_vendor_id_resolved,
            txn_count=int(txn_count),
            amount=round_amount(amount, sim.amount_scale_dp, sim.amount_rounding_mode),
            currency=self.default_currency,
            value_date_policy=dest.value_date_policy,
            value_date_offset_days=dest.value_date_offset_days,
            resolved_value_date=v_date,
        )

    def _calendar_for_vendor(self, vendor_id: str) -> Optional[Calendar]:
        # Vendor's region_id determines the calendar; lookup helper is provided by engine.
        try:
            return self.calendar_lookup(vendor_id)
        except Exception:
            return None

    # ------------------------------------------------------------------ emit shims

    def _emit_intent(self, i: TransactionIntent) -> None:
        self.emit("transaction_intent_event", {
            "tick_id": i.tick_id,
            "simulation_date": i.simulation_date.isoformat(),
            "pipeline_profile_id": i.pipeline_profile_id,
            "product_id": i.source_product_id,
            "intent_id": i.intent_id,
            "parent_intent_id": i.parent_intent_id,
            "destination_role": i.destination_role,
            "destination_product_id": i.destination_product_id,
            "destination_vendor_id": i.destination_vendor_id,
            "txn_count": i.txn_count,
            "amount": {"amount": f"{i.amount:.2f}", "currency": i.currency},
            "value_date_policy": i.value_date_policy,
            "resolved_value_date": i.resolved_value_date.isoformat(),
        })

    def _emit_fee(self, f: FeeAccrual) -> None:
        self.emit("fee_accrual_event", {
            "tick_id": f.tick_id,
            "simulation_date": f.simulation_date.isoformat(),
            "pipeline_profile_id": f.pipeline_profile_id,
            "product_id": f.product_id,
            "fee_id": f.fee_id,
            "trigger_id": f.trigger_id,
            "beneficiary_role": f.beneficiary_role,
            "beneficiary_agent_id": f.beneficiary_agent_id,
            "beneficiary_product_id": f.beneficiary_product_id,
            "txn_count_basis": f.txn_count_basis,
            "amount_basis": {"amount": f"{f.amount_basis:.2f}", "currency": f.currency},
            "fixed_component": {"amount": f"{f.fixed_component:.2f}", "currency": f.currency},
            "percent_component": {"amount": f"{f.percent_component:.2f}", "currency": f.currency},
            "fee_amount": {"amount": f"{f.fee_amount:.2f}", "currency": f.currency},
            "settlement_value_date_policy": f.settlement_value_date_policy,
            "settlement_due_date": f.settlement_due_date.isoformat(),
            "status": f.status,
        })

    def _emit_posting(self, p: PostingEntry) -> None:
        self.emit("posting_entry_event", {
            "tick_id": p.tick_id,
            "simulation_date": p.simulation_date.isoformat(),
            "pipeline_profile_id": p.pipeline_profile_id,
            "product_id": p.product_id,
            "trigger_id": p.trigger_id,
            "posting_id": p.posting_id,
            "source_ledger_ref": p.source_ledger_ref,
            "destination_ledger_ref": p.destination_ledger_ref,
            "source_ledger_path": p.source_ledger_path,
            "destination_ledger_path": p.destination_ledger_path,
            "amount": {"amount": f"{p.amount:.2f}", "currency": p.currency},
            "value_date_policy": p.value_date_policy,
            "resolved_value_date": p.resolved_value_date.isoformat(),
            "status": p.status,
        })

    def _emit_transfer(self, t: AssetTransfer) -> None:
        self.emit("value_transfer_event", {
            "tick_id": t.tick_id,
            "simulation_date": t.simulation_date.isoformat(),
            "pipeline_profile_id": t.pipeline_profile_id,
            "product_id": t.product_id,
            "trigger_id": t.trigger_id,
            "transfer_id": t.transfer_id,
            "source_container_ref": t.source_container_ref,
            "destination_container_ref": t.destination_container_ref,
            "source_container_path": t.source_container_path,
            "destination_container_path": t.destination_container_path,
            "amount": {"amount": f"{t.amount:.2f}", "currency": t.currency},
            "value_date_policy": t.value_date_policy,
            "resolved_value_date": t.resolved_value_date.isoformat(),
            "status": t.status,
        })

    def _emit_invoice(self, i: InvoiceEvent) -> None:
        self.emit("invoice_transaction_event", {
            "tick_id": i.tick_id,
            "simulation_date": i.simulation_date.isoformat(),
            "pipeline_profile_id": i.pipeline_profile_id,
            "product_id": i.beneficiary_product_id,
            "invoice_id": i.invoice_id,
            "fee_id": i.fee_id,
            "accrual_tick_id": i.accrual_tick_id,
            "accrual_date": i.accrual_date.isoformat(),
            "beneficiary_product_id": i.beneficiary_product_id,
            "payer_agent_id": i.payer_agent_id,
            "payer_product_id": i.payer_product_id,
            "amount": {"amount": f"{i.amount:.2f}", "currency": i.currency},
            "status": i.status,
        })

    def _emit_settlement(self, r: SettlementResolution) -> None:
        self.emit("settlement_resolution_event", {
            "tick_id": r.tick_id,
            "simulation_date": r.simulation_date.isoformat(),
            "pipeline_profile_id": r.pipeline_profile_id,
            "product_id": r.beneficiary_product_id,
            "invoice_id": r.invoice_id,
            "fee_id": r.fee_id,
            "beneficiary_product_id": r.beneficiary_product_id,
            "payer_agent_id": r.payer_agent_id,
            "payer_product_id": r.payer_product_id,
            "settled_amount": {"amount": f"{r.settled_amount:.2f}", "currency": r.currency},
            "residual_amount": {"amount": f"{r.residual_amount:.2f}", "currency": r.currency},
            "mode": r.mode,
            "final_status": r.final_status,
        })


# --------------------------------------------------------------------------- helpers

def cfg_pipeline_runtime(cfg: PrototypeConfig) -> bool:
    return bool(cfg.pipeline is not None and cfg.pipeline.is_runtime)


def _vendor_of_product(model, product_id: str) -> Optional[str]:
    for vid, v in model.vendors.items():
        if product_id in v.products:
            return vid
    return None
