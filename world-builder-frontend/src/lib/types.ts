// Mirrors engine/world_builder service envelopes (spec 74).
// Keep these in sync when service contracts change.

export type Severity = "error" | "warning";

export type Section =
  | "scenario"
  | "simulation"
  | "world"
  | "pipeline"
  | "money"
  | "currency_catalog"
  | "fx"
  | "calendars"
  | "regions"
  | "control_defaults";

export type GraphView = "topology" | "pipeline";

export interface Diagnostic {
  code: string;
  message: string;
  path: string | null;
  severity: Severity;
  /** Optional graph-target hint. When set, UI focuses/highlights this node on click. */
  node_id?: string | null;
  /** Optional edge-target hint (synthetic React-Flow edge id or `pe:*`). */
  edge_id?: string | null;
  section?: Section | null;
  /** Which graph view to switch to before focusing (spec 74 §Diagnostic routing). */
  graph_view?: GraphView | null;
}

export type NodeKind =
  | "vendor"
  | "product"
  | "pop"
  | "region"
  | "calendar"
  | "pipeline_profile"
  | "pv_intent"
  | "pv_destination"
  | "pv_outgoing_intent"
  | "pv_ledger"
  | "pv_container"
  | "pv_posting"
  | "pv_transfer"
  | "pv_fee"
  | "pv_settlement_demand"
  | "pv_settlement_policy"
  // Aggregate-collapsed supernode (one per profile). Click to expand.
  | "pv_super";

export type EdgeKind =
  | "owns"
  | "linked_to"
  | "binds_profile"
  | "in_region"
  | "uses_calendar"
  | "role_binding"
  | "destination_route"
  | "pv_routes_to"
  | "pv_emits"
  | "pv_posts_from"
  | "pv_posts_to"
  | "pv_transfer_from"
  | "pv_transfer_to"
  | "pv_triggers_fee"
  | "pv_triggers_demand"
  | "pv_triggers_posting"
  | "pv_triggers_transfer"
  | "pv_pays_from"
  | "pv_maps_to_container"
  | "pv_cross_pipeline"
  // Synthetic supernode-to-supernode link in the collapsed aggregate view.
  | "pv_super_link";

/** Edge classes for the visibility filter UI (spec 74 §Progressive disclosure).
 *  Each EdgeKind belongs to one class. */
export type EdgeClass =
  | "structural"      // owns / linked_to / binds_profile / in_region / uses_calendar / role_binding / pv_routes_to / pv_emits / pv_pays_from / pv_maps_to_container
  | "trigger"         // pv_triggers_*
  | "posting"         // pv_posts_from / pv_posts_to
  | "transfer"        // pv_transfer_from / pv_transfer_to
  | "cross_pipeline"; // pv_cross_pipeline / pv_super_link / destination_route

export function classifyEdgeKind(kind: EdgeKind): EdgeClass {
  switch (kind) {
    case "pv_triggers_fee":
    case "pv_triggers_demand":
    case "pv_triggers_posting":
    case "pv_triggers_transfer":
      return "trigger";
    case "pv_posts_from":
    case "pv_posts_to":
      return "posting";
    case "pv_transfer_from":
    case "pv_transfer_to":
      return "transfer";
    case "pv_cross_pipeline":
    case "pv_super_link":
    case "destination_route":
      return "cross_pipeline";
    default:
      return "structural";
  }
}

/** Stable id for the synthetic "all profiles" scope used in pipeline mode. */
export const PIPELINE_SCOPE_AGGREGATE = "__aggregate__";
export type PipelineScope = string; // "__aggregate__" | <profile_id>

export interface AnalyzeNode {
  id: string;
  kind: NodeKind;
  label: string;
  attrs: Record<string, unknown>;
}

export interface AnalyzeEdge {
  source: string;
  target: string;
  kind: EdgeKind;
  attrs: Record<string, unknown>;
}

export interface ValidationReport {
  valid: boolean;
  errors: Diagnostic[];
  warnings: Diagnostic[];
  schema_version: string | null;
  pipeline_schema_version: string | null;
  summary?: Record<string, unknown> | null;
}

export interface NormalizationReport {
  valid: boolean;
  errors: Diagnostic[];
  warnings: Diagnostic[];
  normalized_yaml: string | null;
  normalized_json: Record<string, unknown> | null;
  revalidates: boolean | null;
}

export interface PipelineView {
  profile_id: string;
  label: string;
  nodes: AnalyzeNode[];
  edges: AnalyzeEdge[];
  summary: Record<string, unknown>;
}

export interface PipelineAggregate {
  nodes: AnalyzeNode[];
  edges: AnalyzeEdge[];
  summary: Record<string, unknown>;
  profiles: string[];
}

export interface AnalysisReport {
  valid: boolean;
  errors: Diagnostic[];
  warnings: Diagnostic[];
  graph: { nodes: AnalyzeNode[]; edges: AnalyzeEdge[] };
  unresolved_refs: Diagnostic[];
  pipeline_views?: PipelineView[];
  pipeline_aggregate?: PipelineAggregate | null;
}

/** Map a node kind to its containing config section (for filter linking). */
export function sectionForNodeKind(kind: NodeKind): Section | null {
  switch (kind) {
    case "vendor":
    case "product":
    case "pop":
      return "world";
    case "pipeline_profile":
      return "pipeline";
    case "region":
      return "regions";
    case "calendar":
      return "calendars";
    default:
      // pv_* stage nodes live inside the pipeline drill-down view; no
      // direct topology section.
      return null;
  }
}
