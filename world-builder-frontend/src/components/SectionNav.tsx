import { SECTIONS } from "../lib/sections";
import type { Section } from "../lib/types";

export interface SectionNavProps {
  active: Section | null;
  onSelect: (section: Section | null) => void;
  /** Counts per section, supplied by the parent (diagnostics & node counts). */
  counts: Partial<Record<Section, { nodes: number; diagnostics: number }>>;
  totals: { nodes: number; diagnostics: number };
}

export function SectionNav({ active, onSelect, counts, totals }: SectionNavProps) {
  return (
    <nav className="wb-section-nav" aria-label="Config sections" data-testid="section-nav">
      <button
        type="button"
        data-testid="section-all"
        data-active={active === null ? "true" : "false"}
        className={`wb-section${active === null ? " wb-section-active" : ""}`}
        onClick={() => onSelect(null)}
      >
        <span className="wb-section-label">All</span>
        <span className="wb-section-counts">
          {totals.nodes} nodes · {totals.diagnostics} diag
        </span>
      </button>
      {SECTIONS.map((s) => {
        const c = counts[s.id] ?? { nodes: 0, diagnostics: 0 };
        const isActive = active === s.id;
        return (
          <button
            key={s.id}
            type="button"
            data-testid={`section-${s.id}`}
            data-active={isActive ? "true" : "false"}
            className={`wb-section${isActive ? " wb-section-active" : ""}`}
            onClick={() => onSelect(s.id)}
          >
            <span className="wb-section-label">{s.label}</span>
            <span className="wb-section-counts">
              {c.nodes} nodes · {c.diagnostics} diag
            </span>
          </button>
        );
      })}
    </nav>
  );
}
