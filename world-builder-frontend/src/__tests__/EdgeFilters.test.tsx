import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EdgeFilters } from "../components/EdgeFilters";
import type { EdgeClass } from "../lib/types";

describe("EdgeFilters", () => {
  it("renders one toggle per edge class", () => {
    render(
      <EdgeFilters
        visible={new Set<EdgeClass>(["structural", "cross_pipeline"])}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId("edge-filter-structural")).toHaveAttribute("data-on", "true");
    expect(screen.getByTestId("edge-filter-trigger")).toHaveAttribute("data-on", "false");
    expect(screen.getByTestId("edge-filter-posting")).toHaveAttribute("data-on", "false");
    expect(screen.getByTestId("edge-filter-transfer")).toHaveAttribute("data-on", "false");
    expect(screen.getByTestId("edge-filter-cross_pipeline")).toHaveAttribute("data-on", "true");
  });

  it("invokes onChange with the toggled set when a filter is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <EdgeFilters
        visible={new Set<EdgeClass>(["structural"])}
        onChange={onChange}
      />,
    );
    await user.click(screen.getByTestId("edge-filter-input-trigger"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next: Set<EdgeClass> = onChange.mock.calls[0][0];
    expect(next.has("structural")).toBe(true);
    expect(next.has("trigger")).toBe(true);
  });

  it("toggling an already-on filter clears it", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <EdgeFilters
        visible={new Set<EdgeClass>(["structural", "cross_pipeline"])}
        onChange={onChange}
      />,
    );
    await user.click(screen.getByTestId("edge-filter-input-cross_pipeline"));
    const next: Set<EdgeClass> = onChange.mock.calls[0][0];
    expect(next.has("cross_pipeline")).toBe(false);
    expect(next.has("structural")).toBe(true);
  });
});
