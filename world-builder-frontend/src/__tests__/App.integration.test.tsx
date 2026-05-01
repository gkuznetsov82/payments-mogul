/* App-level interaction flow tests for spec 74 §P2 acceptance:
 *   - graph node selection updates details pane
 *   - diagnostic click triggers focus/highlight (via data attributes)
 *   - diagnostic without graph target shows fallback
 *   - section filter updates faded-node set + diagnostic visibility
 *
 * We mock the analyze/validate endpoints so the test is hermetic and
 * deterministic. React Flow's heavy internals are not directly exercised
 * here — we verify the UI plumbing around it (selection callbacks fire
 * the right state changes; focus state propagates).
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import type {
  AnalysisReport,
  Diagnostic,
  ValidationReport,
} from "../lib/types";

// Synthetic analyze payload representing a small but representative slice of
// the v3 fixture: vendor + product + pop + pipeline_profile, with three
// distinct diagnostic shapes for routing tests:
//   - one with node_id (focusable in topology)
//   - one without node_id (must hit fallback)
//   - one that targets a pipeline-view node (must flip to pipeline mode)
const ANALYSIS_FIXTURE: AnalysisReport = {
  valid: false,
  errors: [],
  warnings: [],
  graph: {
    nodes: [
      { id: "vendor:vendor_alpha", kind: "vendor", label: "Vendor Alpha", attrs: { operational: true } },
      { id: "product:vendor_alpha/prod_prepaid_alpha", kind: "product", label: "Alpha Prepaid", attrs: { product_class: "RetailPayment-Card-Prepaid" } },
      { id: "pop:pop_main", kind: "pop", label: "Main Pop", attrs: { pop_count: 10000 } },
      { id: "pipeline_profile:prepaid_card_pipeline", kind: "pipeline_profile", label: "prepaid_card_pipeline", attrs: {} },
    ],
    edges: [
      { source: "vendor:vendor_alpha", target: "product:vendor_alpha/prod_prepaid_alpha", kind: "owns", attrs: {} },
      { source: "pop:pop_main", target: "product:vendor_alpha/prod_prepaid_alpha", kind: "linked_to", attrs: { known: true } },
      { source: "product:vendor_alpha/prod_prepaid_alpha", target: "pipeline_profile:prepaid_card_pipeline", kind: "binds_profile", attrs: {} },
    ],
  },
  unresolved_refs: [
    {
      code: "E_LINK_TARGET_MISSING",
      message: "Pop links to unknown product (vendor_x, prod_x)",
      path: "world.pops[pop_main].product_links",
      severity: "error",
      node_id: "pop:pop_main",
      section: "world",
      graph_view: "topology",
    } as Diagnostic,
    {
      code: "E_METHOD_ORDER_INVALID",
      message: "agent_method_order must be ['Onboard','Transact']",
      path: "simulation.agent_method_order",
      severity: "error",
      node_id: null,
      section: "simulation",
      graph_view: null,
    } as Diagnostic,
    {
      code: "E_PIPELINE_PROFILE_NOT_FOUND",
      message: "fee references unknown trigger",
      path: "pipeline.pipeline_profiles[0].fee_sequences",
      severity: "error",
      node_id: "pv:prepaid_card_pipeline:fee:fee_x",
      section: "pipeline",
      graph_view: "pipeline",
    } as Diagnostic,
  ],
  pipeline_views: [
    {
      profile_id: "prepaid_card_pipeline",
      label: "prepaid_card_pipeline",
      nodes: [
        {
          id: "pv:prepaid_card_pipeline:intent:Transact-Purchase-Clearing",
          kind: "pv_intent",
          label: "Transact-Purchase-Clearing",
          attrs: {},
        },
        {
          id: "pv:prepaid_card_pipeline:fee:fee_x",
          kind: "pv_fee",
          label: "fee_x",
          attrs: { beneficiary_role: "self_agent" },
        },
      ],
      edges: [
        {
          source: "pv:prepaid_card_pipeline:intent:Transact-Purchase-Clearing",
          target: "pv:prepaid_card_pipeline:fee:fee_x",
          kind: "pv_triggers_fee",
          attrs: {},
        },
      ],
      summary: { intent_count: 1, fee_count: 1 },
    },
  ],
  pipeline_aggregate: {
    nodes: [
      {
        id: "pv:prepaid_card_pipeline:intent:Transact-Purchase-Clearing",
        kind: "pv_intent",
        label: "Transact-Purchase-Clearing",
        attrs: {},
      },
      {
        id: "pv:prepaid_card_pipeline:fee:fee_x",
        kind: "pv_fee",
        label: "fee_x",
        attrs: { beneficiary_role: "self_agent" },
      },
    ],
    edges: [
      {
        source: "pv:prepaid_card_pipeline:intent:Transact-Purchase-Clearing",
        target: "pv:prepaid_card_pipeline:fee:fee_x",
        kind: "pv_triggers_fee",
        attrs: {},
      },
    ],
    summary: {
      profile_count: 1,
      node_count: 2,
      edge_count: 1,
      cross_pipeline_edge_count: 0,
    },
    profiles: ["prepaid_card_pipeline"],
  },
};

const VALIDATION_FIXTURE: ValidationReport = {
  valid: false,
  errors: [
    {
      code: "E_METHOD_ORDER_INVALID",
      message: "agent_method_order must be ['Onboard','Transact']",
      path: "simulation.agent_method_order",
      severity: "error",
      node_id: null,
      section: "simulation",
    } as Diagnostic,
  ],
  warnings: [],
  schema_version: "v0",
  pipeline_schema_version: "v3_runtime",
};

beforeEach(() => {
  // Default: route /validate to validation fixture, /analyze to analysis fixture.
  // Tests that need a different response can re-stub `globalThis.fetch`.
  globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/validate")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(JSON.stringify(VALIDATION_FIXTURE)),
        json: () => Promise.resolve(VALIDATION_FIXTURE),
      } as Response);
    }
    if (url.endsWith("/analyze")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(JSON.stringify(ANALYSIS_FIXTURE)),
        json: () => Promise.resolve(ANALYSIS_FIXTURE),
      } as Response);
    }
    if (url.endsWith("/normalize")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve("{}"),
        json: () => Promise.resolve({
          valid: true,
          errors: [],
          warnings: [],
          normalized_yaml: "config_version: v0\n",
          normalized_json: { config_version: "v0" },
          revalidates: true,
        }),
      } as Response);
    }
    return Promise.reject(new Error(`unmocked: ${url}`));
  }) as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function loadFixtureAndAnalyze() {
  const user = userEvent.setup();
  render(<App />);
  // Drop the YAML straight into the textarea; bypass the file input which
  // jsdom doesn't fully simulate.
  const ta = screen.getByTestId("yaml-input") as HTMLTextAreaElement;
  fireEvent.change(ta, { target: { value: "config_version: v0\n# fake yaml — analyzer is mocked\n" } });
  await user.click(screen.getByTestId("btn-analyze"));
  // Wait for analysis to land — diagnostics list is the surface signal.
  await waitFor(() => expect(screen.getAllByTestId("diagnostic-row").length).toBeGreaterThan(0));
  return { user };
}

describe("App integration", () => {
  it("renders the app shell with a section navigator and toolbar", () => {
    render(<App />);
    expect(screen.getByTestId("wb-app")).toBeInTheDocument();
    expect(screen.getByTestId("section-nav")).toBeInTheDocument();
    expect(screen.getByTestId("btn-analyze")).toBeInTheDocument();
  });

  it("shows diagnostics from /analyze including unresolved_refs", async () => {
    await loadFixtureAndAnalyze();
    const rows = screen.getAllByTestId("diagnostic-row");
    expect(rows.length).toBeGreaterThanOrEqual(2);
    const codes = rows.map((r) => r.getAttribute("data-code"));
    expect(codes).toContain("E_LINK_TARGET_MISSING");
    expect(codes).toContain("E_METHOD_ORDER_INVALID");
  });

  it("can switch view mode between topology and pipeline", async () => {
    const { user } = await loadFixtureAndAnalyze();
    const app = screen.getByTestId("wb-app");
    expect(app).toHaveAttribute("data-view-mode", "topology");
    await user.click(screen.getByTestId("btn-view-pipeline"));
    await waitFor(() => expect(app).toHaveAttribute("data-view-mode", "pipeline"));
    // Pipeline-mode shell brings up the prominent scope control.
    expect(screen.getByTestId("pipeline-scope-control")).toBeInTheDocument();
    // And switches back.
    await user.click(screen.getByTestId("btn-view-topology"));
    await waitFor(() => expect(app).toHaveAttribute("data-view-mode", "topology"));
  });

  it("pipeline mode defaults to aggregate scope and renders the active-scope summary", async () => {
    const { user } = await loadFixtureAndAnalyze();
    await user.click(screen.getByTestId("btn-view-pipeline"));
    const control = await screen.findByTestId("pipeline-scope-control");
    // Spec 74 §Pipeline scope UX: aggregate scope is the default and visible.
    expect(control).toHaveAttribute("data-active-scope", "__aggregate__");
    expect(screen.getByTestId("pipeline-scope-aggregate")).toHaveAttribute(
      "data-active",
      "true",
    );
    // Side-pane summary echoes the active scope so it's clear where the user is.
    const scopeBanner = await screen.findByTestId("pipeline-active-scope");
    expect(scopeBanner).toHaveAttribute("data-scope", "__aggregate__");
    expect(scopeBanner.textContent).toContain("All profiles");
  });

  it("clicking a diagnostic with graph_view=pipeline switches to pipeline mode", async () => {
    const { user } = await loadFixtureAndAnalyze();
    const app = screen.getByTestId("wb-app");
    expect(app).toHaveAttribute("data-view-mode", "topology");
    const row = screen
      .getAllByTestId("diagnostic-row")
      .find((r) => r.getAttribute("data-code") === "E_PIPELINE_PROFILE_NOT_FOUND")!;
    await user.click(row);
    await waitFor(() => expect(app).toHaveAttribute("data-view-mode", "pipeline"));
    // And focuses the pipeline-stage node in the details pane.
    await waitFor(() => {
      expect(screen.getByTestId("details-id")).toHaveTextContent(
        "pv:prepaid_card_pipeline:fee:fee_x",
      );
    });
  });

  it("reset manual layout button clears overrides without breaking the canvas", async () => {
    const { user } = await loadFixtureAndAnalyze();
    // Reset doesn't throw and the graph pane is still rendered.
    await user.click(screen.getByTestId("btn-reset-layout"));
    expect(screen.getByTestId("graph-pane")).toBeInTheDocument();
  });

  it("auto layout button is wired and re-runs without errors", async () => {
    const { user } = await loadFixtureAndAnalyze();
    await user.click(screen.getByTestId("btn-auto-layout"));
    expect(screen.getByTestId("graph-pane")).toBeInTheDocument();
  });

  it("switching scope from aggregate to a single profile changes graph counts", async () => {
    const { user } = await loadFixtureAndAnalyze();
    await user.click(screen.getByTestId("btn-view-pipeline"));
    const banner = screen.getByTestId("pipeline-active-scope");
    // Aggregate scope defaults to a collapsed supernode-per-profile view
    // (spec 74 §Progressive disclosure). The fixture has one profile so we
    // start with one supernode + zero edges.
    expect(banner.textContent).toMatch(/nodes1/);
    // Switch to per-profile scope: the underlying view has 2 stage nodes.
    await user.click(screen.getByTestId("pipeline-scope-prepaid_card_pipeline"));
    await waitFor(() => {
      expect(banner).toHaveAttribute("data-scope", "prepaid_card_pipeline");
    });
    expect(banner.textContent).toContain("prepaid_card_pipeline");
    expect(banner.textContent).toMatch(/nodes2/);
  });

  it("spacing dropdown defaults to normal and changing it triggers a layout reflow", async () => {
    const { user } = await loadFixtureAndAnalyze();
    const select = screen.getByTestId("spacing-select") as HTMLSelectElement;
    expect(select).toHaveAttribute("data-spacing", "normal");
    expect(select.value).toBe("normal");
    // Capture the topology-node positions before changing spacing.
    const nodesBefore = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".react-flow__node.wb-node-vendor, .react-flow__node.wb-node-product",
      ),
    ).map((el) => ({
      id: el.getAttribute("data-id"),
      transform: el.style.transform,
    }));
    expect(nodesBefore.length).toBeGreaterThan(0);
    fireEvent.change(select, { target: { value: "spacious" } });
    await waitFor(() => expect(select).toHaveAttribute("data-spacing", "spacious"));
    // After spacing change at least one node's transform must update.
    const nodesAfter = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".react-flow__node.wb-node-vendor, .react-flow__node.wb-node-product",
      ),
    ).map((el) => ({
      id: el.getAttribute("data-id"),
      transform: el.style.transform,
    }));
    let differs = false;
    for (let i = 0; i < nodesBefore.length; i++) {
      if (nodesBefore[i].transform !== nodesAfter[i]?.transform) {
        differs = true;
        break;
      }
    }
    expect(differs).toBe(true);
    // Use the user-event path too just to make sure the dropdown is keyboard
    // navigable to "compact".
    await user.selectOptions(select, "compact");
    await waitFor(() => expect(select).toHaveAttribute("data-spacing", "compact"));
  });

  it("lock-drag button toggles between locked and unlocked", async () => {
    const { user } = await loadFixtureAndAnalyze();
    const btn = screen.getByTestId("btn-toggle-lock");
    expect(btn).toHaveAttribute("data-locked", "false");
    await user.click(btn);
    expect(btn).toHaveAttribute("data-locked", "true");
    await user.click(btn);
    expect(btn).toHaveAttribute("data-locked", "false");
  });

  it("clicking a diagnostic with node_id focuses the matching node and clears any prior fallback", async () => {
    const { user } = await loadFixtureAndAnalyze();
    const row = screen
      .getAllByTestId("diagnostic-row")
      .find((r) => r.getAttribute("data-code") === "E_LINK_TARGET_MISSING")!;
    await user.click(row);
    // The selected diagnostic carries a node_id, so the details pane should
    // now show that node, and no fallback message should be present.
    await waitFor(() => {
      expect(screen.getByTestId("details-pane")).toBeInTheDocument();
    });
    expect(screen.getByTestId("details-id")).toHaveTextContent("pop:pop_main");
    expect(screen.queryByTestId("diagnostic-no-target-fallback")).toBeNull();
    // Focused row reflects the click.
    expect(row).toHaveAttribute("data-focused", "true");
  });

  it("clicking a diagnostic without node_id renders the explicit 'no graph target' fallback", async () => {
    const { user } = await loadFixtureAndAnalyze();
    const row = screen
      .getAllByTestId("diagnostic-row")
      .find((r) => r.getAttribute("data-code") === "E_METHOD_ORDER_INVALID")!;
    expect(row).toHaveAttribute("data-has-target", "false");
    await user.click(row);
    await waitFor(() => {
      expect(screen.getByTestId("diagnostic-no-target-fallback")).toBeInTheDocument();
    });
    const fb = screen.getByTestId("diagnostic-no-target-fallback");
    expect(fb.textContent).toContain("E_METHOD_ORDER_INVALID");
  });

  it("section filter scopes diagnostics list", async () => {
    const { user } = await loadFixtureAndAnalyze();
    // Default = All; all three diagnostics visible.
    expect(screen.getAllByTestId("diagnostic-row").length).toBe(3);
    // Switch to Simulation: only the simulation diag remains.
    await user.click(screen.getByTestId("section-simulation"));
    await waitFor(() => {
      const rows = screen.getAllByTestId("diagnostic-row");
      expect(rows.length).toBe(1);
      expect(rows[0]).toHaveAttribute("data-code", "E_METHOD_ORDER_INVALID");
    });
    // Switch to World: only the world diag remains.
    await user.click(screen.getByTestId("section-world"));
    await waitFor(() => {
      const rows = screen.getAllByTestId("diagnostic-row");
      expect(rows.length).toBe(1);
      expect(rows[0]).toHaveAttribute("data-code", "E_LINK_TARGET_MISSING");
    });
  });

  it("section navigator reports node + diagnostic counts correctly", async () => {
    await loadFixtureAndAnalyze();
    // World section has 3 nodes (vendor + product + pop) and 1 diagnostic.
    const worldBtn = screen.getByTestId("section-world");
    expect(within(worldBtn).getByText(/3 nodes/)).toBeInTheDocument();
    expect(within(worldBtn).getByText(/1 diag/)).toBeInTheDocument();
    // Pipeline section has 1 node (the profile) and 1 diagnostic.
    const pipelineBtn = screen.getByTestId("section-pipeline");
    expect(within(pipelineBtn).getByText(/1 nodes/)).toBeInTheDocument();
    expect(within(pipelineBtn).getByText(/1 diag/)).toBeInTheDocument();
  });

  it("search filter narrows visible nodes by label or id substring", async () => {
    const { user } = await loadFixtureAndAnalyze();
    const search = screen.getByTestId("search-input");
    await user.type(search, "Prepaid");
    // After typing, layoutGraph keeps all nodes but the App marks
    // non-matches as faded. We verify by inspecting the React Flow node
    // rendering: faded nodes carry the `wb-node-faded` class.
    await waitFor(() => {
      const fadedNodes = document.querySelectorAll(".react-flow__node.wb-node-faded");
      // pop and vendor and pipeline_profile should fade out — only the
      // product label contains "Prepaid".
      expect(fadedNodes.length).toBeGreaterThan(0);
    });
  });
});


// =============================================================================
// Cross-pipeline navigation (spec 74 §Cross-pipeline connectivity)
// =============================================================================

describe("Cross-pipeline navigation", () => {
  // Two-profile fixture with a cross-pipeline edge from prepaid's outgoing
  // intent into scheme's fee. Lets us drive the click-through behavior.
  const TWO_PROFILE: AnalysisReport = {
    valid: true,
    errors: [],
    warnings: [],
    graph: { nodes: [], edges: [] },
    unresolved_refs: [],
    pipeline_views: [
      {
        profile_id: "prepaid_card_pipeline",
        label: "prepaid_card_pipeline",
        nodes: [
          {
            id: "pv:prepaid_card_pipeline:intent:Transact-Purchase-Clearing",
            kind: "pv_intent",
            label: "Transact-Purchase-Clearing",
            attrs: {},
          },
          {
            id: "pv:prepaid_card_pipeline:outgoing:Transact-Purchase-Clearing-Scheme",
            kind: "pv_outgoing_intent",
            label: "Transact-Purchase-Clearing-Scheme",
            attrs: {},
          },
        ],
        edges: [],
        summary: { intent_count: 1 },
      },
      {
        profile_id: "scheme_access_pipeline",
        label: "scheme_access_pipeline",
        nodes: [
          {
            id: "pv:scheme_access_pipeline:fee:fee_scheme_access",
            kind: "pv_fee",
            label: "fee_scheme_access",
            attrs: { beneficiary_role: "self_agent" },
          },
        ],
        edges: [],
        summary: { fee_count: 1 },
      },
    ],
    pipeline_aggregate: {
      nodes: [
        {
          id: "pv:prepaid_card_pipeline:intent:Transact-Purchase-Clearing",
          kind: "pv_intent",
          label: "Transact-Purchase-Clearing",
          attrs: {},
        },
        {
          id: "pv:prepaid_card_pipeline:outgoing:Transact-Purchase-Clearing-Scheme",
          kind: "pv_outgoing_intent",
          label: "Transact-Purchase-Clearing-Scheme",
          attrs: {},
        },
        {
          id: "pv:scheme_access_pipeline:fee:fee_scheme_access",
          kind: "pv_fee",
          label: "fee_scheme_access",
          attrs: { beneficiary_role: "self_agent" },
        },
      ],
      edges: [
        {
          source: "pv:prepaid_card_pipeline:outgoing:Transact-Purchase-Clearing-Scheme",
          target: "pv:scheme_access_pipeline:fee:fee_scheme_access",
          kind: "pv_cross_pipeline",
          attrs: {
            trigger_id: "Transact-Purchase-Clearing-Scheme",
            source_profile_id: "prepaid_card_pipeline",
            target_profile_id: "scheme_access_pipeline",
            target_instance_id: "vendor_scheme/prod_scheme_access",
            target_node_id: "pv:scheme_access_pipeline:fee:fee_scheme_access",
          },
        },
      ],
      summary: {
        profile_count: 2,
        node_count: 3,
        edge_count: 1,
        cross_pipeline_edge_count: 1,
      },
      profiles: ["prepaid_card_pipeline", "scheme_access_pipeline"],
    },
  };

  beforeEach(() => {
    globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/analyze")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          text: () => Promise.resolve(JSON.stringify(TWO_PROFILE)),
          json: () => Promise.resolve(TWO_PROFILE),
        } as Response);
      }
      return Promise.reject(new Error(`unmocked: ${url}`));
    }) as typeof fetch;
  });

  async function loadAndEnterPipeline() {
    const user = userEvent.setup();
    render(<App />);
    fireEvent.change(screen.getByTestId("yaml-input"), {
      target: { value: "config_version: v0\n" },
    });
    await user.click(screen.getByTestId("btn-analyze"));
    // Wait for analysis to land then enter pipeline mode.
    await waitFor(() =>
      expect(screen.getByTestId("btn-view-pipeline")).not.toBeDisabled(),
    );
    await user.click(screen.getByTestId("btn-view-pipeline"));
    await screen.findByTestId("pipeline-scope-control");
    return { user };
  }

  it("aggregate scope reports cross-pipeline edge count in the scope banner", async () => {
    await loadAndEnterPipeline();
    // The active-scope banner is the user-visible signal that the aggregate
    // scope is active and includes cross-pipeline links.
    const banner = screen.getByTestId("pipeline-active-scope");
    expect(banner.textContent).toContain("All profiles");
    expect(banner.textContent).toContain("cross-pipeline");
    expect(banner.textContent).toContain("1 edges");
  });

  it("scope control surfaces both profile names + aggregate option", async () => {
    await loadAndEnterPipeline();
    expect(screen.getByTestId("pipeline-scope-aggregate")).toBeInTheDocument();
    expect(
      screen.getByTestId("pipeline-scope-prepaid_card_pipeline"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("pipeline-scope-scheme_access_pipeline"),
    ).toBeInTheDocument();
  });

  it("scope counts on the segmented control include the cross-pipeline indicator", async () => {
    await loadAndEnterPipeline();
    const aggregateBtn = screen.getByTestId("pipeline-scope-aggregate");
    // The aggregate button surfaces `n / e · cross ↪` so the user sees the
    // cross-pipeline breadth without having to switch scope.
    expect(aggregateBtn.textContent).toContain("All profiles");
    expect(aggregateBtn.textContent).toContain("3n / 1e");
    expect(aggregateBtn.textContent).toContain("1 ↪");
  });

  it("switching to per-profile scope reduces visible counts", async () => {
    const { user } = await loadAndEnterPipeline();
    const banner = screen.getByTestId("pipeline-active-scope");
    // Aggregate scope is collapsed-by-default (spec 74 §Progressive
    // disclosure): two profiles → two supernodes + the cross-pipeline link.
    expect(banner.textContent).toMatch(/nodes2/);
    expect(banner.textContent).toContain("All profiles");
    await user.click(screen.getByTestId("pipeline-scope-prepaid_card_pipeline"));
    await waitFor(() =>
      expect(banner).toHaveAttribute("data-scope", "prepaid_card_pipeline"),
    );
    expect(banner.textContent).toContain("prepaid_card_pipeline");
    // Per-profile prepaid view has 2 stage nodes (intent + outgoing-intent).
    expect(banner.textContent).toMatch(/nodes2/);
  });

  // -------------------------------------------------------------------------
  // Spec 74 §Progressive disclosure
  // -------------------------------------------------------------------------

  it("aggregate scope renders supernodes by default (one per profile)", async () => {
    await loadAndEnterPipeline();
    const supers = document.querySelectorAll(".react-flow__node.wb-node-pv_super");
    expect(supers.length).toBe(2);
    // Stage nodes from inside the profiles must NOT be visible.
    const stageNodes = document.querySelectorAll(
      ".react-flow__node.wb-node-pv_intent, .react-flow__node.wb-node-pv_fee",
    );
    expect(stageNodes.length).toBe(0);
  });

  it("expand-all reveals stage internals and collapse-all collapses again", async () => {
    const { user } = await loadAndEnterPipeline();
    await user.click(screen.getByTestId("btn-expand-all"));
    await waitFor(() => {
      const stageNodes = document.querySelectorAll(
        ".react-flow__node.wb-node-pv_intent, .react-flow__node.wb-node-pv_fee, .react-flow__node.wb-node-pv_outgoing_intent",
      );
      expect(stageNodes.length).toBeGreaterThan(0);
    });
    expect(screen.getByTestId("expand-state").textContent).toContain("2/2");
    await user.click(screen.getByTestId("btn-collapse-all"));
    await waitFor(() => {
      const supers = document.querySelectorAll(".react-flow__node.wb-node-pv_super");
      expect(supers.length).toBe(2);
    });
    expect(screen.getByTestId("expand-state").textContent).toContain("0/2");
  });

  it("turning off the cross_pipeline edge filter drops the visible edge count", async () => {
    // React Flow doesn't render edges in jsdom (it needs measured node
    // dimensions), so we verify the filter behavior via the active-scope
    // banner edge count — which IS user-visible feedback.
    const { user } = await loadAndEnterPipeline();
    const banner = screen.getByTestId("pipeline-active-scope");
    // Default: structural + cross_pipeline ON → supernode link visible (1 edge).
    expect(banner.textContent).toMatch(/edges1/);
    await user.click(screen.getByTestId("edge-filter-input-cross_pipeline"));
    await waitFor(() => expect(banner.textContent).toMatch(/edges0/));
  });

  it("mental-map continuity: supernode positions stay stable across filter toggle", async () => {
    const { user } = await loadAndEnterPipeline();
    // Read the supernode position before any toggle.
    const supersBefore = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".react-flow__node.wb-node-pv_super",
      ),
    );
    expect(supersBefore.length).toBe(2);
    const before = supersBefore.map((el) => ({
      id: el.getAttribute("data-id"),
      transform: el.style.transform,
    }));
    // Toggle a filter that doesn't change the node set.
    await user.click(screen.getByTestId("edge-filter-input-trigger"));
    const supersAfter = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".react-flow__node.wb-node-pv_super",
      ),
    );
    const after = supersAfter.map((el) => ({
      id: el.getAttribute("data-id"),
      transform: el.style.transform,
    }));
    expect(after).toEqual(before);
  });

  // -------------------------------------------------------------------------
  // Spec 74 §Layout strategy hybrid (radial focus mode)
  // -------------------------------------------------------------------------

  it("graph-pane reports baseline flavor when focus mode is off", async () => {
    await loadAndEnterPipeline();
    const pane = screen.getByTestId("graph-pane");
    expect(pane).toHaveAttribute("data-flavor", "pipeline_aggregate");
    expect(pane).toHaveAttribute("data-focus-active", "false");
  });

  it("focus mode requires a selected node before activating the radial layout", async () => {
    const { user } = await loadAndEnterPipeline();
    // Toggle focus mode WITHOUT a node selected — flavor stays baseline.
    await user.click(screen.getByTestId("toggle-neighborhood"));
    const pane = screen.getByTestId("graph-pane");
    expect(pane).toHaveAttribute("data-flavor", "pipeline_aggregate");
    expect(pane).toHaveAttribute("data-focus-active", "false");
  });

  it("expanding a profile then enabling focus on a stage node switches to radial flavor", async () => {
    const { user } = await loadAndEnterPipeline();
    // Expand both profiles so stage nodes are clickable.
    await user.click(screen.getByTestId("btn-expand-all"));
    await waitFor(() => {
      const stage = document.querySelectorAll(
        ".react-flow__node.wb-node-pv_intent, .react-flow__node.wb-node-pv_fee",
      );
      expect(stage.length).toBeGreaterThan(0);
    });
    // Use fireEvent.click directly: userEvent fires the full mousedown chain
    // which trips React Flow's d3-drag handler in jsdom. A pure click event
    // still reaches React Flow's onNodeClick callback and selects the node.
    const fee = document.querySelector<HTMLElement>(
      ".react-flow__node.wb-node-pv_fee",
    )!;
    fireEvent.click(fee);
    // Activate focus mode.
    await user.click(screen.getByTestId("toggle-neighborhood"));
    await waitFor(() => {
      const pane = screen.getByTestId("graph-pane");
      expect(pane).toHaveAttribute("data-flavor", "focus");
      expect(pane).toHaveAttribute("data-focus-active", "true");
    });
    // Active-pill labels the focused node id.
    expect(screen.getByTestId("focus-active-pill").textContent).toMatch(/radial/);
  });

  it("focus mode hides nodes outside the depth-N neighborhood", async () => {
    // Regression for the cluttered focus screenshot: when focus mode is
    // active, only nodes inside the BFS neighborhood should remain on
    // canvas. Previously they were just faded, leaving the original
    // dendrogram visible behind the radial cluster.
    const { user } = await loadAndEnterPipeline();
    // Expand all so we have stage nodes to test against.
    await user.click(screen.getByTestId("btn-expand-all"));
    await waitFor(() => {
      const stage = document.querySelectorAll(
        ".react-flow__node.wb-node-pv_intent, .react-flow__node.wb-node-pv_fee",
      );
      expect(stage.length).toBeGreaterThan(0);
    });
    const totalBefore = document.querySelectorAll(".react-flow__node").length;
    // Select an intent node — it has only an outgoing edge to a single
    // outgoing-intent in the same profile, so depth=1 should yield 2 nodes.
    const intent = document.querySelector<HTMLElement>(
      ".react-flow__node.wb-node-pv_intent",
    )!;
    fireEvent.click(intent);
    // Force depth=1 first so we know the expected count (intent + 1 child).
    const depthInput = screen.getByTestId("neighborhood-depth") as HTMLInputElement;
    fireEvent.change(depthInput, { target: { value: "1" } });
    await user.click(screen.getByTestId("toggle-neighborhood"));
    await waitFor(() => {
      const pane = screen.getByTestId("graph-pane");
      expect(pane).toHaveAttribute("data-focus-active", "true");
    });
    const totalAfter = document.querySelectorAll(".react-flow__node").length;
    expect(totalAfter).toBeLessThan(totalBefore);
    // The selected intent must still be present.
    expect(
      document.querySelector(".react-flow__node.wb-node-pv_intent"),
    ).not.toBeNull();
  });

  // -------------------------------------------------------------------------
  // Spec 74 §Canvas controls theme — dark-theme overrides
  // -------------------------------------------------------------------------

  it("React Flow controls + minimap are styled (no default white background)", async () => {
    // Vitest is configured with css: false, so the stylesheet isn't loaded
    // into the JSDOM document. Read the CSS file from the project root —
    // vitest's cwd is the package directory.
    const fs = await import("node:fs/promises");
    const css = await fs.readFile("src/styles.css", "utf-8");
    expect(css).toMatch(/\.react-flow__controls\s*\{[^}]*background:\s*var\(--wb-panel\)/);
    expect(css).toMatch(/\.react-flow__minimap\s*\{[^}]*background:\s*var\(--wb-panel\)/);
    expect(css).toMatch(/\.react-flow__controls-button\b/);
    expect(css).toMatch(/\.react-flow__minimap-mask\b/);
    expect(css).not.toMatch(/\.react-flow__controls\s*\{[^}]*background:\s*#fff/i);
  });
});
