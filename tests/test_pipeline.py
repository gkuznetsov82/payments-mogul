"""End-to-end pipeline tests (ADR-0002 / spec 33 / spec 40 §pipeline / spec 52).

Covers:
- Config validation: missing profile ref, unresolved roles, missing offset, bad refs.
- Determinism: same seed/config -> identical event sequence.
- Pipeline behavior: prepaid -> sink handoff, processor fixed fee, scheme fixed+percent fee.
- Invoice emission on due date; direct-payment settlement (netting deferred per ADR-0002).
- Realtime contract: required correlation keys per spec 52.
- v2_foundations gating: profile attached but schema_version v2 -> no pipeline events.
- SinkProduct rejects pop-origin onboard/transact.
- value_date resolution helpers.
"""

from __future__ import annotations

import asyncio
from datetime import date as _date_t
from pathlib import Path

import pytest
import yaml as pyyaml

from engine.config.loader import ConfigValidationError, load_config
from engine.pipeline.value_dates import resolve_value_date
from engine.simulation.engine import SimulationEngine


ROOT = Path(__file__).parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "v3_pipeline_full.yaml"


# ---------------------------------------------------------------- helpers

async def _drain(q: asyncio.Queue, timeout: float = 0.1) -> list[dict]:
    out = []
    while True:
        try:
            ev = await asyncio.wait_for(q.get(), timeout=timeout)
            out.append(ev)
        except asyncio.TimeoutError:
            return out


def _engine() -> SimulationEngine:
    cfg, _ = load_config(FIXTURE)
    eng = SimulationEngine(cfg, config_path=FIXTURE)
    eng.state_from_idle()
    return eng


def _yaml_data() -> dict:
    return pyyaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def _write_tmp(tmp_path, data: dict) -> Path:
    p = tmp_path / "cfg.yaml"
    p.write_text(pyyaml.dump(data))
    return p


# ---------------------------------------------------------------- config validation

def test_unknown_pipeline_profile_id_rejected(tmp_path):
    data = _yaml_data()
    data["world"]["vendor_agents"][0]["products"][0]["pipeline_profile_id"] = "no_such_profile"
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_PIPELINE_PROFILE_NOT_FOUND"


def test_unresolved_pipeline_role_rejected(tmp_path):
    data = _yaml_data()
    # Drop a role the prepaid profile actually references.
    del data["world"]["vendor_agents"][0]["products"][0]["pipeline_role_bindings"]["entity_roles"]["scheme_access_product"]
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_PIPELINE_ROLE_UNRESOLVED"


def test_missing_offset_for_plus_x_rejected(tmp_path):
    data = _yaml_data()
    # Strip required offset on a posting rule that uses next_month_day_plus_x.
    fee_profile = data["pipeline"]["pipeline_profiles"][1]  # scheme_access_pipeline
    fee_profile["posting_rules"][0]["value_date_offset_days"] = None
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_VALUE_DATE_OFFSET_REQUIRED"


def test_bad_ledger_ref_rejected(tmp_path):
    data = _yaml_data()
    data["pipeline"]["pipeline_profiles"][1]["posting_rules"][0]["source_ledger_ref"] = "no_such_ledger"
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_LEDGER_REF_NOT_FOUND"


def test_unknown_fee_trigger_rejected(tmp_path):
    data = _yaml_data()
    data["pipeline"]["pipeline_profiles"][1]["fee_sequences"][0]["fees"][0]["trigger_ids"] = ["no_such_trigger"]
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_FEE_TRIGGER_UNKNOWN"


def test_invalid_product_class_rejected(tmp_path):
    data = _yaml_data()
    data["world"]["vendor_agents"][0]["products"][0]["product_class"] = "MysteryClass"
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_INVALID_PRODUCT_CLASS"


def test_duplicate_pipeline_profile_id_rejected(tmp_path):
    data = _yaml_data()
    dup = dict(data["pipeline"]["pipeline_profiles"][1])
    data["pipeline"]["pipeline_profiles"].append(dup)
    with pytest.raises(ConfigValidationError) as exc:
        load_config(_write_tmp(tmp_path, data))
    assert exc.value.code == "E_PIPELINE_PROFILE_DUPLICATE"


# ---------------------------------------------------------------- value_date resolver

def test_resolve_value_date_same_day():
    d = _date_t(2026, 1, 15)
    assert resolve_value_date(d, "same_day") == d


def test_resolve_value_date_next_day_plus_x():
    d = _date_t(2026, 1, 15)
    assert resolve_value_date(d, "next_day_plus_x", 0) == _date_t(2026, 1, 16)
    assert resolve_value_date(d, "next_day_plus_x", 4) == _date_t(2026, 1, 20)


def test_resolve_value_date_next_month_day_plus_x():
    d = _date_t(2026, 1, 15)
    assert resolve_value_date(d, "next_month_day_plus_x", 5) == _date_t(2026, 2, 6)
    # Year-roll
    d = _date_t(2026, 12, 30)
    assert resolve_value_date(d, "next_month_day_plus_x", 0) == _date_t(2027, 1, 1)


def test_resolve_value_date_offset_required_for_plus_x():
    from engine.pipeline.value_dates import ValueDateError
    with pytest.raises(ValueDateError):
        resolve_value_date(_date_t(2026, 1, 15), "next_day_plus_x")


# ---------------------------------------------------------------- end-to-end

@pytest.mark.asyncio
async def test_pipeline_emits_intent_fee_posting_transfer_for_prepaid_to_sinks():
    """One tick under the v3_runtime fixture must emit:
       - intents from prepaid -> scheme_access_product + processor_services_product
       - fees at scheme + processor (count_cost ± amount_percentage)
       - posting + transfer for the prepaid intent
    """
    eng = _engine()
    q = eng.subscribe()
    await eng._run_one_tick(next_day_mode=True)
    events = await _drain(q)
    types = [e["event"] for e in events]

    assert "transaction_intent_event" in types
    assert "fee_accrual_event" in types
    assert "posting_entry_event" in types
    assert "value_transfer_event" in types

    intents = [e["data"] for e in events if e["event"] == "transaction_intent_event"]
    intent_outgoing_ids = {i["intent_id"] for i in intents}
    assert "Transact-Purchase-Clearing-Scheme" in intent_outgoing_ids
    assert "Transact-Purchase-Clearing-Processor" in intent_outgoing_ids

    fees = [e["data"] for e in events if e["event"] == "fee_accrual_event"]
    fee_ids = {f["fee_id"] for f in fees}
    assert "fee_scheme_access" in fee_ids
    assert "fee_processor_services" in fee_ids


@pytest.mark.asyncio
async def test_pipeline_realtime_payload_correlation_keys():
    """Every pipeline event must carry tick_id, simulation_date, pipeline_profile_id,
    product_id, plus at least one of intent_id/trigger_id/fee_id/invoice_id (spec 52)."""
    eng = _engine()
    q = eng.subscribe()
    await eng._run_one_tick(next_day_mode=True)
    events = await _drain(q)
    pipeline_event_types = {
        "transaction_intent_event", "fee_accrual_event", "value_transfer_event",
        "posting_entry_event", "invoice_transaction_event", "settlement_resolution_event",
    }
    for ev in events:
        if ev["event"] not in pipeline_event_types:
            continue
        d = ev["data"]
        assert "tick_id" in d
        assert "simulation_date" in d
        assert "pipeline_profile_id" in d
        assert "product_id" in d
        assert any(k in d for k in ("intent_id", "trigger_id", "fee_id", "invoice_id")), (
            f"event {ev['event']} missing correlation key: {d}"
        )


@pytest.mark.asyncio
async def test_invoice_emitted_on_due_date_with_direct_payment_settlement():
    """Run one tick to accrue fees with next_month_day_plus_x offset 5; advance
    until the fee's due date and confirm invoice + settlement events fire."""
    eng = _engine()
    q = eng.subscribe()
    # Tick 1: accrue scheme + processor fees with due_date = 2026-02-06.
    await eng._run_one_tick(next_day_mode=True)
    accrual_events = await _drain(q)
    fees = [e["data"] for e in accrual_events if e["event"] == "fee_accrual_event"]
    assert fees, "expected fee accruals on tick 1"
    due_date = fees[0]["settlement_due_date"]
    assert due_date == "2026-02-06"

    # Advance until simulation_date hits the due date.
    while eng.simulation_date.isoformat() < due_date:
        await eng._run_one_tick(next_day_mode=True)
    # Drain everything emitted across ticks 2..N including the due-date tick.
    later_events = await _drain(q)
    types = [e["event"] for e in later_events]
    assert "invoice_transaction_event" in types
    assert "settlement_resolution_event" in types
    settlement = next(e["data"] for e in later_events
                      if e["event"] == "settlement_resolution_event")
    # ADR-0002: netting deferred; only direct payment.
    assert settlement["mode"] == "paid"
    assert settlement["final_status"] == "paid"


@pytest.mark.asyncio
async def test_pipeline_money_object_payloads():
    """All amount-bearing pipeline payloads must be money objects {amount, currency}
    when money.enforce_money_object=True (critical contract decision #1)."""
    eng = _engine()
    q = eng.subscribe()
    await eng._run_one_tick(next_day_mode=True)
    events = await _drain(q)
    intents = [e["data"] for e in events if e["event"] == "transaction_intent_event"]
    assert intents and isinstance(intents[0]["amount"], dict)
    assert intents[0]["amount"]["currency"] == "USD"
    fees = [e["data"] for e in events if e["event"] == "fee_accrual_event"]
    assert fees and isinstance(fees[0]["fee_amount"], dict)


# ---------------------------------------------------------------- determinism

@pytest.mark.asyncio
async def test_pipeline_determinism_same_seed_same_events():
    """Two engines built from the same fixture must emit identical pipeline events."""
    async def run(eng) -> list[tuple]:
        q = eng.subscribe()
        for _ in range(3):
            await eng._run_one_tick(next_day_mode=True)
        events = await _drain(q)
        # Collapse to (type, key fields) signatures so timestamps in tick_committed
        # don't break equality.
        sig: list[tuple] = []
        for e in events:
            t = e["event"]
            d = e["data"]
            if t in ("transaction_intent_event", "fee_accrual_event",
                     "posting_entry_event", "value_transfer_event"):
                sig.append((t, d.get("tick_id"), d.get("intent_id") or d.get("fee_id") or d.get("posting_id") or d.get("transfer_id"),
                            str(d.get("amount") or d.get("fee_amount"))))
        return sig

    a = await run(_engine())
    b = await run(_engine())
    assert a == b, "deterministic pipeline must emit identical event signatures"


# ---------------------------------------------------------------- v2_foundations gating

@pytest.mark.asyncio
async def test_v2_foundations_schema_skips_runtime(tmp_path):
    """When pipeline_schema_version=v2_foundations the executor MUST be inert,
    even if every product binds a profile (ADR-0002 gating)."""
    data = _yaml_data()
    data["pipeline"]["pipeline_schema_version"] = "v2_foundations"
    cfg, _ = load_config(_write_tmp(tmp_path, data))
    eng = SimulationEngine(cfg, config_path=FIXTURE)
    eng.state_from_idle()
    q = eng.subscribe()
    await eng._run_one_tick(next_day_mode=True)
    events = await _drain(q)
    pipeline_types = {
        "transaction_intent_event", "fee_accrual_event", "value_transfer_event",
        "posting_entry_event", "invoice_transaction_event", "settlement_resolution_event",
    }
    emitted = [e["event"] for e in events if e["event"] in pipeline_types]
    assert emitted == [], f"v2_foundations must skip runtime; emitted: {emitted}"


# ---------------------------------------------------------------- SinkProduct contract

@pytest.mark.asyncio
async def test_sink_product_rejects_pop_origin_traffic():
    """SinkProduct.transact_product (pop-origin) returns SINK_PRODUCT_NO_POP_TRAFFIC
    and accumulates no counters from pop traffic (spec 31 §SinkProduct)."""
    import random
    from engine.agents.product import SinkProduct
    from engine.config.models import ProductConfig
    cfg = ProductConfig(
        product_id="sink",
        product_label="Sink",
        product_class="SinkProduct",
    )
    sink = SinkProduct(cfg, owner_vendor_id="v", accepting_onboard=True, accepting_transact=True)
    res = sink.transact_product("pop", 100, 100, 1000, random.Random(0))
    assert res.reason_code == "SINK_PRODUCT_NO_POP_TRAFFIC"
    assert res.successful_txn_count == 0
    assert sink.successful_transact_count == 0


# ---------------------------------------------------------------- SQLite store

@pytest.mark.asyncio
async def test_pipeline_sqlite_store_records_events():
    """Pipeline events must land in the engine's SQLite observability store."""
    eng = _engine()
    await eng._run_one_tick(next_day_mode=True)
    store = eng._pipeline_store
    assert store is not None
    intents = store.list("intents")
    fees = store.list("fees")
    postings = store.list("postings")
    transfers = store.list("transfers")
    assert intents, "intents table should have rows"
    assert fees, "fees table should have rows"
    assert postings, "postings table should have rows"
    assert transfers, "transfers table should have rows"
