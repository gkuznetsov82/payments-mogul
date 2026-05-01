import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DiagnosticsList } from "../components/DiagnosticsList";
import type { Diagnostic } from "../lib/types";

const diagWithTarget: Diagnostic = {
  code: "E_LINK_TARGET_MISSING",
  message: "Pop links to unknown product",
  path: "world.pops[pop_main].product_links",
  severity: "error",
  node_id: "pop:pop_main",
};

const diagWithoutTarget: Diagnostic = {
  code: "E_METHOD_ORDER_INVALID",
  message: "agent_method_order must be ['Onboard','Transact']",
  path: "simulation.agent_method_order",
  severity: "error",
  node_id: null,
};

describe("DiagnosticsList", () => {
  it("renders an empty state when no diagnostics", () => {
    render(<DiagnosticsList diagnostics={[]} onDiagnosticClick={() => {}} />);
    expect(screen.getByTestId("diagnostics-empty")).toBeInTheDocument();
  });

  it("invokes onDiagnosticClick when a row is clicked", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <DiagnosticsList
        diagnostics={[diagWithTarget, diagWithoutTarget]}
        onDiagnosticClick={onClick}
      />,
    );
    const rows = screen.getAllByTestId("diagnostic-row");
    expect(rows).toHaveLength(2);
    await user.click(rows[0]);
    expect(onClick).toHaveBeenCalledWith(diagWithTarget);
  });

  it("flags rows without a graph target with the inline hint", () => {
    render(
      <DiagnosticsList
        diagnostics={[diagWithTarget, diagWithoutTarget]}
        onDiagnosticClick={() => {}}
      />,
    );
    const rows = screen.getAllByTestId("diagnostic-row");
    expect(rows[0]).toHaveAttribute("data-has-target", "true");
    expect(rows[1]).toHaveAttribute("data-has-target", "false");
    expect(rows[1].textContent).toContain("no graph target");
  });

  it("renders the parent-supplied 'no graph target' fallback when present", () => {
    render(
      <DiagnosticsList
        diagnostics={[diagWithoutTarget]}
        onDiagnosticClick={() => {}}
        noTargetFallback={{
          code: "E_METHOD_ORDER_INVALID",
          reason: "This diagnostic has no graph target",
        }}
      />,
    );
    const fb = screen.getByTestId("diagnostic-no-target-fallback");
    expect(fb).toBeInTheDocument();
    expect(fb.textContent).toContain("no graph target");
    expect(fb.textContent).toContain("E_METHOD_ORDER_INVALID");
  });

  it("highlights the focused diagnostic via data-focused", () => {
    render(
      <DiagnosticsList
        diagnostics={[diagWithTarget, diagWithoutTarget]}
        onDiagnosticClick={() => {}}
        focusedIndex={1}
      />,
    );
    const rows = screen.getAllByTestId("diagnostic-row");
    expect(rows[0]).toHaveAttribute("data-focused", "false");
    expect(rows[1]).toHaveAttribute("data-focused", "true");
  });
});
