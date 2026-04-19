"""Engine tests: determinism, intake timing, agent boundary, control-plane (pause freeze, reload, shutdown)."""

import asyncio
import copy
from pathlib import Path

import pytest

from engine.config.loader import load_config
from engine.simulation.engine import ControlCommand, EngineState, SimulationEngine

VALID = Path(__file__).parent.parent / "configs" / "prototype_v0.yaml"


def make_engine(config_path: Path | None = None) -> SimulationEngine:
    path = config_path or VALID
    cfg, _ = load_config(path)
    engine = SimulationEngine(cfg, config_path=path)
    engine.state_from_idle()
    return engine


async def drain_events(q: asyncio.Queue, timeout: float = 0.1) -> list[dict]:
    """Drain currently queued events without blocking for new ones."""
    events = []
    while True:
        try:
            ev = await asyncio.wait_for(q.get(), timeout=timeout)
            events.append(ev)
        except asyncio.TimeoutError:
            break
    return events


# ------------------------------------------------------------------ helpers

async def run_tick_no_intake(engine: SimulationEngine) -> dict:
    """Run one tick in next_day mode, return snapshot after commit."""
    events = []
    q = engine.subscribe()

    async def collect():
        while True:
            ev = await asyncio.wait_for(q.get(), timeout=2.0)
            events.append(ev)
            if ev["event"] == "state_snapshot":
                break

    await asyncio.gather(
        engine._run_one_tick(next_day_mode=True),
        collect(),
    )
    engine.unsubscribe(q)
    return engine.build_snapshot()


# ------------------------------------------------------------------ determinism

@pytest.mark.asyncio
async def test_determinism_no_commands():
    """Same seed + no commands → identical outcomes across two fresh engines."""
    engine_a = make_engine()
    engine_b = make_engine()

    snap_a = await run_tick_no_intake(engine_a)
    snap_b = await run_tick_no_intake(engine_b)

    # Pop onboarded counts must match
    for pop_id in snap_a["pops"]:
        for link_a, link_b in zip(
            snap_a["pops"][pop_id]["product_links"],
            snap_b["pops"][pop_id]["product_links"],
        ):
            assert link_a["onboarded_count"] == link_b["onboarded_count"]

    # Vendor product counters must match
    for vid in snap_a["vendors"]:
        for pid in snap_a["vendors"][vid]["products"]:
            pa = snap_a["vendors"][vid]["products"][pid]
            pb = snap_b["vendors"][vid]["products"][pid]
            assert pa["onboarded_pop_count"] == pb["onboarded_pop_count"]
            assert pa["successful_transact_count"] == pb["successful_transact_count"]


@pytest.mark.asyncio
async def test_determinism_with_commands():
    """Same seed + same command sequence → identical outcomes."""
    cmd = ControlCommand(
        command_id="det-test-1",
        command_type="CloseOnboarding",
        vendor_id="vendor_alpha",
        product_id="prod_prepaid_alpha",
    )

    async def run_with_cmd(engine: SimulationEngine) -> dict:
        # Submit command before intake (goes to pending → applied in tick)
        await engine.submit_command(cmd)
        return await run_tick_no_intake(engine)

    engine_a = make_engine()
    engine_b = make_engine()

    snap_a = await run_with_cmd(engine_a)
    snap_b = await run_with_cmd(engine_b)

    for vid in snap_a["vendors"]:
        for pid in snap_a["vendors"][vid]["products"]:
            pa = snap_a["vendors"][vid]["products"][pid]
            pb = snap_b["vendors"][vid]["products"][pid]
            assert pa["accepting_onboard"] == pb["accepting_onboard"]
            assert pa["onboarded_pop_count"] == pb["onboarded_pop_count"]


# ------------------------------------------------------------------ intake timing / scenario A + B

@pytest.mark.asyncio
async def test_scenario_a_command_in_intake_applies_same_tick():
    """Scenario A: command submitted before intake close applies in tick T."""
    engine = make_engine()

    # Submit CloseOnboarding before intake opens (goes to pending → moved to current on open)
    cmd = ControlCommand(
        command_id="close-ob-before",
        command_type="CloseOnboarding",
        vendor_id="vendor_alpha",
        product_id="prod_prepaid_alpha",
    )
    await engine.submit_command(cmd)

    snap = await run_tick_no_intake(engine)

    # accepting_onboard must be False after this tick
    product = snap["vendors"]["vendor_alpha"]["products"]["prod_prepaid_alpha"]
    assert product["accepting_onboard"] is False

    # No onboarding should have been accepted (gate was closed before simulation ran)
    outcomes = snap["recent_outcomes"]
    onboard_outcomes = [o for o in outcomes if o["action_type"] == "Onboard"]
    for o in onboard_outcomes:
        assert o["accepted_pop_count"] == 0, "Expected 0 accepted (gate closed in same tick)"


@pytest.mark.asyncio
async def test_scenario_b_command_after_intake_close_applies_next_tick():
    """Scenario B: command after intake close has no effect in T, takes effect in T+1."""
    engine = make_engine()

    # Run tick 1 with onboarding open → some pops onboard
    snap_t1 = await run_tick_no_intake(engine)
    assert snap_t1["tick_id"] == 1
    onboarded_t1 = (
        snap_t1["vendors"]["vendor_alpha"]["products"]["prod_prepaid_alpha"]["onboarded_pop_count"]
    )
    assert onboarded_t1 > 0, "Expected some onboarding in tick 1"

    # Simulate 'after intake close': directly put command in pending (intake is closed between ticks)
    cmd = ControlCommand(
        command_id="close-ob-after",
        command_type="CloseOnboarding",
        vendor_id="vendor_alpha",
        product_id="prod_prepaid_alpha",
    )
    # Intake is currently closed (between ticks) — submit goes to pending
    assert not engine._intake_open
    await engine.submit_command(cmd)  # → pending queue

    # Tick 2: command should apply in T2's intake → gate closes BEFORE simulation
    snap_t2 = await run_tick_no_intake(engine)
    assert snap_t2["tick_id"] == 2
    product_t2 = snap_t2["vendors"]["vendor_alpha"]["products"]["prod_prepaid_alpha"]
    assert product_t2["accepting_onboard"] is False

    # onboarded count should not increase in tick 2 vs tick 1 (gate closed in T2 intake)
    onboarded_t2 = product_t2["onboarded_pop_count"]
    assert onboarded_t2 == onboarded_t1, (
        f"No new onboarding expected in T2 (gate closed). T1={onboarded_t1}, T2={onboarded_t2}"
    )


# ------------------------------------------------------------------ agent boundary (Scenario C)

@pytest.mark.asyncio
async def test_scenario_c_api_does_not_bypass_agent_loop():
    """Scenario C: API command only mutates control state, not execution path."""
    engine = make_engine()

    # Submit OpenOnboarding (gate already open by default, but this proves API path)
    cmd = ControlCommand(
        command_id="open-ob-api",
        command_type="OpenOnboarding",
        vendor_id="vendor_alpha",
        product_id="prod_prepaid_alpha",
    )
    ack = await engine.submit_command(cmd)
    assert ack.accepted is True

    # Product counters must be untouched — no execution happened
    product = engine.model.vendors["vendor_alpha"].products["prod_prepaid_alpha"]
    assert product.onboarded_pop_count == 0, "API command must not execute agent actions"
    assert product.successful_transact_count == 0


# ------------------------------------------------------------------ basic tick sequence

@pytest.mark.asyncio
async def test_onboarded_count_never_exceeds_pop_count():
    """Stock-flow cap (spec 31-agents §pops, spec 40 §pops): onboarded_count
    must stay <= pop_count at runtime, not just at config load. Regression
    against the bug where 541 ticks of 3% onboard against pop=10000 produced
    150k onboarded customers.
    """
    engine = make_engine()
    pop = engine.model.pops["pop_main"]
    cap = float(pop.pop_count)
    for _ in range(50):  # >> 1/daily_onboard so saturation is reached
        await engine._run_one_tick(next_day_mode=True)
    snap = engine.build_snapshot()
    p = snap["vendors"]["vendor_alpha"]["products"]["prod_prepaid_alpha"]
    assert p["onboarded_pop_count"] <= int(cap), (
        f"onboarded_pop_count={p['onboarded_pop_count']} exceeds pop_count cap={int(cap)}"
    )
    for pop_snap in snap["pops"].values():
        for link in pop_snap["product_links"]:
            assert link["onboarded_count"] <= int(cap), (
                f"link onboarded_count={link['onboarded_count']} exceeds pop_count cap={int(cap)}"
            )


@pytest.mark.asyncio
async def test_onboard_then_transact_ordering():
    """Onboard runs before Transact within the same tick.

    Proof: pop starts at 0 onboarded. In tick 1, Onboard runs first and
    updates onboarded_count. Transact then sees that stock and produces
    successful transactions. If the order were reversed, tick-1 transact
    would be empty (no stock yet).
    """
    engine = make_engine()

    snap1 = await run_tick_no_intake(engine)
    t1_outcomes = snap1["recent_outcomes"]

    t1_onboard = [o for o in t1_outcomes if o["action_type"] == "Onboard"]
    t1_transact = [o for o in t1_outcomes if o["action_type"] == "Transact"]

    # Onboard must have run and accepted some stock
    assert any(o["accepted_pop_count"] > 0 for o in t1_onboard), "Expected onboard in tick 1"

    # Because Onboard ran first, Transact in the same tick sees stock > 0
    assert any(o["successful_txn_count"] > 0 for o in t1_transact), (
        "Expected transact in tick 1 (Onboard runs first so stock is available)"
    )


# ------------------------------------------------------------------ command_ack envelope (51-api-contract)

@pytest.mark.asyncio
async def test_command_ack_envelope_uses_target_tick():
    """CommandAck exposes target_tick and processed_in_tick per 51-api-contract."""
    engine = make_engine()
    cmd = ControlCommand(
        command_id="ack-shape",
        command_type="OpenOnboarding",
        vendor_id="vendor_alpha",
        product_id="prod_prepaid_alpha",
    )
    ack = await engine.submit_command(cmd)
    assert ack.command_id == "ack-shape"
    assert ack.accepted is True
    assert ack.target_tick == engine.tick_id + 1
    assert ack.processed_in_tick is None  # not yet processed
    assert ack.rejection_reason is None
    # Must NOT carry the old field name
    assert not hasattr(ack, "effective_tick"), "effective_tick was renamed to target_tick"


# ------------------------------------------------------------------ run_mode property (51-api-contract)

def test_run_mode_states():
    """run_mode reflects engine state + pause-pending + intake-frozen flags."""
    engine = make_engine()
    assert engine.run_mode == "paused"  # state_from_idle moved IDLE → PAUSED

    engine.state = EngineState.RUNNING
    assert engine.run_mode == "running"

    engine._pause_requested = True
    assert engine.run_mode == "pause_pending"

    engine._pause_requested = False
    engine._intake_frozen = True
    assert engine.run_mode == "pause_pending"

    engine._intake_frozen = False
    engine.state = EngineState.RESTARTING
    assert engine.run_mode == "restarting"


# ------------------------------------------------------------------ intake freeze on pause-during-intake (51, 52)

@pytest.mark.asyncio
async def test_pause_during_intake_freezes_countdown():
    """Pause while intake is open emits intake_countdown_paused; resume emits intake_countdown_resumed."""
    cfg, _ = load_config(VALID)
    cfg.simulation.intake_window_ms = 500   # short but observable
    cfg.simulation.tick_wall_clock_base_ms = 0
    engine = SimulationEngine(cfg, config_path=VALID)
    engine.state_from_idle()
    q = engine.subscribe()

    # Drive a real continuous tick so _intake_wait runs
    engine.state = EngineState.RUNNING
    tick_task = asyncio.create_task(engine._run_one_tick(next_day_mode=False))

    # Wait until intake is open
    deadline = asyncio.get_event_loop().time() + 1.0
    while not engine._intake_open and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.01)
    assert engine._intake_open

    # Pause while intake is open → freeze pending
    pause_result = await engine.pause()
    assert pause_result["effect"] == "freeze_intake_pending"
    assert pause_result["run_mode"] == "pause_pending"

    # Wait for the freeze to actually emit (poll cycle is 100ms)
    await asyncio.sleep(0.25)
    assert engine._intake_frozen

    # Resume → unfreeze
    resume_result = await engine.resume()
    assert resume_result["effect"] == "resumed_from_pause_pending"
    assert resume_result["run_mode"] == "running"

    await asyncio.wait_for(tick_task, timeout=2.0)

    events = await drain_events(q)
    types = [e["event"] for e in events]
    assert "tick_intake_window_opened" in types
    assert "intake_countdown_paused" in types
    assert "intake_countdown_resumed" in types
    assert "tick_intake_window_closed" in types
    assert "tick_committed" in types

    # Ordering: opened → paused → resumed → closed → committed
    idx = {t: types.index(t) for t in (
        "tick_intake_window_opened",
        "intake_countdown_paused",
        "intake_countdown_resumed",
        "tick_intake_window_closed",
        "tick_committed",
    )}
    assert (
        idx["tick_intake_window_opened"]
        < idx["intake_countdown_paused"]
        < idx["intake_countdown_resumed"]
        < idx["tick_intake_window_closed"]
        < idx["tick_committed"]
    )

    # intake_countdown_paused payload must include remaining_ms
    paused_evt = next(e for e in events if e["event"] == "intake_countdown_paused")
    assert isinstance(paused_evt["data"].get("remaining_ms"), int)
    assert paused_evt["data"]["remaining_ms"] > 0


# ------------------------------------------------------------------ pause-after-intake-close (51)

@pytest.mark.asyncio
async def test_pause_after_intake_close_pauses_after_commit():
    """Pause requested after intake closed pauses after current tick commits, not mid-tick."""
    engine = make_engine()
    engine.state = EngineState.RUNNING
    # Intake is closed (tick not started yet)
    assert not engine._intake_open

    pause_result = await engine.pause()
    assert pause_result["effect"] == "pause_after_tick_commit"
    assert pause_result["run_mode"] == "pause_pending"
    assert engine._pause_requested is True


# ------------------------------------------------------------------ snapshot includes new fields (51, 52)

@pytest.mark.asyncio
async def test_snapshot_includes_run_mode_and_world_generation():
    engine = make_engine()
    snap = engine.build_snapshot()
    assert snap["run_mode"] == "paused"
    assert snap["world_generation"] == 0
    assert snap["intake_frozen"] is False
    assert snap["intake_remaining_ms"] is None
    assert "config" in snap and "intake_window_ms" in snap["config"]


# ------------------------------------------------------------------ reload_config success (51, 52)

@pytest.mark.asyncio
async def test_reload_config_success_emits_lifecycle():
    """Reload from PAUSED replaces world, bumps generation, emits world_restarting + world_restarted."""
    engine = make_engine()
    q = engine.subscribe()

    # Advance one tick so we have non-trivial state to reset
    await engine._run_one_tick(next_day_mode=True)
    assert engine.tick_id == 1
    pre_gen = engine._world_generation

    result = await engine.reload_config()
    assert result["accepted"] is True
    assert result["reloaded"] is True
    assert result["world_generation"] == pre_gen + 1
    assert result["run_mode"] == "paused"

    # World should be reset
    assert engine.tick_id == 0
    assert engine.state == EngineState.PAUSED

    events = await drain_events(q)
    types = [e["event"] for e in events]
    assert "world_restarting" in types
    assert "world_restarted" in types
    restarting_idx = types.index("world_restarting")
    restarted_idx = types.index("world_restarted")
    assert restarting_idx < restarted_idx


@pytest.mark.asyncio
async def test_reload_config_validation_failure_keeps_world():
    """Reload with invalid YAML must keep current world running and surface error_codes."""
    engine = make_engine()
    # Point at an invalid config file
    engine.config_path = Path(__file__).parent.parent / "configs" / "invalid_scenario_id.yaml"
    pre_gen = engine._world_generation
    pre_tick = engine.tick_id

    result = await engine.reload_config()
    assert result["accepted"] is False
    assert result["reloaded"] is False
    assert "E_SCENARIO_ID_UNSUPPORTED" in result.get("error_codes", [])
    assert engine._world_generation == pre_gen  # unchanged on failure
    assert engine.tick_id == pre_tick
    assert engine.state == EngineState.PAUSED  # restored


@pytest.mark.asyncio
async def test_reload_config_works_from_running_state():
    """Reload while continuous loop is active: cancels loop, replaces world, ends PAUSED."""
    cfg, _ = load_config(VALID)
    cfg.simulation.intake_window_ms = 500
    cfg.simulation.tick_wall_clock_base_ms = 0
    engine = SimulationEngine(cfg, config_path=VALID)
    engine.state_from_idle()

    # Start continuous loop
    await engine.resume()
    assert engine.state == EngineState.RUNNING
    await asyncio.sleep(0.05)  # let the loop get to the intake wait

    result = await engine.reload_config()
    assert result["accepted"] is True
    assert result["reloaded"] is True
    assert engine.state == EngineState.PAUSED
    assert engine.tick_id == 0
    # Continuous task should be torn down
    assert engine._continuous_task is None or engine._continuous_task.done()


# ------------------------------------------------------------------ server_shutdown event (52)

@pytest.mark.asyncio
async def test_shutdown_emits_server_shutdown_event():
    engine = make_engine()
    q = engine.subscribe()
    await engine.shutdown(reason="test_shutdown",
                          grace_period_ms=10,
                          reconnect_after_ms=500,
                          will_restart=False)
    events = await drain_events(q)
    shutdown_evts = [e for e in events if e["event"] == "server_shutdown"]
    assert len(shutdown_evts) == 1
    payload = shutdown_evts[0]["data"]
    assert payload["reason"] == "test_shutdown"
    assert payload["grace_period_ms"] == 10
    assert payload["reconnect_after_ms"] == 500
    assert payload["will_restart"] is False


@pytest.mark.asyncio
async def test_shutdown_transitions_to_shutting_down_run_mode():
    """After shutdown(), engine state is SHUTTING_DOWN and run_mode == 'shutting_down' (51-api-contract)."""
    engine = make_engine()
    await engine.shutdown(reason="test", grace_period_ms=10, reconnect_after_ms=100)
    assert engine.state == EngineState.SHUTTING_DOWN
    assert engine.run_mode == "shutting_down"


@pytest.mark.asyncio
async def test_tick_committed_includes_inter_tick_wait_ms():
    """tick_committed carries the server-computed inter-tick wait so the TUI
    doesn't have to sum intake + post-commit itself (40-yaml-config). The
    emitted value is the remainder of tick_wall_clock_base_ms after elapsed."""
    cfg, _ = load_config(VALID)
    cfg.simulation.intake_window_ms = 100
    cfg.simulation.tick_wall_clock_base_ms = 1000  # 1s total, 100ms intake
    engine = SimulationEngine(cfg, config_path=VALID)
    engine.state_from_idle()
    q = engine.subscribe()

    engine.state = EngineState.RUNNING
    await engine._run_one_tick(next_day_mode=False)

    events = await drain_events(q)
    committed = next(e for e in events if e["event"] == "tick_committed")
    wait_ms = committed["data"]["inter_tick_wait_ms"]
    # Intake ran ~100ms, sim ~0ms → remaining should be close to 900ms
    # (allow generous envelope for timing jitter on slow CI machines)
    assert 700 <= wait_ms <= 1000, (
        f"inter_tick_wait_ms should be close to base - intake (~900ms), got {wait_ms}"
    )


@pytest.mark.asyncio
async def test_action_outcome_counts_are_integers():
    """Counts in emitted action_outcome must be int per spec 40/51/52 numeric typing."""
    engine = make_engine()
    q = engine.subscribe()
    await engine._run_one_tick(next_day_mode=True)
    events = await drain_events(q)
    outcomes = [e for e in events if e["event"] == "action_outcome"]
    assert outcomes, "expected at least one action_outcome"
    for evt in outcomes:
        d = evt["data"]
        for field in ("accepted_pop_count", "rejected_pop_count",
                      "successful_txn_count", "failed_txn_count"):
            v = d[field]
            assert isinstance(v, int), (
                f"{field} must be int per spec 40 §numeric typing, got {type(v).__name__}={v!r}"
            )


@pytest.mark.asyncio
async def test_snapshot_counts_are_integers():
    """Snapshot vendor/product/pop counts must be int per spec 40 §numeric typing."""
    engine = make_engine()
    await engine._run_one_tick(next_day_mode=True)
    snap = engine.build_snapshot()
    for vid, v in snap["vendors"].items():
        for pid, p in v["products"].items():
            assert isinstance(p["onboarded_pop_count"], int), (
                f"product.onboarded_pop_count must be int, got {type(p['onboarded_pop_count']).__name__}"
            )
            assert isinstance(p["successful_transact_count"], int)
    for pid, pop in snap["pops"].items():
        assert isinstance(pop["pop_count"], int)
        for link in pop["product_links"]:
            assert isinstance(link["onboarded_count"], int)


@pytest.mark.asyncio
async def test_tick_summary_counts_are_integers():
    """tick_committed summary fields (onboard/transact requested/accepted/succeeded/failed)
    must be integers per spec 40."""
    engine = make_engine()
    q = engine.subscribe()
    await engine._run_one_tick(next_day_mode=True)
    events = await drain_events(q)
    committed = next(e for e in events if e["event"] == "tick_committed")
    d = committed["data"]
    for field in ("onboard_requested", "onboard_accepted", "onboard_rejected",
                  "transact_requested", "transact_succeeded", "transact_failed"):
        assert isinstance(d[field], int), (
            f"{field} must be int, got {type(d[field]).__name__}={d[field]!r}"
        )
    # transact_amount remains numeric (float) with configured scale
    assert isinstance(d["transact_amount"], (int, float))


@pytest.mark.asyncio
async def test_inter_tick_wait_is_zero_when_no_pacing():
    """When tick_wall_clock_base_ms=0, inter_tick_wait_ms must be 0 (no pacing)."""
    cfg, _ = load_config(VALID)
    cfg.simulation.intake_window_ms = 100
    cfg.simulation.tick_wall_clock_base_ms = 0
    engine = SimulationEngine(cfg, config_path=VALID)
    engine.state_from_idle()
    q = engine.subscribe()
    await engine._run_one_tick(next_day_mode=True)

    events = await drain_events(q)
    committed = next(e for e in events if e["event"] == "tick_committed")
    assert committed["data"]["inter_tick_wait_ms"] == 0


@pytest.mark.asyncio
async def test_shutdown_cancels_running_continuous_loop():
    """shutdown() while running cancels the in-flight tick loop cleanly."""
    cfg, _ = load_config(VALID)
    cfg.simulation.intake_window_ms = 500
    cfg.simulation.tick_wall_clock_base_ms = 0
    engine = SimulationEngine(cfg, config_path=VALID)
    engine.state_from_idle()
    await engine.resume()
    await asyncio.sleep(0.05)  # let intake wait start

    await engine.shutdown(reason="test_cancel", grace_period_ms=10, reconnect_after_ms=100)
    assert engine.state == EngineState.SHUTTING_DOWN
    assert engine._continuous_task is None or engine._continuous_task.done()
