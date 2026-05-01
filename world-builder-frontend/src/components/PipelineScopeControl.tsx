import { PIPELINE_SCOPE_AGGREGATE, type PipelineScope, type PipelineView } from "../lib/types";

export interface PipelineScopeControlProps {
  scope: PipelineScope;
  views: PipelineView[];
  onChange: (scope: PipelineScope) => void;
  /** Counts shown beside each option. Optional. */
  counts?: { aggregate?: { nodes: number; edges: number; cross: number }; perProfile?: Record<string, { nodes: number; edges: number }> };
}

/** Prominent, always-visible scope control for pipeline view mode. Spec 74
 *  §Pipeline scope UX requires aggregate vs per-profile to be unambiguous;
 *  the segmented control sits in the toolbar right next to the view-mode
 *  toggle so it is impossible to miss. */
export function PipelineScopeControl({
  scope,
  views,
  onChange,
  counts,
}: PipelineScopeControlProps) {
  if (views.length === 0) {
    return (
      <div className="wb-empty" data-testid="pipeline-scope-empty">
        No pipeline profiles in this config.
      </div>
    );
  }
  const isAggregate = scope === PIPELINE_SCOPE_AGGREGATE;
  return (
    <div
      className="wb-scope-control"
      role="radiogroup"
      aria-label="Pipeline scope"
      data-testid="pipeline-scope-control"
      data-active-scope={scope}
    >
      <span className="wb-scope-label">Scope:</span>
      <button
        type="button"
        role="radio"
        aria-checked={isAggregate}
        data-testid="pipeline-scope-aggregate"
        data-active={isAggregate ? "true" : "false"}
        className={`wb-scope-btn${isAggregate ? " wb-scope-btn-active" : ""}`}
        onClick={() => onChange(PIPELINE_SCOPE_AGGREGATE)}
      >
        All profiles
        {counts?.aggregate && (
          <span className="wb-scope-counts">
            · {counts.aggregate.nodes}n / {counts.aggregate.edges}e
            {counts.aggregate.cross > 0 && ` · ${counts.aggregate.cross} ↪`}
          </span>
        )}
      </button>
      {views.map((v) => {
        const active = scope === v.profile_id;
        const c = counts?.perProfile?.[v.profile_id];
        return (
          <button
            key={v.profile_id}
            type="button"
            role="radio"
            aria-checked={active}
            data-testid={`pipeline-scope-${v.profile_id}`}
            data-active={active ? "true" : "false"}
            className={`wb-scope-btn${active ? " wb-scope-btn-active" : ""}`}
            onClick={() => onChange(v.profile_id)}
          >
            {v.label}
            {c && (
              <span className="wb-scope-counts">
                · {c.nodes}n / {c.edges}e
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
