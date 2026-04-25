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
from engine.calendars.registry import CalendarRegistry, RegionRegistry
from engine.config.loader import ConfigValidationError, load_config
from engine.config.models import PrototypeConfig
from engine.money import CurrencyCatalog
from engine.numeric import round_amount, round_count
from engine.pipeline.executor import PipelineExecutor, cfg_pipeline_runtime
from engine.pipeline.store import PipelineStore
from engine.scenario import ScenarioDates
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
    # Per spec 51 §Minimum command acknowledgement envelope: "world" | "agent".
    # Agent gate commands (OpenOnboarding etc.) are "agent" scope; control-plane
    # actions (reload, shutdown, pause, resume) are "world" scope and carry their
    # own response shape.
    command_scope: str = "agent"


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
        # Wall-clock speed multiplier (spec 51 §Speed / 52 §Set speed / 60
        # §Tick timing display contract). `>= 0.01` scalar; shrinks the full
        # tick wall-clock budget (intake + inter-tick processing wait).
        # Simulation math is unaffected — wall-clock only.
        self.speed_multiplier: float = 1.0
        # v2 foundations runtime context (spec 40 §scenario.start_date, §money,
        # §currency_catalog). Populated from optional config sections; in v0
        # configs these stay at sensible defaults.
        self._scenario_dates: ScenarioDates = ScenarioDates.from_config(
            cfg.scenario.start_date if cfg.scenario.start_date else None
        )
        self._currency_catalog: CurrencyCatalog | None = self._load_currency_catalog(cfg, config_path)
        self.money_object_mode: bool = bool(
            cfg.money is not None and cfg.money.enforce_money_object
        )
        self.default_currency: str | None = cfg.money.default_currency if cfg.money else None
        # v3_runtime pipeline executor (ADR-0002 gating). Calendar lookup wires
        # vendor.region_id -> calendar via the calendar/region registries.
        self._calendar_registry: CalendarRegistry | None = None
        self._region_registry: RegionRegistry | None = None
        if cfg.calendars:
            self._calendar_registry = CalendarRegistry.from_config(cfg)
            self._region_registry = RegionRegistry.from_config(cfg, self._calendar_registry)
        self._pending_pipeline_events: list[dict] = []
        self._pipeline_executor: PipelineExecutor | None = None
        self._pipeline_store: PipelineStore | None = None
        if cfg_pipeline_runtime(cfg):
            self._pipeline_store = PipelineStore(":memory:")
            self._pipeline_executor = PipelineExecutor(
                cfg=cfg,
                model=self.model,
                default_currency=self.default_currency or "USD",
                calendar_lookup=self._calendar_for_vendor,
                emit=self._buffer_pipeline_event,
            )

    def _calendar_for_vendor(self, vendor_id: str):
        """Resolve a vendor's calendar via region binding (spec 40)."""
        if self._region_registry is None:
            return None
        vendor = self.model.vendors.get(vendor_id)
        if vendor is None:
            return None
        # Vendor stored config carries region_id; agents copy it from cfg.
        region_id = getattr(vendor, "region_id", None)
        try:
            return self._region_registry.calendar_for_entity(region_id)
        except Exception:
            return None

    def _buffer_pipeline_event(self, event_type: str, data: dict) -> None:
        """Pipeline executor pushes here; engine drains to SSE after tick commit
        and persists to the SQLite observability store (ADR-0002)."""
        self._pending_pipeline_events.append({"event": event_type, "data": data})
        if self._pipeline_store is not None:
            self._pipeline_store.record(event_type, data)

    @staticmethod
    def _load_currency_catalog(cfg: PrototypeConfig,
                                config_path: Path | None) -> CurrencyCatalog | None:
        if cfg.currency_catalog is None:
            return None
        # Catalog path is relative to repo root or absolute. Resolve relative to
        # config_path's parent if config_path is set.
        path = Path(cfg.currency_catalog.local_file.path)
        if not path.is_absolute() and config_path is not None:
            # Try relative to repo root (parent of configs/) first since the spec's
            # example paths read like "configs/reference/...".
            candidates = [
                Path.cwd() / path,
                config_path.parent.parent / path if config_path.parent.name == "configs" else None,
            ]
            for c in candidates:
                if c is not None and c.exists():
                    path = c
                    break
        return CurrencyCatalog.from_file(path, fmt=cfg.currency_catalog.local_file.format)

    # ------------------------------------------------------------------ properties

    @property
    def tick_id(self) -> int:
        return self.model.steps

    @property
    def simulation_date(self):
        """Date for the current tick per spec 40 §scenario.start_date."""
        return self._scenario_dates.date_for_tick(self.tick_id)

    @property
    def scenario_start_date_resolved(self):
        """Resolved scenario start date (after `today` resolution)."""
        return self._scenario_dates.start_date

    # ---- v2 amount payload helpers ----
    # Spec 40/51/52 + critical contract decision #1: when money_object_mode is
    # active, all externally-visible amount-bearing fields must be money objects
    # `{amount, currency}`. v0 configs (no `money` section) keep scalar floats.

    def _amount_payload(self, amount):
        """Convert an internal scalar amount to the wire shape for this engine.

        v2 mode -> {"amount": "<scaled string>", "currency": "USD"}
        v0 mode -> rounded float (legacy)"""
        sim = self.cfg.simulation
        scaled = round_amount(float(amount or 0), sim.amount_scale_dp, sim.amount_rounding_mode)
        if self.money_object_mode and self.default_currency:
            # Format with fixed scale_dp decimals so the string round-trips losslessly.
            fmt = f"{{:.{sim.amount_scale_dp}f}}"
            return {"amount": fmt.format(scaled), "currency": self.default_currency}
        return scaled

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
            return {"accepted": True, "effect": "resumed_from_pause_pending",
                    "run_mode": "running", "command_scope": "world"}
        if self.state == EngineState.RUNNING and self._pause_requested:
            self._pause_requested = False
            return {"accepted": True, "effect": "cancelled_pause_pending",
                    "run_mode": "running", "command_scope": "world"}
        if self.state in (EngineState.IDLE, EngineState.PAUSED):
            self._pause_requested = False
            self.state = EngineState.RUNNING
            self._continuous_task = asyncio.get_event_loop().create_task(self._run_continuous())
            return {"accepted": True, "effect": "immediate",
                    "run_mode": "running", "command_scope": "world"}
        return {"accepted": True, "effect": "noop",
                "run_mode": self.run_mode, "command_scope": "world"}

    async def pause(self) -> dict:
        """Request pause. Freezes intake countdown if intake is open;
        otherwise pauses after current tick commits.

        Returns control-plane status dict per 51-api-contract:
        accepted, effect (freeze_intake_pending | pause_after_tick_commit | noop), run_mode.
        """
        if self.state in (EngineState.PAUSED, EngineState.IDLE):
            return {"accepted": True, "effect": "noop",
                    "run_mode": self.run_mode, "command_scope": "world"}
        if self._intake_frozen:
            return {"accepted": True, "effect": "noop",
                    "run_mode": self.run_mode, "command_scope": "world"}

        self._pause_requested = True

        if self._intake_open:
            # _intake_wait poll will detect this and emit intake_countdown_paused
            return {"accepted": True, "effect": "freeze_intake_pending",
                    "run_mode": "pause_pending", "command_scope": "world"}
        await self._emit("pause_requested", {
            "tick_id": self.tick_id + 1,
            "freeze_intake": False,
        })
        return {"accepted": True, "effect": "pause_after_tick_commit",
                "run_mode": "pause_pending", "command_scope": "world"}

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
                "command_scope": "world",
            }
        self._next_day_event.set()
        return {"accepted": True, "effect": "advance_one_tick",
                "run_mode": "paused", "command_scope": "world"}

    # ------------------------------------------------------------------ speed control (spec 51/52/60)

    # ------------------------------------------------------------------ operator actions (v4)

    async def submit_operator_action(self,
                                      action: str,
                                      entity_type: str,
                                      entity_id: str) -> dict:
        """Spec 33 §Operator action binding + spec 52 §Message and action
        acknowledgement contract. Actions target entity IDs
        (invoice_id / settlement_demand_id), never message_id.

        Emits `operator_action_ack_event` on the SSE stream so clients can
        reflect the ack without waiting for the next snapshot.
        """
        if entity_type not in ("invoice", "settlement_demand"):
            return {
                "accepted": False,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "rejection_reason": "invalid_entity_type",
                "command_scope": "world",
            }
        if action not in ("pay_now", "hold", "release_hold"):
            return {
                "accepted": False,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "rejection_reason": "invalid_action",
                "command_scope": "world",
            }
        if self._pipeline_executor is None:
            return {
                "accepted": False,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "rejection_reason": "pipeline_not_runtime",
                "command_scope": "world",
            }
        executor = self._pipeline_executor
        if action == "hold":
            result = executor.request_hold(entity_id)
        elif action == "release_hold":
            result = executor.request_release_hold(entity_id)
        else:  # pay_now
            result = executor.request_pay_now(entity_id)
        # Emit ack SSE event (spec 52 §operator_action_ack_event).
        ack_payload = {
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "accepted": result.get("accepted", False),
            "entity_known": result.get("entity_known", False),
            "tick_id": self.tick_id,
            "simulation_date": self.simulation_date.isoformat(),
        }
        if result.get("rejection_reason"):
            ack_payload["rejection_reason"] = result["rejection_reason"]
        await self._emit("operator_action_ack_event", ack_payload)
        return {
            "accepted": result.get("accepted", False),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_known": result.get("entity_known", False),
            "rejection_reason": result.get("rejection_reason"),
            "command_scope": "world",
        }

    async def set_speed(self, multiplier: float) -> dict:
        """Set wall-clock speed multiplier (spec 51 §Speed / 52 §Set speed).

        `multiplier` is a positive scalar: 1.0 = baseline pacing, 2.0 = half the
        configured tick wall-clock budget, 0.5 = doubled budget (slow-mo). Only
        affects wall-clock waits (intake countdown + inter-tick processing
        wait); simulation math is unchanged (spec CLAUDE.md §Determinism).

        Rejects non-finite or non-positive values with
        `rejection_reason=invalid_speed_multiplier`.
        """
        import math
        try:
            m = float(multiplier)
        except (TypeError, ValueError):
            return {
                "accepted": False,
                "rejection_reason": "invalid_speed_multiplier",
                "run_mode": self.run_mode,
                "command_scope": "world",
                "speed_multiplier": self.speed_multiplier,
            }
        if not math.isfinite(m) or m <= 0:
            return {
                "accepted": False,
                "rejection_reason": "invalid_speed_multiplier",
                "run_mode": self.run_mode,
                "command_scope": "world",
                "speed_multiplier": self.speed_multiplier,
            }
        # Guard-rail: clamp to a sensible scalar window to keep tick budgets
        # finite and positive. 0.01×..100× spans slow-mo review through
        # fast-forward smoke runs.
        if m < 0.01:
            m = 0.01
        if m > 100.0:
            m = 100.0
        previous = self.speed_multiplier
        self.speed_multiplier = m
        await self._emit("speed_changed", {
            "speed_multiplier": self.speed_multiplier,
            "previous_multiplier": previous,
            "effective_intake_window_ms": int(self._effective_intake_window_ms()),
            "effective_tick_wall_clock_base_ms": int(self._effective_tick_wall_clock_base_ms()),
        })
        return {
            "accepted": True,
            "effect": "speed_changed" if previous != m else "noop",
            "run_mode": self.run_mode,
            "command_scope": "world",
            "speed_multiplier": self.speed_multiplier,
            "previous_multiplier": previous,
            "effective_intake_window_ms": int(self._effective_intake_window_ms()),
            "effective_tick_wall_clock_base_ms": int(self._effective_tick_wall_clock_base_ms()),
        }

    def _effective_intake_window_ms(self) -> float:
        """Speed-adjusted intake window (spec 60 §Tick timing display contract)."""
        base = float(self.cfg.simulation.intake_window_ms)
        return base / max(self.speed_multiplier, 0.01)

    def _effective_tick_wall_clock_base_ms(self) -> float:
        """Speed-adjusted total tick wall-clock budget (spec 40 §tick cycle timing)."""
        base = float(self.cfg.simulation.tick_wall_clock_base_ms)
        return base / max(self.speed_multiplier, 0.01)

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
            command_scope="agent",
        )
        await self._emit("command_ack", {
            "command_id": ack.command_id,
            "accepted": ack.accepted,
            "target_tick": ack.target_tick,
            "processed_in_tick": ack.processed_in_tick,
            "rejection_reason": ack.rejection_reason,
            "command_scope": ack.command_scope,
        })
        return ack

    # ------------------------------------------------------------------ config reload + world restart

    async def reload_config(self,
                             grace_period_ms: int = 500,
                             reconnect_after_ms: int = 2000) -> dict:
        """Re-read YAML, validate, and replace world (51-api-contract).

        Works from any state: cancels any in-flight continuous tick loop, drains
        a frozen intake, then re-initializes the world and resets to PAUSED at tick 0.

        Per spec 51 §Config reload + spec 52 §Shutdown: reload acceptance implies
        a graceful-restart intent. Emit `server_shutdown(reason=config_reload_restart,
        will_restart=true)` BEFORE `world_restarting`, so any subscriber watching
        the stream can disambiguate this restart from an unexpected close.

        Returns structured result dict:
        accepted, reloaded, world_generation (on success), error_codes (on validation fail),
        rejection_reason, run_mode, command_scope="world", will_restart, reconnect_after_ms.
        """
        if self.config_path is None:
            return {"accepted": False, "reloaded": False,
                    "rejection_reason": "no_config_path_registered",
                    "run_mode": self.run_mode,
                    "command_scope": "world"}

        prev_state = self.state
        # Restart intent notification — emit before world_restarting so clients
        # have the will_restart hint before any lifecycle transition (spec 52).
        await self._emit("server_shutdown", {
            "reason": "config_reload_restart",
            "grace_period_ms": grace_period_ms,
            "reconnect_after_ms": reconnect_after_ms,
            "will_restart": True,
        })
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
                "command_scope": "world",
                "will_restart": False,
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
        # Re-resolve v2 runtime context after reload (spec 40).
        self._scenario_dates = ScenarioDates.from_config(
            cfg.scenario.start_date if cfg.scenario.start_date else None
        )
        self._currency_catalog = self._load_currency_catalog(cfg, self.config_path)
        self.money_object_mode = bool(
            cfg.money is not None and cfg.money.enforce_money_object
        )
        self.default_currency = cfg.money.default_currency if cfg.money else None
        self._calendar_registry = None
        self._region_registry = None
        if cfg.calendars:
            self._calendar_registry = CalendarRegistry.from_config(cfg)
            self._region_registry = RegionRegistry.from_config(cfg, self._calendar_registry)
        self._pipeline_executor = None
        if self._pipeline_store is not None:
            self._pipeline_store.close()
            self._pipeline_store = None
        if cfg_pipeline_runtime(cfg):
            self._pipeline_store = PipelineStore(":memory:")
            self._pipeline_executor = PipelineExecutor(
                cfg=cfg,
                model=self.model,
                default_currency=self.default_currency or "USD",
                calendar_lookup=self._calendar_for_vendor,
                emit=self._buffer_pipeline_event,
            )

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
            "command_scope": "world",
            "will_restart": True,
            "reconnect_after_ms": reconnect_after_ms,
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
            # Speed-adjusted per spec 51/52/60: effective budget shrinks at
            # 2× / 3×; simulation math is unaffected (CLAUDE.md §Determinism).
            # The intake window already consumed some of it; we wait for the
            # remainder. Live speed changes take effect on the next tick.
            effective_base_ms = self._effective_tick_wall_clock_base_ms()
            if effective_base_ms > 0:
                elapsed_ms = (time.monotonic() - tick_start) * 1000
                wait_ms = max(0.0, effective_base_ms - elapsed_ms)
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

        # Spec 60 §Tick timing display contract: the intake/tick values on this
        # event are EFFECTIVE (speed-adjusted) so client countdowns reflect the
        # real wall-clock time the server will spend. The base values are
        # observable via state_snapshot.config for UIs that want them.
        effective_intake_ms = int(self._effective_intake_window_ms())
        effective_tick_ms = int(self._effective_tick_wall_clock_base_ms())
        await self._emit("tick_intake_window_opened", {
            "tick_id": self.tick_id + 1,
            "intake_window_ms": effective_intake_ms,
            "tick_wall_clock_base_ms": effective_tick_ms,
            "speed_multiplier": self.speed_multiplier,
        })

        if not next_day_mode:
            await self._intake_wait(effective_intake_ms)

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
        sim_date_iso = self.simulation_date.isoformat()
        for o in outcomes:
            d = o.as_dict(
                count_mode=sim.count_rounding_mode,
                amount_scale_dp=sim.amount_scale_dp,
                amount_mode=sim.amount_rounding_mode,
            )
            # v2: amount fields become money objects {amount, currency}; v0: scalar.
            d["successful_total_amount"] = self._amount_payload(o.successful_total_amount)
            d["failed_total_amount"] = self._amount_payload(o.failed_total_amount)
            # Stamp the day this outcome belongs to (spec 40 §scenario.start_date).
            d["simulation_date"] = sim_date_iso
            self._recent_outcomes.append(d)
            await self._emit("action_outcome", d)

        # ADR-0002 gating: run promoted pipeline stages after v1 adjudication.
        # Stage order (spec 30 §v3_runtime): intents -> fees -> postings ->
        # asset transfers -> invoice/settlement. tick_id and simulation_date
        # already reflect the day just simulated by Mesa's model.step().
        if self._pipeline_executor is not None:
            self._pending_pipeline_events.clear()
            self._pipeline_executor.run_post_adjudication(
                outcomes=outcomes,
                tick_id=self.tick_id,
                simulation_date=self.simulation_date,
            )
            for evt in self._pending_pipeline_events:
                await self._emit(evt["event"], evt["data"])
            self._pending_pipeline_events.clear()

        if len(self._recent_outcomes) > self._max_recent:
            self._recent_outcomes = self._recent_outcomes[-self._max_recent:]

        # Phase 5: commit. Compute remaining inter-tick wait so the client can
        # render an accurate "next tick in N" countdown without doing its own
        # math (40-yaml-config: intake is part of the total tick budget).
        # Speed-adjusted (spec 51/52/60): effective budget shrinks at > 1×.
        effective_base_ms = self._effective_tick_wall_clock_base_ms()
        if effective_base_ms > 0:
            elapsed_ms = (time.monotonic() - tick_start_monotonic) * 1000
            inter_tick_wait_ms = int(max(0, effective_base_ms - elapsed_ms))
        else:
            inter_tick_wait_ms = 0

        summary = self._build_summary(outcomes)
        await self._emit("tick_committed", {
            "tick_id": self.tick_id,
            "simulation_date": self.simulation_date.isoformat(),
            "committed_at": time.time(),
            "inter_tick_wait_ms": inter_tick_wait_ms,
            "speed_multiplier": self.speed_multiplier,
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
            # Amount routes through _amount_payload so v2 mode emits money objects.
            "transact_amount": self._amount_payload(transact_amt),
        }

    def build_snapshot(self) -> dict:
        snap = self.model.snapshot()
        sim = self.cfg.simulation
        # In v2 money mode, rewrite product successful_transact_amount as money
        # objects (spec 40 §money + critical contract decision #1: no scalar
        # fallback in v2).
        if self.money_object_mode:
            for vid, v in snap.get("vendors", {}).items():
                for pid, p in v.get("products", {}).items():
                    if "successful_transact_amount" in p:
                        p["successful_transact_amount"] = self._amount_payload(
                            p["successful_transact_amount"]
                        )
        return {
            "tick_id": self.tick_id,
            "engine_state": self.state.value,
            "run_mode": self.run_mode,
            "intake_open": self._intake_open,
            "intake_frozen": self._intake_frozen,
            "intake_remaining_ms": self._intake_remaining_ms if self._intake_frozen else None,
            "world_generation": self._world_generation,
            # v2 foundations: scenario time + currency context (spec 40, 51 §Numeric, 52).
            "simulation_date": self.simulation_date.isoformat(),
            "scenario_start_date_resolved": self.scenario_start_date_resolved.isoformat(),
            "default_currency": self.default_currency,
            "money_object_mode": self.money_object_mode,
            # Wall-clock pacing (spec 51/52/60). Speed_multiplier is reported
            # at top level so reconnecting clients pick it up without probing
            # the config block. Effective intake/tick shown so UIs don't have
            # to do the math (base × 1/speed).
            "speed_multiplier": self.speed_multiplier,
            "effective_intake_window_ms": int(self._effective_intake_window_ms()),
            "effective_tick_wall_clock_base_ms": int(self._effective_tick_wall_clock_base_ms()),
            "config": {
                "intake_window_ms": sim.intake_window_ms,
                "tick_wall_clock_base_ms": sim.tick_wall_clock_base_ms,
                "amount_scale_dp": sim.amount_scale_dp,
                "amount_rounding_mode": sim.amount_rounding_mode,
                "count_rounding_mode": sim.count_rounding_mode,
            },
            **snap,
            "recent_outcomes": list(self._recent_outcomes[-20:]),
        }
