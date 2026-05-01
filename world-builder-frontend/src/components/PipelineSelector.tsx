import type { PipelineView } from "../lib/types";

export interface PipelineSelectorProps {
  views: PipelineView[];
  activeProfileId: string | null;
  onSelect: (profileId: string) => void;
}

export function PipelineSelector({ views, activeProfileId, onSelect }: PipelineSelectorProps) {
  if (views.length === 0) {
    return (
      <div className="wb-empty" data-testid="pipeline-selector-empty">
        No pipeline profiles in this config.
      </div>
    );
  }
  return (
    <div className="wb-pipeline-selector" data-testid="pipeline-selector">
      <label className="wb-section-label">Profile</label>
      <select
        data-testid="pipeline-selector-select"
        value={activeProfileId ?? ""}
        onChange={(e) => onSelect(e.target.value)}
      >
        {views.map((v) => {
          const intents = numAttr(v.summary?.intent_count);
          const fees = numAttr(v.summary?.fee_count);
          return (
            <option key={v.profile_id} value={v.profile_id}>
              {v.label} ({intents} intents, {fees} fees)
            </option>
          );
        })}
      </select>
    </div>
  );
}

function numAttr(v: unknown): number {
  return typeof v === "number" ? v : 0;
}
