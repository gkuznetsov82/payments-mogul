import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DetailsPane } from "../components/DetailsPane";

describe("DetailsPane", () => {
  it("shows empty state when no target", () => {
    render(<DetailsPane target={null} />);
    expect(screen.getByTestId("details-empty")).toBeInTheDocument();
  });

  it("renders id/kind/label/attrs for a node target", () => {
    render(
      <DetailsPane
        target={{
          kind: "node",
          node: {
            id: "product:vendor_alpha/prod_prepaid_alpha",
            kind: "product",
            label: "Alpha Prepaid Card",
            attrs: { product_class: "RetailPayment-Card-Prepaid", vendor_id: "vendor_alpha" },
          },
        }}
      />,
    );
    expect(screen.getByTestId("details-id")).toHaveTextContent(
      "product:vendor_alpha/prod_prepaid_alpha",
    );
    expect(screen.getByTestId("details-kind")).toHaveTextContent("product");
    expect(screen.getByTestId("details-label")).toHaveTextContent("Alpha Prepaid Card");
    const attrs = screen.getByTestId("details-attrs");
    expect(attrs.textContent).toContain("RetailPayment-Card-Prepaid");
    expect(attrs.textContent).toContain("vendor_alpha");
  });

  it("renders source/target/kind for an edge target", () => {
    render(
      <DetailsPane
        target={{
          kind: "edge",
          edge: {
            source: "pop:pop_main",
            target: "product:vendor_alpha/prod_prepaid_alpha",
            kind: "linked_to",
            attrs: { known: true, onboarded_count: 0 },
          },
        }}
      />,
    );
    expect(screen.getByTestId("details-kind")).toHaveTextContent("linked_to");
    const id = screen.getByTestId("details-id");
    expect(id.textContent).toContain("pop:pop_main");
    expect(id.textContent).toContain("product:vendor_alpha/prod_prepaid_alpha");
  });

  it("renders kind-specific summary card for product nodes", () => {
    render(
      <DetailsPane
        target={{
          kind: "node",
          node: {
            id: "product:V/P",
            kind: "product",
            label: "P",
            attrs: {
              vendor_id: "V",
              product_class: "RetailPayment-Card-Prepaid",
              pipeline_profile_id: "prepaid_card_pipeline",
            },
          },
        }}
      />,
    );
    const summary = screen.getByTestId("kind-summary-product");
    expect(summary.textContent).toContain("V");
    expect(summary.textContent).toContain("RetailPayment-Card-Prepaid");
    expect(summary.textContent).toContain("prepaid_card_pipeline");
  });

  it("renders kind-specific summary card for fee stage nodes", () => {
    render(
      <DetailsPane
        target={{
          kind: "node",
          node: {
            id: "pv:scheme_access_pipeline:fee:fee_scheme_access",
            kind: "pv_fee",
            label: "fee_scheme_access",
            attrs: {
              beneficiary_role: "self_agent",
              payer_role: "payer_role",
              amount_percentage: 0.0015,
              non_payable_statement: false,
              settlement_value_date_policy: "next_month_day_plus_x",
              settlement_value_date_offset_days: 5,
            },
          },
        }}
      />,
    );
    const summary = screen.getByTestId("kind-summary-fee");
    expect(summary.textContent).toContain("self_agent");
    expect(summary.textContent).toContain("0.0015");
    expect(summary.textContent).toContain("next_month_day_plus_x");
    expect(summary.textContent).toContain("+5d");
  });

  it("renders posting-rule lineage fields for pv_posting nodes", () => {
    render(
      <DetailsPane
        target={{
          kind: "node",
          node: {
            id: "pv:prepaid_card_pipeline:posting:0",
            kind: "pv_posting",
            label: "Transact-Purchase-Clearing → posting",
            attrs: {
              trigger_id: "Transact-Purchase-Clearing",
              source_ledger_ref: "customer_funds",
              destination_ledger_ref: "settlement_funds",
              amount_basis: "transaction_intent_amount",
              value_date_policy: "next_working_day_plus_x",
              value_date_offset_days: 0,
              profile_id: "prepaid_card_pipeline",
              rule_index: 0,
            },
          },
        }}
      />,
    );
    const summary = screen.getByTestId("kind-summary-posting");
    expect(summary.textContent).toContain("Transact-Purchase-Clearing");
    expect(summary.textContent).toContain("customer_funds");
    expect(summary.textContent).toContain("settlement_funds");
    expect(summary.textContent).toContain("next_working_day_plus_x");
    expect(summary.textContent).toContain("prepaid_card_pipeline");
  });

  it("renders transfer-rule lineage fields for pv_transfer nodes", () => {
    render(
      <DetailsPane
        target={{
          kind: "node",
          node: {
            id: "pv:prepaid_card_pipeline:transfer:0",
            kind: "pv_transfer",
            label: "Transact-Purchase-Clearing → transfer",
            attrs: {
              trigger_id: "Transact-Purchase-Clearing",
              source_container_ref: "customer_funds_container",
              destination_container_ref: "settlement_funds_container",
              amount_basis: "transaction_intent_amount",
              value_date_policy: "next_working_day_plus_x",
              value_date_offset_days: 0,
              profile_id: "prepaid_card_pipeline",
              rule_index: 0,
            },
          },
        }}
      />,
    );
    const summary = screen.getByTestId("kind-summary-transfer");
    expect(summary.textContent).toContain("customer_funds_container");
    expect(summary.textContent).toContain("settlement_funds_container");
    expect(summary.textContent).toContain("Transact-Purchase-Clearing");
    expect(summary.textContent).toContain("next_working_day_plus_x");
  });

  it("renders cross-pipeline navigation metadata for pv_cross_pipeline edges", () => {
    render(
      <DetailsPane
        target={{
          kind: "edge",
          edge: {
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
        }}
      />,
    );
    const summary = screen.getByTestId("kind-summary-cross-pipeline");
    expect(summary.textContent).toContain("scheme_access_pipeline");
    expect(summary.textContent).toContain("vendor_scheme/prod_scheme_access");
    expect(summary.textContent).toContain("Transact-Purchase-Clearing-Scheme");
  });

  it("lists incoming + outgoing edges for the selected node", () => {
    render(
      <DetailsPane
        target={{
          kind: "node",
          node: {
            id: "product:V/P",
            kind: "product",
            label: "P",
            attrs: {},
          },
        }}
        edges={[
          { source: "vendor:V", target: "product:V/P", kind: "owns", attrs: {} },
          { source: "pop:POP", target: "product:V/P", kind: "linked_to", attrs: {} },
          { source: "product:V/P", target: "pipeline_profile:PRO", kind: "binds_profile", attrs: {} },
        ]}
      />,
    );
    const rows = screen.getAllByTestId("related-edge-row");
    expect(rows.length).toBe(3);
    const directions = rows.map((r) => r.getAttribute("data-direction"));
    expect(directions).toContain("in");
    expect(directions).toContain("out");
  });
});
