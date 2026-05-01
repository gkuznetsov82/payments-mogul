import type { AnalyzeEdge, AnalyzeNode } from "../lib/types";

export type DetailsTarget =
  | { kind: "node"; node: AnalyzeNode }
  | { kind: "edge"; edge: AnalyzeEdge }
  | null;

export interface DetailsPaneProps {
  target: DetailsTarget;
  /** Full edge list for the active graph view; used to compute incoming
   *  / outgoing edge summaries when the target is a node. */
  edges?: AnalyzeEdge[];
  /** Optional callback so users can jump from a related-edge row directly
   *  to that edge in the graph (focus + highlight). */
  onRelatedEdgeClick?: (edge: AnalyzeEdge) => void;
  /** Optional callback to focus a related node from the related-node list. */
  onRelatedNodeClick?: (nodeId: string) => void;
}

export function DetailsPane({
  target,
  edges = [],
  onRelatedEdgeClick,
  onRelatedNodeClick,
}: DetailsPaneProps) {
  if (target === null) {
    return (
      <div className="wb-details-empty" data-testid="details-empty">
        Select a node or edge to inspect.
      </div>
    );
  }
  if (target.kind === "node") {
    return (
      <NodeDetails
        node={target.node}
        edges={edges}
        onRelatedEdgeClick={onRelatedEdgeClick}
        onRelatedNodeClick={onRelatedNodeClick}
      />
    );
  }
  return <EdgeDetails edge={target.edge} onRelatedNodeClick={onRelatedNodeClick} />;
}

// --------------------------------------------------------------------- node

function NodeDetails({
  node,
  edges,
  onRelatedEdgeClick,
  onRelatedNodeClick,
}: {
  node: AnalyzeNode;
  edges: AnalyzeEdge[];
  onRelatedEdgeClick?: (edge: AnalyzeEdge) => void;
  onRelatedNodeClick?: (nodeId: string) => void;
}) {
  const incoming = edges.filter((e) => e.target === node.id);
  const outgoing = edges.filter((e) => e.source === node.id);
  const kindBlock = renderKindSpecific(node);

  return (
    <div className="wb-details" data-testid="details-pane" data-target="node">
      <header className="wb-details-header">
        <span className="wb-kind-tag">{node.kind}</span>
        <h3 data-testid="details-label">{node.label}</h3>
      </header>
      <dl className="wb-details-fields">
        <dt>id</dt>
        <dd data-testid="details-id">{node.id}</dd>
        <dt>kind</dt>
        <dd data-testid="details-kind">{node.kind}</dd>
        <dt>label</dt>
        <dd>{node.label}</dd>
      </dl>
      {kindBlock}
      <h4>attrs</h4>
      <pre data-testid="details-attrs" className="wb-details-attrs">
        {JSON.stringify(node.attrs, null, 2)}
      </pre>
      <h4>
        Connections{" "}
        <span className="wb-muted">
          (in {incoming.length} · out {outgoing.length})
        </span>
      </h4>
      <div className="wb-related" data-testid="related-edges">
        {incoming.length === 0 && outgoing.length === 0 && (
          <div className="wb-empty">No connections.</div>
        )}
        {outgoing.map((e, idx) => (
          <div
            key={`out-${idx}-${e.kind}-${e.target}`}
            role="button"
            tabIndex={0}
            className="wb-related-row"
            data-testid="related-edge-row"
            data-direction="out"
            onClick={() => onRelatedEdgeClick?.(e)}
            onKeyDown={(ev) => {
              if (ev.key === "Enter" || ev.key === " ") onRelatedEdgeClick?.(e);
            }}
          >
            <span className="wb-related-arrow">→</span>
            <span className="wb-related-kind">{e.kind}</span>
            <button
              type="button"
              className="wb-related-target"
              data-testid="related-node-link"
              onClick={(ev) => {
                ev.stopPropagation();
                onRelatedNodeClick?.(e.target);
              }}
            >
              {e.target}
            </button>
          </div>
        ))}
        {incoming.map((e, idx) => (
          <div
            key={`in-${idx}-${e.kind}-${e.source}`}
            role="button"
            tabIndex={0}
            className="wb-related-row"
            data-testid="related-edge-row"
            data-direction="in"
            onClick={() => onRelatedEdgeClick?.(e)}
            onKeyDown={(ev) => {
              if (ev.key === "Enter" || ev.key === " ") onRelatedEdgeClick?.(e);
            }}
          >
            <span className="wb-related-arrow">←</span>
            <span className="wb-related-kind">{e.kind}</span>
            <button
              type="button"
              className="wb-related-target"
              data-testid="related-node-link"
              onClick={(ev) => {
                ev.stopPropagation();
                onRelatedNodeClick?.(e.source);
              }}
            >
              {e.source}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------- edge

function EdgeDetails({
  edge,
  onRelatedNodeClick,
}: {
  edge: AnalyzeEdge;
  onRelatedNodeClick?: (nodeId: string) => void;
}) {
  const isCross = edge.kind === "pv_cross_pipeline";
  return (
    <div className="wb-details" data-testid="details-pane" data-target="edge">
      <header className="wb-details-header">
        <span className="wb-kind-tag">{edge.kind}</span>
        <h3>{edge.kind} edge</h3>
      </header>
      <dl className="wb-details-fields">
        <dt>id</dt>
        <dd data-testid="details-id">{`${edge.source}->${edge.target}:${edge.kind}`}</dd>
        <dt>kind</dt>
        <dd data-testid="details-kind">{edge.kind}</dd>
        <dt>source</dt>
        <dd>
          <button
            type="button"
            className="wb-related-target"
            data-testid="edge-source-link"
            onClick={() => onRelatedNodeClick?.(edge.source)}
          >
            {edge.source}
          </button>
        </dd>
        <dt>target</dt>
        <dd>
          <button
            type="button"
            className="wb-related-target"
            data-testid="edge-target-link"
            onClick={() => onRelatedNodeClick?.(edge.target)}
          >
            {edge.target}
          </button>
        </dd>
      </dl>
      {isCross && (
        <section className="wb-kind-summary" data-testid="kind-summary-cross-pipeline">
          <h4>Cross-pipeline navigation</h4>
          <dl className="wb-details-fields">
            <dt>trigger_id</dt>
            <dd>{String(edge.attrs.trigger_id ?? "?")}</dd>
            <dt>source_profile_id</dt>
            <dd>{String(edge.attrs.source_profile_id ?? "?")}</dd>
            <dt>target_profile_id</dt>
            <dd>{String(edge.attrs.target_profile_id ?? "?")}</dd>
            <dt>target_instance_id</dt>
            <dd>{String(edge.attrs.target_instance_id ?? "—")}</dd>
            <dt>target_node_id</dt>
            <dd>
              <button
                type="button"
                className="wb-related-target"
                data-testid="cross-target-link"
                onClick={() =>
                  onRelatedNodeClick?.(String(edge.attrs.target_node_id ?? edge.target))
                }
              >
                {String(edge.attrs.target_node_id ?? edge.target)}
              </button>
            </dd>
          </dl>
        </section>
      )}
      <h4>attrs</h4>
      <pre data-testid="details-attrs" className="wb-details-attrs">
        {JSON.stringify(edge.attrs, null, 2)}
      </pre>
    </div>
  );
}

// --------------------------------------------------------- kind-specific

/** Render kind-specific summary cards above the generic attrs blob so the
 *  user can read the most relevant fields at a glance (spec 74 §Details
 *  pane depth). */
function renderKindSpecific(node: AnalyzeNode): JSX.Element | null {
  switch (node.kind) {
    case "product":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-product">
          <h4>Product</h4>
          <dl className="wb-details-fields">
            <dt>vendor</dt>
            <dd>{String(node.attrs.vendor_id ?? "?")}</dd>
            <dt>class</dt>
            <dd>{String(node.attrs.product_class ?? "?")}</dd>
            <dt>profile</dt>
            <dd>{String(node.attrs.pipeline_profile_id ?? "—")}</dd>
          </dl>
        </section>
      );
    case "pipeline_profile":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-profile">
          <h4>Pipeline profile</h4>
          <dl className="wb-details-fields">
            <dt>intents</dt>
            <dd>{numberAttr(node.attrs.transaction_intent_count)}</dd>
            <dt>fees</dt>
            <dd>{numberAttr(node.attrs.fee_sequence_count)}</dd>
            <dt>demands</dt>
            <dd>{numberAttr(node.attrs.settlement_demand_sequence_count)}</dd>
          </dl>
        </section>
      );
    case "pop":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-pop">
          <h4>Pop</h4>
          <dl className="wb-details-fields">
            <dt>pop_count</dt>
            <dd>{numberAttr(node.attrs.pop_count)}</dd>
            <dt>region</dt>
            <dd>{String(node.attrs.region_id ?? "—")}</dd>
          </dl>
        </section>
      );
    case "vendor":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-vendor">
          <h4>Vendor</h4>
          <dl className="wb-details-fields">
            <dt>operational</dt>
            <dd>{String(node.attrs.operational ?? "?")}</dd>
            <dt>region</dt>
            <dd>{String(node.attrs.region_id ?? "—")}</dd>
          </dl>
        </section>
      );
    case "pv_intent":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-intent">
          <h4>Transaction intent</h4>
          <dl className="wb-details-fields">
            <dt>source_volume_ratio</dt>
            <dd>{numberAttr(node.attrs.source_volume_ratio)}</dd>
          </dl>
        </section>
      );
    case "pv_destination":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-destination">
          <h4>Routing destination</h4>
          <dl className="wb-details-fields">
            <dt>role</dt>
            <dd>{String(node.attrs.destination_role ?? "?")}</dd>
            <dt>outgoing_intent_id</dt>
            <dd>{String(node.attrs.outgoing_intent_id ?? "?")}</dd>
            <dt>value_date_policy</dt>
            <dd>{String(node.attrs.value_date_policy ?? "?")}</dd>
            <dt>routing_completion_mode</dt>
            <dd>{String(node.attrs.routing_completion_mode ?? "?")}</dd>
          </dl>
        </section>
      );
    case "pv_fee":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-fee">
          <h4>Fee</h4>
          <dl className="wb-details-fields">
            <dt>beneficiary_role</dt>
            <dd>{String(node.attrs.beneficiary_role ?? "?")}</dd>
            <dt>payer_role</dt>
            <dd>{String(node.attrs.payer_role ?? "—")}</dd>
            <dt>amount_percentage</dt>
            <dd>{numberAttr(node.attrs.amount_percentage)}</dd>
            <dt>non_payable_statement</dt>
            <dd>{String(node.attrs.non_payable_statement ?? "false")}</dd>
            <dt>settlement</dt>
            <dd>
              {String(node.attrs.settlement_value_date_policy ?? "?")}
              {node.attrs.settlement_value_date_offset_days !== undefined &&
                ` +${String(node.attrs.settlement_value_date_offset_days)}d`}
            </dd>
          </dl>
        </section>
      );
    case "pv_settlement_demand":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-demand">
          <h4>Settlement demand</h4>
          <dl className="wb-details-fields">
            <dt>creditor</dt>
            <dd>{String(node.attrs.creditor_role ?? "?")}</dd>
            <dt>debtor</dt>
            <dd>{String(node.attrs.debtor_role ?? "?")}</dd>
            <dt>category</dt>
            <dd>{String(node.attrs.invoice_category ?? "?")}</dd>
            <dt>amount_percentage</dt>
            <dd>{numberAttr(node.attrs.amount_percentage)}</dd>
            <dt>formula_ref</dt>
            <dd>{String(node.attrs.formula_ref ?? "—")}</dd>
          </dl>
        </section>
      );
    case "pv_ledger":
    case "pv_container":
      return (
        <section className="wb-kind-summary" data-testid={`kind-summary-${node.kind}`}>
          <h4>{node.kind === "pv_ledger" ? "Ledger ref" : "Container ref"}</h4>
          <dl className="wb-details-fields">
            <dt>path_pattern</dt>
            <dd>{String(node.attrs.path_pattern ?? "?")}</dd>
            {node.kind === "pv_ledger" && (
              <>
                <dt>normal_side</dt>
                <dd>{String(node.attrs.normal_side ?? "—")}</dd>
              </>
            )}
          </dl>
        </section>
      );
    case "pv_posting":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-posting">
          <h4>Posting rule</h4>
          <dl className="wb-details-fields">
            <dt>trigger_id</dt>
            <dd>{String(node.attrs.trigger_id ?? "?")}</dd>
            <dt>source ledger</dt>
            <dd>{String(node.attrs.source_ledger_ref ?? "?")}</dd>
            <dt>destination ledger</dt>
            <dd>{String(node.attrs.destination_ledger_ref ?? "?")}</dd>
            <dt>amount_basis</dt>
            <dd>{String(node.attrs.amount_basis ?? "?")}</dd>
            <dt>value_date</dt>
            <dd>
              {String(node.attrs.value_date_policy ?? "?")}
              {node.attrs.value_date_offset_days !== undefined &&
                ` +${String(node.attrs.value_date_offset_days)}d`}
            </dd>
            <dt>profile</dt>
            <dd>{String(node.attrs.profile_id ?? "—")}</dd>
            <dt>rule_index</dt>
            <dd>{String(node.attrs.rule_index ?? "—")}</dd>
          </dl>
        </section>
      );
    case "pv_transfer":
      return (
        <section className="wb-kind-summary" data-testid="kind-summary-transfer">
          <h4>Asset transfer rule</h4>
          <dl className="wb-details-fields">
            <dt>trigger_id</dt>
            <dd>{String(node.attrs.trigger_id ?? "?")}</dd>
            <dt>source container</dt>
            <dd>{String(node.attrs.source_container_ref ?? "?")}</dd>
            <dt>destination container</dt>
            <dd>{String(node.attrs.destination_container_ref ?? "?")}</dd>
            <dt>amount_basis</dt>
            <dd>{String(node.attrs.amount_basis ?? "?")}</dd>
            <dt>value_date</dt>
            <dd>
              {String(node.attrs.value_date_policy ?? "?")}
              {node.attrs.value_date_offset_days !== undefined &&
                ` +${String(node.attrs.value_date_offset_days)}d`}
            </dd>
            <dt>profile</dt>
            <dd>{String(node.attrs.profile_id ?? "—")}</dd>
            <dt>rule_index</dt>
            <dd>{String(node.attrs.rule_index ?? "—")}</dd>
          </dl>
        </section>
      );
    default:
      return null;
  }
}

function numberAttr(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return String(v);
}
