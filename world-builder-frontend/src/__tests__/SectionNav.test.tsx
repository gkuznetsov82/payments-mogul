import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SectionNav } from "../components/SectionNav";

describe("SectionNav", () => {
  it("renders all sections + an All button and reflects the active state", () => {
    render(
      <SectionNav
        active="world"
        onSelect={() => {}}
        counts={{ world: { nodes: 4, diagnostics: 1 } }}
        totals={{ nodes: 4, diagnostics: 1 }}
      />,
    );
    expect(screen.getByTestId("section-all")).toHaveAttribute("data-active", "false");
    expect(screen.getByTestId("section-world")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("section-pipeline")).toHaveAttribute("data-active", "false");
  });

  it("calls onSelect with the section id when clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <SectionNav
        active={null}
        onSelect={onSelect}
        counts={{}}
        totals={{ nodes: 0, diagnostics: 0 }}
      />,
    );
    await user.click(screen.getByTestId("section-pipeline"));
    expect(onSelect).toHaveBeenCalledWith("pipeline");
    await user.click(screen.getByTestId("section-all"));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
