"""Pipeline executor — v3_runtime / v4 semantics.

Deterministic stage order per spec 30 §v3_runtime:
    intents -> fees -> postings -> asset transfers -> retention/invoice lifecycle

V4 extensions (per spec 33 §Fan-out completion semantics + §Invoice and
settlement lifecycle, gated under current `v3_runtime` schema per spec 73):

1. Routing completion semantics
   - destinations declare `routing_completion_mode` (synchronous | asynchronous;
     default synchronous); loader enforces same_day for synchronous legs
     (`E_SYNC_LEG_VALUE_DATE_INVALID`).
   - synchronous legs: root-blocking; planning pre-computes `root_ok = all
     synchronous legs can accept`. Commit only happens if root_ok; otherwise
     destination state is left untouched and each sync leg is emitted as
     rejected.
   - asynchronous legs: emitted as `pending` at origin tick; enqueued for
     resolution on/after the leg's `resolved_value_date`. Root outcome is
     decided from synchronous legs only — async outcomes never retroactively
     flip an already-resolved root.
   - graph recursion: when a synchronous destination has its own profile with
     `transaction_intents`, planning recursively evaluates that destination's
     synchronous sub-legs; if any sub-sync-dependency fails, the parent leg is
     treated as rejected (`SYNC_SUBDEP_FAILED`).

2. Root intent emission (spec 33 §Transaction-intent log visibility)
   - For each declared intent_cfg the source profile emits an `original_incoming`
     event with final status computed from synchronous dependencies.
   - Routed derivatives carry the same `root_intent_id` as the original and
     explicit `routing_completion_mode`, `status`, and `reason_code` fields.

3. Invoice + settlement lifecycle
   - Fees with `settlement_trigger_event = invoice_transaction_event` queue
     into an aggregation table keyed by `(fee_id, beneficiary_agent_id,
     beneficiary_product_id, payer_agent_id, settlement_due_date, currency)`.
   - On tick whose `simulation_date == settlement_due_date`, emit exactly one
     `invoice_transaction_event` per aggregation group (total = sum of
     components), then one `settlement_resolution_event` per group with final
     status `paid` and residual 0 under the direct-payment default.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
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


_INTENT_NS = uuid.UUID("00000000-0000-0000-0000-000000000033")  # spec 33 namespace


# --------------------------------------------------------------------------- internal plans

@dataclass
class _SyncLegPlan:
    """Planning result for a sync destination leg (pre-commit, pure)."""
    intent: TransactionIntent
    accepted: bool
    reason_code: str


@dataclass
class _AsyncLegPlan:
    """Pending async leg produced at origin tick; committed on resolution tick."""
    intent: TransactionIntent


@dataclass
class _RootPlan:
    """Aggregated plan for a single intent_cfg (root intent)."""
    root_cfg_id: str
    original_intent: TransactionIntent
    sync_legs: list[_SyncLegPlan]
    async_legs: list[_AsyncLegPlan]

    @property
    def root_ok(self) -> bool:
        # Root success = all synchronous legs individually accepted AND their
        # synchronous sub-paths all accepted (the sub-path recursion is baked
        # into sync_legs[].accepted during _plan_sync_leg).
        return all(leg.accepted for leg in self.sync_legs)

    @property
    def first_fail_reason(self) -> str:
        for leg in self.sync_legs:
            if not leg.accepted:
                return leg.reason_code
        return "OK"


@dataclass
class _PendingAsync:
    """Async leg awaiting resolution on or after its resolved_value_date."""
    intent: TransactionIntent
    source_vendor_id: str
    source_product_id: str


@dataclass
class _InvoiceGroup:
    """Aggregates multiple accrued fees that share (fee_id, beneficiary, payer, due_date).

    Spec 33 §Invoice and settlement lifecycle: one aggregated invoice per group
    on the due date — not one invoice per component fee.
    """
    key: tuple  # (fee_id, beneficiary_agent_id, beneficiary_product_id, payer_agent_id, settlement_due_date, currency)
    invoice_id: str
    pipeline_profile_id: str
    beneficiary_product_id: str
    payer_agent_id: str
    payer_product_id: Optional[str]
    fee_id: str
    settlement_due_date: _date_t
    currency: str
    total_amount: float = 0.0
    component_count: int = 0
    component_tick_ids: list[int] = field(default_factory=list)
    earliest_tick_id: Optional[int] = None
    earliest_date: Optional[_date_t] = None


# --------------------------------------------------------------------------- executor


class PipelineExecutor:
    """Runs pipeline stages for a single tick.

    State retained across ticks:
    - `_pending_async`: async legs awaiting resolution.
    - `_invoice_groups`: aggregation table for deferred-settlement fees.
    """

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
        self.emit = emit
        self._profile_index = self._index_profiles(cfg)
        self._pending_async: list[_PendingAsync] = []
        self._invoice_groups: dict[tuple, _InvoiceGroup] = {}

    @staticmethod
    def _index_profiles(cfg: PrototypeConfig) -> dict[str, PipelineProfileConfig]:
        if cfg.pipeline is None:
            return {}
        return {p.pipeline_profile_id: p for p in cfg.pipeline.pipeline_profiles}

    @property
    def is_runtime(self) -> bool:
        return cfg_pipeline_runtime(self.cfg)

    # ------------------------------------------------------------------ per-tick entrypoint

    def run_post_adjudication(self,
                              outcomes: list[ActionOutcome],
                              tick_id: int,
                              simulation_date: _date_t) -> None:
        """Run v3_runtime / v4 pipeline stages for a tick (spec 30 §v3_runtime)."""
        if not self.is_runtime:
            return

        # 1. Resolve async legs from prior ticks whose value date has arrived
        # (before processing new outcomes so cross-tick resolution is observable
        # at the top of the tick stream per spec 52 §Ordering requirement).
        self._resolve_pending_async(tick_id, simulation_date)

        # 2. Process new source outcomes (original + routed intents, source stages).
        sorted_outcomes = sorted(
            (o for o in outcomes
             if o.action_type == "Transact" and o.successful_txn_count > 0),
            key=lambda o: (o.vendor_id, o.product_id, o.pop_id),
        )
        for o in sorted_outcomes:
            self._process_outcome(o, tick_id, simulation_date)

        # 3. Same-tick async resolution: any pending async intent whose
        # resolved_value_date == today resolves within the same tick AFTER the
        # root already resolved (async never flips root — spec 33 v4).
        self._resolve_pending_async(tick_id, simulation_date)

        # 4. End-of-tick: invoice + settlement aggregation for groups whose
        # due date has arrived.
        self._emit_due_invoices_aggregated(tick_id, simulation_date)

    # ------------------------------------------------------------------ outcome -> routing plan

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
        txn_count = int(round(outcome.successful_txn_count))
        amount = float(outcome.successful_total_amount)

        # Local trigger pool for source-profile stages. Only successfully-rooted
        # intents contribute (spec 33 v4 §Root intent success-gating).
        local_trigger_amounts: dict[str, tuple[int, float]] = {}

        for root_cfg in sorted(profile.transaction_intents, key=lambda i: i.intent_id):
            plan = self._plan_root(
                root_cfg=root_cfg,
                profile=profile,
                source_product=product,
                source_vendor_id=vendor.vendor_id,
                resolver=resolver,
                txn_count=txn_count,
                amount=amount,
                tick_id=tick_id,
                simulation_date=simulation_date,
            )
            self._commit_root(plan)
            if plan.root_ok:
                local_trigger_amounts[root_cfg.intent_id] = (txn_count, amount)
                for leg in plan.sync_legs:
                    if leg.accepted:
                        local_trigger_amounts[leg.intent.intent_id] = (
                            leg.intent.txn_count, leg.intent.amount
                        )

        # Source profile stages — fees / postings / transfers anchored on the
        # accumulated trigger pool (roots that resolved OK only).
        self._run_profile_stages(
            profile=profile,
            owning_product=product,
            owning_vendor_id=vendor.vendor_id,
            resolver=resolver,
            tick_id=tick_id,
            simulation_date=simulation_date,
            trigger_amounts=local_trigger_amounts,
        )

    # ------------------------------------------------------------------ root planning (recursive)

    def _plan_root(self,
                   root_cfg,
                   profile: PipelineProfileConfig,
                   source_product: GenericProduct,
                   source_vendor_id: str,
                   resolver: RoleResolver,
                   txn_count: int,
                   amount: float,
                   tick_id: int,
                   simulation_date: _date_t) -> _RootPlan:
        original = self._materialize_original_intent(
            profile=profile,
            source_product=source_product,
            intent_cfg_id=root_cfg.intent_id,
            txn_count=txn_count,
            amount=amount,
            tick_id=tick_id,
            simulation_date=simulation_date,
        )
        sync_legs: list[_SyncLegPlan] = []
        async_legs: list[_AsyncLegPlan] = []
        for dest in sorted(root_cfg.destinations,
                           key=lambda d: (d.destination_role, d.outgoing_intent_id)):
            intent = self._materialize_intent(
                profile=profile,
                source_product=source_product,
                source_vendor_id=source_vendor_id,
                parent_intent_id=root_cfg.intent_id,
                root_intent_id=root_cfg.intent_id,
                dest=dest,
                resolver=resolver,
                txn_count=txn_count,
                amount=amount,
                tick_id=tick_id,
                simulation_date=simulation_date,
            )
            if intent is None:
                continue
            if dest.routing_completion_mode == "synchronous":
                accepted, reason = self._plan_sync_leg(intent)
                sync_legs.append(_SyncLegPlan(intent=intent, accepted=accepted, reason_code=reason))
            else:
                async_legs.append(_AsyncLegPlan(intent=intent))
        return _RootPlan(
            root_cfg_id=root_cfg.intent_id,
            original_intent=original,
            sync_legs=sync_legs,
            async_legs=async_legs,
        )

    def _plan_sync_leg(self, intent: TransactionIntent) -> tuple[bool, str]:
        """Dry-run acceptance for a sync leg, recursing through destination sync sub-legs.

        Spec 33 v4: "synchronous dependency evaluation is graph-recursive (whole
        synchronous path must succeed)". Returns (accepted, reason_code).
        """
        accepted, reason = self._peek_destination_acceptance(intent)
        if not accepted:
            return False, reason
        dest_product, dest_profile = self._destination_context(intent)
        if dest_product is None or dest_profile is None:
            # Destination accepted upstream but has no profile — no sub-deps.
            return True, "OK_UPSTREAM"
        # Recurse on destination's sync-outgoing legs (if any). Async sub-legs
        # never block the parent leg's outcome.
        for sub_cfg in sorted(dest_profile.transaction_intents, key=lambda i: i.intent_id):
            for sub_dest in sorted(sub_cfg.destinations,
                                   key=lambda d: (d.destination_role, d.outgoing_intent_id)):
                if sub_dest.routing_completion_mode != "synchronous":
                    continue
                sub_resolver = RoleResolver(dest_product.cfg_role_bindings)
                sub_intent = self._materialize_intent(
                    profile=dest_profile,
                    source_product=dest_product,
                    source_vendor_id=intent.destination_vendor_id,
                    parent_intent_id=sub_cfg.intent_id,
                    root_intent_id=sub_cfg.intent_id,
                    dest=sub_dest,
                    resolver=sub_resolver,
                    txn_count=intent.txn_count,
                    amount=intent.amount,
                    tick_id=intent.tick_id,
                    simulation_date=intent.simulation_date,
                )
                if sub_intent is None:
                    continue
                sub_ok, sub_reason = self._plan_sync_leg(sub_intent)
                if not sub_ok:
                    return False, f"SYNC_SUBDEP_FAILED:{sub_reason}"
        return True, "OK_UPSTREAM"

    def _peek_destination_acceptance(self, intent: TransactionIntent) -> tuple[bool, str]:
        """Evaluate destination gate *without* mutating state.

        Mirrors the checks in `VendorAgent.handle_transact_from_vendor` /
        `Product.transact_product_from_upstream` so the plan phase can decide
        root success without committing destination counters until the plan is
        approved.
        """
        dest_vendor = self.model.vendors.get(intent.destination_vendor_id)
        if dest_vendor is None:
            return False, "DESTINATION_VENDOR_NOT_FOUND"
        if not dest_vendor.operational:
            return False, "VENDOR_NOT_OPERATIONAL"
        dest_product = dest_vendor.products.get(intent.destination_product_id)
        if dest_product is None:
            return False, "PRODUCT_NOT_FOUND"
        if not dest_product.accepting_transact:
            return False, "TRANSACT_CLOSED"
        return True, "OK_UPSTREAM"

    def _destination_context(self,
                              intent: TransactionIntent) -> tuple[Optional[GenericProduct], Optional[PipelineProfileConfig]]:
        dest_vendor = self.model.vendors.get(intent.destination_vendor_id)
        if dest_vendor is None:
            return None, None
        dest_product = dest_vendor.products.get(intent.destination_product_id)
        if dest_product is None:
            return None, None
        if dest_product.cfg_profile_id is None:
            return dest_product, None
        return dest_product, self._profile_index.get(dest_product.cfg_profile_id)

    # ------------------------------------------------------------------ commit phase

    def _commit_root(self, plan: _RootPlan) -> None:
        """Emit original + routed events and run destination-side stages for
        each accepted sync leg when root_ok. Always schedule async legs."""
        root_ok = plan.root_ok
        orig_status = "executed" if root_ok else "rejected"
        orig_reason = "OK" if root_ok else plan.first_fail_reason
        original = replace(plan.original_intent, status=orig_status, reason_code=orig_reason)
        self._emit_intent(original)

        for leg in plan.sync_legs:
            if root_ok and leg.accepted:
                # Commit destination handoff + run destination stages (which
                # may recursively trigger destination's own routing + stages).
                self._commit_sync_leg(leg.intent)
                self._emit_intent(replace(leg.intent, status="executed",
                                           reason_code=leg.reason_code))
            else:
                # Root failed (possibly because of a sibling); this leg is
                # rejected at the observability layer. No destination state
                # mutation (state stays intact because we used peek).
                if leg.accepted and not root_ok:
                    reason = "SIBLING_SYNC_LEG_FAILED"
                else:
                    reason = leg.reason_code
                self._emit_intent(replace(leg.intent, status="rejected",
                                           reason_code=reason))

        for leg in plan.async_legs:
            # Emit pending at origin tick + enqueue for resolution.
            pending = replace(leg.intent, status="pending", reason_code="OK")
            self._emit_intent(pending)
            source_vendor_id = _vendor_of_product(self.model, leg.intent.source_product_id) or ""
            self._pending_async.append(_PendingAsync(
                intent=leg.intent,
                source_vendor_id=source_vendor_id,
                source_product_id=leg.intent.source_product_id,
            ))

    def _commit_sync_leg(self, intent: TransactionIntent) -> None:
        """Commit the destination Transact() call + run destination profile stages."""
        dest_vendor = self.model.vendors.get(intent.destination_vendor_id)
        if dest_vendor is None:
            return
        source_vendor_id = _vendor_of_product(self.model, intent.source_product_id) or ""
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
            client_id=source_vendor_id,
            product_id=intent.destination_product_id,
            details=details,
        )
        self._run_destination_stages(intent)

    def _run_destination_stages(self, intent: TransactionIntent) -> None:
        dest_product, dest_profile = self._destination_context(intent)
        if dest_product is None or dest_profile is None:
            return
        dest_resolver = RoleResolver(dest_product.cfg_role_bindings)
        dest_triggers: dict[str, tuple[int, float]] = {
            intent.intent_id: (intent.txn_count, intent.amount),
        }
        self._run_profile_stages(
            profile=dest_profile,
            owning_product=dest_product,
            owning_vendor_id=intent.destination_vendor_id,
            resolver=dest_resolver,
            tick_id=intent.tick_id,
            simulation_date=intent.simulation_date,
            trigger_amounts=dest_triggers,
        )

    # ------------------------------------------------------------------ async resolution

    def _resolve_pending_async(self,
                                tick_id: int,
                                simulation_date: _date_t) -> None:
        """Resolve pending async legs whose resolved_value_date <= simulation_date.

        Spec 52 §Ordering requirement (async): resolution tick emits routed
        intent as executed or rejected; destination stages follow if executed.
        Preserves `intent_id` + `root_intent_id` from origin tick for
        correlation continuity (spec 33 v4 §Correlation requirements).
        """
        if not self._pending_async:
            return
        still_pending: list[_PendingAsync] = []
        # Deterministic order: by (resolved_value_date, root_intent_id, intent_id,
        # destination_product_id) so replays emit identical streams.
        due_now: list[_PendingAsync] = []
        for p in self._pending_async:
            if p.intent.resolved_value_date <= simulation_date:
                due_now.append(p)
            else:
                still_pending.append(p)
        due_now.sort(key=lambda p: (p.intent.resolved_value_date,
                                     p.intent.root_intent_id,
                                     p.intent.intent_id,
                                     p.intent.destination_product_id))
        self._pending_async = still_pending
        for p in due_now:
            # Re-check destination gate at resolution time.
            accepted, reason = self._peek_destination_acceptance(p.intent)
            if accepted:
                # Commit handoff with updated tick_id / simulation_date so
                # destination stages carry resolution-tick context.
                resolved_intent = replace(
                    p.intent,
                    tick_id=tick_id,
                    simulation_date=simulation_date,
                    status="executed",
                    reason_code="OK_UPSTREAM",
                )
                self._emit_intent(resolved_intent)
                self._commit_sync_leg(resolved_intent)
            else:
                rejected_intent = replace(
                    p.intent,
                    tick_id=tick_id,
                    simulation_date=simulation_date,
                    status="rejected",
                    reason_code=reason,
                )
                self._emit_intent(rejected_intent)

    # ------------------------------------------------------------------ destination / source stages

    def _run_profile_stages(self,
                            profile: PipelineProfileConfig,
                            owning_product: GenericProduct,
                            owning_vendor_id: str,
                            resolver: RoleResolver,
                            tick_id: int,
                            simulation_date: _date_t,
                            trigger_amounts: dict[str, tuple[int, float]]) -> None:
        """Stages 2-4 of v3_runtime (fees / postings / transfers)."""
        cal = self._calendar_for_vendor(owning_vendor_id)
        fee_amounts: dict[str, tuple[int, float]] = {}
        for seq in profile.fee_sequences:
            for fee_cfg in seq.fees:
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
                # Deferred-settlement fees fold into the aggregation table.
                if fee.settlement_trigger_event == "invoice_transaction_event":
                    self._queue_invoice_component(fee)

        for rule in profile.posting_rules:
            self._maybe_post(rule, profile, owning_product, resolver, tick_id,
                             simulation_date, trigger_amounts, fee_amounts, cal)

        for rule in profile.asset_transfer_rules:
            self._maybe_transfer(rule, profile, owning_product, resolver, tick_id,
                                 simulation_date, trigger_amounts, fee_amounts, cal)

    # ------------------------------------------------------------------ fee / posting / transfer

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

        # Resolve payer role if bound (enables invoice aggregation by payer).
        payer_agent_id: Optional[str] = None
        payer_product_id: Optional[str] = None
        try:
            payer_resolved = resolver.resolve("payer_role")
            payer_agent_id = payer_resolved.agent_id
            payer_product_id = payer_resolved.product_id
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
            payer_role="payer_role" if payer_agent_id else None,
            payer_agent_id=payer_agent_id,
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
        if trigger_id in trigger_amounts:
            return trigger_amounts[trigger_id][1]
        if trigger_id in fee_amounts:
            return fee_amounts[trigger_id][1]
        return None

    # ------------------------------------------------------------------ invoice aggregation (v4)

    def _queue_invoice_component(self, fee: FeeAccrual) -> None:
        """Fold an accrued fee into its aggregation group (spec 33 §Invoice aggregation)."""
        key = (
            fee.fee_id,
            fee.beneficiary_agent_id,
            fee.beneficiary_product_id or "",
            fee.payer_agent_id or "",
            fee.settlement_due_date.isoformat(),
            fee.currency,
        )
        group = self._invoice_groups.get(key)
        if group is None:
            # Deterministic invoice_id built from the group key so replays match.
            invoice_id = (
                f"inv_{fee.fee_id}_"
                f"{fee.settlement_due_date.isoformat()}_"
                f"{fee.beneficiary_product_id or fee.beneficiary_agent_id or 'self'}_"
                f"{fee.payer_agent_id or 'self'}"
            )
            group = _InvoiceGroup(
                key=key,
                invoice_id=invoice_id,
                pipeline_profile_id=fee.pipeline_profile_id,
                beneficiary_product_id=fee.beneficiary_product_id or fee.product_id,
                payer_agent_id=fee.payer_agent_id or "",
                payer_product_id=None,
                fee_id=fee.fee_id,
                settlement_due_date=fee.settlement_due_date,
                currency=fee.currency,
            )
            self._invoice_groups[key] = group
        sim = self.cfg.simulation
        group.total_amount = round_amount(
            group.total_amount + float(fee.fee_amount),
            sim.amount_scale_dp,
            sim.amount_rounding_mode,
        )
        group.component_count += 1
        group.component_tick_ids.append(fee.tick_id)
        if group.earliest_tick_id is None or fee.tick_id < group.earliest_tick_id:
            group.earliest_tick_id = fee.tick_id
            group.earliest_date = fee.simulation_date

    def _emit_due_invoices_aggregated(self,
                                       tick_id: int,
                                       simulation_date: _date_t) -> None:
        """Emit one aggregate invoice + one settlement per due group (spec 33 v4)."""
        if not self._invoice_groups:
            return
        # Deterministic emission order: sorted by key.
        due_keys = sorted(k for k, g in self._invoice_groups.items()
                          if g.settlement_due_date == simulation_date)
        for key in due_keys:
            group = self._invoice_groups.pop(key)
            invoice = InvoiceEvent(
                invoice_id=group.invoice_id,
                tick_id=tick_id,
                simulation_date=simulation_date,
                pipeline_profile_id=group.pipeline_profile_id,
                beneficiary_product_id=group.beneficiary_product_id,
                payer_agent_id=group.payer_agent_id,
                payer_product_id=group.payer_product_id,
                fee_id=group.fee_id,
                accrual_tick_id=group.earliest_tick_id or tick_id,
                accrual_date=group.earliest_date or simulation_date,
                amount=group.total_amount,
                currency=group.currency,
                status="invoiced",
                component_count=group.component_count,
                component_tick_ids=tuple(sorted(group.component_tick_ids)),
            )
            self._emit_invoice(invoice)
            # Direct-payment settlement (ADR-0002 netting deferred).
            resolution = SettlementResolution(
                invoice_id=invoice.invoice_id,
                tick_id=tick_id,
                simulation_date=simulation_date,
                pipeline_profile_id=invoice.pipeline_profile_id,
                beneficiary_product_id=invoice.beneficiary_product_id,
                payer_agent_id=invoice.payer_agent_id,
                payer_product_id=invoice.payer_product_id,
                fee_id=invoice.fee_id,
                settled_amount=invoice.amount,
                residual_amount=0.0,
                currency=invoice.currency,
                mode="paid",
                final_status="paid",
            )
            self._emit_settlement(resolution)

    # ------------------------------------------------------------------ intent materialization

    def _materialize_original_intent(self,
                                     profile: PipelineProfileConfig,
                                     source_product: GenericProduct,
                                     intent_cfg_id: str,
                                     txn_count: int,
                                     amount: float,
                                     tick_id: int,
                                     simulation_date: _date_t) -> TransactionIntent:
        sim = self.cfg.simulation
        return TransactionIntent(
            intent_id=intent_cfg_id,
            parent_intent_id=None,
            tick_id=tick_id,
            simulation_date=simulation_date,
            pipeline_profile_id=profile.pipeline_profile_id,
            source_product_id=source_product.product_id,
            destination_role="",
            destination_product_id="",
            destination_vendor_id="",
            txn_count=int(txn_count),
            amount=round_amount(amount, sim.amount_scale_dp, sim.amount_rounding_mode),
            currency=self.default_currency,
            value_date_policy="same_day",
            value_date_offset_days=0,
            resolved_value_date=simulation_date,
            intent_stage="original_incoming",
            root_intent_id=intent_cfg_id,
            routing_completion_mode="",
            status="executed",
            reason_code="OK",
        )

    def _materialize_intent(self,
                            profile: PipelineProfileConfig,
                            source_product: GenericProduct,
                            source_vendor_id: str,
                            parent_intent_id: str,
                            root_intent_id: str,
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
            return None
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
            intent_stage="routed_outgoing",
            root_intent_id=root_intent_id,
            routing_completion_mode=dest.routing_completion_mode,
            status="pending",  # overwritten in _commit_root
            reason_code="",
        )

    def _calendar_for_vendor(self, vendor_id: str) -> Optional[Calendar]:
        try:
            return self.calendar_lookup(vendor_id)
        except Exception:
            return None

    # ------------------------------------------------------------------ emit shims

    def _emit_intent(self, i: TransactionIntent) -> None:
        payload = {
            "tick_id": i.tick_id,
            "simulation_date": i.simulation_date.isoformat(),
            "pipeline_profile_id": i.pipeline_profile_id,
            "product_id": i.source_product_id,
            "intent_id": i.intent_id,
            "parent_intent_id": i.parent_intent_id,
            "intent_stage": i.intent_stage,
            "root_intent_id": i.root_intent_id or i.intent_id,
            "destination_role": i.destination_role,
            "destination_product_id": i.destination_product_id,
            "destination_vendor_id": i.destination_vendor_id,
            "txn_count": i.txn_count,
            "amount": {"amount": f"{i.amount:.2f}", "currency": i.currency},
            "value_date_policy": i.value_date_policy,
            "resolved_value_date": i.resolved_value_date.isoformat(),
            "status": i.status,
            "reason_code": i.reason_code,
        }
        # `routing_completion_mode` only meaningful on routed_outgoing legs.
        if i.intent_stage == "routed_outgoing":
            payload["routing_completion_mode"] = i.routing_completion_mode
        self.emit("transaction_intent_event", payload)

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
            # v4 aggregation transparency.
            "component_count": i.component_count,
            "component_tick_ids": list(i.component_tick_ids),
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
