import { describe, expect, it } from "vitest";

import {
  composeAggregateGraph,
  isSuperNodeId,
  superNodeId,
} from "../lib/supernodes";
import type { PipelineAggregate, PipelineView } from "../lib/types";

const VIEWS: PipelineView[] = [
  {
    profile_id: "prepaid_card_pipeline",
    label: "prepaid_card_pipeline",
    nodes: [
      { id: "pv:prepaid_card_pipeline:intent:Purchase", kind: "pv_intent", label: "Purchase", attrs: {} },
      { id: "pv:prepaid_card_pipeline:outgoing:Purchase-Scheme", kind: "pv_outgoing_intent", label: "Purchase-Scheme", attrs: {} },
    ],
    edges: [
      {
        source: "pv:prepaid_card_pipeline:intent:Purchase",
        target: "pv:prepaid_card_pipeline:outgoing:Purchase-Scheme",
        kind: "pv_emits",
        attrs: {},
      },
    ],
    summary: { intent_count: 1, fee_count: 0 },
  },
  {
    profile_id: "scheme_access_pipeline",
    label: "scheme_access_pipeline",
    nodes: [
      { id: "pv:scheme_access_pipeline:fee:fee_scheme", kind: "pv_fee", label: "fee_scheme", attrs: {} },
    ],
    edges: [],
    summary: { intent_count: 0, fee_count: 1 },
  },
];

const AGGREGATE: PipelineAggregate = {
  nodes: [...VIEWS[0].nodes, ...VIEWS[1].nodes],
  edges: [
    ...VIEWS[0].edges,
    {
      source: "pv:prepaid_card_pipeline:outgoing:Purchase-Scheme",
      target: "pv:scheme_access_pipeline:fee:fee_scheme",
      kind: "pv_cross_pipeline",
      attrs: {
        source_profile_id: "prepaid_card_pipeline",
        target_profile_id: "scheme_access_pipeline",
        target_node_id: "pv:scheme_access_pipeline:fee:fee_scheme",
        target_instance_id: "vendor_scheme/prod_scheme_access",
        trigger_id: "Purchase-Scheme",
      },
    },
  ],
  summary: { profile_count: 2, cross_pipeline_edge_count: 1 },
  profiles: ["prepaid_card_pipeline", "scheme_access_pipeline"],
};

describe("composeAggregateGraph", () => {
  it("returns one supernode per profile when nothing is expanded", () => {
    const out = composeAggregateGraph({
      views: VIEWS,
      aggregate: AGGREGATE,
      expandedProfiles: new Set(),
    });
    expect(out.nodes).toHaveLength(2);
    expect(out.nodes.every((n) => n.kind === "pv_super")).toBe(true);
    expect(out.nodes.map((n) => n.id)).toEqual([
      superNodeId("prepaid_card_pipeline"),
      superNodeId("scheme_access_pipeline"),
    ]);
  });

  it("collapses cross-pipeline edges into a single supernode link", () => {
    const out = composeAggregateGraph({
      views: VIEWS,
      aggregate: AGGREGATE,
      expandedProfiles: new Set(),
    });
    const links = out.edges.filter((e) => e.kind === "pv_super_link");
    expect(links).toHaveLength(1);
    expect(links[0].source).toBe(superNodeId("prepaid_card_pipeline"));
    expect(links[0].target).toBe(superNodeId("scheme_access_pipeline"));
    expect(links[0].attrs.target_profile_id).toBe("scheme_access_pipeline");
    expect(links[0].attrs.target_node_id).toBe(
      "pv:scheme_access_pipeline:fee:fee_scheme",
    );
  });

  it("expands the requested profile to its stage internals", () => {
    const out = composeAggregateGraph({
      views: VIEWS,
      aggregate: AGGREGATE,
      expandedProfiles: new Set(["prepaid_card_pipeline"]),
    });
    const ids = out.nodes.map((n) => n.id);
    // Stage internals from prepaid_card_pipeline are present...
    expect(ids).toContain("pv:prepaid_card_pipeline:intent:Purchase");
    expect(ids).toContain("pv:prepaid_card_pipeline:outgoing:Purchase-Scheme");
    // ...and the OTHER profile is still represented as its supernode.
    expect(ids).toContain(superNodeId("scheme_access_pipeline"));
  });

  it("rewrites cross-pipeline edges between expanded and collapsed sides to point at the supernode", () => {
    const out = composeAggregateGraph({
      views: VIEWS,
      aggregate: AGGREGATE,
      expandedProfiles: new Set(["prepaid_card_pipeline"]),
    });
    const cross = out.edges.find((e) => e.kind === "pv_cross_pipeline");
    expect(cross).toBeDefined();
    // Source side stayed as the genuine outgoing-intent (prepaid expanded).
    expect(cross!.source).toBe(
      "pv:prepaid_card_pipeline:outgoing:Purchase-Scheme",
    );
    // Target side was rewritten to the scheme supernode (still collapsed).
    expect(cross!.target).toBe(superNodeId("scheme_access_pipeline"));
  });

  it("returns the original full graph when every profile is expanded", () => {
    const out = composeAggregateGraph({
      views: VIEWS,
      aggregate: AGGREGATE,
      expandedProfiles: new Set([
        "prepaid_card_pipeline",
        "scheme_access_pipeline",
      ]),
    });
    const ids = new Set(out.nodes.map((n) => n.id));
    expect(ids.has("pv:prepaid_card_pipeline:intent:Purchase")).toBe(true);
    expect(ids.has("pv:scheme_access_pipeline:fee:fee_scheme")).toBe(true);
    // No supernodes when everything is expanded.
    expect(out.nodes.some((n) => isSuperNodeId(n.id))).toBe(false);
    // The genuine cross-pipeline edge survives unchanged.
    const cross = out.edges.find((e) => e.kind === "pv_cross_pipeline");
    expect(cross).toBeDefined();
    expect(cross!.source).toBe(
      "pv:prepaid_card_pipeline:outgoing:Purchase-Scheme",
    );
    expect(cross!.target).toBe("pv:scheme_access_pipeline:fee:fee_scheme");
  });
});

describe("supernode helpers", () => {
  it("isSuperNodeId distinguishes supernodes from stage nodes", () => {
    expect(isSuperNodeId("pv_super:foo")).toBe(true);
    expect(isSuperNodeId("pv:foo:intent:bar")).toBe(false);
    expect(isSuperNodeId("vendor:bar")).toBe(false);
  });
});
