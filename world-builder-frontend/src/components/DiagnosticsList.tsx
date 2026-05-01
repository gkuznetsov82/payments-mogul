import type { Diagnostic } from "../lib/types";

export interface DiagnosticsListProps {
  diagnostics: Diagnostic[];
  /** Called with the diagnostic the user clicked. Parent decides what to do
   *  (focus a node when `node_id` is set, or surface a fallback when not). */
  onDiagnosticClick: (diag: Diagnostic) => void;
  /** When set, the parent has decided no graph target is reachable; we render
   *  the explicit fallback message inline (spec 74/75). */
  noTargetFallback?: { code: string; reason: string } | null;
  /** Highlight the currently focused diagnostic, if any (driven by parent). */
  focusedIndex?: number | null;
}

export function DiagnosticsList({
  diagnostics,
  onDiagnosticClick,
  noTargetFallback,
  focusedIndex,
}: DiagnosticsListProps) {
  if (diagnostics.length === 0) {
    return (
      <div className="wb-empty" data-testid="diagnostics-empty">
        No diagnostics.
      </div>
    );
  }

  return (
    <div className="wb-diag-list" role="list" data-testid="diagnostics-list">
      {noTargetFallback && (
        <div
          role="status"
          className="wb-diag-fallback"
          data-testid="diagnostic-no-target-fallback"
        >
          <strong>no graph target</strong>
          <div>
            {noTargetFallback.code}: {noTargetFallback.reason}
          </div>
        </div>
      )}
      {diagnostics.map((d, idx) => {
        const isFocused = focusedIndex === idx;
        const hasTarget = Boolean(d.node_id);
        return (
          <button
            key={`${idx}-${d.code}-${d.path ?? ""}`}
            role="listitem"
            type="button"
            data-testid="diagnostic-row"
            data-code={d.code}
            data-severity={d.severity}
            data-has-target={hasTarget ? "true" : "false"}
            data-focused={isFocused ? "true" : "false"}
            onClick={() => onDiagnosticClick(d)}
            className={`wb-diag wb-diag-${d.severity}${isFocused ? " wb-diag-focused" : ""}`}
          >
            <span className="wb-diag-code">{d.code}</span>
            <span className="wb-diag-msg">{d.message}</span>
            {d.path && <span className="wb-diag-path">@ {d.path}</span>}
            {!hasTarget && (
              <span className="wb-diag-fallback-hint">no graph target</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
