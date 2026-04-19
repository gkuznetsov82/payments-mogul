"""FastAPI server: REST control plane + SSE realtime stream."""

from __future__ import annotations

import asyncio
import json
import logging
import logging.config
import os
import signal
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from engine.config.loader import ConfigValidationError, load_config
from engine.simulation.engine import ControlCommand, SimulationEngine

# Patch uvicorn loggers to include timestamps
logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "timestamped": {
            "format": "%(asctime)s.%(msecs)03d  %(levelname)s  %(message)s",
            "datefmt": "%H:%M:%S",
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "timestamped",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
})

# v2 foundations runtime config: enables money-object mode, currency catalog,
# regions/calendars/FX sections (spec 40 §Prototype v2 foundations).
# Switch to "prototype_v0.yaml" if you want the legacy scalar-amount scenario.
CONFIG_PATH = Path(__file__).parent.parent.parent / "configs" / "prototype_v2_foundations_example.yaml"

# Global engine instance (set on startup)
_engine: SimulationEngine | None = None
_config_warnings: list[str] = []


# ------------------------------------------------------------------ lifespan

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    cfg, warns = load_config(CONFIG_PATH)
    _config_warnings.extend(str(w) for w in warns)
    _engine = SimulationEngine(cfg, config_path=CONFIG_PATH)
    await _engine.start_next_day_loop()
    _engine.state_from_idle()  # mark as PAUSED, ready to run
    yield
    # Shutdown: emit server_shutdown SSE so clients can reconnect gracefully
    try:
        await _engine.shutdown(reason="manual_shutdown",
                               grace_period_ms=1000,
                               reconnect_after_ms=2000,
                               will_restart=False)
    except Exception:
        pass


app = FastAPI(title="Payments Mogul Engine", lifespan=lifespan)


def get_engine() -> SimulationEngine:
    if _engine is None:
        raise HTTPException(503, "Engine not initialized")
    return _engine


# ------------------------------------------------------------------ request models

class CommandRequest(BaseModel):
    command_id: Optional[str] = None
    command_type: str      # OpenOnboarding | CloseOnboarding | OpenTransacting | CloseTransacting
    vendor_id: str
    product_id: str


# ------------------------------------------------------------------ control routes

@app.get("/health")
async def health():
    engine = get_engine()
    return {
        "status": "ok",
        "tick_id": engine.tick_id,
        "engine_state": engine.state.value,
        "run_mode": engine.run_mode,
    }


@app.get("/snapshot")
async def snapshot():
    return get_engine().build_snapshot()


@app.post("/control/pause")
async def pause():
    engine = get_engine()
    result = await engine.pause()
    return {"ok": result.get("accepted", True), **result}


@app.post("/control/resume")
async def resume():
    engine = get_engine()
    result = await engine.resume()
    return {"ok": result.get("accepted", True), **result}


@app.post("/control/next_day")
async def next_day():
    engine = get_engine()
    result = await engine.next_day()
    return {"ok": result.get("accepted", True), "tick_id": engine.tick_id, **result}


@app.post("/control/reload_config")
async def reload_config():
    """Re-read scenario YAML, validate, and replace world if valid (51-api-contract)."""
    engine = get_engine()
    result = await engine.reload_config()
    # Refresh cached warnings on successful reload
    if result.get("reloaded"):
        try:
            _, warns = load_config(CONFIG_PATH)
            _config_warnings.clear()
            _config_warnings.extend(str(w) for w in warns)
        except ConfigValidationError:
            pass
    return {"ok": result.get("accepted", False), **result}


@app.post("/command")
async def submit_command(req: CommandRequest):
    engine = get_engine()
    cmd = ControlCommand(
        command_id=req.command_id or str(uuid.uuid4()),
        command_type=req.command_type,
        vendor_id=req.vendor_id,
        product_id=req.product_id,
    )
    valid_types = {"OpenOnboarding", "CloseOnboarding", "OpenTransacting", "CloseTransacting"}
    if cmd.command_type not in valid_types:
        raise HTTPException(400, f"Unknown command_type: {cmd.command_type}")
    ack = await engine.submit_command(cmd)
    return {
        "command_id": ack.command_id,
        "accepted": ack.accepted,
        "target_tick": ack.target_tick,
        "processed_in_tick": ack.processed_in_tick,
        "rejection_reason": ack.rejection_reason,
    }


@app.get("/config/warnings")
async def config_warnings():
    return {"warnings": _config_warnings}


async def _orchestrate_process_exit(post_response_delay_ms: int = 500,
                                     uvicorn_grace_seconds: float = 2.0) -> None:
    """Bring the worker process down after the HTTP response has flushed.

    1. Wait `post_response_delay_ms` so the in-flight 200 reaches the caller.
    2. Try `signal.raise_signal(SIGINT)` — uvicorn's own SIGINT handler then
       runs graceful shutdown. This is the clean path on Linux/macOS.
    3. If after `uvicorn_grace_seconds` the loop is still alive (Windows under
       `--reload` doesn't always honor SIGINT in the worker), force-exit via
       `os._exit(0)`. By this point clients have already received the
       `server_shutdown` SSE event during engine.shutdown()'s grace period.
    """
    await asyncio.sleep(post_response_delay_ms / 1000)
    try:
        signal.raise_signal(signal.SIGINT)
    except (AttributeError, ValueError, OSError):
        pass
    await asyncio.sleep(uvicorn_grace_seconds)
    os._exit(0)


@app.post("/control/shutdown")
async def control_shutdown():
    """Graceful shutdown (51-api-contract §Server shutdown command, 52 §Shutdown).

    Emits `server_shutdown` to all SSE subscribers, returns a clean HTTP
    response, then signals the process to exit.

    Use this instead of Ctrl+C when you want clients to receive the shutdown
    signal — Ctrl+C in `--reload` mode force-kills the worker before lifespan
    shutdown runs, so the emit never reaches SSE subscribers.
    """
    engine = get_engine()
    grace_ms = 500
    reconnect_ms = 2000
    await engine.shutdown(
        reason="manual_shutdown",
        grace_period_ms=grace_ms,
        reconnect_after_ms=reconnect_ms,
        will_restart=False,
    )
    asyncio.create_task(_orchestrate_process_exit(post_response_delay_ms=grace_ms))
    return {
        "accepted": True,
        "ok": True,
        "run_mode": engine.run_mode,
        "grace_period_ms": grace_ms,
        "reconnect_after_ms": reconnect_ms,
        "will_restart": False,
    }


# ------------------------------------------------------------------ SSE stream

@app.get("/events")
async def events(request: Request):
    engine = get_engine()
    queue = engine.subscribe()

    async def generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(envelope)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            engine.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")
