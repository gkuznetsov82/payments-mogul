import type { EdgeClass } from "../lib/types";

const CLASSES: { id: EdgeClass; label: string; hint: string }[] = [
  { id: "structural", label: "Structural", hint: "owns / linked / binds / routes / pays" },
  { id: "trigger", label: "Triggers", hint: "trigger → fee / demand / posting / transfer" },
  { id: "posting", label: "Postings", hint: "posting source/destination ledgers" },
  { id: "transfer", label: "Transfers", hint: "asset-transfer source/destination containers" },
  { id: "cross_pipeline", label: "Cross-pipeline", hint: "supernode + cross-profile links" },
];

export interface EdgeFiltersProps {
  visible: Set<EdgeClass>;
  onChange: (next: Set<EdgeClass>) => void;
}

export function EdgeFilters({ visible, onChange }: EdgeFiltersProps) {
  function toggle(c: EdgeClass) {
    const next = new Set<EdgeClass>(visible);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    onChange(next);
  }
  return (
    <div className="wb-edge-filters" data-testid="edge-filters" role="group" aria-label="Edge classes">
      <span className="wb-scope-label">Edges:</span>
      {CLASSES.map((c) => {
        const on = visible.has(c.id);
        return (
          <label
            key={c.id}
            className={`wb-edge-filter${on ? " wb-edge-filter-on" : ""}`}
            data-testid={`edge-filter-${c.id}`}
            data-on={on ? "true" : "false"}
            title={c.hint}
          >
            <input
              type="checkbox"
              checked={on}
              onChange={() => toggle(c.id)}
              data-testid={`edge-filter-input-${c.id}`}
            />
            <span>{c.label}</span>
          </label>
        );
      })}
    </div>
  );
}
