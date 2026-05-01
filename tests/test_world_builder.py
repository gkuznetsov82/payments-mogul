"""World Builder service tests (spec 74 §Acceptance criteria, spec 75 §P1/P2).

Covers:
- valid config -> /validate passes with no errors
- invalid config -> deterministic stable diagnostics
- /normalize -> deterministic byte-stable output for same input
- normalized output round-trips through canonical loader
- /analyze -> nodes + edges + unresolved refs

Reuses tests/fixtures/v3_pipeline_full.yaml (and configs/* invalid samples)
to avoid forking validation rules.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from engine.world_builder.analyze import PipelineAggregate, analyze_yaml_string
from engine.world_builder.normalize import normalize_yaml_string
from engine.world_builder.service import app
from engine.world_builder.validation import validate_yaml_string


REPO_ROOT = Path(__file__).parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
CONFIGS = REPO_ROOT / "configs"

VALID_V3 = FIXTURES / "v3_pipeline_full.yaml"
VALID_V0 = CONFIGS / "prototype_v0.yaml"
INVALID_SCENARIO = CONFIGS / "invalid_scenario_id.yaml"
INVALID_METHOD_ORDER = CONFIGS / "invalid_method_order.yaml"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# -----------------------------------------------------------------------------
# /validate
# -----------------------------------------------------------------------------


def test_validate_valid_v3_pipeline_full(client: TestClient) -> None:
    body = VALID_V3.read_text(encoding="utf-8")
    r = client.post("/validate", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is True, rep
    assert rep["errors"] == []
    assert rep["schema_version"] == "v0"
    assert rep["pipeline_schema_version"] == "v3_runtime"
    assert rep["summary"]["scenario_id"] == "prototype_vendor_pop_v1"
    assert rep["summary"]["pipeline_profile_count"] >= 1


def test_validate_valid_v0_config(client: TestClient) -> None:
    body = VALID_V0.read_text(encoding="utf-8")
    r = client.post("/validate", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is True
    assert rep["schema_version"] == "v0"


def test_validate_invalid_scenario_returns_stable_code(client: TestClient) -> None:
    body = INVALID_SCENARIO.read_text(encoding="utf-8")
    r = client.post("/validate", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is False
    codes = {e["code"] for e in rep["errors"]}
    assert "E_SCENARIO_ID_UNSUPPORTED" in codes


def test_validate_invalid_method_order_returns_stable_code(client: TestClient) -> None:
    body = INVALID_METHOD_ORDER.read_text(encoding="utf-8")
    r = client.post("/validate", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is False
    codes = {e["code"] for e in rep["errors"]}
    assert "E_METHOD_ORDER_INVALID" in codes


def test_validate_yaml_parse_error(client: TestClient) -> None:
    bad = "scenario: { id: bad\n  not_yaml: ["
    r = client.post("/validate", json={"yaml_text": bad})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is False
    codes = {e["code"] for e in rep["errors"]}
    assert "E_YAML_PARSE" in codes


def test_validate_empty_yaml(client: TestClient) -> None:
    r = client.post("/validate", json={"yaml_text": ""})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is False
    assert rep["errors"][0]["code"] == "E_YAML_EMPTY"


def test_validate_top_level_not_mapping(client: TestClient) -> None:
    r = client.post("/validate", json={"yaml_text": "- item1\n- item2\n"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is False
    assert rep["errors"][0]["code"] == "E_YAML_TOPLEVEL_NOT_MAPPING"


def test_validate_pop_count_invalid_returns_diagnostic(client: TestClient) -> None:
    body = VALID_V0.read_text(encoding="utf-8").replace(
        "pop_count: 10000", "pop_count: -5"
    )
    r = client.post("/validate", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is False
    codes = {e["code"] for e in rep["errors"]}
    assert "E_POP_COUNT_INVALID" in codes


def test_validate_invalid_diagnostic_is_deterministic() -> None:
    """Same invalid input must produce the same diagnostic envelope each run."""
    body = INVALID_METHOD_ORDER.read_text(encoding="utf-8")
    rep_a = validate_yaml_string(body).to_dict()
    rep_b = validate_yaml_string(body).to_dict()
    assert rep_a == rep_b


def test_validate_accepts_raw_yaml_body(client: TestClient) -> None:
    """Spec 74 §UX: raw YAML content should also work for non-browser clients."""
    body = VALID_V0.read_text(encoding="utf-8")
    r = client.post("/validate", content=body, headers={"Content-Type": "text/yaml"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is True


# -----------------------------------------------------------------------------
# /normalize
# -----------------------------------------------------------------------------


def test_normalize_returns_yaml_for_valid_input(client: TestClient) -> None:
    body = VALID_V3.read_text(encoding="utf-8")
    r = client.post("/normalize", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is True
    assert isinstance(rep["normalized_yaml"], str) and rep["normalized_yaml"]
    assert rep["revalidates"] is True


def test_normalize_is_deterministic() -> None:
    """Same input -> same normalized output (spec 74 §Normalization ownership,
    spec 75 §P1 acceptance: byte-stable normalization)."""
    body = VALID_V3.read_text(encoding="utf-8")
    a = normalize_yaml_string(body)
    b = normalize_yaml_string(body)
    assert a.normalized_yaml == b.normalized_yaml
    assert a.normalized_yaml is not None


def test_normalize_reorders_vendors_by_id() -> None:
    """Canonical ordering: vendor_agents are sorted by vendor_id."""
    body = VALID_V3.read_text(encoding="utf-8")
    rep = normalize_yaml_string(body)
    parsed = yaml.safe_load(rep.normalized_yaml)
    vendor_ids = [v["vendor_id"] for v in parsed["world"]["vendor_agents"]]
    assert vendor_ids == sorted(vendor_ids), vendor_ids


def test_normalize_top_level_key_order() -> None:
    """Top-level keys appear in the canonical order defined by the normalizer."""
    body = VALID_V3.read_text(encoding="utf-8")
    rep = normalize_yaml_string(body)
    parsed = yaml.safe_load(rep.normalized_yaml)
    keys = list(parsed.keys())
    # config_version is always first; scenario before simulation; world before
    # control_defaults; pipeline appears before world per canonical order.
    assert keys[0] == "config_version"
    assert keys.index("scenario") < keys.index("simulation")
    assert keys.index("world") < keys.index("control_defaults")
    if "pipeline" in keys and "world" in keys:
        assert keys.index("pipeline") < keys.index("world")


def test_normalize_round_trips_through_loader() -> None:
    """Normalized output must re-validate (spec 74 §Acceptance criteria)."""
    from engine.config.loader import load_config_from_string

    body = VALID_V3.read_text(encoding="utf-8")
    rep = normalize_yaml_string(body)
    cfg, _ = load_config_from_string(rep.normalized_yaml)
    assert cfg.scenario.id == "prototype_vendor_pop_v1"


def test_normalize_invalid_returns_no_yaml(client: TestClient) -> None:
    body = INVALID_METHOD_ORDER.read_text(encoding="utf-8")
    r = client.post("/normalize", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is False
    assert rep["normalized_yaml"] is None
    codes = {e["code"] for e in rep["errors"]}
    assert "E_METHOD_ORDER_INVALID" in codes


def test_normalize_double_pass_is_idempotent() -> None:
    """Normalizing already-normalized output must produce the same bytes."""
    body = VALID_V3.read_text(encoding="utf-8")
    once = normalize_yaml_string(body)
    twice = normalize_yaml_string(once.normalized_yaml)
    assert once.normalized_yaml == twice.normalized_yaml


# -----------------------------------------------------------------------------
# /analyze
# -----------------------------------------------------------------------------


def test_analyze_returns_nodes_and_edges(client: TestClient) -> None:
    body = VALID_V3.read_text(encoding="utf-8")
    r = client.post("/analyze", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["valid"] is True
    g = rep["graph"]
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"vendor", "product", "pop"}.issubset(kinds)
    # v3 fixture binds pipeline profiles, so we expect them in the graph.
    assert "pipeline_profile" in kinds
    edge_kinds = {e["kind"] for e in g["edges"]}
    assert "owns" in edge_kinds
    assert "linked_to" in edge_kinds
    assert "binds_profile" in edge_kinds
    assert rep["unresolved_refs"] == []


def test_analyze_unresolved_link_target() -> None:
    """If a pop links to an unknown product, /analyze must surface unresolved refs
    even though parse-level YAML is fine."""
    body = VALID_V0.read_text(encoding="utf-8").replace(
        'product_id: "prod_prepaid_alpha"\n          known: true',
        'product_id: "prod_does_not_exist"\n          known: true',
        1,  # only the link reference, not the product definition
    )
    rep = analyze_yaml_string(body)
    # Validation should fail with E_LINK_TARGET_MISSING from the loader, AND
    # the analyzer should also surface the unresolved ref in its graph view.
    assert rep.valid is False
    codes_in_unresolved = {d.code for d in rep.unresolved_refs}
    assert "E_LINK_TARGET_MISSING" in codes_in_unresolved


def test_analyze_partial_graph_for_invalid_input() -> None:
    """Even when validation fails, structural graph must still render
    (spec 74 §Failure behavior, spec 75 §P2)."""
    body = INVALID_METHOD_ORDER.read_text(encoding="utf-8")
    rep = analyze_yaml_string(body)
    assert rep.valid is False
    assert any(n.kind == "vendor" for n in rep.nodes)
    assert any(n.kind == "pop" for n in rep.nodes)
    assert any(e.kind == "owns" for e in rep.edges)


def test_analyze_yaml_parse_error_is_graceful() -> None:
    """Parse errors must not crash the analyzer (spec 74 §Failure behavior)."""
    rep = analyze_yaml_string("scenario: { id: bad\n  not_yaml: [")
    assert rep.valid is False
    assert rep.errors[0].code == "E_YAML_PARSE"
    assert rep.nodes == []
    assert rep.edges == []


def test_analyze_unresolved_pipeline_profile_ref(client: TestClient) -> None:
    """Pipeline profile reference to undefined ID is surfaced as unresolved."""
    body = VALID_V3.read_text(encoding="utf-8").replace(
        'pipeline_profile_id: "prepaid_card_pipeline"',
        'pipeline_profile_id: "missing_profile_id"',
        1,
    )
    r = client.post("/analyze", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    codes = {d["code"] for d in rep["unresolved_refs"]}
    assert "E_PIPELINE_PROFILE_NOT_FOUND" in codes


# -----------------------------------------------------------------------------
# /health (sanity)
# -----------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["binding_level"] == "v0_viewer"
    assert "v3_runtime" in body["supported_pipeline_schema_versions"]


def test_index_serves_ui_scaffold(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    # Should serve the React SPA index.html (or a JSON pointer when ui dir
    # is absent in this checkout) — both shapes are acceptable for spec 75 §P0.
    body = r.text
    body_lower = body.lower()
    assert (
        "world builder" in body_lower            # SPA <title>
        or "world_builder" in body_lower         # JSON pointer fallback
        or "world-builder" in body_lower
    )


def test_static_assets_are_served(client: TestClient) -> None:
    """The mounted /ui/ static asset directory must serve the built bundle so
    the SPA loads correctly when behind the FastAPI service (spec 74)."""
    # The Vite build emits hashed asset filenames; we just probe the directory
    # listing endpoint indirectly by hitting the index and confirming it
    # references the /assets/ subpath.
    r = client.get("/")
    assert r.status_code == 200
    if "<div id=\"root\">" in r.text:
        # SPA build is present; assets/ should be linked.
        assert "/assets/" in r.text


# -----------------------------------------------------------------------------
# Analyzer: composite identity for duplicate product_ids (spec 40 §pipeline_role_bindings)
# -----------------------------------------------------------------------------


_DUPLICATE_PRODUCT_IDS_YAML = """
config_version: "v0"

scenario:
  id: "prototype_vendor_pop_v1"
  seed: 1
  market_id: "market_test"

simulation:
  tick_wall_clock_base_ms: 0
  debug_history_max_ticks: 30
  debug_history_default_ticks: 7
  intake_window_ms: 1
  agent_method_order: ["Onboard", "Transact"]
  agent_iteration_policy: "stable_sorted_ids"
  count_rounding_mode: "half_up"
  amount_scale_dp: 2
  amount_rounding_mode: "half_up"

world:
  vendor_agents:
    - vendor_id: "vendor_a"
      vendor_label: "Vendor A"
      operational: true
      products:
        - product_id: "prod_shared"
          product_label: "A's prod_shared"
          product_class: "GenericProduct"
        - product_id: "prod_a_caller"
          product_label: "A caller"
          product_class: "GenericProduct"
    - vendor_id: "vendor_b"
      vendor_label: "Vendor B"
      operational: true
      products:
        - product_id: "prod_shared"
          product_label: "B's prod_shared"
          product_class: "GenericProduct"

  pops:
    - pop_id: "pop_main"
      pop_label: "Main"
      pop_count: 1000
      daily_onboard: 0.01
      daily_active: 0.10
      daily_transact_count: 1.0
      daily_transact_amount: 10.0
      product_links:
        - vendor_id: "vendor_a"
          product_id: "prod_a_caller"
          known: true
          onboarded_count: 0

control_defaults:
  accepting_onboard: true
  accepting_transact: true
"""


def _inject_role_binding(yaml_text: str, binding_yaml: str) -> str:
    """Add a pipeline_role_bindings block to vendor_a.prod_a_caller for tests."""
    needle = (
        '          product_label: "A caller"\n'
        '          product_class: "GenericProduct"\n'
    )
    return yaml_text.replace(needle, needle + binding_yaml)


def test_analyzer_duplicate_product_id_alone_is_ambiguous() -> None:
    """If two vendors define the same product_id, a `{ product_id: X }` selector
    alone cannot resolve a unique target — analyzer must surface
    E_ROLE_TARGET_PRODUCT_AMBIGUOUS rather than silently picking one."""
    binding = (
        "          pipeline_role_bindings:\n"
        "            entity_roles:\n"
        "              partner: { product_id: 'prod_shared' }\n"
    )
    body = _inject_role_binding(_DUPLICATE_PRODUCT_IDS_YAML, binding)
    rep = analyze_yaml_string(body)
    codes = {d.code for d in rep.unresolved_refs}
    assert "E_ROLE_TARGET_PRODUCT_AMBIGUOUS" in codes
    # The role-binding edge MUST NOT have been emitted because the target was
    # ambiguous — otherwise the UI would point at the wrong product.
    role_edges = [e for e in rep.edges if e.kind == "role_binding"]
    assert role_edges == [], f"unexpected role_binding edges: {role_edges}"


def test_analyzer_composite_identity_resolves_correctly() -> None:
    """`{ agent_id, product_id }` form must always pin the exact product node,
    even when the same product_id exists on another vendor."""
    binding = (
        "          pipeline_role_bindings:\n"
        "            entity_roles:\n"
        "              partner: { agent_id: 'vendor_b', product_id: 'prod_shared' }\n"
    )
    body = _inject_role_binding(_DUPLICATE_PRODUCT_IDS_YAML, binding)
    rep = analyze_yaml_string(body)
    role_edges = [e for e in rep.edges if e.kind == "role_binding"]
    assert len(role_edges) == 1, role_edges
    edge = role_edges[0]
    assert edge.source == "product:vendor_a/prod_a_caller"
    # Critical: edge resolves to vendor_b's prod_shared, NOT vendor_a's.
    assert edge.target == "product:vendor_b/prod_shared", (
        "composite identity must pin the target to the agent that owns the product"
    )
    # No ambiguity diagnostic when both fields are provided.
    codes = {d.code for d in rep.unresolved_refs}
    assert "E_ROLE_TARGET_PRODUCT_AMBIGUOUS" not in codes


def test_analyzer_composite_identity_missing_pair_is_unresolved() -> None:
    """If the (agent, product) pair doesn't exist (agent owns product, but not
    THIS product), analyzer must flag E_ROLE_TARGET_PRODUCT_MISSING."""
    binding = (
        "          pipeline_role_bindings:\n"
        "            entity_roles:\n"
        "              partner: { agent_id: 'vendor_a', product_id: 'prod_shared_typo' }\n"
    )
    body = _inject_role_binding(_DUPLICATE_PRODUCT_IDS_YAML, binding)
    rep = analyze_yaml_string(body)
    codes = {d.code for d in rep.unresolved_refs}
    assert "E_ROLE_TARGET_PRODUCT_MISSING" in codes


def test_analyzer_unique_product_id_still_resolves_with_short_form() -> None:
    """Backwards-compatible: when the product_id is unique across vendors, the
    short `{ product_id: X }` form still resolves to its single owner."""
    # Drop the duplicate by removing vendor_b's prod_shared.
    body = _DUPLICATE_PRODUCT_IDS_YAML.replace(
        "    - vendor_id: \"vendor_b\"\n"
        "      vendor_label: \"Vendor B\"\n"
        "      operational: true\n"
        "      products:\n"
        "        - product_id: \"prod_shared\"\n"
        "          product_label: \"B's prod_shared\"\n"
        "          product_class: \"GenericProduct\"\n",
        "",
    )
    binding = (
        "          pipeline_role_bindings:\n"
        "            entity_roles:\n"
        "              partner: { product_id: 'prod_shared' }\n"
    )
    body = _inject_role_binding(body, binding)
    rep = analyze_yaml_string(body)
    role_edges = [e for e in rep.edges if e.kind == "role_binding"]
    assert len(role_edges) == 1
    assert role_edges[0].target == "product:vendor_a/prod_shared"


# -----------------------------------------------------------------------------
# Diagnostic graph-target hints (spec 74 §UI diagnostics-to-node linking)
# -----------------------------------------------------------------------------


def test_analyzer_unresolved_diagnostics_carry_node_id() -> None:
    """For analyzer-emitted unresolved refs, the originating node id must be
    attached so the UI can focus/highlight it on click. When no graph context
    exists, the field is None and UI must show the explicit fallback state."""
    binding = (
        "          pipeline_role_bindings:\n"
        "            entity_roles:\n"
        "              partner: { product_id: 'prod_shared' }\n"
    )
    body = _inject_role_binding(_DUPLICATE_PRODUCT_IDS_YAML, binding)
    rep = analyze_yaml_string(body)
    diag = next(
        d for d in rep.unresolved_refs if d.code == "E_ROLE_TARGET_PRODUCT_AMBIGUOUS"
    )
    assert diag.node_id == "product:vendor_a/prod_a_caller"


def test_diagnostic_section_is_derived_from_path() -> None:
    """Diagnostic.to_dict backfills `section` from `path` so the UI section
    navigator can group/filter consistently."""
    body = INVALID_METHOD_ORDER.read_text(encoding="utf-8")
    rep = validate_yaml_string(body).to_dict()
    err = rep["errors"][0]
    # invalid_method_order.yaml triggers a simulation.* path.
    assert err["section"] == "simulation"


# -----------------------------------------------------------------------------
# Visual chain traceability for v3 fixture (spec 74 §Acceptance criteria)
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Pipeline aggregate scope + cross-pipeline edges (spec 74 §Pipeline scope UX,
# §Pipeline visibility completeness, §Cross-pipeline connectivity)
# -----------------------------------------------------------------------------


V3_RUNTIME_EXAMPLE = REPO_ROOT / "configs" / "prototype_v3_runtime_example.yaml"


def test_analyze_returns_pipeline_aggregate(client: TestClient) -> None:
    body = V3_RUNTIME_EXAMPLE.read_text(encoding="utf-8")
    r = client.post("/analyze", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    agg = rep.get("pipeline_aggregate")
    assert agg is not None, "aggregate scope should be emitted"
    summary = agg["summary"]
    assert summary["profile_count"] == 3
    # All v3 profiles are present in the aggregate.
    assert set(agg["profiles"]) == {
        "prepaid_card_pipeline",
        "scheme_access_pipeline",
        "processor_services_pipeline",
    }
    # Aggregate node count is the union over per-profile views.
    per_profile_total = sum(len(v["nodes"]) for v in rep["pipeline_views"])
    assert len(agg["nodes"]) <= per_profile_total
    assert len(agg["nodes"]) >= summary["intent_count"] + summary["fee_count"]


def test_aggregate_scope_includes_union_of_postings_transfers_fees_demands() -> None:
    """Aggregate must surface every posting/transfer/fee/demand defined across
    profiles (spec 74 §Pipeline visibility completeness)."""
    body = V3_RUNTIME_EXAMPLE.read_text(encoding="utf-8")
    rep = analyze_yaml_string(body)
    agg = rep.pipeline_aggregate
    assert agg is not None
    kinds = {n.kind for n in agg.nodes}
    for required in (
        "pv_posting",
        "pv_transfer",
        "pv_fee",
        "pv_settlement_demand",
        "pv_intent",
        "pv_outgoing_intent",
        "pv_ledger",
        "pv_container",
    ):
        assert required in kinds, f"aggregate must include kind {required}"
    # Counts roughly match per-profile total.
    posting_count = sum(int(v.summary.get("posting_count", 0)) for v in rep.pipeline_views)
    transfer_count = sum(int(v.summary.get("transfer_count", 0)) for v in rep.pipeline_views)
    assert sum(1 for n in agg.nodes if n.kind == "pv_posting") == posting_count
    assert sum(1 for n in agg.nodes if n.kind == "pv_transfer") == transfer_count


def test_posting_and_transfer_have_trigger_lineage_edges() -> None:
    """Spec 74 §Pipeline visibility completeness: postings/transfers must be
    traceable from triggers to rule nodes to ledger/container endpoints."""
    body = V3_RUNTIME_EXAMPLE.read_text(encoding="utf-8")
    rep = analyze_yaml_string(body)
    prepaid = next(v for v in rep.pipeline_views if v.profile_id == "prepaid_card_pipeline")
    posts = [n for n in prepaid.nodes if n.kind == "pv_posting"]
    assert posts, "expected posting rules in prepaid"
    for posting in posts:
        # There must be at least one pv_triggers_posting edge into this rule.
        trig_edges = [
            e for e in prepaid.edges
            if e.kind == "pv_triggers_posting" and e.target == posting.id
        ]
        assert trig_edges, f"posting {posting.id} missing trigger lineage edge"

    transfers = [n for n in prepaid.nodes if n.kind == "pv_transfer"]
    assert transfers, "expected transfer rules in prepaid"
    for transfer in transfers:
        trig_edges = [
            e for e in prepaid.edges
            if e.kind == "pv_triggers_transfer" and e.target == transfer.id
        ]
        assert trig_edges, f"transfer {transfer.id} missing trigger lineage edge"


def test_cross_pipeline_edges_for_vendor_to_scheme_and_processor() -> None:
    """v3 fixture: prepaid pipeline emits Transact-Purchase-Clearing-Scheme and
    -Processor; those become triggers in the scheme/processor sink profiles.
    Aggregate scope must surface a pv_cross_pipeline edge for each."""
    body = V3_RUNTIME_EXAMPLE.read_text(encoding="utf-8")
    rep = analyze_yaml_string(body)
    agg = rep.pipeline_aggregate
    assert agg is not None
    cross = [e for e in agg.edges if e.kind == "pv_cross_pipeline"]
    assert cross, "expected at least one cross-pipeline edge"

    target_profiles = {str(e.attrs.get("target_profile_id")) for e in cross}
    assert "scheme_access_pipeline" in target_profiles
    assert "processor_services_pipeline" in target_profiles


def test_cross_pipeline_edge_target_metadata_present() -> None:
    """Each cross-pipeline edge must carry the navigation metadata the UI
    needs: target_profile_id, target_node_id, target_instance_id."""
    body = V3_RUNTIME_EXAMPLE.read_text(encoding="utf-8")
    rep = analyze_yaml_string(body)
    cross = [e for e in (rep.pipeline_aggregate or PipelineAggregate()).edges
             if e.kind == "pv_cross_pipeline"]
    assert cross
    for e in cross:
        assert e.attrs.get("target_profile_id"), e
        assert e.attrs.get("target_node_id"), e
        # target_instance_id is `vendor_id/product_id` for the resolved owner.
        instance = e.attrs.get("target_instance_id")
        assert instance and "/" in str(instance), e
        assert e.attrs.get("source_profile_id"), e
        assert e.attrs.get("trigger_id"), e


def test_cross_pipeline_edges_are_deterministic_across_runs() -> None:
    """Same input must produce identical cross-pipeline edges (spec 74 §Preserve
    deterministic output ordering)."""
    body = V3_RUNTIME_EXAMPLE.read_text(encoding="utf-8")
    a = analyze_yaml_string(body).to_dict()
    b = analyze_yaml_string(body).to_dict()
    assert a["pipeline_aggregate"] == b["pipeline_aggregate"]


# -----------------------------------------------------------------------------
# Pipeline drill-down (spec 74 §Pipeline drill-down)
# -----------------------------------------------------------------------------


def test_analyze_returns_pipeline_views_for_v3_fixture(client: TestClient) -> None:
    body = VALID_V3.read_text(encoding="utf-8")
    r = client.post("/analyze", json={"yaml_text": body})
    assert r.status_code == 200, r.text
    rep = r.json()
    views = rep.get("pipeline_views")
    assert isinstance(views, list) and len(views) >= 1
    by_id = {v["profile_id"]: v for v in views}
    # v3 fixture defines prepaid + scheme_access + processor_services profiles.
    assert "prepaid_card_pipeline" in by_id
    prepaid = by_id["prepaid_card_pipeline"]
    # Stage nodes must include intents, ledgers, containers, postings, transfers.
    node_kinds = {n["kind"] for n in prepaid["nodes"]}
    assert "pv_intent" in node_kinds
    assert "pv_ledger" in node_kinds
    assert "pv_container" in node_kinds
    assert "pv_posting" in node_kinds
    assert "pv_transfer" in node_kinds
    # Stage edges must include routing, posting flow, and transfer flow.
    edge_kinds = {e["kind"] for e in prepaid["edges"]}
    assert "pv_routes_to" in edge_kinds
    assert "pv_posts_from" in edge_kinds or "pv_posts_to" in edge_kinds
    assert "pv_transfer_from" in edge_kinds or "pv_transfer_to" in edge_kinds


def test_pipeline_view_contains_full_intent_to_destination_chain() -> None:
    """For each transaction_intent in the v3 prepaid profile we must be able
    to follow intent -> destination -> outgoing_intent in the drill-down."""
    body = VALID_V3.read_text(encoding="utf-8")
    rep = analyze_yaml_string(body)
    prepaid = next(v for v in rep.pipeline_views if v.profile_id == "prepaid_card_pipeline")
    # Pick the purchase intent.
    intent_node = next(
        n for n in prepaid.nodes
        if n.kind == "pv_intent" and n.label == "Transact-Purchase-Clearing"
    )
    routes = [e for e in prepaid.edges if e.kind == "pv_routes_to" and e.source == intent_node.id]
    assert len(routes) >= 2, "purchase intent should have at least 2 destinations (scheme + processor)"
    # Each destination should emit an outgoing_intent stage node.
    for r in routes:
        emits = [
            e for e in prepaid.edges if e.kind == "pv_emits" and e.source == r.target
        ]
        assert emits, f"destination {r.target} must emit an outgoing-intent node"


def test_pipeline_view_sink_profile_links_fees_to_upstream_outgoing() -> None:
    """Sink profiles' fees trigger on the upstream profile's outgoing intent
    ids; the drill-down must surface those as synthetic outgoing-intent nodes
    so traceability isn't broken across profile boundaries."""
    body = VALID_V3.read_text(encoding="utf-8")
    rep = analyze_yaml_string(body)
    scheme = next(
        v for v in rep.pipeline_views if v.profile_id == "scheme_access_pipeline"
    )
    # The fee triggers on Transact-Purchase-Clearing-Scheme, which is defined
    # in the prepaid profile, not in scheme. The view must still show it.
    has_external_intent = any(
        n.kind == "pv_outgoing_intent" and bool(n.attrs.get("external"))
        for n in scheme.nodes
    )
    assert has_external_intent, "scheme profile must surface its external trigger"


# -----------------------------------------------------------------------------
# Diagnostic edge_id + graph_view hints (spec 74 §Diagnostic routing)
# -----------------------------------------------------------------------------


def test_diagnostic_graph_view_pipeline_for_pipeline_path(client: TestClient) -> None:
    """Diagnostics whose path is rooted in the pipeline section must hint
    `graph_view = "pipeline"` so the UI flips to drill-down on click."""
    body = VALID_V3.read_text(encoding="utf-8").replace(
        "pipeline_schema_version: \"v3_runtime\"",
        "pipeline_schema_version: \"v9_unknown\"",
    )
    r = client.post("/validate", json={"yaml_text": body})
    rep = r.json()
    pipeline_diags = [e for e in rep["errors"] if e.get("section") == "pipeline"]
    assert pipeline_diags, "expected at least one pipeline-section diagnostic"
    assert all(d.get("graph_view") == "pipeline" for d in pipeline_diags)


def test_diagnostic_graph_view_topology_for_world_path() -> None:
    """World/region/calendar-rooted diagnostics route to the topology view."""
    body = VALID_V0.read_text(encoding="utf-8").replace("pop_count: 10000", "pop_count: -5")
    rep = validate_yaml_string(body)
    serialized = rep.to_dict()
    world_diags = [d for d in serialized["errors"] if d.get("section") == "world"]
    assert world_diags
    assert all(d.get("graph_view") == "topology" for d in world_diags)


def test_diagnostic_no_graph_view_for_non_graph_sections() -> None:
    """Simulation/scenario diagnostics have no natural graph view; the UI
    must render the 'no graph target' fallback."""
    body = INVALID_METHOD_ORDER.read_text(encoding="utf-8")
    rep = validate_yaml_string(body).to_dict()
    err = rep["errors"][0]
    assert err["section"] == "simulation"
    assert err["graph_view"] is None


def test_v3_fixture_visual_chain_pop_to_profile() -> None:
    """At least one full visual chain pop -> product_link -> product ->
    pipeline_profile must be traceable in the analyze graph for the v3 fixture
    (spec 74 §Acceptance: "Topology view shows all key entity classes and
    references", spec 75 §P2 acceptance: traceability)."""
    body = VALID_V3.read_text(encoding="utf-8")
    rep = analyze_yaml_string(body)
    nodes_by_id = {n.id: n for n in rep.nodes}

    pop_nodes = [n for n in rep.nodes if n.kind == "pop"]
    assert pop_nodes, "no pop nodes in v3 fixture"

    found_chain = False
    for pop in pop_nodes:
        # pop -> product (linked_to)
        link_edges = [
            e for e in rep.edges if e.kind == "linked_to" and e.source == pop.id
        ]
        for le in link_edges:
            product = nodes_by_id.get(le.target)
            if product is None or product.kind != "product":
                continue
            # product -> pipeline_profile (binds_profile)
            prof_edges = [
                e for e in rep.edges
                if e.kind == "binds_profile" and e.source == product.id
            ]
            for pe in prof_edges:
                profile = nodes_by_id.get(pe.target)
                if profile is not None and profile.kind == "pipeline_profile":
                    found_chain = True
                    break
            if found_chain:
                break
        if found_chain:
            break

    assert found_chain, (
        "v3 fixture must allow visual tracing of at least one "
        "pop -> product_link -> product -> pipeline_profile chain"
    )
