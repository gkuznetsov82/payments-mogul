"""Graceful-reload dev server.

Drop-in replacement for `uvicorn ... --reload` that emits `server_shutdown`
SSE events (52-realtime-ui-protocol) to connected clients on every reload.

Why: uvicorn's built-in `--reload` uses `multiprocessing.Process.terminate()`
on Windows, which calls `TerminateProcess` — an instant, uncatchable kill.
The worker never gets a signal, so lifespan shutdown never runs and clients
see SSE errors instead of a clean `server_shutdown` notice.

This wrapper:
  1. Starts uvicorn as a subprocess (no --reload).
  2. Watches engine/ and configs/ for changes via `watchfiles`.
  3. On change: POSTs /control/shutdown → the app emits server_shutdown with
     will_restart=True, flushes the grace period, then exits.
  4. Waits for the old process to exit, starts a fresh one.
  5. Ctrl+C on this wrapper also triggers the graceful path.

Usage:
    python dev.py [--port 8080] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

import httpx
import watchfiles


ROOT = Path(__file__).parent
DEFAULT_WATCH_DIRS = [ROOT / "engine", ROOT / "configs"]
APP_TARGET = "engine.api.server:app"

# On Windows, CREATE_NEW_PROCESS_GROUP prevents the child from receiving the
# console Ctrl+C — otherwise the uvicorn subprocess starts tearing itself down
# at the exact same instant we catch KeyboardInterrupt, and our graceful
# POST /control/shutdown races the subprocess's own shutdown. With a separate
# process group, only the wrapper gets Ctrl+C and we have clean control over
# the subprocess lifecycle.
if sys.platform == "win32":
    _SUBPROCESS_FLAGS = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    _GRACEFUL_BREAK_SIGNAL = signal.CTRL_BREAK_EVENT
else:
    _SUBPROCESS_FLAGS = {"start_new_session": True}
    _GRACEFUL_BREAK_SIGNAL = signal.SIGTERM


def _uvicorn_cmd(host: str, port: int) -> list[str]:
    return [
        sys.executable, "-m", "uvicorn", APP_TARGET,
        "--host", host,
        "--port", str(port),
    ]


async def _graceful_shutdown(base_url: str, timeout: float = 3.0) -> bool:
    """POST /control/shutdown. Returns True if the server accepted the request."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{base_url}/control/shutdown")
            return r.status_code == 200
    except Exception as exc:
        print(f"[dev] graceful_shutdown request failed: {exc}")
        return False


def _start_server(host: str, port: int) -> subprocess.Popen:
    return subprocess.Popen(_uvicorn_cmd(host, port), **_SUBPROCESS_FLAGS)


def _send_break(proc: subprocess.Popen) -> None:
    """Send the platform's "graceful break" signal to the subprocess.

    On Windows that's CTRL_BREAK_EVENT (the subprocess has its own group, so
    this doesn't also hit the wrapper). On Unix it's SIGTERM."""
    try:
        if sys.platform == "win32":
            os.kill(proc.pid, _GRACEFUL_BREAK_SIGNAL)
        else:
            proc.send_signal(_GRACEFUL_BREAK_SIGNAL)
    except Exception as exc:
        print(f"[dev] send_break failed: {exc}")


def _stop_server(proc: subprocess.Popen, label: str, timeout: float = 5.0) -> None:
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[dev] {label}: process did not exit in {timeout:.0f}s; terminating")
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            print(f"[dev] {label}: still alive; killing")
            proc.kill()


# State shared between the asyncio task and the outer cleanup (which runs
# *outside* the cancelled asyncio scope on Ctrl+C — see main() below).
_state: dict = {"proc": None}


async def _watch_and_reload(host: str, port: int, watch_dirs: list[Path]) -> None:
    base_url = f"http://{host}:{port}"
    _state["proc"] = _start_server(host, port)
    print(f"[dev] uvicorn pid={_state['proc'].pid} listening on {base_url}")
    print(f"[dev] watching: {', '.join(str(d.relative_to(ROOT)) for d in watch_dirs)}")

    async for changes in watchfiles.awatch(*[str(d) for d in watch_dirs]):
        changed_names = sorted({Path(p).name for _, p in changes})[:5]
        summary = ", ".join(changed_names)
        print(f"\n[dev] change detected ({summary}); requesting graceful shutdown")

        ok = await _graceful_shutdown(base_url)
        if not ok:
            print("[dev] graceful path failed; sending break signal")
            _send_break(_state["proc"])
        _stop_server(_state["proc"], label="reload")

        _state["proc"] = _start_server(host, port)
        print(f"[dev] uvicorn pid={_state['proc'].pid} restarted")


def _run_cleanup(base_url: str) -> None:
    """Synchronous cleanup entry point. Called from `main()` after the watch
    loop exits (normally or via KeyboardInterrupt).

    Crucially this is NOT inside the asyncio task that was cancelled by the
    Ctrl+C handler — it spins up a fresh event loop, so the `await` on the
    HTTP POST is not re-interrupted by a pending CancelledError.
    """
    proc = _state.get("proc")
    if proc is None:
        return
    if proc.poll() is not None:
        # Already exited
        return
    print("[dev] requesting graceful shutdown of running server...")
    ok = False
    try:
        ok = asyncio.run(_graceful_shutdown(base_url))
    except Exception as exc:
        print(f"[dev] graceful shutdown call failed: {exc}")
    if not ok:
        print("[dev] graceful path failed; sending break signal")
        _send_break(proc)
    _stop_server(proc, label="exit")


def main() -> None:
    parser = argparse.ArgumentParser(description="Graceful-reload dev server for Payments Mogul")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--watch", action="append", default=None,
        help="Directory to watch (repeatable). Defaults to engine/ and configs/.",
    )
    args = parser.parse_args()

    watch_dirs = [Path(p).resolve() for p in args.watch] if args.watch else DEFAULT_WATCH_DIRS
    missing = [d for d in watch_dirs if not d.exists()]
    if missing:
        print(f"[dev] watch dirs not found: {missing}", file=sys.stderr)
        sys.exit(1)

    base_url = f"http://{args.host}:{args.port}"

    try:
        asyncio.run(_watch_and_reload(args.host, args.port, watch_dirs))
    except KeyboardInterrupt:
        print("\n[dev] Ctrl+C received")
    except Exception as exc:
        print(f"\n[dev] watch loop error: {exc}")
    finally:
        _run_cleanup(base_url)
        print("[dev] done")


if __name__ == "__main__":
    main()
