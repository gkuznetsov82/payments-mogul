import dagre from "dagre";
import type { ELK as ElkType, ElkNode, ElkExtendedEdge } from "elkjs/lib/elk-api";
import type { Edge, Node } from "@xyflow/react";

import type { AnalyzeEdge, AnalyzeNode } from "./types";

// Hierarchical crossing-minimised layout (spec 74 §Hierarchical layout quality).
// Primary engine is Eclipse Layout Kernel via elkjs. Dagre is retained as the
// deterministic synchronous fallback used for tests and as a bootstrap before
// the async ELK pass completes.

const NODE_WIDTH = 220;
const NODE_HEIGHT = 56;

/** ELK singleton. `elkjs/lib/elk.bundled.js` ships the kernel inline but
 *  still uses a Web Worker by default. We dynamic-import it so unit tests
 *  running under jsdom (where `Worker` is undefined) never load the bundle
 *  and never crash the worker pool. */
let elkInstance: ElkType | null = null;
async function getElk(): Promise<ElkType | null> {
  if (elkInstance) return elkInstance;
  if (!elkAvailable()) return null;
  // Dynamic import keeps elkjs out of the module-load graph for jsdom test
  // runs. Vite + the SPA bundle still tree-shake-include it normally.
  const mod = await import("elkjs/lib/elk.bundled.js");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ELK = (mod as any).default as new () => ElkType;
  elkInstance = new ELK();
  return elkInstance;
}

/** True when this runtime can safely run elkjs. Vitest jsdom polyfills
 *  `Worker` but the worker that elkjs spawns ends up crashing the tinypool
 *  child process — so we explicitly detect the test runner and skip the
 *  ELK pass there. */
function elkAvailable(): boolean {
  if (typeof Worker === "undefined") return false;
  const proc = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  const env = proc?.env;
  if (env?.VITEST) return false;
  if (env?.NODE_ENV === "test") return false;
  return true;
}

function elkLayoutOptionsForFlavor(
  _flavor: Flavor,
  spacingFactor = 1,
): Record<string, string> {
  // Topology + pipeline share the same hierarchical top-down options now
  // (spec 74 §Hierarchical layout quality). The flavor argument is kept
  // for future divergence but no longer changes ELK behaviour.
  const s = clampSpacing(spacingFactor);
  return {
    "elk.algorithm": "layered",
    "elk.direction": "DOWN",
    "elk.layered.spacing.nodeNodeBetweenLayers": String(Math.round(110 * s)),
    "elk.spacing.nodeNode": String(Math.round(55 * s)),
    "elk.spacing.edgeNode": String(Math.round(20 * s)),
    "elk.spacing.edgeEdge": String(Math.round(15 * s)),
    "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
    "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
    "elk.layered.cycleBreaking.strategy": "GREEDY",
    "elk.edgeRouting": "POLYLINE",
  };
}

// Kind-lane tables used to live here (TOPOLOGY_LAYER + PIPELINE_LAYER) to
// pin specific kinds into specific columns. They were removed: forcing
// every fee / posting / transfer onto a shared x produced the tangled
// vertical pile users reported. Both topology and pipeline flavors now
// trust dagre / ELK ranking by edge structure for a proper top-down tree.


export type Flavor =
  | "topology"
  | "pipeline"
  | "pipeline_aggregate"
  | "focus";

export interface LayoutOptions {
  /** Manual position overrides (from user drag). Pinned: never re-laid out. */
  overrides?: Record<string, { x: number; y: number }>;
  /** Mental-map cache: positions from the previous layout that should be
   *  preserved if the same node id appears in this layout (spec 74 §Mental-map
   *  continuity). Caller passes the cache; layout writes computed positions
   *  for *new* nodes only. */
  hintPositions?: Record<string, { x: number; y: number }>;
  flavor?: Flavor;
  /** For aggregate flavor: profile id stack order. */
  profileBands?: string[];
  /** For "focus" flavor: node id placed at the center of the radial layout. */
  focusNodeId?: string | null;
  /** For "focus" flavor: how many hops out to lay out. Defaults to 2. */
  focusDepth?: number;
  /** Multiplier applied to nodesep + ranksep (dagre + ELK) and to the
   *  topology lane stride. 1.0 = normal density; <1 packs nodes tighter;
   *  >1 spreads them apart for dense graphs (spec 74 §Readability). */
  spacingFactor?: number;
}

export interface LaidOutGraph {
  nodes: Node[];
  edges: Edge[];
}

/** Synchronous deterministic dagre layout. Used as bootstrap before the async
 *  ELK pass resolves and as the layout in test environments where async UI
 *  layout would slow tests down. */
export function layoutGraph(
  analyzeNodes: AnalyzeNode[],
  analyzeEdges: AnalyzeEdge[],
  options: LayoutOptions = {},
): LaidOutGraph {
  const flavor = options.flavor ?? "topology";
  const overrides = options.overrides ?? {};
  const hints = options.hintPositions ?? {};
  if (flavor === "pipeline_aggregate") {
    return layoutAggregateDagre(analyzeNodes, analyzeEdges, options);
  }
  if (flavor === "focus") {
    return layoutFocusRadial(analyzeNodes, analyzeEdges, options);
  }

  // Both topology and pipeline use the same top-down dendrogram layout
  // (spec 74 §Hierarchical layout quality). The earlier topology-specific
  // L→R + kind-lane snap forced unrelated nodes into shared columns and
  // produced unreadable spaghetti — the tree shape that pipeline view
  // adopted reads better here too.
  const ids = new Set(analyzeNodes.map((n) => n.id));
  const validEdges = analyzeEdges.filter((e) => ids.has(e.source) && ids.has(e.target));

  const spacing = clampSpacing(options.spacingFactor);

  const g = new dagre.graphlib.Graph({ multigraph: true, compound: false });
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: "TB",
    nodesep: Math.round(56 * spacing),
    ranksep: Math.round(110 * spacing),
    // network-simplex (dagre's default) gives a proper fan-out for small
    // hub-and-spoke graphs. tight-tree collapses them into chains, which
    // is why the 3-supernode aggregate view rendered as a vertical column.
    ranker: "network-simplex",
  });

  for (const n of analyzeNodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  validEdges.forEach((e, idx) => g.setEdge(e.source, e.target, {}, `e${idx}`));

  dagre.layout(g);

  const nodes: Node[] = analyzeNodes.map((n) => {
    const pos = g.node(n.id);
    const computed = pos
      ? { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 }
      : { x: 0, y: 0 };
    const final = overrides[n.id] ?? hints[n.id] ?? computed;
    return makeNode(n, final, Boolean(overrides[n.id]));
  });
  const edges = makeEdges(validEdges);
  return { nodes, edges };
}

/** Async ELK-layered layout. Primary engine in the browser. Output is
 *  deterministic for the same input + options. Manual `overrides` and
 *  `hintPositions` win over ELK's freshly computed positions, in that order.
 *  When ELK isn't available (test runner without Web Workers) we fall back
 *  to the synchronous dagre layout — same shape, deterministic, just less
 *  pretty for dense graphs. */
export async function elkLayoutGraph(
  analyzeNodes: AnalyzeNode[],
  analyzeEdges: AnalyzeEdge[],
  options: LayoutOptions = {},
): Promise<LaidOutGraph> {
  if (!elkAvailable()) return layoutGraph(analyzeNodes, analyzeEdges, options);
  const flavor = options.flavor ?? "topology";
  if (flavor === "focus") {
    // Radial layout doesn't benefit from ELK — small subgraph + explicit
    // ring placement is faster and more interpretable.
    return layoutGraph(analyzeNodes, analyzeEdges, options);
  }
  if (flavor === "pipeline_aggregate") {
    return elkLayoutAggregate(analyzeNodes, analyzeEdges, options);
  }
  return elkLayoutSingle(analyzeNodes, analyzeEdges, options);
}

async function elkLayoutSingle(
  analyzeNodes: AnalyzeNode[],
  analyzeEdges: AnalyzeEdge[],
  options: LayoutOptions,
  yOffset = 0,
): Promise<LaidOutGraph> {
  const overrides = options.overrides ?? {};
  const hints = options.hintPositions ?? {};
  const flavor = options.flavor ?? "topology";

  const ids = new Set(analyzeNodes.map((n) => n.id));
  const validEdges = analyzeEdges.filter((e) => ids.has(e.source) && ids.has(e.target));

  // Topology + pipeline both rank purely by edge structure now — let ELK
  // place every node freely without per-kind layer pinning.
  const elkChildren: ElkNode[] = analyzeNodes.map((n) => ({
    id: n.id,
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
    layoutOptions: {} as Record<string, string>,
  }));

  const elkEdges: ElkExtendedEdge[] = validEdges.map((e, idx) => ({
    id: `e-${idx}-${e.source}->${e.target}-${e.kind}`,
    sources: [e.source],
    targets: [e.target],
  }));

  let result: ElkNode;
  try {
    const elk = await getElk();
    if (!elk) return layoutGraph(analyzeNodes, analyzeEdges, options);
    result = await elk.layout({
      id: "root",
      layoutOptions: elkLayoutOptionsForFlavor(flavor, options.spacingFactor),
      children: elkChildren,
      edges: elkEdges,
    });
  } catch {
    // Fall back to synchronous dagre layout if ELK errors out for any reason
    // — never let layout failure break the UI (spec 74 §Failure behavior).
    return layoutGraph(analyzeNodes, analyzeEdges, options);
  }

  const positions: Record<string, { x: number; y: number }> = {};
  for (const c of result.children ?? []) {
    if (c.x !== undefined && c.y !== undefined) {
      positions[c.id] = { x: c.x, y: c.y + yOffset };
    }
  }

  const nodes: Node[] = analyzeNodes.map((n) => {
    const computed = positions[n.id] ?? { x: 0, y: yOffset };
    const final = overrides[n.id] ?? hints[n.id] ?? computed;
    return makeNode(n, final, Boolean(overrides[n.id]));
  });
  const edges = makeEdges(validEdges);
  return { nodes, edges };
}

const BAND_GAP = 80;

async function elkLayoutAggregate(
  analyzeNodes: AnalyzeNode[],
  analyzeEdges: AnalyzeEdge[],
  options: LayoutOptions,
): Promise<LaidOutGraph> {
  // Mirrors layoutAggregateDagre: supernodes go into one shared group at
  // the top so 1-root-N-children fans out instead of one-supernode-per-band
  // stacking; expanded profiles each get their own band below.
  const knownBands = options.profileBands ?? [];
  const supernodes: AnalyzeNode[] = [];
  const expandedByProfile = new Map<string, AnalyzeNode[]>();
  for (const n of analyzeNodes) {
    if (n.kind === "pv_super") {
      supernodes.push(n);
      continue;
    }
    const prof = profileIdFromNodeId(n.id) ?? "__default__";
    if (!expandedByProfile.has(prof)) expandedByProfile.set(prof, []);
    expandedByProfile.get(prof)!.push(n);
  }
  const expandedBandOrder: string[] = [];
  for (const p of knownBands) {
    if (expandedByProfile.has(p)) expandedBandOrder.push(p);
  }
  for (const p of expandedByProfile.keys()) {
    if (!expandedBandOrder.includes(p)) expandedBandOrder.push(p);
  }

  const supernodeIds = new Set(supernodes.map((n) => n.id));
  const supernodeEdges: AnalyzeEdge[] = [];
  const intra: Record<string, AnalyzeEdge[]> = {};
  const cross: AnalyzeEdge[] = [];
  for (const e of analyzeEdges) {
    if (supernodeIds.has(e.source) && supernodeIds.has(e.target)) {
      supernodeEdges.push(e);
      continue;
    }
    const sp = profileIdFromNodeId(e.source);
    const tp = profileIdFromNodeId(e.target);
    if (sp && tp && sp === tp && expandedByProfile.has(sp)) {
      (intra[sp] ??= []).push(e);
    } else {
      cross.push(e);
    }
  }

  const allLaidNodes: Node[] = [];
  let yOffset = 0;

  if (supernodes.length > 0) {
    const sub = await elkLayoutSingle(
      supernodes,
      supernodeEdges,
      { ...options, flavor: "pipeline" },
      yOffset,
    );
    allLaidNodes.push(...sub.nodes);
    let groupMaxY = yOffset;
    for (const n of sub.nodes) {
      groupMaxY = Math.max(groupMaxY, n.position.y + NODE_HEIGHT);
    }
    yOffset = groupMaxY + BAND_GAP;
  }

  for (const profileId of expandedBandOrder) {
    const bandNodes = expandedByProfile.get(profileId) ?? [];
    const bandEdges = intra[profileId] ?? [];
    const sub = await elkLayoutSingle(
      bandNodes,
      bandEdges,
      { ...options, flavor: "pipeline" },
      yOffset,
    );
    allLaidNodes.push(...sub.nodes);
    let bandMaxY = yOffset;
    for (const n of sub.nodes) {
      bandMaxY = Math.max(bandMaxY, n.position.y + NODE_HEIGHT);
    }
    yOffset = bandMaxY + BAND_GAP;
  }

  const validIds = new Set(analyzeNodes.map((n) => n.id));
  const crossInScope = cross.filter((e) => validIds.has(e.source) && validIds.has(e.target));
  const intraInScope = expandedBandOrder.flatMap((p) => intra[p] ?? []);
  const allEdges = makeEdges([...supernodeEdges, ...intraInScope, ...crossInScope]);

  return { nodes: allLaidNodes, edges: allEdges };
}

function layoutAggregateDagre(
  analyzeNodes: AnalyzeNode[],
  analyzeEdges: AnalyzeEdge[],
  options: LayoutOptions,
): LaidOutGraph {
  // Aggregate scope mixes:
  //   - supernode placeholders (one per collapsed profile) → laid out
  //     TOGETHER as a single dagre tree so 1-root-2-children renders as
  //     proper fan-out (instead of per-profile bands stacking each
  //     supernode in its own row);
  //   - expanded profiles' stage nodes → each profile keeps its own
  //     vertical band so its internal tree stays self-contained.
  // Cross-pipeline edges between an expanded profile and a collapsed one
  // bridge the two sub-layouts — they're added back at the end.
  const knownBands = options.profileBands ?? [];
  const supernodes: AnalyzeNode[] = [];
  const expandedByProfile = new Map<string, AnalyzeNode[]>();
  for (const n of analyzeNodes) {
    if (n.kind === "pv_super") {
      supernodes.push(n);
      continue;
    }
    const prof = profileIdFromNodeId(n.id) ?? "__default__";
    if (!expandedByProfile.has(prof)) expandedByProfile.set(prof, []);
    expandedByProfile.get(prof)!.push(n);
  }

  const expandedBandOrder: string[] = [];
  for (const p of knownBands) {
    if (expandedByProfile.has(p)) expandedBandOrder.push(p);
  }
  for (const p of expandedByProfile.keys()) {
    if (!expandedBandOrder.includes(p)) expandedBandOrder.push(p);
  }

  // Edge buckets:
  //   - "supernode": both endpoints are supernodes (the dedup'd super-links)
  //   - per-profile intra: both endpoints in the same expanded profile
  //   - cross-everything-else: rendered as straight edges between absolute
  //     positions (no per-band sub-layout participation)
  const supernodeIds = new Set(supernodes.map((n) => n.id));
  const supernodeEdges: AnalyzeEdge[] = [];
  const intra: Record<string, AnalyzeEdge[]> = {};
  for (const e of analyzeEdges) {
    if (supernodeIds.has(e.source) && supernodeIds.has(e.target)) {
      supernodeEdges.push(e);
      continue;
    }
    const sp = profileIdFromNodeId(e.source);
    const tp = profileIdFromNodeId(e.target);
    if (sp && tp && sp === tp && expandedByProfile.has(sp)) {
      (intra[sp] ??= []).push(e);
    }
  }

  const placed: Record<string, { x: number; y: number }> = {};
  let yOffset = 0;

  if (supernodes.length > 0) {
    const sub = layoutGraph(supernodes, supernodeEdges, {
      ...options,
      flavor: "pipeline",
    });
    let groupMaxY = yOffset;
    for (const sn of sub.nodes) {
      const pos = { x: sn.position.x, y: sn.position.y + yOffset };
      placed[sn.id] = pos;
      groupMaxY = Math.max(groupMaxY, pos.y + NODE_HEIGHT);
    }
    yOffset = groupMaxY + BAND_GAP;
  }

  for (const profileId of expandedBandOrder) {
    const bandNodes = expandedByProfile.get(profileId) ?? [];
    const bandEdges = intra[profileId] ?? [];
    const sub = layoutGraph(bandNodes, bandEdges, {
      ...options,
      flavor: "pipeline",
    });
    let bandMaxY = yOffset;
    for (const sn of sub.nodes) {
      const pos = { x: sn.position.x, y: sn.position.y + yOffset };
      placed[sn.id] = pos;
      bandMaxY = Math.max(bandMaxY, pos.y + NODE_HEIGHT);
    }
    yOffset = bandMaxY + BAND_GAP;
  }

  const overrides = options.overrides ?? {};
  const hints = options.hintPositions ?? {};
  const nodes: Node[] = analyzeNodes.map((n) => {
    const computed = placed[n.id] ?? { x: 0, y: 0 };
    const final = overrides[n.id] ?? hints[n.id] ?? computed;
    return makeNode(n, final, Boolean(overrides[n.id]));
  });

  const validIds = new Set(analyzeNodes.map((n) => n.id));
  const validEdges = analyzeEdges.filter(
    (e) => validIds.has(e.source) && validIds.has(e.target),
  );
  return { nodes, edges: makeEdges(validEdges) };
}

function makeNode(
  n: AnalyzeNode,
  position: { x: number; y: number },
  manualPlaced: boolean,
): Node {
  return {
    id: n.id,
    type: "default",
    position,
    data: {
      label: n.label,
      kind: n.kind,
      attrs: n.attrs,
      original: n,
      manualPlaced,
      bandProfileId: profileIdFromNodeId(n.id),
    },
    className: `wb-node wb-node-${n.kind}`,
    draggable: true,
  };
}

function makeEdges(edges: AnalyzeEdge[]): Edge[] {
  return edges.map((e, idx) => ({
    id: `e-${idx}-${e.source}->${e.target}-${e.kind}`,
    source: e.source,
    target: e.target,
    label: e.kind === "pv_cross_pipeline" ? "↪" : e.kind,
    data: { kind: e.kind, attrs: e.attrs, original: e },
    className: `wb-edge wb-edge-${e.kind}`,
  }));
}

/** Clamp the spacing knob into a sane range so a stray slider value can't
 *  produce a 100k-pixel canvas or a degenerate zero-sep layout. Defaults to 1. */
function clampSpacing(factor: number | undefined): number {
  if (typeof factor !== "number" || !Number.isFinite(factor)) return 1;
  if (factor < 0.5) return 0.5;
  if (factor > 3) return 3;
  return factor;
}

function profileIdFromNodeId(id: string): string | null {
  // Stage nodes are `pv:<profile_id>:<rest>`; supernodes use the
  // `pv_super:<profile_id>` namespace and resolve to that profile too.
  const stage = /^pv:([^:]+):/.exec(id);
  if (stage) return stage[1];
  const super_ = /^pv_super:([^:]+)$/.exec(id);
  if (super_) return super_[1];
  return null;
}

// =============================================================================
// Mindmap-style radial focus layout (spec 74 §Layout strategy hybrid).
// Selected node sits at the origin. Each child's angular sector is *inherited
// from its parent*: a ring-2 child takes a sub-slice of its ring-1 parent's
// own sector instead of fighting other parents on the same ring. This keeps
// subtrees grouped — the property that makes hand-drawn mindmaps readable.
// Upstream subtrees (incoming edges) sit on the LEFT semicircle;
// downstream subtrees (outgoing edges) on the RIGHT; preserving the L→R flow.
// Synchronous + deterministic.
// =============================================================================

const FOCUS_RING_RADIUS = 220; // px between consecutive rings
const FOCUS_RING_GROWTH = 80;  // each subsequent ring widens by this much

interface FocusBfsNode {
  id: string;
  depth: number;
  parent: string | null;
  side: "upstream" | "downstream" | "self";
}

function layoutFocusRadial(
  analyzeNodes: AnalyzeNode[],
  analyzeEdges: AnalyzeEdge[],
  options: LayoutOptions,
): LaidOutGraph {
  const overrides = options.overrides ?? {};
  const hints = options.hintPositions ?? {};
  const focusId = options.focusNodeId ?? null;
  const depth = Math.max(1, options.focusDepth ?? 2);

  if (!focusId || !analyzeNodes.some((n) => n.id === focusId)) {
    return layoutGraph(analyzeNodes, analyzeEdges, {
      ...options,
      flavor: "pipeline",
    });
  }

  const nodeIds = new Set(analyzeNodes.map((n) => n.id));
  const validEdges = analyzeEdges.filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target),
  );

  // BFS to assemble the focus tree. We classify each non-root node by "side"
  // (upstream vs downstream) at the moment we discover it; the side is
  // inherited from the parent for nodes deeper than 1 hop, so a downstream
  // subtree stays on the right even if it has incoming edges from siblings.
  const tree = new Map<string, FocusBfsNode>();
  tree.set(focusId, { id: focusId, depth: 0, parent: null, side: "self" });
  const queue: string[] = [focusId];

  // Stable adjacency for deterministic ordering: out-neighbours (downstream)
  // and in-neighbours (upstream), each sorted by id. We mark each parent's
  // children in deterministic order so sibling angles match across runs.
  const outOf = new Map<string, string[]>();
  const inOf = new Map<string, string[]>();
  for (const e of validEdges) {
    if (!outOf.has(e.source)) outOf.set(e.source, []);
    outOf.get(e.source)!.push(e.target);
    if (!inOf.has(e.target)) inOf.set(e.target, []);
    inOf.get(e.target)!.push(e.source);
  }
  for (const arr of outOf.values()) arr.sort();
  for (const arr of inOf.values()) arr.sort();

  while (queue.length > 0) {
    const here = queue.shift()!;
    const node = tree.get(here)!;
    if (node.depth >= depth) continue;
    if (node.depth === 0) {
      // Direct neighbours of the focus split between upstream + downstream.
      for (const child of outOf.get(here) ?? []) {
        if (tree.has(child)) continue;
        tree.set(child, { id: child, depth: 1, parent: here, side: "downstream" });
        queue.push(child);
      }
      for (const child of inOf.get(here) ?? []) {
        if (tree.has(child)) continue;
        tree.set(child, { id: child, depth: 1, parent: here, side: "upstream" });
        queue.push(child);
      }
    } else {
      // Deeper nodes inherit their parent's side; we walk both directions
      // (out + in) since downstream subtrees still contain inbound edges.
      const sides = ["downstream", "upstream"] as const;
      void sides; // semantic comment only
      const children = [
        ...(outOf.get(here) ?? []),
        ...(inOf.get(here) ?? []),
      ];
      // Stable, dedup by insertion order
      const seenChild = new Set<string>();
      for (const child of children) {
        if (child === here) continue;
        if (tree.has(child)) continue;
        if (seenChild.has(child)) continue;
        seenChild.add(child);
        tree.set(child, {
          id: child,
          depth: node.depth + 1,
          parent: here,
          side: node.side === "self" ? "downstream" : node.side,
        });
        queue.push(child);
      }
    }
  }

  // Build parent → children map (deterministic order: by id) for sector
  // assignment. Compute each node's "subtree size" so wider subtrees get
  // proportionally larger angular slices — keeps dense subtrees from
  // squashing sparse ones.
  const childrenOf = new Map<string, string[]>();
  for (const n of tree.values()) {
    if (n.parent === null) continue;
    if (!childrenOf.has(n.parent)) childrenOf.set(n.parent, []);
    childrenOf.get(n.parent)!.push(n.id);
  }
  for (const arr of childrenOf.values()) arr.sort();

  const subtreeSize = new Map<string, number>();
  function computeSubtreeSize(id: string): number {
    if (subtreeSize.has(id)) return subtreeSize.get(id)!;
    const kids = childrenOf.get(id) ?? [];
    let size = 1;
    for (const k of kids) size += computeSubtreeSize(k);
    subtreeSize.set(id, size);
    return size;
  }
  computeSubtreeSize(focusId);

  // Polar placement.
  // Convention: angle 0° = east (+x), 90° = south (+y), 180° = west (-x), 270° = north (-y).
  // Downstream subtree spans -90°..+90° (right semicircle, centered on east).
  // Upstream subtree spans 90°..270° (left semicircle, centered on west).
  const positions: Record<string, { x: number; y: number }> = {
    [focusId]: { x: 0, y: 0 },
  };

  // Seed: assign sectors to the focus node's direct children.
  const focusKids = childrenOf.get(focusId) ?? [];
  const downstream = focusKids.filter((id) => tree.get(id)!.side === "downstream");
  const upstream = focusKids.filter((id) => tree.get(id)!.side === "upstream");

  // Each side's children share that semicircle, weighted by subtree size.
  const sectors = new Map<string, { startDeg: number; endDeg: number }>();
  assignSectorsWeighted(downstream, -90, 90, subtreeSize, sectors);
  assignSectorsWeighted(upstream, 90, 270, subtreeSize, sectors);

  // Now BFS-layout: place each node at the midpoint of its sector at its
  // ring radius, then split its sector among its own children.
  const placeQueue: string[] = [...focusKids];
  while (placeQueue.length > 0) {
    const id = placeQueue.shift()!;
    const node = tree.get(id)!;
    const sector = sectors.get(id);
    if (!sector) continue;
    const midDeg = (sector.startDeg + sector.endDeg) / 2;
    const focusSpacing = clampSpacing(options.spacingFactor);
    const radius =
      (FOCUS_RING_RADIUS +
        (node.depth - 1) * (FOCUS_RING_RADIUS + FOCUS_RING_GROWTH)) *
      focusSpacing;
    const rad = (midDeg * Math.PI) / 180;
    positions[id] = { x: Math.cos(rad) * radius, y: Math.sin(rad) * radius };

    const kids = childrenOf.get(id) ?? [];
    if (kids.length > 0 && node.depth < depth) {
      // Slightly shrink the sector so children stay visibly inside their
      // parent's column. The shrink factor controls how fast subtrees
      // narrow with depth — too aggressive ⇒ overlap; too gentle ⇒ siblings
      // bleed into one another. 0.85 reads well for typical configs.
      const span = sector.endDeg - sector.startDeg;
      const shrink = 0.85;
      const newSpan = span * shrink;
      const center = midDeg;
      const childStart = center - newSpan / 2;
      const childEnd = center + newSpan / 2;
      assignSectorsWeighted(kids, childStart, childEnd, subtreeSize, sectors);
      placeQueue.push(...kids);
    }
  }

  const nodes: Node[] = analyzeNodes.map((n) => {
    const computed = positions[n.id];
    const fallback = hints[n.id] ?? { x: 0, y: 0 };
    const final = overrides[n.id] ?? computed ?? fallback;
    return makeNode(n, final, Boolean(overrides[n.id]));
  });
  const edges = makeEdges(validEdges);
  return { nodes, edges };
}

function assignSectorsWeighted(
  ids: string[],
  startDeg: number,
  endDeg: number,
  subtreeSize: Map<string, number>,
  out: Map<string, { startDeg: number; endDeg: number }>,
): void {
  if (ids.length === 0) return;
  const totalWeight = ids.reduce((s, id) => s + (subtreeSize.get(id) ?? 1), 0);
  const span = endDeg - startDeg;
  let cursor = startDeg;
  for (const id of ids) {
    const w = subtreeSize.get(id) ?? 1;
    const slice = (w / totalWeight) * span;
    out.set(id, { startDeg: cursor, endDeg: cursor + slice });
    cursor += slice;
  }
}

/** Compute a depth-limited neighborhood around a focus node id. Used for the
 *  k-hop focus toggle (spec 74 §Progressive disclosure). */
export function neighborhood(
  focusNodeId: string,
  edges: AnalyzeEdge[],
  depth: number,
): Set<string> {
  const visible = new Set<string>([focusNodeId]);
  let frontier: Set<string> = new Set([focusNodeId]);
  for (let d = 0; d < depth; d++) {
    const nextFrontier = new Set<string>();
    for (const e of edges) {
      if (frontier.has(e.source) && !visible.has(e.target)) nextFrontier.add(e.target);
      if (frontier.has(e.target) && !visible.has(e.source)) nextFrontier.add(e.source);
    }
    nextFrontier.forEach((id) => visible.add(id));
    frontier = nextFrontier;
    if (frontier.size === 0) break;
  }
  return visible;
}
