"""SimulationEngine — async orchestrator wrapping PaymentsMogulModel.

Responsibilities (51-api-contract, 52-realtime-ui-protocol):
- intake window with freeze/unfreeze on pause-during-intake
- pause-after-commit semantics for pause-after-intake-close
- config reload + world restart with world_restarting/world_restarted events
- server_shutdown emit before SSE stream termination
- SSE event broadcast to subscribers

All simulation logic lives in PaymentsMogulModel.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from engine.agents.pop import ActionOutcome
from engine.config.loader import ConfigValidationError, load_config
from engine.config.models import PrototypeConfig
from engine.numeric import round_amount, round_count
from engine.simulation.model import PaymentsMogulModel


class EngineState(str, Enum):
    IDLE = "idle"
    PAUSED = "paused"
    RUNNING = "running"
    RESTARTING = "restarting"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class ControlCommand:
    command_id: str
    command_type: str   # OpenOnboarding | CloseOnboarding | OpenTransacting | CloseTransacting
    vendor_id: str
    product_id: str
    received_at: float = field(default_factory=time.monotonic)


@dataclass
class CommandAck:
    command_id: str
    accepted: bool
    target_tick: int | None
    processed_in_tick: int | None
    rejection_reason: str | None


class SimulationEngine:
    def __init__(self, cfg: PrototypeConfig, config_path: Path | None = None) -> None:
        self.cfg = cfg
        self.config_path = config_path
        self.model = PaymentsMogulModel(cfg)
        self.state: EngineState = EngineState.IDLE
        self._intake_open: bool = False
        self._intake_frozen: bool = False
        self._intake_remaining_ms: int = 0
        self._pending: list[ControlCommand] = []
        self._current: list[ControlCommand] = []
        self._intake_lock = asyncio.Lock()
        self._pause_requested: bool = False
        self._resume_event: asyncio.Event = asyncio.Event()
        self._next_day_event: asyncio.Event = asyncio.Event()
        self._subscribers: list[asyncio.Queue] = []
        self._recent_outcomes: list[dict] = []
        self._max_recent = 50
        self._world_generation: int = 0
        # Task handles (so reload/shutdown can cancel them cleanly)
        self._continuous_task: asyncio.Task | None = None
        self._next_day_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ properties

    @property
    def tick_id(self) -> int:
        return self.model.steps

    @property
    def run_mode(self) -> str:
        """UI-facing run mode (51-api-contract): running | pause_pending | paused | restarting | shutting_down | idle."""
        if self.state == EngineState.SHUTTING_DOWN:
            return "shutting_down"
        if self.state == EngineState.RESTARTING:
            return "restarting"
        if self.state == EngineState.PAUSED:
            return "paused"
        if self.state == EngineState.RUNNING:
            if self._pause_requested or self._intake_frozen:
                return "pause_pending"
            return "running"
        return "idle"

    # ------------------------------------------------------------------ SSE

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def _emit(self, event_type: str, data: dict) -> None:
        envelope = {"event": event_type, "data": data}
        for q in list(self._subscribers):
            await q.put(envelope)

    # ------------------------------------------------------------------ control API

    def state_from_idle(self) -> None:
        if self.state == EngineState.IDLE:
            self.state = EngineState.PAUSED

    async def resume(self) -> dict:
        """Resume continuous play, or unfreeze intake countdown if currently frozen.

        Returns control-plane status dict per 51-api-contract:
        accepted, effect (immediate | resumed_from_pause_pending | cancelled_pause_pending | noop),
        run_mode.
        """
        if self._intake_frozen:
            self._pause_requested = False
            self._resume_event.set()
            return {"accepted": True, "effect": "resumed_from_pause_pending", "run_mode": "running"}
        if self.state == EngineState.RUNNING and self._pause_requested:
            self._pause_requested = False
            return {"accepted": True, "effect": "cancelled_pause_pending", "run_mode": "running"}
        if self.state in (EngineState.IDLE, EngineState.PAUSED):
            self._pause_requested = False
            self.state = EngineState.RUNNING
            self._continuous_task = asyncio.get_event_loop().create_task(self._run_continuous())
            return {"accepted": True, "effect": "immediate", "run_mode": "running"}
        return {"accepted": True, "effect": "noop", "run_mode": self.run_mode}

    async def pause(self) -> dict:
        """Request pause. Freezes intake countdown if intake is open;
        otherwise pauses after current tick commits.

        Returns control-plane status dict per 51-api-contract:
        accepted, effect (freeze_intake_pending | pause_after_tick_commit | noop), run_mode.
        """
        if self.state in (EngineState.PAUSED, EngineState.IDLE):
            return {"accepted": True, "effect": "noop", "run_mode": self.run_mode}
        if self._intake_frozen:
            return {"accepted": True, "effect": "noop", "run_mode": self.run_mode}

        self._pause_requested = True

        if self._intake_open:
            # _intake_wait poll will detect this and emit intake_countdown_paused
            return {"accepted": True, "effect": "freeze_intake_pending", "run_mode": "pause_pending"}
        await self._emit("pause_requested", {
            "tick_id": self.tick_id + 1,
            "freeze_intake": False,
        })
        return {"accepted": True, "effect": "pause_after_tick_commit", "run_mode": "pause_pending"}

    async def next_day(self) -> dict:
        """Advance one tick from PAUSED state. Returns control-plane status dict."""
        if self.state == EngineState.IDLE:
            self.state = EngineState.PAUSED
        if self.state != EngineState.PAUSED:
            return {
                "accepted": False,
                "effect": "rejected",
                "run_mode": self.run_mode,
                "rejection_reason": "next_day_requires_paused_state",
            }
        self._next_day_event.set()
        return {"accepted": True, "effect": "advance_one_tick", "run_mode": "paused"}

    async def submit_command(self, cmd: ControlCommand) -> CommandAck:
        async with self._intake_lock:
            if self._intake_open:
                self._current.append(cmd)
            else:
                self._pending.append(cmd)
            target_tick = self.tick_id + 1
        ack = CommandAck(
            command_id=cmd.command_id,
            accepted=True,
            target_tick=target_tick,
            processed_in_tick=None,
            rejection_reason=None,
        )
        await self._emit("command_ack", {
            "command_id": ack.command_id,
            "accepted": ack.accepted,
            "target_tick": ack.target_tick,
            "processed_in_tick": ack.processed_in_tick,
            "rejection_reason": ack.rejection_reason,
        })
        return ack

    # ------------------------------------------------------------------ config reload + world restart

    async def reload_config(self) -> dict:
        """Re-read YAML, validate, and replace world (51-api-contract).

        Works from any state: cancels any in-flight continuous tick loop, drains
        a frozen intake, then re-initializes the world and resets to PAUSED at tick 0.

        Returns structured result dict:
        accepted, reloaded, world_generation (on success), error_codes (on validation fail),
        rejection_reason, run_mode.
        """
        if self.config_path is None:
            return {"accepted": False, "reloaded": False,
                    "rejection_reason": "no_config_path_registered",
                    "run_mode": self.run_mode}

        prev_state = self.state
        self.state = EngineState.RESTARTING
        next_gen = self._world_generation + 1
        await self._emit("world_restarting", {
            "world_generation": next_gen,
            "reason": "reload_requested",
            "prev_run_mode": prev_state.value,
        })

        # Release any frozen intake waiter so the continuous loop can unwind
        if self._intake_frozen:
            self._resume_event.set()

        # Cancel an in-flight continuous tick loop if one is running
        if self._continuous_task is not None and not self._continuous_task.done():
            self._continuous_task.cancel()
            try:
                await self._continuous_task
            except (asyncio.CancelledError, Exception):
                pass
        self._continuous_task = None

        try:
            cfg, _warns = load_config(self.config_path)
        except ConfigValidationError as exc:
            # Restore prior state; world unchanged
            self.state = prev_state
            await self._emit("world_restart_failed", {
                "world_generation": next_gen,
                "error_codes": [exc.code],
                "rejection_reason": exc.message,
            })
            await self._emit("state_snapshot", self.build_snapshot())
            return {
                "accepted": False,
                "reloaded": False,
                "error_codes": [exc.code],
                "rejection_reason": exc.message,
                "run_mode": self.run_mode,
            }

        # Replace world; reset transient queues; baseline is PAUSED at tick 0
        self.cfg = cfg
        self.model = PaymentsMogulModel(cfg)
        self._intake_open = False
        self._intake_frozen = False
        self._intake_remaining_ms = 0
        self._pause_requested = False
        self._pending.clear()
        self._current.clear()
        self._recent_outcomes.clear()
        self._next_day_event.clear()
        self._world_generation = next_gen
        self.state = EngineState.PAUSED

        await self._emit("world_restarted", {
            "world_generation": self._world_generation,
            "tick_id": self.tick_id,
            "snapshot": self.build_snapshot(),
        })
        await self._emit("state_snapshot", self.build_snapshot())
        return {
            "accepted": True,
            "reloaded": True,
            "world_generation": self._world_generation,
            "run_mode": self.run_mode,
        }

    # ------------------------------------------------------------------ server shutdown

    async def shutdown(self,
                       reason: str = "manual_shutdown",
                       grace_period_ms: int = 1000,
                       reconnect_after_ms: int = 2000,
                       will_restart: bool = False) -> None:
        """Emit server_shutdown SSE event before stream termination (52-realtime-ui-protocol).

        Transitions engine state to SHUTTING_DOWN so subsequent control queries
        report run_mode="shutting_down" until the process exits.
        """
        # Cancel in-flight loops so they don't keep emitting after shutdown notice
        if self._intake_frozen:
            self._resume_event.set()
        if self._continuous_task is not None and not self._continuous_task.done():
            self._continuous_task.cancel()
            try:
                await self._continuous_task
            except (asyncio.CancelledError, Exception):
                pass
            self._continuous_task = None

        self.state = EngineState.SHUTTING_DOWN
        await self._emit("server_shutdown", {
            "reason": reason,
            "grace_period_ms": grace_period_ms,
            "reconnect_after_ms": reconnect_after_ms,
            "will_restart": will_restart,
        })
        # Brief grace period so SSE flushes to subscribers before the loop dies
        await asyncio.sleep(min(grace_period_ms, 1000) / 1000)

    # ------------------------------------------------------------------ tick loops

    async def _run_continuous(self) -> None:
        while self.state == EngineState.RUNNING:
            tick_start = time.monotonic()
            await self._run_one_tick(next_day_mode=False, tick_start_monotonic=tick_start)
            if self._pause_requested:
                self.state = EngineState.PAUSED
                self._pause_requested = False
                await self._emit("state_snapshot", self.build_snapshot())
                return
            # tick_wall_clock_base_ms is the TOTAL tick duration (40-yaml-config).
            # The intake window already consumed some of it; we wait for the
            # remainder, scaled by speed (speed=1× for now).
            base_ms = self.cfg.simulation.tick_wall_clock_base_ms
            if base_ms > 0:
                elapsed_ms = (time.monotonic() - tick_start) * 1000
                wait_ms = max(0.0, base_ms - elapsed_ms)
                if wait_ms > 0:
                    await asyncio.sleep(wait_ms / 1000)

    async def _run_next_day_loop(self) -> None:
        while True:
            await self._next_day_event.wait()
            self._next_day_event.clear()
            if self.state != EngineState.PAUSED:
                continue
            await self._run_one_tick(next_day_mode=True)

    async def start_next_day_loop(self) -> None:
        self._next_day_task = asyncio.get_event_loop().create_task(self._run_next_day_loop())

    # ------------------------------------------------------------------ core tick

    async def _intake_wait(self, intake_ms: int) -> None:
        """Wait `intake_ms` ms with freeze/unfreeze support (51, 52)."""
        remaining_ms = float(intake_ms)
        poll_ms = 100  # max latency from pause-press to freeze emission
        while remaining_ms > 0:
            if self._pause_requested and self._intake_open:
                self._intake_frozen = True
                self._intake_remaining_ms = int(remaining_ms)
                await self._emit("intake_countdown_paused", {
                    "tick_id": self.tick_id + 1,
                    "remaining_ms": int(remaining_ms),
                })
                self._resume_event.clear()
                await self._resume_event.wait()
                # resume() cleared _pause_requested before setting the event
                self._intake_frozen = False
                await self._emit("intake_countdown_resumed", {
                    "tick_id": self.tick_id + 1,
                    "remaining_ms": int(remaining_ms),
                })
                continue
            chunk_ms = min(remaining_ms, poll_ms)
            await asyncio.sleep(chunk_ms / 1000)
            remaining_ms -= chunk_ms

    async def _run_one_tick(self, next_day_mode: bool,
                            tick_start_monotonic: float | None = None) -> None:
        # tick_start anchors the entire wall-clock budget for this tick (40-yaml-config).
        # Inter-tick wait will be `tick_wall_clock_base_ms - (now - tick_start)`.
        if tick_start_monotonic is None:
            tick_start_monotonic = time.monotonic()

        # Phase 1: open intake window — move pending commands into current
        async with self._intake_lock:
            self._current.extend(self._pending)
            self._pending.clear()
            self._intake_open = True

        await self._emit("tick_intake_window_opened", {
            "tick_id": self.tick_id + 1,
            "intake_window_ms": self.cfg.simulation.intake_window_ms,
            "tick_wall_clock_base_ms": self.cfg.simulation.tick_wall_clock_base_ms,
        })

        if not next_day_mode:
            await self._intake_wait(self.cfg.simulation.intake_window_ms)

        # Phase 2: close intake window
        async with self._intake_lock:
            self._intake_open = False
            commands = list(self._current)
            self._current.clear()

        await self._emit("tick_intake_window_closed", {"tick_id": self.tick_id + 1})

        # Phase 3: apply control commands to agent state (tick_user_inputs_processed)
        for cmd in commands:
            self._apply_command(cmd)

        await self._emit("tick_user_inputs_processed", {
            "tick_id": self.tick_id + 1,
            "command_count": len(commands),
            "commands": [{"command_id": c.command_id,
                          "type": c.command_type,
                          "processed_in_tick": self.tick_id + 1} for c in commands],
        })

        # Phase 4: run Mesa model step — Onboard all agents, then Transact all agents
        # step() is void per Mesa contract; results accumulate in model._tick_outcomes
        self.model.step()
        outcomes: list[ActionOutcome] = self.model._tick_outcomes

        sim = self.cfg.simulation
        for o in outcomes:
            d = o.as_dict(
                count_mode=sim.count_rounding_mode,
                amount_scale_dp=sim.amount_scale_dp,
                amount_mode=sim.amount_rounding_mode,
            )
            self._recent_outcomes.append(d)
            await self._emit("action_outcome", d)

        if len(self._recent_outcomes) > self._max_recent:
            self._recent_outcomes = self._recent_outcomes[-self._max_recent:]

        # Phase 5: commit. Compute remaining inter-tick wait so the client can
        # render an accurate "next tick in N" countdown without doing its own
        # math (40-yaml-config: intake is part of the total tick budget).
        base_ms = self.cfg.simulation.tick_wall_clock_base_ms
        if base_ms > 0:
            elapsed_ms = (time.monotonic() - tick_start_monotonic) * 1000
            inter_tick_wait_ms = int(max(0, base_ms - elapsed_ms))
        else:
            inter_tick_wait_ms = 0

        summary = self._build_summary(outcomes)
        await self._emit("tick_committed", {
            "tick_id": self.tick_id,
            "committed_at": time.time(),
            "inter_tick_wait_ms": inter_tick_wait_ms,
            **summary,
        })
        await self._emit("state_snapshot", self.build_snapshot())

    def _apply_command(self, cmd: ControlCommand) -> None:
        vendor = self.model.vendors.get(cmd.vendor_id)
        if vendor is None:
            return
        product = vendor.products.get(cmd.product_id)
        if product is None:
            return
        dispatch = {
            "CloseOnboarding": product.close_onboarding,
            "OpenOnboarding": product.open_onboarding,
            "CloseTransacting": product.close_transacting,
            "OpenTransacting": product.open_transacting,
        }
        fn = dispatch.get(cmd.command_type)
        if fn:
            fn()

    def _build_summary(self, outcomes: list[ActionOutcome]) -> dict:
        onboard_req = onboard_acc = onboard_rej = 0.0
        transact_req = transact_ok = transact_fail = transact_amt = 0.0
        for o in outcomes:
            if o.action_type == "Onboard":
                onboard_req += o.accepted_pop_count + o.rejected_pop_count
                onboard_acc += o.accepted_pop_count
                onboard_rej += o.rejected_pop_count
            else:
                transact_req += o.successful_txn_count + o.failed_txn_count
                transact_ok += o.successful_txn_count
                transact_fail += o.failed_txn_count
                transact_amt += o.successful_total_amount
        sim = self.cfg.simulation
        cm = sim.count_rounding_mode
        return {
            "onboard_requested": round_count(onboard_req, cm),
            "onboard_accepted": round_count(onboard_acc, cm),
            "onboard_rejected": round_count(onboard_rej, cm),
            "transact_requested": round_count(transact_req, cm),
            "transact_succeeded": round_count(transact_ok, cm),
            "transact_failed": round_count(transact_fail, cm),
            "transact_amount": round_amount(transact_amt, sim.amount_scale_dp, sim.amount_rounding_mode),
        }

    def build_snapshot(self) -> dict:
        snap = self.model.snapshot()
        return {
            "tick_id": self.tick_id,
            "engine_state": self.state.value,
            "run_mode": self.run_mode,
            "intake_open": self._intake_open,
            "intake_frozen": self._intake_frozen,
            "intake_remaining_ms": self._intake_remaining_ms if self._intake_frozen else None,
            "world_generation": self._world_generation,
            "config": {
                "intake_window_ms": self.cfg.simulation.intake_window_ms,
                "tick_wall_clock_base_ms": self.cfg.simulation.tick_wall_clock_base_ms,
            },
            **snap,
            "recent_outcomes": list(self._recent_outcomes[-20:]),
        }
