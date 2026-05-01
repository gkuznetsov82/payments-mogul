import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Edge, Node } from "@xyflow/react";

import { DiagnosticsList } from "./components/DiagnosticsList";
import { DetailsPane, type DetailsTarget } from "./components/DetailsPane";
import { EdgeFilters } from "./components/EdgeFilters";
import { GraphCanvas, type GraphCanvasHandle } from "./components/GraphCanvas";
import { PipelineScopeControl } from "./components/PipelineScopeControl";
import { SectionNav } from "./components/SectionNav";
import { api } from "./lib/api";
import { elkLayoutGraph, layoutGraph, neighborhood } from "./lib/layout";
import {
  diagnosticBelongsToSection,
  nodeKindsForSection,
} from "./lib/sections";
import { composeAggregateGraph, isSuperNodeId } from "./lib/supernodes";
import {
  classifyEdgeKind,
  sectionForNodeKind,
  PIPELINE_SCOPE_AGGREGATE,
  type AnalysisReport,
  type AnalyzeEdge,
  type AnalyzeNode,
  type Diagnostic,
  type EdgeClass,
  type EdgeKind,
  type GraphView,
  type NormalizationReport,
  type PipelineScope,
  type Section,
  type ValidationReport,
} from "./lib/types";

import "./styles.css";

type Mode = "validate" | "normalize" | "analyze" | null;

type Spacing = "compact" | "normal" | "spacious" | "roomy";

const SPACING_FACTOR: Record<Spacing, number> = {
  compact: 0.7,
  normal: 1.0,
  spacious: 1.5,
  roomy: 2.2,
};

interface RunState {
  validation: ValidationReport | null;
  normalization: NormalizationReport | null;
  analysis: AnalysisReport | null;
  mode: Mode;
  busy: boolean;
  serverError: string | null;
}

function emptyState(): RunState {
  return {
    validation: null,
    normalization: null,
    analysis: null,
    mode: null,
    busy: false,
    serverError: null,
  };
}

interface ManualOverrides {
  topology: Record<string, { x: number; y: number }>;
  // Per-scope overrides; keyed by scope (`__aggregate__` or profile_id).
  pipeline: Record<string, Record<string, { x: number; y: number }>>;
}

export default function App() {
  const [yamlText, setYamlText] = useState<string>("");
  const [run, setRun] = useState<RunState>(emptyState());
  const [activeSection, setActiveSection] = useState<Section | null>(null);
  const [search, setSearch] = useState<string>("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [focusedEdgeId, setFocusedEdgeId] = useState<string | null>(null);
  const [focusedDiagIndex, setFocusedDiagIndex] = useState<number | null>(null);
  const [noTargetFallback, setNoTargetFallback] = useState<
    { code: string; reason: string } | null
  >(null);

  const [viewMode, setViewMode] = useState<GraphView>("topology");
  // Pipeline scope: `__aggregate__` (default) or a profile_id. Spec 74
  // §Pipeline scope UX requires this to be explicit and prominent — surfaced
  // via the toolbar PipelineScopeControl component.
  const [pipelineScope, setPipelineScope] = useState<PipelineScope>(PIPELINE_SCOPE_AGGREGATE);
  const [overrides, setOverrides] = useState<ManualOverrides>({
    topology: {},
    pipeline: {},
  });
  const [layoutNonce, setLayoutNonce] = useState(0); // forces re-layout on demand
  const [dragLocked, setDragLocked] = useState(false);
  const [neighborhoodMode, setNeighborhoodMode] = useState(false);
  const [neighborhoodDepth, setNeighborhoodDepth] = useState(2);
  // Spacing knob (spec 74 §Readability): scales node + rank separation so
  // dense graphs can be spread out on demand. Mental-map cache is cleared
  // on change so the new spacing visibly takes effect.
  const [spacing, setSpacing] = useState<Spacing>("normal");

  // Progressive disclosure (spec 74 §Progressive disclosure):
  //   - aggregate scope defaults to a collapsed supernode-per-profile view;
  //     `expandedProfiles` holds the profiles whose internals are visible.
  //   - edge-class filters narrow the visible edges to the relevant class set.
  const [expandedProfiles, setExpandedProfiles] = useState<Set<string>>(new Set());
  const [edgeClassFilter, setEdgeClassFilter] = useState<Set<EdgeClass>>(
    new Set(["structural", "cross_pipeline"]),
  );

  const graphRef = useRef<GraphCanvasHandle>(null);
  // Mental-map continuity (spec 74 §Mental-map continuity): cache positions
  // by node id so unchanged nodes stay put across scope switches, filter
  // toggles, and expand/collapse transitions. ELK only computes positions
  // for nodes the cache doesn't already cover. Manual drag updates the cache.
  const positionCacheRef = useRef<Record<string, { x: number; y: number }>>({});

  const analysis = run.analysis;
  const topologyNodes = analysis?.graph.nodes ?? [];
  const topologyEdges = analysis?.graph.edges ?? [];
  const pipelineViews = analysis?.pipeline_views ?? [];
  const pipelineAggregate = analysis?.pipeline_aggregate ?? null;

  const isAggregateScope = pipelineScope === PIPELINE_SCOPE_AGGREGATE;

  // -------------------------------------------------- active drill-down view
  const activePipelineView = useMemo(() => {
    if (pipelineViews.length === 0) return null;
    if (isAggregateScope) return null;
    return (
      pipelineViews.find((v) => v.profile_id === pipelineScope) ?? pipelineViews[0] ?? null
    );
  }, [pipelineViews, pipelineScope, isAggregateScope]);

  // Active graph derivation. In aggregate scope we COMPOSE nodes/edges from
  // the per-profile views + cross-pipeline edges, collapsing un-expanded
  // profiles into supernodes. Edge-class filter is then applied so the user
  // sees only the relations they care about.
  const composed = useMemo(() => {
    if (viewMode === "topology") {
      return { nodes: topologyNodes, edges: topologyEdges };
    }
    if (isAggregateScope) {
      return composeAggregateGraph({
        views: pipelineViews,
        aggregate: pipelineAggregate,
        expandedProfiles,
      });
    }
    return {
      nodes: activePipelineView?.nodes ?? [],
      edges: activePipelineView?.edges ?? [],
    };
  }, [
    viewMode,
    topologyNodes,
    topologyEdges,
    isAggregateScope,
    pipelineViews,
    pipelineAggregate,
    expandedProfiles,
    activePipelineView,
  ]);

  const activeNodes: AnalyzeNode[] = composed.nodes;
  const activeEdges: AnalyzeEdge[] = useMemo(() => {
    return composed.edges.filter((e) =>
      edgeClassFilter.has(classifyEdgeKind(e.kind as EdgeKind)),
    );
  }, [composed.edges, edgeClassFilter]);

  const activeOverrides = useMemo(() => {
    if (viewMode === "topology") return overrides.topology;
    return overrides.pipeline[pipelineScope] ?? {};
  }, [viewMode, overrides, pipelineScope]);

  // -------------------------------------------------- section + search filter
  const sectionKinds = nodeKindsForSection(activeSection);
  const searchLower = search.trim().toLowerCase();
  const visibleNodeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const n of activeNodes) {
      const kindOk =
        viewMode === "pipeline" ||
        sectionKinds === null ||
        sectionKinds.size === 0 ||
        sectionKinds.has(n.kind);
      const searchOk =
        searchLower.length === 0 ||
        n.label.toLowerCase().includes(searchLower) ||
        n.id.toLowerCase().includes(searchLower);
      if (kindOk && searchOk) ids.add(n.id);
    }
    return ids;
  }, [activeNodes, sectionKinds, searchLower, viewMode]);

  // Neighborhood mode: only a depth-N subgraph around the selected node.
  const neighborhoodIds = useMemo(() => {
    if (!neighborhoodMode || !selectedNodeId) return null;
    return neighborhood(selectedNodeId, activeEdges, neighborhoodDepth);
  }, [neighborhoodMode, selectedNodeId, activeEdges, neighborhoodDepth]);

  const fadedNodeIds = useMemo(() => {
    const faded = new Set<string>();
    for (const n of activeNodes) {
      if (!visibleNodeIds.has(n.id)) {
        faded.add(n.id);
        continue;
      }
      if (neighborhoodIds && !neighborhoodIds.has(n.id)) faded.add(n.id);
    }
    return faded;
  }, [activeNodes, visibleNodeIds, neighborhoodIds]);

  // -------------------------------------------------- layout
  // Synchronous dagre is the primary layout engine inside React's render
  // cycle so component tests stay synchronous and deterministic. ELK
  // (hierarchical, crossing-minimised) runs as a non-blocking enhancement
  // pass in the browser only; in tests/jsdom we skip it (spec 74 §Hierarchical
  // layout quality, with a deterministic fallback being acceptable).
  //
  // When focus mode is on AND a node is selected, we route layout through
  // the radial "focus" flavor instead — spec 74 §Layout strategy hybrid:
  // mindmap-style local view that's visibly less tangled than the baseline.
  const focusActive = neighborhoodMode && Boolean(selectedNodeId);

  // In focus mode we restrict the layout *input* to just the depth-N
  // neighborhood. Otherwise the radial cluster sits on top of every
  // non-neighborhood node still rendered at its old TB-tree position
  // (just at 25% opacity), producing the cluttered view the user reported.
  const layoutNodes: AnalyzeNode[] = useMemo(() => {
    if (focusActive && neighborhoodIds) {
      return activeNodes.filter((n) => neighborhoodIds.has(n.id));
    }
    return activeNodes;
  }, [focusActive, neighborhoodIds, activeNodes]);

  const layoutEdges: AnalyzeEdge[] = useMemo(() => {
    if (focusActive && neighborhoodIds) {
      return activeEdges.filter(
        (e) => neighborhoodIds.has(e.source) && neighborhoodIds.has(e.target),
      );
    }
    return activeEdges;
  }, [focusActive, neighborhoodIds, activeEdges]);

  const baseFlavor: "topology" | "pipeline" | "pipeline_aggregate" =
    viewMode === "topology"
      ? "topology"
      : isAggregateScope
        ? "pipeline_aggregate"
        : "pipeline";
  const flavor = focusActive ? "focus" : baseFlavor;

  const spacingFactor = SPACING_FACTOR[spacing];

  const baseLayout = useMemo(() => {
    return layoutGraph(layoutNodes, layoutEdges, {
      flavor,
      overrides: activeOverrides,
      hintPositions: positionCacheRef.current,
      profileBands: pipelineAggregate?.profiles,
      focusNodeId: focusActive ? selectedNodeId : null,
      focusDepth: neighborhoodDepth,
      spacingFactor,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    layoutNodes,
    layoutEdges,
    flavor,
    activeOverrides,
    pipelineAggregate?.profiles,
    layoutNonce,
    focusActive,
    selectedNodeId,
    neighborhoodDepth,
    spacingFactor,
  ]);

  const [elkOverlay, setElkOverlay] = useState<{ nodes: Node[]; edges: Edge[] } | null>(
    null,
  );

  useEffect(() => {
    // Skip ELK overlay when running under vitest/jsdom — saves us ~700kB of
    // module load and the worker-pool crash that elkjs's bundled worker
    // boot causes in the test runner.
    if (typeof window === "undefined") return;
    const proc = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
    const env = proc?.env;
    if (env?.VITEST || env?.NODE_ENV === "test") return;
    let cancelled = false;
    elkLayoutGraph(layoutNodes, layoutEdges, {
      flavor,
      overrides: activeOverrides,
      hintPositions: positionCacheRef.current,
      profileBands: pipelineAggregate?.profiles,
      focusNodeId: focusActive ? selectedNodeId : null,
      focusDepth: neighborhoodDepth,
      spacingFactor,
    })
      .then((next) => {
        if (cancelled) return;
        for (const n of next.nodes) {
          positionCacheRef.current[n.id] = n.position;
        }
        setElkOverlay(next);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    layoutNodes,
    layoutEdges,
    flavor,
    activeOverrides,
    pipelineAggregate?.profiles,
    layoutNonce,
    focusActive,
    selectedNodeId,
    neighborhoodDepth,
    spacingFactor,
  ]);

  // Update the position cache from the synchronous base layout too, so
  // mental-map continuity works in tests where ELK doesn't run.
  for (const n of baseLayout.nodes) {
    if (!positionCacheRef.current[n.id]) {
      positionCacheRef.current[n.id] = n.position;
    }
  }

  const laidOut = elkOverlay ?? baseLayout;

  // -------------------------------------------------- counts for nav
  const sectionCounts = useMemo(() => {
    const counts: Record<string, { nodes: number; diagnostics: number }> = {};
    for (const n of topologyNodes) {
      const sec = sectionForNodeKind(n.kind);
      if (!sec) continue;
      counts[sec] = counts[sec] ?? { nodes: 0, diagnostics: 0 };
      counts[sec].nodes += 1;
    }
    const allDiags = collectDiagnostics(run);
    for (const d of allDiags) {
      const sec = d.section;
      if (!sec) continue;
      counts[sec] = counts[sec] ?? { nodes: 0, diagnostics: 0 };
      counts[sec].diagnostics += 1;
    }
    return counts as Partial<
      Record<Section, { nodes: number; diagnostics: number }>
    >;
  }, [topologyNodes, run]);

  const totals = {
    nodes: topologyNodes.length,
    diagnostics: collectDiagnostics(run).length,
  };

  // -------------------------------------------------- diagnostics filtered
  const diagnostics = useMemo(() => {
    const all = collectDiagnostics(run);
    return all.filter((d) => diagnosticBelongsToSection(d, activeSection));
  }, [run, activeSection]);

  // -------------------------------------------------- details target
  const detailsTarget: DetailsTarget = useMemo(() => {
    if (selectedNodeId) {
      const node = activeNodes.find((n) => n.id === selectedNodeId);
      if (node) return { kind: "node", node };
    }
    if (selectedEdgeId) {
      const idx = parseSyntheticEdgeIndex(selectedEdgeId);
      if (idx !== null && idx < activeEdges.length) {
        return { kind: "edge", edge: activeEdges[idx] };
      }
    }
    return null;
  }, [selectedNodeId, selectedEdgeId, activeNodes, activeEdges]);

  // -------------------------------------------------- drag persistence
  const handleNodeMoved = useCallback(
    (id: string, position: { x: number; y: number }) => {
      setOverrides((prev) => {
        if (viewMode === "topology") {
          return { ...prev, topology: { ...prev.topology, [id]: position } };
        }
        const prevPipeline = prev.pipeline[pipelineScope] ?? {};
        return {
          ...prev,
          pipeline: {
            ...prev.pipeline,
            [pipelineScope]: { ...prevPipeline, [id]: position },
          },
        };
      });
    },
    [viewMode, pipelineScope],
  );

  function resetManualLayout() {
    if (viewMode === "topology") {
      setOverrides((prev) => ({ ...prev, topology: {} }));
    } else {
      setOverrides((prev) => {
        const next = { ...prev.pipeline };
        delete next[pipelineScope];
        return { ...prev, pipeline: next };
      });
    }
    // Mental-map cache must also clear or reset becomes a no-op visually.
    positionCacheRef.current = {};
    setLayoutNonce((n) => n + 1);
    graphRef.current?.fitView();
  }

  function handleSpacingChange(next: Spacing) {
    setSpacing(next);
    // Spacing change is a deliberate reflow — cached positions would
    // override the new spacing if we kept them, so we clear them and bump
    // the layout nonce to trigger a fresh layout pass.
    positionCacheRef.current = {};
    setLayoutNonce((n) => n + 1);
  }

  function reapplyAutoLayout() {
    // Re-run layout but KEEP the position cache so unchanged nodes don't
    // shift; only newly added or filter-introduced nodes get fresh positions.
    setLayoutNonce((n) => n + 1);
    graphRef.current?.fitView();
  }

  function toggleProfileExpand(profileId: string) {
    setExpandedProfiles((prev) => {
      const next = new Set(prev);
      if (next.has(profileId)) next.delete(profileId);
      else next.add(profileId);
      return next;
    });
  }

  function expandAllProfiles() {
    const all = new Set<string>(pipelineViews.map((v) => v.profile_id));
    setExpandedProfiles(all);
  }

  function collapseAllProfiles() {
    setExpandedProfiles(new Set());
  }

  // -------------------------------------------------- diagnostic click
  function handleDiagnosticClick(diag: Diagnostic, index: number) {
    setFocusedDiagIndex(index);

    // Switch view if hinted.
    if (diag.graph_view && diag.graph_view !== viewMode) {
      setViewMode(diag.graph_view);
    }

    // Edge target hint takes precedence when both are present, since edges
    // are more specific.
    if (diag.edge_id) {
      setNoTargetFallback(null);
      setFocusedEdgeId(diag.edge_id);
      setSelectedEdgeId(diag.edge_id);
      setSelectedNodeId(null);
      return;
    }
    if (diag.node_id) {
      setNoTargetFallback(null);
      // Auto-expand the containing profile if the target stage node sits
      // behind a collapsed supernode in aggregate scope. We queue this
      // via the state setter so it works even when handleDiagnosticClick
      // also flipped viewMode in the same React tick (spec 74 §Diagnostic
      // routing × §Progressive disclosure).
      const stageMatch = /^pv:([^:]+):/.exec(diag.node_id);
      if (stageMatch) {
        const profileId = stageMatch[1];
        setExpandedProfiles((prev) => {
          if (prev.has(profileId)) return prev;
          const next = new Set(prev);
          next.add(profileId);
          return next;
        });
      }
      navigateToNode(diag.node_id, null);
      return;
    }
    setNoTargetFallback({
      code: diag.code,
      reason:
        "This diagnostic has no graph target — its source field is not visualised on the topology graph.",
    });
    setFocusedNodeId(null);
    setFocusedEdgeId(null);
  }

  function handleSectionSelect(section: Section | null) {
    setActiveSection(section);
    setFocusedNodeId(null);
    setNoTargetFallback(null);
  }

  function handleViewModeChange(next: GraphView) {
    setViewMode(next);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setFocusedNodeId(null);
    setFocusedEdgeId(null);
    setNoTargetFallback(null);
  }

  function handleScopeChange(next: PipelineScope) {
    setPipelineScope(next);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setFocusedNodeId(null);
    setFocusedEdgeId(null);
    setNoTargetFallback(null);
  }

  /** Resolve a target node id against the current view; if not present, flip
   *  to the right scope (or aggregate as a safe fallback) so the navigation
   *  is honored even when the user is in a per-profile drill-down. */
  const navigateToNode = useCallback(
    (targetNodeId: string, targetProfileId?: string | null) => {
      // Stage nodes embed `pv:<profile_id>:` in the id. If the user is in
      // pipeline view but the target sits in a profile that's currently
      // collapsed (aggregate scope) or in a different per-profile scope,
      // we have to flip scope and/or auto-expand the containing profile so
      // the node becomes visible.
      const stageProfile = (() => {
        const m = /^pv:([^:]+):/.exec(targetNodeId);
        return m ? m[1] : null;
      })();
      const containingProfile = targetProfileId ?? stageProfile;
      if (viewMode === "pipeline") {
        const inCurrent = activeNodes.some((n) => n.id === targetNodeId);
        if (!inCurrent) {
          if (isAggregateScope) {
            // Stay in aggregate but auto-expand the containing profile so
            // the supernode unwraps to reveal the target.
            if (containingProfile) {
              setExpandedProfiles((prev) => {
                if (prev.has(containingProfile)) return prev;
                const next = new Set(prev);
                next.add(containingProfile);
                return next;
              });
            }
          } else if (containingProfile) {
            setPipelineScope(containingProfile);
          } else {
            setPipelineScope(PIPELINE_SCOPE_AGGREGATE);
          }
        }
      }
      setSelectedNodeId(targetNodeId);
      setFocusedNodeId(targetNodeId);
      setSelectedEdgeId(null);
      setFocusedEdgeId(null);
      // Defer focus call by one tick: when the scope changes or a profile
      // is just expanded, the new node only registers on the next render.
      setTimeout(() => graphRef.current?.focusNode(targetNodeId), 0);
    },
    [viewMode, activeNodes, isAggregateScope],
  );

  // -------------------------------------------------- run handlers
  async function runOp(op: Mode) {
    if (!yamlText.trim()) {
      setRun((r) => ({ ...r, serverError: "No YAML to send" }));
      return;
    }
    setRun((r) => ({ ...r, busy: true, mode: op, serverError: null }));
    try {
      const next = { ...run, busy: false, mode: op, serverError: null };
      next.analysis = await api.analyze(yamlText);
      if (op === "validate") {
        next.validation = await api.validate(yamlText);
      } else if (op === "normalize") {
        next.normalization = await api.normalize(yamlText);
      }
      setRun(next);
      // Pipeline scope defaults to aggregate (spec 74 §Pipeline scope UX);
      // we never auto-switch to a single profile.
    } catch (exc) {
      setRun((r) => ({
        ...r,
        busy: false,
        serverError: exc instanceof Error ? exc.message : String(exc),
      }));
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    setYamlText(text);
  }

  function downloadNormalized() {
    const norm = run.normalization?.normalized_yaml;
    if (!norm) return;
    const blob = new Blob([norm], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "world-config.normalized.yaml";
    a.click();
    URL.revokeObjectURL(url);
  }

  const validBadge = renderValidBadge(run);

  return (
    <div className="wb-app" data-testid="wb-app" data-view-mode={viewMode}>
      <header className="wb-header">
        <h1>WORLD BUILDER · v0_viewer</h1>
        <span className="wb-meta">
          {run.busy ? "running…" : run.mode ? `last: ${run.mode}` : "idle"}
          {run.serverError && (
            <span className="wb-error" data-testid="server-error">
              {" "}
              · {run.serverError}
            </span>
          )}
        </span>
      </header>

      <div className="wb-toolbar">
        <input
          type="file"
          accept=".yaml,.yml"
          aria-label="Load YAML file"
          data-testid="file-input"
          onChange={handleFileChange}
        />
        <button data-testid="btn-validate" onClick={() => runOp("validate")}>
          Validate
        </button>
        <button data-testid="btn-normalize" onClick={() => runOp("normalize")}>
          Normalize
        </button>
        <button data-testid="btn-analyze" onClick={() => runOp("analyze")}>
          Analyze
        </button>
        <button
          data-testid="btn-download"
          disabled={!run.normalization?.normalized_yaml}
          onClick={downloadNormalized}
        >
          Download normalized
        </button>

        <span className="wb-toolbar-sep" />

        <button
          data-testid="btn-view-topology"
          data-active={viewMode === "topology" ? "true" : "false"}
          className={viewMode === "topology" ? "wb-btn-active" : ""}
          onClick={() => handleViewModeChange("topology")}
        >
          Topology
        </button>
        <button
          data-testid="btn-view-pipeline"
          data-active={viewMode === "pipeline" ? "true" : "false"}
          className={viewMode === "pipeline" ? "wb-btn-active" : ""}
          onClick={() => handleViewModeChange("pipeline")}
          disabled={pipelineViews.length === 0}
        >
          Pipeline
        </button>

        {viewMode === "pipeline" && (
          <PipelineScopeControl
            scope={pipelineScope}
            views={pipelineViews}
            onChange={handleScopeChange}
            counts={{
              aggregate: pipelineAggregate
                ? {
                    nodes: pipelineAggregate.nodes.length,
                    edges: pipelineAggregate.edges.length,
                    cross:
                      Number(
                        (pipelineAggregate.summary as { cross_pipeline_edge_count?: number })
                          .cross_pipeline_edge_count ?? 0,
                      ),
                  }
                : undefined,
              perProfile: Object.fromEntries(
                pipelineViews.map((v) => [
                  v.profile_id,
                  { nodes: v.nodes.length, edges: v.edges.length },
                ]),
              ),
            }}
          />
        )}

        <span className="wb-toolbar-sep" />

        <button
          data-testid="btn-fit-view"
          onClick={() => graphRef.current?.fitView()}
        >
          Fit view
        </button>
        <button data-testid="btn-auto-layout" onClick={reapplyAutoLayout}>
          Auto layout
        </button>
        <button data-testid="btn-reset-layout" onClick={resetManualLayout}>
          Reset manual layout
        </button>
        <button
          data-testid="btn-toggle-lock"
          data-locked={dragLocked ? "true" : "false"}
          onClick={() => setDragLocked((v) => !v)}
        >
          {dragLocked ? "Unlock drag" : "Lock drag"}
        </button>
        <label className="wb-inline-label" data-testid="spacing-control">
          <span>Spacing</span>
          <select
            data-testid="spacing-select"
            data-spacing={spacing}
            value={spacing}
            onChange={(e) => handleSpacingChange(e.target.value as Spacing)}
          >
            <option value="compact">Compact</option>
            <option value="normal">Normal</option>
            <option value="spacious">Spacious</option>
            <option value="roomy">Roomy</option>
          </select>
        </label>
        {viewMode === "pipeline" && isAggregateScope && pipelineViews.length > 0 && (
          <>
            <span className="wb-toolbar-sep" />
            <button
              data-testid="btn-expand-all"
              onClick={expandAllProfiles}
              disabled={expandedProfiles.size === pipelineViews.length}
            >
              Expand all
            </button>
            <button
              data-testid="btn-collapse-all"
              onClick={collapseAllProfiles}
              disabled={expandedProfiles.size === 0}
            >
              Collapse all
            </button>
            <span className="wb-meta" data-testid="expand-state">
              {expandedProfiles.size}/{pipelineViews.length} expanded
            </span>
          </>
        )}
        <span className="wb-toolbar-sep" />
        <EdgeFilters visible={edgeClassFilter} onChange={setEdgeClassFilter} />
        <label className="wb-inline-label" data-testid="focus-mode-label">
          <input
            type="checkbox"
            data-testid="toggle-neighborhood"
            checked={neighborhoodMode}
            onChange={(e) => setNeighborhoodMode(e.target.checked)}
          />
          Focus mode (depth{" "}
          <input
            type="number"
            min={1}
            max={6}
            value={neighborhoodDepth}
            data-testid="neighborhood-depth"
            onChange={(e) => setNeighborhoodDepth(Number(e.target.value) || 1)}
            style={{ width: 40 }}
          />
          )
          {focusActive && (
            <span className="wb-focus-active" data-testid="focus-active-pill">
              radial · {selectedNodeId}
            </span>
          )}
        </label>
        <input
          type="search"
          placeholder="Search nodes…"
          aria-label="Search nodes"
          data-testid="search-input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {validBadge}
      </div>

      <main className="wb-main">
        <aside className="wb-pane wb-pane-left">
          {viewMode === "topology" ? (
            <>
              <h2>Sections</h2>
              <SectionNav
                active={activeSection}
                onSelect={handleSectionSelect}
                counts={sectionCounts}
                totals={totals}
              />
            </>
          ) : (
            <>
              <h2>Pipeline scope</h2>
              <div
                className="wb-pipeline-summary"
                data-testid="pipeline-active-scope"
                data-scope={pipelineScope}
              >
                <dl className="wb-details-fields">
                  <dt>scope</dt>
                  <dd>
                    {isAggregateScope ? "All profiles (aggregate)" : pipelineScope}
                  </dd>
                  <dt>nodes</dt>
                  <dd>{activeNodes.length}</dd>
                  <dt>edges</dt>
                  <dd>{activeEdges.length}</dd>
                  {isAggregateScope && pipelineAggregate && (
                    <>
                      <dt>cross-pipeline</dt>
                      <dd>
                        {String(
                          (pipelineAggregate.summary as { cross_pipeline_edge_count?: number })
                            .cross_pipeline_edge_count ?? 0,
                        )}{" "}
                        edges
                      </dd>
                    </>
                  )}
                </dl>
              </div>
            </>
          )}
          <h2>YAML Input</h2>
          <textarea
            data-testid="yaml-input"
            spellCheck={false}
            value={yamlText}
            onChange={(e) => setYamlText(e.target.value)}
            placeholder="Paste YAML or use Load YAML…"
          />
        </aside>

        <section
          className="wb-pane wb-pane-graph"
          data-testid="graph-pane"
          data-flavor={flavor}
          data-focus-active={focusActive ? "true" : "false"}
        >
          <GraphCanvas
            ref={graphRef}
            nodes={laidOut.nodes}
            edges={laidOut.edges}
            focusedNodeId={focusedNodeId}
            focusedEdgeId={focusedEdgeId}
            fadedNodeIds={fadedNodeIds}
            dragLocked={dragLocked}
            onSelectNode={(id) => {
              setSelectedNodeId(id);
              setSelectedEdgeId(null);
              setFocusedNodeId(id);
              setFocusedEdgeId(null);
              setFocusedDiagIndex(null);
              setNoTargetFallback(null);
              // Supernode click expands/collapses the underlying profile —
              // primary progressive-disclosure interaction (spec 74).
              if (id && isSuperNodeId(id)) {
                const profile = id.replace(/^pv_super:/, "");
                toggleProfileExpand(profile);
              }
            }}
            onSelectEdge={(id) => {
              setSelectedEdgeId(id);
              setSelectedNodeId(null);
              setFocusedEdgeId(id);
              if (id === null) return;
              // Cross-pipeline edges navigate to their resolved target.
              const idx = parseSyntheticEdgeIndex(id);
              if (idx !== null && idx < activeEdges.length) {
                const e = activeEdges[idx];
                if (e.kind === "pv_cross_pipeline") {
                  const targetNodeId = String(
                    e.attrs.target_node_id ?? e.target,
                  );
                  const targetProfileId = e.attrs.target_profile_id
                    ? String(e.attrs.target_profile_id)
                    : null;
                  navigateToNode(targetNodeId, targetProfileId);
                }
              }
            }}
            onNodeMoved={handleNodeMoved}
          />
        </section>

        <aside className="wb-pane wb-pane-right">
          <h2>Details</h2>
          <DetailsPane
            target={detailsTarget}
            edges={activeEdges}
            onRelatedEdgeClick={(e) => {
              // Find the synthetic id of this edge in the laid-out array so
              // the canvas can highlight it.
              const idx = activeEdges.findIndex((x) => x === e);
              if (idx >= 0) {
                const id = `e-${idx}-${e.source}->${e.target}-${e.kind}`;
                setSelectedEdgeId(id);
                setFocusedEdgeId(id);
                setSelectedNodeId(null);
              }
            }}
            onRelatedNodeClick={(nodeId) => {
              // Use navigateToNode so cross-scope jumps (e.g. clicking the
              // edge-target link of a cross-pipeline edge in per-profile
              // mode) flip the scope to where the target lives.
              navigateToNode(nodeId, null);
            }}
          />
          <h2>Diagnostics</h2>
          <DiagnosticsList
            diagnostics={diagnostics}
            focusedIndex={focusedDiagIndex}
            noTargetFallback={noTargetFallback}
            onDiagnosticClick={(d) =>
              handleDiagnosticClick(
                d,
                diagnostics.findIndex((x) => x === d),
              )
            }
          />
          {run.normalization?.normalized_yaml && (
            <>
              <h2>Normalized YAML</h2>
              <pre data-testid="normalized-preview" className="wb-normalized">
                {run.normalization.normalized_yaml}
              </pre>
            </>
          )}
        </aside>
      </main>
    </div>
  );
}

// --------------------------------------------------------------------------- helpers

function collectDiagnostics(run: RunState): Diagnostic[] {
  const out: Diagnostic[] = [];
  if (run.analysis) {
    out.push(...run.analysis.errors, ...run.analysis.warnings, ...run.analysis.unresolved_refs);
  } else if (run.validation) {
    out.push(...run.validation.errors, ...run.validation.warnings);
  }
  return out;
}

function renderValidBadge(run: RunState) {
  const v = run.analysis ?? run.validation ?? run.normalization;
  if (!v) return <span className="wb-badge wb-badge-muted">no run</span>;
  if (v.valid) return <span className="wb-badge wb-badge-ok">VALID</span>;
  return <span className="wb-badge wb-badge-fail">INVALID</span>;
}

function parseSyntheticEdgeIndex(syntheticId: string): number | null {
  const m = /^e-(\d+)-/.exec(syntheticId);
  if (!m) return null;
  const idx = Number(m[1]);
  return Number.isFinite(idx) ? idx : null;
}
