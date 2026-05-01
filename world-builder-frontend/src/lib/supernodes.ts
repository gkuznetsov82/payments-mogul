// Aggregate "collapsed" view derivation. One synthetic supernode per pipeline
// profile, plus deduplicated supernode-to-supernode links representing the
// cross-pipeline relationships (spec 74 §Progressive disclosure).
//
// The expanded set of profile ids causes those profiles to be replaced by
// their full stage internals; remaining profiles stay collapsed. Cross-pipeline
// edges between an expanded profile and a collapsed one are reattached to the
// collapsed profile's supernode so the link stays visible.

import type { AnalyzeEdge, AnalyzeNode, PipelineAggregate, PipelineView } from "./types";

export function superNodeId(profileId: string): string {
  return `pv_super:${profileId}`;
}

export function isSuperNodeId(id: string): boolean {
  return id.startsWith("pv_super:");
}

export function profileIdFromAnyId(id: string): string | null {
  const stage = /^pv:([^:]+):/.exec(id);
  if (stage) return stage[1];
  const sup = /^pv_super:([^:]+)$/.exec(id);
  if (sup) return sup[1];
  return null;
}

interface ComposeArgs {
  views: PipelineView[];
  aggregate: PipelineAggregate | null;
  expandedProfiles: Set<string>;
}

/** Compose the active aggregate-scope graph: a mix of supernodes (collapsed
 *  profiles) and stage internals (expanded profiles). Cross-pipeline edges
 *  between mixed states are reattached to whichever endpoint is collapsed.
 *  Returns nodes/edges in deterministic insertion order. */
export function composeAggregateGraph({
  views,
  aggregate,
  expandedProfiles,
}: ComposeArgs): { nodes: AnalyzeNode[]; edges: AnalyzeEdge[] } {
  const profileIds = (aggregate?.profiles ?? views.map((v) => v.profile_id));
  const viewById = new Map(views.map((v) => [v.profile_id, v]));

  const nodes: AnalyzeNode[] = [];
  for (const pid of profileIds) {
    if (expandedProfiles.has(pid)) {
      const v = viewById.get(pid);
      if (!v) continue;
      // Skip stub nodes (per-profile drill-down navigation aids); we add the
      // genuine supernodes separately for collapsed neighbours.
      for (const n of v.nodes) {
        if (n.attrs && (n.attrs as Record<string, unknown>)["stub_for_profile_id"]) continue;
        nodes.push(n);
      }
    } else {
      const v = viewById.get(pid);
      const summary = v?.summary as Record<string, unknown> | undefined;
      nodes.push({
        id: superNodeId(pid),
        kind: "pv_super",
        label: pid,
        attrs: {
          profile_id: pid,
          intent_count: summary?.intent_count ?? 0,
          fee_count: summary?.fee_count ?? 0,
          settlement_demand_count: summary?.settlement_demand_count ?? 0,
          posting_count: summary?.posting_count ?? 0,
          transfer_count: summary?.transfer_count ?? 0,
          ledger_count: summary?.ledger_count ?? 0,
          container_count: summary?.container_count ?? 0,
          collapsed: true,
        },
      });
    }
  }

  const visibleNodeIds = new Set(nodes.map((n) => n.id));
  const edges: AnalyzeEdge[] = [];
  // Within expanded profiles: include the per-profile internal edges.
  for (const v of views) {
    if (!expandedProfiles.has(v.profile_id)) continue;
    for (const e of v.edges) {
      if (e.kind === "pv_cross_pipeline") continue; // handled in cross pass
      if (visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)) {
        edges.push(e);
      }
    }
  }

  // Cross-pipeline edges: rewrite endpoints to supernodes when the relevant
  // profile is collapsed. Aggregate or coalesce duplicates so the collapsed
  // view stays clean.
  const crossEdges = (aggregate?.edges ?? []).filter((e) => e.kind === "pv_cross_pipeline");
  const seenSuperLink = new Map<string, AnalyzeEdge>();
  for (const e of crossEdges) {
    const sourceProfile = profileIdFromAnyId(e.source);
    const targetProfile =
      (e.attrs && (e.attrs as Record<string, unknown>)["target_profile_id"] as string | undefined) ??
      profileIdFromAnyId(e.target);
    const sourceCollapsed = sourceProfile && !expandedProfiles.has(sourceProfile);
    const targetCollapsed = targetProfile && !expandedProfiles.has(targetProfile);

    let src = e.source;
    let tgt = e.target;
    if (sourceCollapsed && sourceProfile) src = superNodeId(sourceProfile);
    if (targetCollapsed && targetProfile) tgt = superNodeId(targetProfile);
    if (!visibleNodeIds.has(src) || !visibleNodeIds.has(tgt)) continue;

    if (src === tgt) continue; // self-loop on the same supernode

    if (src.startsWith("pv_super:") && tgt.startsWith("pv_super:")) {
      const key = `${src}|${tgt}`;
      const existing = seenSuperLink.get(key);
      if (existing) {
        const c = (existing.attrs.cross_count as number | undefined) ?? 1;
        existing.attrs = {
          ...existing.attrs,
          cross_count: c + 1,
        };
        continue;
      }
      const synthetic: AnalyzeEdge = {
        source: src,
        target: tgt,
        kind: "pv_super_link",
        attrs: {
          source_profile_id: sourceProfile,
          target_profile_id: targetProfile,
          cross_count: 1,
          // Carry the first underlying trigger so click-through still has
          // a concrete navigation hint.
          first_trigger_id: e.attrs.trigger_id,
          target_node_id: e.attrs.target_node_id,
          target_instance_id: e.attrs.target_instance_id,
        },
      };
      seenSuperLink.set(key, synthetic);
      edges.push(synthetic);
      continue;
    }

    // Mixed expanded/collapsed: keep the original cross edge but rewrite its
    // collapsed endpoint to point at the supernode.
    edges.push({
      source: src,
      target: tgt,
      kind: "pv_cross_pipeline",
      attrs: e.attrs,
    });
  }

  return { nodes, edges };
}
