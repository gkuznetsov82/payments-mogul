"""Entity/edge analysis graph for World Builder visualization (spec 74 §P2).

Builds a minimum viable topology graph from a parsed config:
- Nodes: vendors, products, pops, regions, calendars, pipeline profiles.
- Edges: vendor->product, pop->product (product_link), product->profile,
  vendor->region, region->calendar, role-binding edges.
- Unresolved references surfaced as diagnostics so the UI can highlight gaps
  even when the document is partially valid.

Degrades gracefully (spec 74 §Failure behavior, spec 75 §P2): if YAML parses
but full validation fails, we still build a partial graph from the raw mapping
so the UI can render what it can.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import yaml

from engine.world_builder.validation import (
    Diagnostic,
    validate_yaml_string,
)


@dataclass
class GraphNode:
    id: str          # globally unique within the graph (kind-prefixed)
    kind: str        # "vendor" | "product" | "pop" | "region" | "calendar" | "pipeline_profile"
    label: str
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    source: str
    target: str
    kind: str        # "owns" | "linked_to" | "binds_profile" | "in_region" |
                     # "uses_calendar" | "role_binding" | "destination_route"
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineView:
    """Per-profile drill-down stage graph (spec 74 §Visualization, §P2 drill-down).

    Stage nodes/edges describe the *internals* of a single pipeline profile:
    transaction intents, destinations, postings, asset transfers, fees,
    settlement demands, and ledger<->container mappings. The drill-down view
    deliberately doesn't reuse the topology graph because role-binding edges
    only describe inter-product wiring, not in-profile execution flow.
    """
    profile_id: str
    label: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "summary": self.summary,
        }


@dataclass
class PipelineAggregate:
    """Aggregate scope view across all pipeline profiles, plus cross-profile
    edges that bridge them via role-resolved routing/payment relationships
    (spec 74 §Cross-pipeline connectivity)."""
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    profiles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "summary": self.summary,
            "profiles": list(self.profiles),
        }


@dataclass
class AnalysisReport:
    valid: bool
    errors: list[Diagnostic] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    unresolved_refs: list[Diagnostic] = field(default_factory=list)
    pipeline_views: list[PipelineView] = field(default_factory=list)
    pipeline_aggregate: Optional[PipelineAggregate] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [d.to_dict() for d in self.errors],
            "warnings": [d.to_dict() for d in self.warnings],
            "graph": {
                "nodes": [n.to_dict() for n in self.nodes],
                "edges": [e.to_dict() for e in self.edges],
            },
            "unresolved_refs": [d.to_dict() for d in self.unresolved_refs],
            "pipeline_views": [v.to_dict() for v in self.pipeline_views],
            "pipeline_aggregate": (
                self.pipeline_aggregate.to_dict()
                if self.pipeline_aggregate is not None
                else None
            ),
        }


def _vendor_node_id(vendor_id: str) -> str:
    return f"vendor:{vendor_id}"


def _product_node_id(vendor_id: str, product_id: str) -> str:
    return f"product:{vendor_id}/{product_id}"


def _pop_node_id(pop_id: str) -> str:
    return f"pop:{pop_id}"


def _region_node_id(region_id: str) -> str:
    return f"region:{region_id}"


def _calendar_node_id(calendar_id: str) -> str:
    return f"calendar:{calendar_id}"


def _profile_node_id(profile_id: str) -> str:
    return f"pipeline_profile:{profile_id}"


def _build_graph(data: dict[str, Any]) -> tuple[
    list[GraphNode], list[GraphEdge], list[Diagnostic]
]:
    """Construct nodes/edges from a parsed config mapping; collect unresolved refs."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    unresolved: list[Diagnostic] = []

    world = data.get("world") or {}
    vendor_agents = world.get("vendor_agents") or []
    pops = world.get("pops") or []
    calendars = data.get("calendars") or []
    regions = data.get("regions") or []
    pipeline = data.get("pipeline") or {}
    pipeline_profiles = pipeline.get("pipeline_profiles") or []

    # ---- Calendars
    calendar_ids: set[str] = set()
    for c in calendars:
        if not isinstance(c, dict):
            continue
        cid = c.get("calendar_id")
        if not cid:
            continue
        calendar_ids.add(cid)
        nodes.append(GraphNode(
            id=_calendar_node_id(cid),
            kind="calendar",
            label=cid,
            attrs={"weekend_profile": c.get("weekend_profile")},
        ))

    # ---- Regions (and their edge to calendar)
    region_ids: set[str] = set()
    for r in regions:
        if not isinstance(r, dict):
            continue
        rid = r.get("region_id")
        if not rid:
            continue
        region_ids.add(rid)
        nodes.append(GraphNode(
            id=_region_node_id(rid),
            kind="region",
            label=r.get("label") or rid,
            attrs={"calendar_id": r.get("calendar_id")},
        ))
        cal_id = r.get("calendar_id")
        if cal_id:
            if cal_id in calendar_ids:
                edges.append(GraphEdge(
                    source=_region_node_id(rid),
                    target=_calendar_node_id(cal_id),
                    kind="uses_calendar",
                ))
            else:
                unresolved.append(Diagnostic(
                    code="E_CALENDAR_NOT_FOUND",
                    message=f"Region '{rid}' references unknown calendar '{cal_id}'",
                    path=f"regions[{rid}].calendar_id",
                    node_id=_region_node_id(rid),
                ))

    # ---- Pipeline profiles
    profile_ids: set[str] = set()
    for prof in pipeline_profiles:
        if not isinstance(prof, dict):
            continue
        pid = prof.get("pipeline_profile_id")
        if not pid:
            continue
        profile_ids.add(pid)
        nodes.append(GraphNode(
            id=_profile_node_id(pid),
            kind="pipeline_profile",
            label=pid,
            attrs={
                "transaction_intent_count": len(prof.get("transaction_intents") or []),
                "fee_sequence_count": len(prof.get("fee_sequences") or []),
                "settlement_demand_sequence_count": len(
                    prof.get("settlement_demand_sequences") or []
                ),
            },
        ))

    # ---- Vendors and products: pass 1, register all nodes + ownership edges
    # so role bindings (pass 2) can resolve cross-vendor product references
    # regardless of file ordering.
    #
    # Composite identity: products are keyed by (vendor_id, product_id), not
    # product_id alone. Two vendors may legitimately publish products with the
    # same product_id (spec 40 §pipeline_role_bindings PipelineRoleSelector
    # supports `{ agent_id, product_id }` as a disambiguating selector form).
    # The previous naive `product_id -> single owner` map silently picked one
    # of the duplicates for role-binding edges; we now require disambiguation
    # whenever a product_id is non-unique.
    product_owners: dict[str, list[str]] = {}     # product_id -> [owning vendor_ids]
    product_keys: set[tuple[str, str]] = set()    # (vendor_id, product_id)
    vendor_ids: set[str] = set()
    for v in vendor_agents:
        if not isinstance(v, dict):
            continue
        vid = v.get("vendor_id")
        if not vid:
            continue
        vendor_ids.add(vid)
        nodes.append(GraphNode(
            id=_vendor_node_id(vid),
            kind="vendor",
            label=v.get("vendor_label") or vid,
            attrs={
                "operational": v.get("operational"),
                "region_id": v.get("region_id"),
            },
        ))
        vendor_node_id = _vendor_node_id(vid)
        rid = v.get("region_id")
        if rid:
            if rid in region_ids:
                edges.append(GraphEdge(
                    source=vendor_node_id,
                    target=_region_node_id(rid),
                    kind="in_region",
                ))
            else:
                unresolved.append(Diagnostic(
                    code="E_REGION_NOT_FOUND",
                    message=f"Vendor '{vid}' references unknown region '{rid}'",
                    path=f"world.vendor_agents[{vid}].region_id",
                    node_id=vendor_node_id,
                ))

        for p in (v.get("products") or []):
            if not isinstance(p, dict):
                continue
            pid = p.get("product_id")
            if not pid:
                continue
            product_owners.setdefault(pid, []).append(vid)
            product_keys.add((vid, pid))
            product_node_id = _product_node_id(vid, pid)
            nodes.append(GraphNode(
                id=product_node_id,
                kind="product",
                label=p.get("product_label") or pid,
                attrs={
                    "product_class": p.get("product_class"),
                    "vendor_id": vid,
                    "pipeline_profile_id": p.get("pipeline_profile_id"),
                },
            ))
            edges.append(GraphEdge(
                source=vendor_node_id,
                target=product_node_id,
                kind="owns",
            ))
            prof_ref = p.get("pipeline_profile_id")
            if prof_ref:
                if prof_ref in profile_ids:
                    edges.append(GraphEdge(
                        source=product_node_id,
                        target=_profile_node_id(prof_ref),
                        kind="binds_profile",
                    ))
                else:
                    unresolved.append(Diagnostic(
                        code="E_PIPELINE_PROFILE_NOT_FOUND",
                        message=(
                            f"Vendor '{vid}' product '{pid}' references unknown "
                            f"pipeline_profile_id '{prof_ref}'"
                        ),
                        path=f"world.vendor_agents[{vid}].products[{pid}].pipeline_profile_id",
                        node_id=product_node_id,
                    ))

    # Pass 2: role bindings — now that all vendors/products are registered we
    # can resolve forward references regardless of file ordering, and apply
    # composite-identity rules (spec 40 §pipeline_role_bindings).
    for v in vendor_agents:
        if not isinstance(v, dict):
            continue
        vid = v.get("vendor_id")
        if not vid:
            continue
        for p in (v.get("products") or []):
            if not isinstance(p, dict):
                continue
            pid = p.get("product_id")
            if not pid:
                continue
            source_node_id = _product_node_id(vid, pid)
            bindings = (p.get("pipeline_role_bindings") or {}).get("entity_roles") or {}
            for role_name, sel in bindings.items():
                if not isinstance(sel, dict):
                    continue
                tgt_agent = sel.get("agent_id")
                tgt_product = sel.get("product_id")
                local = sel.get("local")
                if local:
                    continue
                base_path = (
                    f"world.vendor_agents[{vid}].products[{pid}]."
                    f"pipeline_role_bindings.entity_roles.{role_name}"
                )
                if tgt_agent and tgt_product:
                    # Spec 40 §PipelineRoleSelector: `{ agent_id, product_id }` form
                    # binds a specific product owned by a specific agent — the
                    # only fully-disambiguated form when product_ids collide.
                    if tgt_agent not in vendor_ids:
                        unresolved.append(Diagnostic(
                            code="E_ROLE_TARGET_AGENT_MISSING",
                            message=(
                                f"Vendor '{vid}' product '{pid}' role '{role_name}' "
                                f"references unknown agent_id '{tgt_agent}'"
                            ),
                            path=f"{base_path}.agent_id",
                            node_id=source_node_id,
                        ))
                    elif (tgt_agent, tgt_product) not in product_keys:
                        unresolved.append(Diagnostic(
                            code="E_ROLE_TARGET_PRODUCT_MISSING",
                            message=(
                                f"Vendor '{vid}' product '{pid}' role '{role_name}' "
                                f"references unknown product '{tgt_product}' on "
                                f"agent '{tgt_agent}'"
                            ),
                            path=f"{base_path}.product_id",
                            node_id=source_node_id,
                        ))
                    else:
                        edges.append(GraphEdge(
                            source=source_node_id,
                            target=_product_node_id(tgt_agent, tgt_product),
                            kind="role_binding",
                            attrs={"role_name": role_name},
                        ))
                elif tgt_product:
                    owners = product_owners.get(tgt_product) or []
                    if not owners:
                        unresolved.append(Diagnostic(
                            code="E_ROLE_TARGET_PRODUCT_MISSING",
                            message=(
                                f"Vendor '{vid}' product '{pid}' role '{role_name}' "
                                f"references unknown product_id '{tgt_product}'"
                            ),
                            path=f"{base_path}.product_id",
                            node_id=source_node_id,
                        ))
                    elif len(owners) > 1:
                        # Composite identity required: multiple vendors define
                        # this product_id, so a `product_id` selector alone is
                        # ambiguous and the role binding cannot be resolved
                        # safely. Caller must use `{ agent_id, product_id }`.
                        unresolved.append(Diagnostic(
                            code="E_ROLE_TARGET_PRODUCT_AMBIGUOUS",
                            message=(
                                f"Vendor '{vid}' product '{pid}' role '{role_name}' "
                                f"references product_id '{tgt_product}' which is "
                                f"defined by multiple vendors {sorted(owners)}; "
                                f"add 'agent_id' to disambiguate"
                            ),
                            path=f"{base_path}.product_id",
                            node_id=source_node_id,
                        ))
                    else:
                        edges.append(GraphEdge(
                            source=source_node_id,
                            target=_product_node_id(owners[0], tgt_product),
                            kind="role_binding",
                            attrs={"role_name": role_name},
                        ))
                elif tgt_agent:
                    if tgt_agent in vendor_ids:
                        edges.append(GraphEdge(
                            source=source_node_id,
                            target=_vendor_node_id(tgt_agent),
                            kind="role_binding",
                            attrs={"role_name": role_name},
                        ))
                    else:
                        unresolved.append(Diagnostic(
                            code="E_ROLE_TARGET_AGENT_MISSING",
                            message=(
                                f"Vendor '{vid}' product '{pid}' role '{role_name}' "
                                f"references unknown agent_id '{tgt_agent}'"
                            ),
                            path=f"{base_path}.agent_id",
                            node_id=source_node_id,
                        ))

    # ---- Pops + product_link edges
    for pop in pops:
        if not isinstance(pop, dict):
            continue
        pop_id = pop.get("pop_id")
        if not pop_id:
            continue
        nodes.append(GraphNode(
            id=_pop_node_id(pop_id),
            kind="pop",
            label=pop.get("pop_label") or pop_id,
            attrs={
                "pop_count": pop.get("pop_count"),
                "region_id": pop.get("region_id"),
            },
        ))
        pop_node_id = _pop_node_id(pop_id)
        rid = pop.get("region_id")
        if rid:
            if rid in region_ids:
                edges.append(GraphEdge(
                    source=pop_node_id,
                    target=_region_node_id(rid),
                    kind="in_region",
                ))
            else:
                unresolved.append(Diagnostic(
                    code="E_REGION_NOT_FOUND",
                    message=f"Pop '{pop_id}' references unknown region '{rid}'",
                    path=f"world.pops[{pop_id}].region_id",
                    node_id=pop_node_id,
                ))

        for link in (pop.get("product_links") or []):
            if not isinstance(link, dict):
                continue
            lvid = link.get("vendor_id")
            lpid = link.get("product_id")
            if not lvid or not lpid:
                continue
            target_id = _product_node_id(lvid, lpid)
            if (lvid, lpid) in product_keys:
                edges.append(GraphEdge(
                    source=pop_node_id,
                    target=target_id,
                    kind="linked_to",
                    attrs={
                        "known": link.get("known"),
                        "onboarded_count": link.get("onboarded_count"),
                    },
                ))
            else:
                unresolved.append(Diagnostic(
                    code="E_LINK_TARGET_MISSING",
                    message=(
                        f"Pop '{pop_id}' links to unknown product "
                        f"({lvid}, {lpid})"
                    ),
                    path=f"world.pops[{pop_id}].product_links",
                    node_id=pop_node_id,
                ))

    return nodes, edges, unresolved


# =============================================================================
# Pipeline drill-down view builder (spec 74 §Pipeline drill-down).
# =============================================================================


def _pv_intent(profile: str, intent: str) -> str:
    return f"pv:{profile}:intent:{intent}"


def _pv_destination(profile: str, intent: str, role: str) -> str:
    return f"pv:{profile}:destination:{intent}:{role}"


def _pv_outgoing(profile: str, outgoing: str) -> str:
    return f"pv:{profile}:outgoing:{outgoing}"


def _pv_ledger(profile: str, ref: str) -> str:
    return f"pv:{profile}:ledger:{ref}"


def _pv_container(profile: str, ref: str) -> str:
    return f"pv:{profile}:container:{ref}"


def _pv_fee(profile: str, fee_id: str) -> str:
    return f"pv:{profile}:fee:{fee_id}"


def _pv_demand(profile: str, demand_id: str) -> str:
    return f"pv:{profile}:demand:{demand_id}"


def _pv_posting(profile: str, idx: int) -> str:
    return f"pv:{profile}:posting:{idx}"


def _pv_transfer(profile: str, idx: int) -> str:
    return f"pv:{profile}:transfer:{idx}"


def _pv_policy(profile: str, applies_to: str) -> str:
    return f"pv:{profile}:policy:{applies_to}"


def _build_pipeline_view(profile: dict[str, Any]) -> PipelineView:
    """Construct a stage graph for a single pipeline profile.

    The resulting nodes/edges visualise execution flow inside the profile:
    transaction_intents -> destinations, posting source/destination ledgers,
    asset transfer source/destination containers, fee triggers and
    beneficiaries, settlement demand triggers and creditor/debtor roles,
    and ledger<->container mappings.
    """
    profile_id = profile.get("pipeline_profile_id") or "?"
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # Index for downstream cross-references.
    intent_ids: set[str] = set()
    outgoing_ids: set[str] = set()
    fee_ids: set[str] = set()
    demand_ids: set[str] = set()

    transaction_intents = profile.get("transaction_intents") or []
    ledger_construction = profile.get("ledger_construction") or []
    posting_rules = profile.get("posting_rules") or []
    container_construction = profile.get("value_container_construction") or []
    asset_transfer_rules = profile.get("asset_transfer_rules") or []
    fee_sequences = profile.get("fee_sequences") or []
    demand_sequences = profile.get("settlement_demand_sequences") or []
    policy_list = profile.get("settlement_payment_policies") or []
    ledger_container_map = profile.get("ledger_value_container_map") or []

    # ---- Ledger nodes
    for l in ledger_construction:
        if not isinstance(l, dict):
            continue
        ref = l.get("ledger_ref")
        if not ref:
            continue
        nodes.append(GraphNode(
            id=_pv_ledger(profile_id, ref),
            kind="pv_ledger",
            label=ref,
            attrs={
                "path_pattern": l.get("path_pattern"),
                "normal_side": l.get("normal_side"),
            },
        ))

    # ---- Container nodes
    for c in container_construction:
        if not isinstance(c, dict):
            continue
        ref = c.get("container_ref")
        if not ref:
            continue
        nodes.append(GraphNode(
            id=_pv_container(profile_id, ref),
            kind="pv_container",
            label=ref,
            attrs={"path_pattern": c.get("path_pattern")},
        ))

    # ---- Transaction intents and their destinations
    for intent in transaction_intents:
        if not isinstance(intent, dict):
            continue
        iid = intent.get("intent_id")
        if not iid:
            continue
        intent_ids.add(iid)
        intent_node_id = _pv_intent(profile_id, iid)
        nodes.append(GraphNode(
            id=intent_node_id,
            kind="pv_intent",
            label=iid,
            attrs={"source_volume_ratio": intent.get("source_volume_ratio")},
        ))
        for dest in (intent.get("destinations") or []):
            if not isinstance(dest, dict):
                continue
            role = dest.get("destination_role") or "?"
            outgoing = dest.get("outgoing_intent_id") or "?"
            outgoing_ids.add(outgoing)
            dest_node_id = _pv_destination(profile_id, iid, role)
            nodes.append(GraphNode(
                id=dest_node_id,
                kind="pv_destination",
                label=f"{role} ({outgoing})",
                attrs={
                    "destination_role": role,
                    "outgoing_intent_id": outgoing,
                    "value_date_policy": dest.get("value_date_policy"),
                    "value_date_offset_days": dest.get("value_date_offset_days"),
                    "currency_mode": dest.get("currency_mode"),
                    "routing_completion_mode": dest.get("routing_completion_mode"),
                },
            ))
            edges.append(GraphEdge(
                source=intent_node_id,
                target=dest_node_id,
                kind="pv_routes_to",
                attrs={
                    "value_date_policy": dest.get("value_date_policy"),
                    "routing_completion_mode": dest.get("routing_completion_mode"),
                },
            ))
            # An outgoing-intent stand-alone node so downstream sink fees can
            # show their trigger origin.
            outgoing_node_id = _pv_outgoing(profile_id, outgoing)
            if not any(n.id == outgoing_node_id for n in nodes):
                nodes.append(GraphNode(
                    id=outgoing_node_id,
                    kind="pv_outgoing_intent",
                    label=outgoing,
                    attrs={"from_intent": iid, "destination_role": role},
                ))
            edges.append(GraphEdge(
                source=dest_node_id,
                target=outgoing_node_id,
                kind="pv_emits",
                attrs={},
            ))

    # ---- Posting rules: source ledger -> destination ledger.
    # Posting/transfer rule indexes built first so fee/demand passes can also
    # reference rule_ids when needed; trigger lineage edges are emitted in a
    # second sweep once intent/outgoing/fee/demand ids are all populated.
    ledger_refs = {l.get("ledger_ref") for l in ledger_construction if isinstance(l, dict)}
    posting_meta: list[dict[str, Any]] = []
    for idx, r in enumerate(posting_rules):
        if not isinstance(r, dict):
            continue
        trigger = r.get("trigger_id") or "?"
        src = r.get("source_ledger_ref")
        dst = r.get("destination_ledger_ref")
        posting_id = _pv_posting(profile_id, idx)
        posting_meta.append({"id": posting_id, "trigger": trigger})
        nodes.append(GraphNode(
            id=posting_id,
            kind="pv_posting",
            label=f"{trigger} → posting",
            attrs={
                "trigger_id": trigger,
                "source_ledger_ref": src,
                "destination_ledger_ref": dst,
                "amount_basis": r.get("amount_basis"),
                "value_date_policy": r.get("value_date_policy"),
                "value_date_offset_days": r.get("value_date_offset_days"),
                "rule_index": idx,
                "profile_id": profile_id,
            },
        ))
        if src and src in ledger_refs:
            edges.append(GraphEdge(
                source=_pv_ledger(profile_id, src),
                target=posting_id,
                kind="pv_posts_from",
                attrs={"trigger_id": trigger},
            ))
        if dst and dst in ledger_refs:
            edges.append(GraphEdge(
                source=posting_id,
                target=_pv_ledger(profile_id, dst),
                kind="pv_posts_to",
                attrs={"trigger_id": trigger},
            ))

    # ---- Asset transfer rules: source container -> destination container.
    container_refs = {c.get("container_ref") for c in container_construction if isinstance(c, dict)}
    transfer_meta: list[dict[str, Any]] = []
    for idx, r in enumerate(asset_transfer_rules):
        if not isinstance(r, dict):
            continue
        trigger = r.get("trigger_id") or "?"
        src = r.get("source_container_ref")
        dst = r.get("destination_container_ref")
        transfer_id = _pv_transfer(profile_id, idx)
        transfer_meta.append({"id": transfer_id, "trigger": trigger})
        nodes.append(GraphNode(
            id=transfer_id,
            kind="pv_transfer",
            label=f"{trigger} → transfer",
            attrs={
                "trigger_id": trigger,
                "source_container_ref": src,
                "destination_container_ref": dst,
                "amount_basis": r.get("amount_basis"),
                "value_date_policy": r.get("value_date_policy"),
                "value_date_offset_days": r.get("value_date_offset_days"),
                "rule_index": idx,
                "profile_id": profile_id,
            },
        ))
        if src and src in container_refs:
            edges.append(GraphEdge(
                source=_pv_container(profile_id, src),
                target=transfer_id,
                kind="pv_transfer_from",
                attrs={"trigger_id": trigger},
            ))
        if dst and dst in container_refs:
            edges.append(GraphEdge(
                source=transfer_id,
                target=_pv_container(profile_id, dst),
                kind="pv_transfer_to",
                attrs={"trigger_id": trigger},
            ))

    # ---- Fees with trigger relationships.
    for seq in fee_sequences:
        if not isinstance(seq, dict):
            continue
        for fee in (seq.get("fees") or []):
            if not isinstance(fee, dict):
                continue
            fid = fee.get("fee_id")
            if not fid:
                continue
            fee_ids.add(fid)
            fee_node_id = _pv_fee(profile_id, fid)
            nodes.append(GraphNode(
                id=fee_node_id,
                kind="pv_fee",
                label=fid,
                attrs={
                    "beneficiary_role": fee.get("beneficiary_role"),
                    "payer_role": fee.get("payer_role"),
                    "beneficiary_product_role": fee.get("beneficiary_product_role"),
                    "settlement_value_date_policy": fee.get("settlement_value_date_policy"),
                    "settlement_value_date_offset_days": fee.get("settlement_value_date_offset_days"),
                    "amount_percentage": fee.get("amount_percentage"),
                    "count_cost": fee.get("count_cost"),
                    "non_payable_statement": fee.get("non_payable_statement"),
                    "sequence_id": seq.get("sequence_id"),
                },
            ))
            for tid in (fee.get("trigger_ids") or []):
                # Origin node: prefer matching intent or outgoing-intent or
                # earlier fee in the same profile; fall back to a synthetic
                # intent node if absent so the chain is still visible.
                origin_id: Optional[str] = None
                if tid in intent_ids:
                    origin_id = _pv_intent(profile_id, tid)
                elif tid in outgoing_ids:
                    origin_id = _pv_outgoing(profile_id, tid)
                elif tid in fee_ids:
                    origin_id = _pv_fee(profile_id, tid)
                if origin_id is None:
                    # Sink-profile fees often trigger on upstream-profile outgoing
                    # ids that aren't defined in this profile. Keep the trigger
                    # visible as a synthetic outgoing-intent node.
                    origin_id = _pv_outgoing(profile_id, tid)
                    if not any(n.id == origin_id for n in nodes):
                        nodes.append(GraphNode(
                            id=origin_id,
                            kind="pv_outgoing_intent",
                            label=tid,
                            attrs={"external": True},
                        ))
                edges.append(GraphEdge(
                    source=origin_id,
                    target=fee_node_id,
                    kind="pv_triggers_fee",
                    attrs={"trigger_id": tid},
                ))

    # ---- Settlement demands with trigger relationships.
    for seq in demand_sequences:
        if not isinstance(seq, dict):
            continue
        for demand in (seq.get("settlement_demands") or []):
            if not isinstance(demand, dict):
                continue
            did = demand.get("settlement_demand_id")
            if not did:
                continue
            demand_ids.add(did)
            demand_node_id = _pv_demand(profile_id, did)
            nodes.append(GraphNode(
                id=demand_node_id,
                kind="pv_settlement_demand",
                label=did,
                attrs={
                    "creditor_role": demand.get("creditor_role"),
                    "debtor_role": demand.get("debtor_role"),
                    "invoice_category": demand.get("invoice_category"),
                    "invoice_issue_date_policy": demand.get("invoice_issue_date_policy"),
                    "payment_due_date_policy": demand.get("payment_due_date_policy"),
                    "amount_percentage": demand.get("amount_percentage"),
                    "formula_ref": demand.get("formula_ref"),
                    "sequence_id": seq.get("sequence_id"),
                },
            ))
            for tid in (demand.get("trigger_ids") or []):
                origin_id = None
                if tid in intent_ids:
                    origin_id = _pv_intent(profile_id, tid)
                elif tid in outgoing_ids:
                    origin_id = _pv_outgoing(profile_id, tid)
                elif tid in demand_ids:
                    origin_id = _pv_demand(profile_id, tid)
                if origin_id is None:
                    origin_id = _pv_outgoing(profile_id, tid)
                    if not any(n.id == origin_id for n in nodes):
                        nodes.append(GraphNode(
                            id=origin_id,
                            kind="pv_outgoing_intent",
                            label=tid,
                            attrs={"external": True},
                        ))
                edges.append(GraphEdge(
                    source=origin_id,
                    target=demand_node_id,
                    kind="pv_triggers_demand",
                    attrs={"trigger_id": tid},
                ))

    # ---- Settlement payment policies.
    for policy in policy_list:
        if not isinstance(policy, dict):
            continue
        applies = policy.get("applies_to_category") or "?"
        policy_id = _pv_policy(profile_id, applies)
        nodes.append(GraphNode(
            id=policy_id,
            kind="pv_settlement_policy",
            label=f"policy:{applies}",
            attrs={
                "applies_to_category": applies,
                "source_container_ref": policy.get("source_container_ref"),
                "auto_pay_enabled": policy.get("auto_pay_enabled"),
                "hold_default": policy.get("hold_default"),
                "grace_ticks": policy.get("grace_ticks"),
                "non_payable_statement": policy.get("non_payable_statement"),
            },
        ))
        src = policy.get("source_container_ref")
        if src and src in container_refs:
            edges.append(GraphEdge(
                source=_pv_container(profile_id, src),
                target=policy_id,
                kind="pv_pays_from",
                attrs={"applies_to_category": applies},
            ))

    # ---- Ledger <-> container mapping (reconciliation hint).
    for m in ledger_container_map:
        if not isinstance(m, dict):
            continue
        l_ref = m.get("ledger_ref")
        c_ref = m.get("container_ref")
        if l_ref in ledger_refs and c_ref in container_refs:
            edges.append(GraphEdge(
                source=_pv_ledger(profile_id, l_ref),
                target=_pv_container(profile_id, c_ref),
                kind="pv_maps_to_container",
                attrs={"mapping_mode": m.get("mapping_mode")},
            ))

    # ---- Trigger lineage: trigger_id -> posting / transfer rule.
    # Spec 74 §Pipeline visibility completeness: postings/transfers must be
    # traceable from their triggers to the rule node and on to the
    # ledger/container endpoints. The endpoint edges (pv_posts_*/pv_transfer_*)
    # already exist; here we emit the missing trigger-side edges so a fee or
    # an outgoing-intent visibly drives the posting/transfer rule.
    def _resolve_trigger_origin(trigger: str) -> str:
        if trigger in intent_ids:
            return _pv_intent(profile_id, trigger)
        if trigger in outgoing_ids:
            return _pv_outgoing(profile_id, trigger)
        if trigger in fee_ids:
            return _pv_fee(profile_id, trigger)
        if trigger in demand_ids:
            return _pv_demand(profile_id, trigger)
        # Sink-profile rule triggered on an upstream outgoing-intent that
        # wasn't authored locally — emit it as a synthetic external node.
        synthetic_id = _pv_outgoing(profile_id, trigger)
        if not any(n.id == synthetic_id for n in nodes):
            nodes.append(GraphNode(
                id=synthetic_id,
                kind="pv_outgoing_intent",
                label=trigger,
                attrs={"external": True},
            ))
        return synthetic_id

    for meta in posting_meta:
        if meta["trigger"] == "?":
            continue
        edges.append(GraphEdge(
            source=_resolve_trigger_origin(meta["trigger"]),
            target=meta["id"],
            kind="pv_triggers_posting",
            attrs={"trigger_id": meta["trigger"]},
        ))
    for meta in transfer_meta:
        if meta["trigger"] == "?":
            continue
        edges.append(GraphEdge(
            source=_resolve_trigger_origin(meta["trigger"]),
            target=meta["id"],
            kind="pv_triggers_transfer",
            attrs={"trigger_id": meta["trigger"]},
        ))

    return PipelineView(
        profile_id=profile_id,
        label=profile_id,
        nodes=nodes,
        edges=edges,
        summary={
            "intent_count": len(intent_ids),
            "fee_count": len(fee_ids),
            "settlement_demand_count": len(demand_ids),
            "ledger_count": len(ledger_refs),
            "container_count": len(container_refs),
            "posting_count": len(posting_meta),
            "transfer_count": len(transfer_meta),
        },
    )


def _build_pipeline_views(data: dict[str, Any]) -> list[PipelineView]:
    pipeline = data.get("pipeline") or {}
    profiles = pipeline.get("pipeline_profiles") or []
    views: list[PipelineView] = []
    for prof in profiles:
        if not isinstance(prof, dict):
            continue
        pid = prof.get("pipeline_profile_id")
        if not pid:
            continue
        views.append(_build_pipeline_view(prof))
    return views


def _build_profile_owner_index(data: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """profile_id -> list of (vendor_id, product_id) attaching it.

    Spec 40 §pipeline_role_bindings: a single profile can be reused across
    multiple product instances. Cross-pipeline edges therefore expose all
    candidate target instances; the UI picks the first one as the canonical
    `target_instance_id` for navigation.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    world = data.get("world") or {}
    for v in (world.get("vendor_agents") or []):
        if not isinstance(v, dict):
            continue
        vid = v.get("vendor_id")
        for p in (v.get("products") or []):
            if not isinstance(p, dict):
                continue
            pid = p.get("product_id")
            prof = p.get("pipeline_profile_id")
            if not (vid and pid and prof):
                continue
            out.setdefault(prof, []).append((vid, pid))
    # Deterministic order for downstream tests/snapshots.
    for prof_id, owners in out.items():
        owners.sort()
    return out


def _trigger_ids_of(node: GraphNode) -> list[str]:
    """Return the trigger_ids consumed by a stage node, if any."""
    if node.kind in ("pv_posting", "pv_transfer"):
        t = node.attrs.get("trigger_id")
        return [str(t)] if t and t != "?" else []
    if node.kind in ("pv_fee", "pv_settlement_demand"):
        # Fee/demand trigger_ids are not stored on the node attrs by this
        # builder (we attach them to edges); recover by walking the node's
        # incoming pv_triggers_* edges in the calling context if needed.
        return []
    return []


def _emitted_id_of(node: GraphNode) -> Optional[str]:
    """Return the id this node emits as a trigger consumable by other stages.

    - intents emit their `intent_id` (the node label)
    - outgoing-intent stand-ins emit their outgoing intent id (the node label)
    - fees emit their `fee_id` (label)
    - settlement demands emit their `settlement_demand_id` (label)
    """
    if node.kind in (
        "pv_intent",
        "pv_outgoing_intent",
        "pv_fee",
        "pv_settlement_demand",
    ):
        return node.label
    return None


def _consumer_triggers_from_view(view: PipelineView) -> list[tuple[GraphNode, str]]:
    """For a profile view, return (consumer_node, trigger_id) tuples.

    Posting/transfer triggers come from node attrs; fee/demand triggers are
    recovered from the `pv_triggers_fee` / `pv_triggers_demand` edges that the
    profile builder emits with `trigger_id` on the edge attrs.
    """
    out: list[tuple[GraphNode, str]] = []
    nodes_by_id = {n.id: n for n in view.nodes}
    for n in view.nodes:
        for tid in _trigger_ids_of(n):
            out.append((n, tid))
    for e in view.edges:
        if e.kind not in ("pv_triggers_fee", "pv_triggers_demand"):
            continue
        tid = e.attrs.get("trigger_id")
        consumer = nodes_by_id.get(e.target)
        if not (tid and consumer):
            continue
        out.append((consumer, str(tid)))
    return out


def _build_cross_pipeline_edges(
    views: list[PipelineView],
    owner_index: dict[str, list[tuple[str, str]]],
) -> list[GraphEdge]:
    """Bridge profiles via shared trigger ids (spec 74 §Cross-pipeline connectivity).

    For each (consumer, trigger_id) in profile B, find an emitter of the same
    trigger_id in any other profile A. The resulting edge A.emitter -> B.consumer
    carries `target_profile_id`, `target_instance_id`, and `target_node_id` so
    the UI can jump to the resolved target without re-resolving role bindings.
    """
    # Build emitter index: trigger_id -> [(profile_id, emitter_node_id, emitter_kind)]
    emitter_index: dict[str, list[tuple[str, str, str]]] = {}
    for v in views:
        for n in v.nodes:
            emitted = _emitted_id_of(n)
            if not emitted:
                continue
            # Skip synthetic external outgoing-intent stand-ins; they don't
            # emit anything to the rest of the graph (they ARE the borrowed
            # external trigger). The genuine emitter sits in the producing
            # profile.
            if n.kind == "pv_outgoing_intent" and n.attrs.get("external"):
                continue
            emitter_index.setdefault(emitted, []).append((v.profile_id, n.id, n.kind))

    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()  # (src_id, tgt_id, trigger_id)

    for consumer_view in views:
        for consumer, tid in _consumer_triggers_from_view(consumer_view):
            emitters = emitter_index.get(tid) or []
            for src_profile_id, src_node_id, src_kind in emitters:
                if src_profile_id == consumer_view.profile_id:
                    continue
                key = (src_node_id, consumer.id, tid)
                if key in seen:
                    continue
                seen.add(key)
                target_owners = owner_index.get(consumer_view.profile_id) or []
                target_instance_id = (
                    f"{target_owners[0][0]}/{target_owners[0][1]}"
                    if target_owners
                    else None
                )
                edges.append(GraphEdge(
                    source=src_node_id,
                    target=consumer.id,
                    kind="pv_cross_pipeline",
                    attrs={
                        "trigger_id": tid,
                        "source_profile_id": src_profile_id,
                        "source_kind": src_kind,
                        "target_profile_id": consumer_view.profile_id,
                        "target_node_id": consumer.id,
                        "target_kind": consumer.kind,
                        "target_instance_id": target_instance_id,
                        "target_instance_candidates": [
                            f"{vid}/{pid}" for vid, pid in target_owners
                        ],
                    },
                ))

    # Deterministic ordering: by source profile, source node, target node, trigger.
    edges.sort(key=lambda e: (
        str(e.attrs.get("source_profile_id") or ""),
        e.source,
        e.target,
        str(e.attrs.get("trigger_id") or ""),
    ))
    return edges


def _build_pipeline_aggregate(
    views: list[PipelineView],
    cross_edges: list[GraphEdge],
) -> PipelineAggregate:
    """Union of all per-profile nodes/edges + cross-pipeline edges.

    Profile-prefixed node ids are already disjoint by construction. Stub
    jump-target nodes that the per-profile post-processing added are
    deduplicated by id. Cross-pipeline edges added to per-profile views are
    excluded here since they're contributed once via the canonical `cross_edges`
    list — keeps the aggregate edge count exact.
    """
    nodes: list[GraphNode] = []
    seen_node_ids: set[str] = set()
    edges: list[GraphEdge] = []
    for v in views:
        for n in v.nodes:
            # Stub jump-target nodes are a per-profile drill-down convenience
            # only; in the aggregate the genuine, fully-typed node lives in
            # its owning profile view, so skipping the stub here ensures we
            # don't shadow it with the stub's generic `pv_outgoing_intent`
            # kind.
            if n.attrs.get("stub_for_profile_id"):
                continue
            if n.id in seen_node_ids:
                continue
            seen_node_ids.add(n.id)
            nodes.append(n)
        for e in v.edges:
            if e.kind == "pv_cross_pipeline":
                continue   # added once below
            edges.append(e)
    edges.extend(cross_edges)

    summary = {
        "profile_count": len(views),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "cross_pipeline_edge_count": len(cross_edges),
        "intent_count": sum(int(v.summary.get("intent_count", 0)) for v in views),
        "fee_count": sum(int(v.summary.get("fee_count", 0)) for v in views),
        "settlement_demand_count": sum(
            int(v.summary.get("settlement_demand_count", 0)) for v in views
        ),
        "posting_count": sum(int(v.summary.get("posting_count", 0)) for v in views),
        "transfer_count": sum(int(v.summary.get("transfer_count", 0)) for v in views),
    }
    return PipelineAggregate(
        nodes=nodes,
        edges=edges,
        summary=summary,
        profiles=[v.profile_id for v in views],
    )


def analyze_yaml_string(yaml_text: str) -> AnalysisReport:
    """Parse YAML, attempt validation, then build topology graph + pipeline views.

    Even when validation fails, we attempt to build a partial graph from the
    parsed mapping so the UI can render what is structurally present
    (spec 74 §Failure behavior).
    """
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return AnalysisReport(
            valid=False,
            errors=[Diagnostic(code="E_YAML_PARSE", message=str(exc))],
        )
    if parsed is None or not isinstance(parsed, dict):
        return AnalysisReport(
            valid=False,
            errors=[Diagnostic(
                code="E_YAML_TOPLEVEL_NOT_MAPPING",
                message="Top-level YAML must be a mapping",
            )],
        )

    # Run canonical validation for diagnostics; do NOT abort graph construction
    # on failure — degraded view is part of the contract.
    report = validate_yaml_string(yaml_text)

    nodes, edges, unresolved = _build_graph(parsed)
    pipeline_views = _build_pipeline_views(parsed)
    owner_index = _build_profile_owner_index(parsed)
    cross_edges = _build_cross_pipeline_edges(pipeline_views, owner_index)

    # Per-profile views: append cross-pipeline edges that touch that profile so
    # drill-down also shows outbound/inbound jump points (target_profile_id
    # tells the UI it's a navigation cue, not a within-profile flow).
    cross_by_profile: dict[str, list[GraphEdge]] = {}
    for e in cross_edges:
        src_p = str(e.attrs.get("source_profile_id") or "")
        tgt_p = str(e.attrs.get("target_profile_id") or "")
        if src_p:
            cross_by_profile.setdefault(src_p, []).append(e)
        if tgt_p and tgt_p != src_p:
            cross_by_profile.setdefault(tgt_p, []).append(e)
    for v in pipeline_views:
        outbound_inbound = cross_by_profile.get(v.profile_id) or []
        if outbound_inbound:
            # Also pull in the relevant counterpart-profile node so the edge
            # has both endpoints rendered when someone is in single-profile
            # drill-down. The frontend renders these as jump-target stubs.
            existing_ids = {n.id for n in v.nodes}
            stubs: list[GraphNode] = []
            for e in outbound_inbound:
                missing_id = (
                    e.source if e.source not in existing_ids else
                    (e.target if e.target not in existing_ids else None)
                )
                if missing_id is None or any(s.id == missing_id for s in stubs):
                    continue
                # Determine kind from the foreign profile.
                foreign_profile_id = (
                    e.attrs.get("source_profile_id")
                    if missing_id == e.source
                    else e.attrs.get("target_profile_id")
                )
                stubs.append(GraphNode(
                    id=missing_id,
                    kind="pv_outgoing_intent",   # generic stand-in for jump targets
                    label=f"↪ {foreign_profile_id}",
                    attrs={
                        "external": True,
                        "stub_for_profile_id": foreign_profile_id,
                    },
                ))
            v.nodes = list(v.nodes) + stubs
            v.edges = list(v.edges) + outbound_inbound

    aggregate = _build_pipeline_aggregate(pipeline_views, cross_edges)

    return AnalysisReport(
        valid=report.valid,
        errors=report.errors,
        warnings=report.warnings,
        nodes=nodes,
        edges=edges,
        unresolved_refs=unresolved,
        pipeline_views=pipeline_views,
        pipeline_aggregate=aggregate,
    )
