import { describe, expect, it } from "vitest";

import { layoutGraph, neighborhood } from "../lib/layout";
import type { AnalyzeEdge, AnalyzeNode } from "../lib/types";

describe("layoutGraph", () => {
  it("produces nodes/edges with deterministic positions for the same input", () => {
    const nodes: AnalyzeNode[] = [
      { id: "vendor:vendor_alpha", kind: "vendor", label: "Vendor Alpha", attrs: {} },
      { id: "product:vendor_alpha/p1", kind: "product", label: "P1", attrs: {} },
      { id: "pop:pop_main", kind: "pop", label: "Main", attrs: {} },
      { id: "pipeline_profile:prepaid", kind: "pipeline_profile", label: "prepaid", attrs: {} },
    ];
    const edges: AnalyzeEdge[] = [
      { source: "vendor:vendor_alpha", target: "product:vendor_alpha/p1", kind: "owns", attrs: {} },
      { source: "pop:pop_main", target: "product:vendor_alpha/p1", kind: "linked_to", attrs: {} },
      { source: "product:vendor_alpha/p1", target: "pipeline_profile:prepaid", kind: "binds_profile", attrs: {} },
    ];
    const a = layoutGraph(nodes, edges);
    const b = layoutGraph(nodes, edges);
    expect(a.nodes.map((n) => [n.id, n.position])).toEqual(
      b.nodes.map((n) => [n.id, n.position]),
    );
    expect(a.edges.map((e) => [e.source, e.target])).toEqual(
      b.edges.map((e) => [e.source, e.target]),
    );
  });

  it("preserves the pop -> product -> pipeline_profile chain in the output", () => {
    const nodes: AnalyzeNode[] = [
      { id: "vendor:V", kind: "vendor", label: "V", attrs: {} },
      { id: "product:V/P", kind: "product", label: "P", attrs: {} },
      { id: "pop:POP", kind: "pop", label: "POP", attrs: {} },
      { id: "pipeline_profile:PRO", kind: "pipeline_profile", label: "PRO", attrs: {} },
    ];
    const edges: AnalyzeEdge[] = [
      { source: "pop:POP", target: "product:V/P", kind: "linked_to", attrs: {} },
      { source: "product:V/P", target: "pipeline_profile:PRO", kind: "binds_profile", attrs: {} },
    ];
    const out = layoutGraph(nodes, edges);
    const linked = out.edges.find(
      (e) => e.source === "pop:POP" && e.target === "product:V/P",
    );
    const binds = out.edges.find(
      (e) => e.source === "product:V/P" && e.target === "pipeline_profile:PRO",
    );
    expect(linked).toBeDefined();
    expect(binds).toBeDefined();
  });

  it("drops edges with dangling endpoints to keep dagre stable", () => {
    const nodes: AnalyzeNode[] = [
      { id: "n1", kind: "vendor", label: "n1", attrs: {} },
    ];
    const edges: AnalyzeEdge[] = [
      { source: "n1", target: "missing", kind: "owns", attrs: {} },
    ];
    const out = layoutGraph(nodes, edges);
    expect(out.edges).toHaveLength(0);
    expect(out.nodes).toHaveLength(1);
  });

  it("honors per-node manual overrides without disturbing other nodes", () => {
    const nodes: AnalyzeNode[] = [
      { id: "vendor:V", kind: "vendor", label: "V", attrs: {} },
      { id: "product:V/P", kind: "product", label: "P", attrs: {} },
    ];
    const edges: AnalyzeEdge[] = [
      { source: "vendor:V", target: "product:V/P", kind: "owns", attrs: {} },
    ];
    const baseline = layoutGraph(nodes, edges);
    const overridden = layoutGraph(nodes, edges, {
      overrides: { "product:V/P": { x: 9999, y: 9999 } },
    });
    const baseProduct = baseline.nodes.find((n) => n.id === "product:V/P")!;
    const overProduct = overridden.nodes.find((n) => n.id === "product:V/P")!;
    expect(overProduct.position).toEqual({ x: 9999, y: 9999 });
    expect(overProduct.position).not.toEqual(baseProduct.position);
    // Vendor untouched.
    const baseVendor = baseline.nodes.find((n) => n.id === "vendor:V")!;
    const overVendor = overridden.nodes.find((n) => n.id === "vendor:V")!;
    expect(overVendor.position).toEqual(baseVendor.position);
    // Manual placement is signalled in node data so the canvas can style it.
    expect((overProduct.data as { manualPlaced: boolean }).manualPlaced).toBe(true);
    expect((baseProduct.data as { manualPlaced: boolean }).manualPlaced).toBe(false);
  });

  it("hub-and-spoke fans out children at the same rank below the root", () => {
    // Regression for the supernode aggregate column: 1 root + 2 children
    // must put the children at the same y (rank 1), not stack them in a
    // single column. dagre's network-simplex ranker is what produces this;
    // tight-tree did not.
    const nodes: AnalyzeNode[] = [
      { id: "pv_super:root", kind: "pv_super", label: "root", attrs: {} },
      { id: "pv_super:child_a", kind: "pv_super", label: "a", attrs: {} },
      { id: "pv_super:child_b", kind: "pv_super", label: "b", attrs: {} },
    ];
    const edges: AnalyzeEdge[] = [
      { source: "pv_super:root", target: "pv_super:child_a", kind: "pv_super_link", attrs: {} },
      { source: "pv_super:root", target: "pv_super:child_b", kind: "pv_super_link", attrs: {} },
    ];
    const out = layoutGraph(nodes, edges, { flavor: "pipeline_aggregate" });
    const yByName: Record<string, number> = Object.fromEntries(
      out.nodes.map((n) => [n.id, n.position.y]),
    );
    const xByName: Record<string, number> = Object.fromEntries(
      out.nodes.map((n) => [n.id, n.position.x]),
    );
    // Root sits above both children.
    expect(yByName["pv_super:root"]).toBeLessThan(yByName["pv_super:child_a"]);
    expect(yByName["pv_super:root"]).toBeLessThan(yByName["pv_super:child_b"]);
    // Children share a y-rank within a tolerance — the diagnostic for the
    // chain-collapse bug. Equal rank means they fan out side-by-side.
    expect(
      Math.abs(yByName["pv_super:child_a"] - yByName["pv_super:child_b"]),
    ).toBeLessThan(20);
    // …and they have distinct x positions (otherwise they overlap).
    expect(xByName["pv_super:child_a"]).not.toEqual(xByName["pv_super:child_b"]);
  });

  it("topology lays out as a top-down dendrogram tree", () => {
    // Path graph vendor → product → pipeline_profile. After unifying
    // topology + pipeline layouts, both flavors emit a top-down tree, so
    // depth maps to y-coordinate (parent above, child below).
    const nodes: AnalyzeNode[] = [
      { id: "vendor:v", kind: "vendor", label: "v", attrs: {} },
      { id: "product:v/x", kind: "product", label: "x", attrs: {} },
      { id: "pipeline_profile:pro", kind: "pipeline_profile", label: "pro", attrs: {} },
    ];
    const edges: AnalyzeEdge[] = [
      { source: "vendor:v", target: "product:v/x", kind: "owns", attrs: {} },
      {
        source: "product:v/x",
        target: "pipeline_profile:pro",
        kind: "binds_profile",
        attrs: {},
      },
    ];
    const out = layoutGraph(nodes, edges, { flavor: "topology" });
    const yByKind = Object.fromEntries(
      out.nodes.map((n) => [n.id, n.position.y]),
    );
    expect(yByKind["vendor:v"]).toBeLessThan(yByKind["product:v/x"]);
    expect(yByKind["product:v/x"]).toBeLessThan(yByKind["pipeline_profile:pro"]);
  });
});

describe("layoutGraph spacing factor", () => {
  // Two-node graph so dagre has clean separation we can measure. Spacing
  // multiplier scales nodesep + ranksep + (for topology) the LANE_STRIDE.
  const nodes: AnalyzeNode[] = [
    { id: "vendor:V", kind: "vendor", label: "V", attrs: {} },
    { id: "product:V/P", kind: "product", label: "P", attrs: {} },
  ];
  const edges: AnalyzeEdge[] = [
    { source: "vendor:V", target: "product:V/P", kind: "owns", attrs: {} },
  ];

  it("topology: spacious factor pushes ranks further apart than normal", () => {
    // Topology is now top-down, so spacing translates to y-axis separation
    // between connected ranks (vendor above its child product).
    const normal = layoutGraph(nodes, edges, {
      flavor: "topology",
      spacingFactor: 1,
    });
    const spacious = layoutGraph(nodes, edges, {
      flavor: "topology",
      spacingFactor: 1.5,
    });
    const dyNormal = Math.abs(
      normal.nodes.find((n) => n.id === "product:V/P")!.position.y -
        normal.nodes.find((n) => n.id === "vendor:V")!.position.y,
    );
    const dySpacious = Math.abs(
      spacious.nodes.find((n) => n.id === "product:V/P")!.position.y -
        spacious.nodes.find((n) => n.id === "vendor:V")!.position.y,
    );
    expect(dySpacious).toBeGreaterThan(dyNormal);
  });

  it("pipeline: spacious factor increases vertical separation", () => {
    const pipelineNodes: AnalyzeNode[] = [
      { id: "pv:P:intent:i", kind: "pv_intent", label: "i", attrs: {} },
      { id: "pv:P:fee:f", kind: "pv_fee", label: "f", attrs: {} },
    ];
    const pipelineEdges: AnalyzeEdge[] = [
      { source: "pv:P:intent:i", target: "pv:P:fee:f", kind: "pv_triggers_fee", attrs: {} },
    ];
    const normal = layoutGraph(pipelineNodes, pipelineEdges, {
      flavor: "pipeline",
      spacingFactor: 1,
    });
    const spacious = layoutGraph(pipelineNodes, pipelineEdges, {
      flavor: "pipeline",
      spacingFactor: 1.5,
    });
    const dyNormal = Math.abs(
      normal.nodes.find((n) => n.id === "pv:P:fee:f")!.position.y -
        normal.nodes.find((n) => n.id === "pv:P:intent:i")!.position.y,
    );
    const dySpacious = Math.abs(
      spacious.nodes.find((n) => n.id === "pv:P:fee:f")!.position.y -
        spacious.nodes.find((n) => n.id === "pv:P:intent:i")!.position.y,
    );
    expect(dySpacious).toBeGreaterThan(dyNormal);
  });

  it("clamps an absurd spacing factor instead of producing a runaway canvas", () => {
    const out = layoutGraph(nodes, edges, {
      flavor: "topology",
      spacingFactor: 9999,
    });
    // Topology is top-down now ⇒ spacing affects rank y-distance. Clamp
    // caps the multiplier at 3× of the baseline ranksep (110 px).
    const dy = Math.abs(
      out.nodes.find((n) => n.id === "product:V/P")!.position.y -
        out.nodes.find((n) => n.id === "vendor:V")!.position.y,
    );
    expect(dy).toBeLessThan(1000);
  });
});

describe("layoutGraph focus flavor (radial)", () => {
  // Star graph: focus has 2 outgoing (downstream) and 1 incoming (upstream).
  const nodes: AnalyzeNode[] = [
    { id: "focus", kind: "vendor", label: "F", attrs: {} },
    { id: "down1", kind: "product", label: "D1", attrs: {} },
    { id: "down2", kind: "product", label: "D2", attrs: {} },
    { id: "up1", kind: "pop", label: "U1", attrs: {} },
    { id: "far", kind: "calendar", label: "Far", attrs: {} },
  ];
  const edges: AnalyzeEdge[] = [
    { source: "focus", target: "down1", kind: "owns", attrs: {} },
    { source: "focus", target: "down2", kind: "owns", attrs: {} },
    { source: "up1", target: "focus", kind: "linked_to", attrs: {} },
    { source: "far", target: "up1", kind: "in_region", attrs: {} },
  ];

  it("places the focus node at origin", () => {
    const out = layoutGraph(nodes, edges, {
      flavor: "focus",
      focusNodeId: "focus",
      focusDepth: 1,
    });
    const focus = out.nodes.find((n) => n.id === "focus")!;
    expect(focus.position).toEqual({ x: 0, y: 0 });
  });

  it("puts upstream neighbors on the left semicircle, downstream on the right", () => {
    const out = layoutGraph(nodes, edges, {
      flavor: "focus",
      focusNodeId: "focus",
      focusDepth: 1,
    });
    const byId = Object.fromEntries(out.nodes.map((n) => [n.id, n.position]));
    // Upstream = ancestors (incoming edges) → x < 0 (left)
    expect(byId["up1"].x).toBeLessThan(0);
    // Downstream = descendants (outgoing edges) → x > 0 (right)
    expect(byId["down1"].x).toBeGreaterThan(0);
    expect(byId["down2"].x).toBeGreaterThan(0);
  });

  it("expands rings outward by hop distance", () => {
    const out = layoutGraph(nodes, edges, {
      flavor: "focus",
      focusNodeId: "focus",
      focusDepth: 2,
    });
    const byId = Object.fromEntries(out.nodes.map((n) => [n.id, n.position]));
    // far is 2 hops upstream (far -> up1 -> focus); ring 2 is further from origin.
    const ring1 = Math.hypot(byId["up1"].x, byId["up1"].y);
    const ring2 = Math.hypot(byId["far"].x, byId["far"].y);
    expect(ring2).toBeGreaterThan(ring1);
  });

  it("is deterministic for the same input", () => {
    const a = layoutGraph(nodes, edges, {
      flavor: "focus",
      focusNodeId: "focus",
      focusDepth: 2,
    });
    const b = layoutGraph(nodes, edges, {
      flavor: "focus",
      focusNodeId: "focus",
      focusDepth: 2,
    });
    expect(
      a.nodes.map((n) => [n.id, n.position]),
    ).toEqual(b.nodes.map((n) => [n.id, n.position]));
  });

  it("falls back to a non-radial layout when no focus node is present", () => {
    const out = layoutGraph(nodes, edges, {
      flavor: "focus",
      focusNodeId: null,
    });
    // Fallback path must still emit one Node per input and not throw.
    expect(out.nodes).toHaveLength(nodes.length);
    expect(out.edges.length).toBeGreaterThan(0);
    // And the result must differ from the radial layout (different positions
    // for at least one node) so the toggle is meaningful.
    const radial = layoutGraph(nodes, edges, {
      flavor: "focus",
      focusNodeId: "focus",
      focusDepth: 2,
    });
    const fallback = Object.fromEntries(out.nodes.map((n) => [n.id, n.position]));
    const radialMap = Object.fromEntries(
      radial.nodes.map((n) => [n.id, n.position]),
    );
    let differs = false;
    for (const id of Object.keys(fallback)) {
      const a = fallback[id];
      const b = radialMap[id];
      if (Math.abs(a.x - b.x) > 5 || Math.abs(a.y - b.y) > 5) {
        differs = true;
        break;
      }
    }
    expect(differs).toBe(true);
  });

  it("produces visibly different positions than baseline pipeline layout", () => {
    const baseline = layoutGraph(nodes, edges, { flavor: "pipeline" });
    const focus = layoutGraph(nodes, edges, {
      flavor: "focus",
      focusNodeId: "focus",
      focusDepth: 2,
    });
    // At least one node must be in a meaningfully different position
    // — proves the toggle actually does something visible.
    let differs = false;
    for (const n of nodes) {
      const a = baseline.nodes.find((x) => x.id === n.id)!.position;
      const b = focus.nodes.find((x) => x.id === n.id)!.position;
      if (Math.abs(a.x - b.x) > 5 || Math.abs(a.y - b.y) > 5) {
        differs = true;
        break;
      }
    }
    expect(differs).toBe(true);
  });
});

describe("neighborhood", () => {
  it("returns depth-N reachable nodes through both directions", () => {
    const edges: AnalyzeEdge[] = [
      { source: "a", target: "b", kind: "owns", attrs: {} },
      { source: "b", target: "c", kind: "owns", attrs: {} },
      { source: "c", target: "d", kind: "owns", attrs: {} },
      { source: "x", target: "a", kind: "owns", attrs: {} },
    ];
    const d1 = neighborhood("b", edges, 1);
    expect(d1).toEqual(new Set(["b", "a", "c"]));
    const d2 = neighborhood("b", edges, 2);
    expect(d2).toEqual(new Set(["b", "a", "c", "d", "x"]));
  });
});
