import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PipelineSelector } from "../components/PipelineSelector";
import type { PipelineView } from "../lib/types";

const VIEWS: PipelineView[] = [
  {
    profile_id: "prepaid_card_pipeline",
    label: "prepaid_card_pipeline",
    nodes: [],
    edges: [],
    summary: { intent_count: 1, fee_count: 1 },
  },
  {
    profile_id: "scheme_access_pipeline",
    label: "scheme_access_pipeline",
    nodes: [],
    edges: [],
    summary: { intent_count: 0, fee_count: 1 },
  },
];

describe("PipelineSelector", () => {
  it("renders an empty state when there are no pipeline views", () => {
    render(
      <PipelineSelector views={[]} activeProfileId={null} onSelect={() => {}} />,
    );
    expect(screen.getByTestId("pipeline-selector-empty")).toBeInTheDocument();
  });

  it("lists each profile and surfaces its summary counts", () => {
    render(
      <PipelineSelector
        views={VIEWS}
        activeProfileId="prepaid_card_pipeline"
        onSelect={() => {}}
      />,
    );
    const select = screen.getByTestId("pipeline-selector-select") as HTMLSelectElement;
    const options = Array.from(select.querySelectorAll("option"));
    expect(options).toHaveLength(2);
    expect(options[0].textContent).toContain("prepaid_card_pipeline");
    expect(options[0].textContent).toContain("1 intents");
  });

  it("invokes onSelect when the user chooses a profile", () => {
    const onSelect = vi.fn();
    render(
      <PipelineSelector
        views={VIEWS}
        activeProfileId="prepaid_card_pipeline"
        onSelect={onSelect}
      />,
    );
    const select = screen.getByTestId("pipeline-selector-select") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "scheme_access_pipeline" } });
    expect(onSelect).toHaveBeenCalledWith("scheme_access_pipeline");
  });
});
