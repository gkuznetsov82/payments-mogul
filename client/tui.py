"""Textual TUI client for Payments Mogul prototype_vendor_pop_v1.

Usage:
    python -m client.tui [--url http://localhost:8000]

Implements the client-side of 51-api-contract and 52-realtime-ui-protocol:
- intake-freeze countdown, pause-pending UI state
- world_restarting/world_restarted lifecycle banner
- server_shutdown notice with reconnect hint
- expected vs unexpected stream-close handling
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button, DataTable, Footer, Header, Label, Log, RichLog, Select, Static,
    TabbedContent, TabPane,
)

from client.widgets import SelectableRichLog


BASE_URL = "http://localhost:8000"


# ------------------------------------------------------------------ widgets

class StatusBar(Static):
    tick_id: reactive[int] = reactive(0)
    run_mode: reactive[str] = reactive("idle")
    intake_open: reactive[bool] = reactive(False)
    intake_frozen: reactive[bool] = reactive(False)
    countdown: reactive[str] = reactive("")
    world_generation: reactive[int] = reactive(0)
    # v2 foundations (spec 40 §scenario.start_date, §money): scenario date + currency context.
    simulation_date: reactive[str] = reactive("")
    default_currency: reactive[str] = reactive("")

    def render(self) -> str:
        if self.intake_frozen:
            intake_str = "[yellow]FROZEN[/]"
        elif self.intake_open or self.run_mode in ("paused", "pause_pending"):
            # When paused, intake is conceptually open — commands queue for next tick
            intake_str = "[green]OPEN[/]"
        else:
            intake_str = "[yellow]CLOSED[/]"

        mode_colors = {
            "running": "green",
            "paused": "cyan",
            "pause_pending": "yellow",
            "restarting": "magenta",
            "shutting_down": "red",
            "offline": "red",
            "idle": "dim",
        }
        color = mode_colors.get(self.run_mode, "white")
        mode_label = self.run_mode.replace("_", " ").upper()
        mode_str = f"[bold {color}]{mode_label}[/]"

        date_str = f"  Date: [bold]{self.simulation_date}[/]" if self.simulation_date else ""
        ccy_str = f"  [dim]{self.default_currency}[/]" if self.default_currency else ""
        countdown_str = f"  [dim]{self.countdown}[/]" if self.countdown else ""
        gen_str = f"  [dim]gen={self.world_generation}[/]"

        return (
            f"[bold]Payments Mogul[/]  "
            f"Tick: [bold]{self.tick_id}[/]"
            f"{date_str}  "
            f"Mode: {mode_str}  "
            f"Intake: {intake_str}"
            f"{countdown_str}"
            f"{ccy_str}"
            f"{gen_str}"
        )


class Banner(Static):
    """Non-error lifecycle notice banner (world_restarting / server_shutdown)."""
    message: reactive[str] = reactive("")

    def render(self) -> str:
        return self.message or ""


# ------------------------------------------------------------------ main app

class MogulApp(App):
    # Layout + accessibility per spec 60 §TUI layout parameters and 12 §TUI scaling:
    # baseline 120x36, control pane 26-32 cols (chose 30), event log min 8 rows with
    # flexible growth, status bar fixed at top, both panes independently focusable.
    CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    Banner {
        height: auto;
        background: $warning;
        color: $text;
        padding: 0 1;
    }
    #main {
        height: 1fr;
    }
    #run-strip {
        height: 5;
        border: solid $accent;
        padding: 0 1;
        align-vertical: middle;
    }
    #run-strip Button {
        width: 18;
        height: 3;
        min-width: 14;
        margin: 0 1 0 0;
    }
    #ack-label {
        width: 1fr;
        margin: 1 0 0 1;
        color: $text-muted;
    }
    #tabs {
        height: 1fr;
    }
    .tab-pane-content {
        height: 1fr;
        padding: 1;
        overflow: auto;
    }
    .controls-pane Button {
        width: 100%;
        margin: 0 0 1 0;
    }
    Label {
        margin: 1 0 0 0;
    }
    #event-log, #pipeline-log, #books-log, #accounts-log {
        min-height: 8;
        height: 1fr;
        border: solid $surface;
    }
    #books-tree, #accounts-tree {
        height: auto;
        min-height: 4;
        padding: 0 1;
    }
    .agent-controls-row Button {
        width: 1fr;
        margin: 0 1 0 0;
    }
    .agent-controls-row {
        height: 3;
        margin: 0 0 1 0;
    }
    #agent-target-select {
        margin: 0 0 1 0;
    }
    #btn-speed {
        width: 14;
        min-width: 12;
    }
    #run-strip .world-btn {
        width: 22;
    }
    """

    # Keyboard shortcuts per spec 60 §Accessibility: quick-focus shortcuts for
    # event log and control pane; primary lifecycle controls keyboard-reachable.
    BINDINGS = [
        ("ctrl+l", "focus_log", "Focus event log"),
        ("ctrl+k", "focus_controls", "Focus control pane"),
        ("ctrl+r", "resume", "Resume"),
        ("ctrl+p", "pause", "Pause"),
        ("ctrl+n", "next_day", "Next Day"),
        ("ctrl+d", "shutdown_server", "Shutdown server"),
        # Spec 60 §Minimum navigation contract: Run / World / Pipeline / Books /
        # Accounts / Logs. Run controls live in the always-visible strip.
        ("f1", "view_world", "World"),
        ("f2", "view_pipeline", "Pipeline"),
        ("f3", "view_books", "Books"),
        ("f4", "view_accounts", "Accounts"),
        ("f5", "view_logs", "Logs"),
        # Operator copy of log content. Mouse selection on RichLog already works
        # (ALLOW_SELECT=True); this keyboard action covers the case where the
        # terminal eats mouse drag or the user prefers keyboard-only flow.
        # Copies the currently-focused log's selection (if any) or the whole
        # log body to the system clipboard via OSC 52.
        ("ctrl+c", "copy_focused_log", "Copy log"),
    ]

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self._http = httpx.AsyncClient(base_url=base_url, timeout=5.0)
        # Intake countdown tracking
        self._intake_countdown_start: float | None = None
        self._intake_countdown_ms: int = 0
        self._frozen_remaining_ms: int = 0
        self._tick_committed_at: float | None = None
        # Remaining inter-tick wait in ms, as told to us by the server in
        # tick_committed. This already accounts for time consumed by intake +
        # simulation phases, so the TUI doesn't need to do the math itself.
        self._inter_tick_wait_ms: int = 0
        self._in_intake: bool = False
        # Numeric display policy (spec 60 §Numeric presentation rule): counts
        # as integers, amounts at configured decimal scale. Populated from
        # snapshot config.
        self._amount_scale_dp: int = 2
        # Reconnect tracking
        self._server_shutdown_received: bool = False
        self._server_will_restart: bool = False
        self._reconnect_after_ms: int = 2000
        self._reconnect_deadline: float | None = None
        self._reconnect_attempts_since_shutdown: int = 0
        self._max_reconnect_attempts_no_restart: int = 5  # bounded retries when will_restart=false
        self._offline: bool = False
        # Agent-controls target (spec 51 §Agent controls: explicit target required).
        # Populated from snapshot as (vendor_id, product_id) pairs become known.
        self._agent_targets: list[tuple[str, str, str]] = []  # (vendor_id, product_id, label)
        self._selected_target_key: str = "__none__"
        # Books (ledger) + Accounts (value container) hierarchy state, populated
        # from posting_entry_event + value_transfer_event. Key: (product_id, path).
        self._books_by_path: dict[str, dict] = {}
        self._accounts_by_path: dict[str, dict] = {}
        # Speed pacing (spec 51 §Speed / 52 §Set speed). Cycle button steps
        # through 1× → 2× → 3× → 1×; label reflects the server's authoritative
        # value (updated via speed_changed event + state_snapshot).
        self._speed_multiplier: float = 1.0
        self._speed_cycle: tuple[float, ...] = (1.0, 2.0, 3.0)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusBar(id="status")
        yield Banner(id="banner")
        # Spec 60 §TUI layout: run strip is the always-visible section for timing
        # controls + world-scoped controls (reload, shutdown). Agent-scoped controls
        # live in the World tab alongside the target selector so users can see
        # which vendor/product a command targets.
        with Horizontal(id="run-strip"):
            yield Button("▶  Resume", id="btn-resume", variant="success")
            yield Button("⏸  Pause", id="btn-pause", variant="warning")
            yield Button("⏭  Next Day", id="btn-next-day", variant="primary")
            # Spec 51 §Speed / 52 §Set speed: cycle 1× → 2× → 3× → 1×.
            # Label reflects server's authoritative speed_multiplier.
            yield Button("Speed: 1×", id="btn-speed", variant="default")
            yield Button("⟳  Reload Config", id="btn-reload",
                         variant="primary", classes="world-btn")
            yield Button("⛔  Shutdown", id="btn-shutdown",
                         variant="error", classes="world-btn")
            yield Static("", id="ack-label")
        # Spec 60 §Minimum navigation contract: baseline required sections are
        # Run/World/Pipeline/Books/Accounts/Logs.
        with TabbedContent(id="tabs", initial="tab-world"):
            with TabPane("World [F1]", id="tab-world"):
                with Vertical(classes="tab-pane-content"):
                    yield Static("[bold]Vendor / Product State[/]", id="vendor-info")
                    yield Static("[bold]Pop State[/]", id="pop-info")
                    yield Label("── Agent Controls (explicit target) ──")
                    # Select populated from snapshot; required-target contract
                    # per spec 51 §Agent controls.
                    yield Select(
                        options=[("(no target)", "__none__")],
                        prompt="Select vendor / product target",
                        id="agent-target-select",
                        allow_blank=False,
                    )
                    with Horizontal(classes="agent-controls-row"):
                        yield Button("Open OB", id="btn-open-ob")
                        yield Button("Close OB", id="btn-close-ob", variant="error")
                    with Horizontal(classes="agent-controls-row"):
                        yield Button("Open TX", id="btn-open-tx")
                        yield Button("Close TX", id="btn-close-tx", variant="error")
            with TabPane("Pipeline [F2]", id="tab-pipeline"):
                with Vertical(classes="tab-pane-content"):
                    yield Label("Intents (original + routed) · Fees · Transfers · Invoices")
                    yield Static(
                        "[dim]Focus log → ↑/↓ move line · Shift+↑/↓ extend · "
                        "Ctrl+A all · Esc clear · Ctrl+C copy selection[/]",
                        classes="log-hint",
                    )
                    yield SelectableRichLog(id="pipeline-log", highlight=True, markup=True, auto_scroll=True)
            with TabPane("Books [F3]", id="tab-books"):
                with Vertical(classes="tab-pane-content"):
                    yield Label("[bold]Ledger hierarchy[/] — balances and paths per product")
                    yield Static("(no postings yet)", id="books-tree")
                    yield Label("── Posting movements ──")
                    yield Static(
                        "[dim]Focus log → ↑/↓ move line · Shift+↑/↓ extend · "
                        "Ctrl+A all · Esc clear · Ctrl+C copy selection[/]",
                        classes="log-hint",
                    )
                    yield SelectableRichLog(id="books-log", highlight=True, markup=True, auto_scroll=True)
            with TabPane("Accounts [F4]", id="tab-accounts"):
                with Vertical(classes="tab-pane-content"):
                    yield Label("[bold]Value-container hierarchy[/] — funds by owner/product")
                    yield Static("(no transfers yet)", id="accounts-tree")
                    yield Label("── Container movements ──")
                    yield Static(
                        "[dim]Focus log → ↑/↓ move line · Shift+↑/↓ extend · "
                        "Ctrl+A all · Esc clear · Ctrl+C copy selection[/]",
                        classes="log-hint",
                    )
                    yield SelectableRichLog(id="accounts-log", highlight=True, markup=True, auto_scroll=True)
            with TabPane("Logs [F5]", id="tab-logs"):
                with Vertical(classes="tab-pane-content"):
                    yield Label("── Recent Events ──")
                    yield Static(
                        "[dim]Focus log → ↑/↓ move line · Shift+↑/↓ extend · "
                        "Ctrl+A all · Esc clear · Ctrl+C copy selection[/]",
                        classes="log-hint",
                    )
                    yield SelectableRichLog(id="event-log", highlight=True, markup=True, auto_scroll=True)
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._sse_worker(), exclusive=False)
        self.run_worker(self._poll_snapshot(), exclusive=False)
        self.set_interval(0.1, self._update_countdown)

    # ------------------------------------------------------------------ SSE worker with reconnect

    async def _sse_worker(self) -> None:
        backoff = 1.0
        while not self._offline:
            self._reconnect_deadline = None
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", f"{self.base_url}/events") as resp:
                        # Successful connect — reset transient counters
                        backoff = 1.0
                        self._reconnect_attempts_since_shutdown = 0
                        self._server_shutdown_received = False
                        self._server_will_restart = False
                        self._set_banner("")
                        self._log_line(f"[green]SSE connected[/] ({self.base_url}/events)")
                        # Refresh run_mode/tick_id/etc from the new server — otherwise
                        # a stale SHUTTING_DOWN mode from pre-reconnect sticks until
                        # the new server happens to emit a state_snapshot.
                        asyncio.create_task(self._refresh_snapshot())
                        buffer = ""
                        async for chunk in resp.aiter_text():
                            buffer += chunk
                            while "\n\n" in buffer:
                                block, buffer = buffer.split("\n\n", 1)
                                for line in block.splitlines():
                                    if line.startswith("data: "):
                                        try:
                                            envelope = json.loads(line[6:])
                                            self.on_server_event(envelope)
                                        except json.JSONDecodeError:
                                            pass
            except Exception as exc:
                # Spec 52 §Shutdown: close after a received `server_shutdown` is
                # an expected lifecycle transition — do NOT render a transport
                # error. Banner already reflects the shutdown state.
                if not self._server_shutdown_received:
                    self._log_line(f"[red]SSE error: {exc}[/]")

            # Stream closed — decide reconnect strategy (52-realtime-ui-protocol §Shutdown)
            if self._server_shutdown_received:
                self._reconnect_attempts_since_shutdown += 1
                if (not self._server_will_restart
                        and self._reconnect_attempts_since_shutdown
                        > self._max_reconnect_attempts_no_restart):
                    self._offline = True
                    self._set_status_run_mode("offline")
                    self._set_banner(
                        "⚠  Server offline (will not restart). "
                        "Reconnect halted after bounded retries."
                    )
                    self._log_line(
                        "[red]Reconnect halted: will_restart=false and bounded "
                        f"retry limit ({self._max_reconnect_attempts_no_restart}) reached[/]"
                    )
                    break
                delay = self._reconnect_after_ms / 1000
                self._log_line(
                    f"[yellow]Reconnect attempt {self._reconnect_attempts_since_shutdown} "
                    f"in {delay:.1f}s (will_restart={self._server_will_restart})[/]"
                )
            else:
                delay = backoff
                self._log_line(f"[red]Unexpected stream close; retry in {delay:.1f}s[/]")
                backoff = min(backoff * 2, 30.0)
            self._reconnect_deadline = time.monotonic() + delay
            await asyncio.sleep(delay)

    def _set_status_run_mode(self, mode: str) -> None:
        try:
            self.query_one("#status", StatusBar).run_mode = mode
        except Exception:
            pass

    async def _refresh_snapshot(self) -> None:
        """Fetch /snapshot and apply it. Used both at startup and after SSE reconnect
        so the StatusBar run_mode (which can be stale from a pre-reconnect
        SHUTTING_DOWN state) reflects the newly-connected server's current state."""
        try:
            r = await self._http.get("/snapshot")
            if r.status_code == 200:
                self._apply_snapshot(r.json())
        except Exception:
            pass

    async def _poll_snapshot(self) -> None:
        await asyncio.sleep(0.5)
        await self._refresh_snapshot()

    # ------------------------------------------------------------------ helpers

    # Numeric presentation helpers (spec 60 §Numeric presentation rule).
    # Counts display as integers; amounts at configured decimal scale.
    @staticmethod
    def _fmt_count(value) -> str:
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)

    def _fmt_amount(self, value) -> str:
        """Render an amount payload.

        v2 mode: server emits {"amount": "...", "currency": "USD"} per
        spec 40 §money + critical contract decision #1 (no scalar fallback).
        Render as `12.34 USD`. v0 mode: scalar float, render with the
        configured decimal scale.
        """
        if isinstance(value, dict) and "amount" in value:
            ccy = value.get("currency", "")
            try:
                amt = f"{float(value['amount']):,.{self._amount_scale_dp}f}"
            except (TypeError, ValueError):
                amt = str(value["amount"])
            return f"{amt} {ccy}".rstrip()
        try:
            return f"{float(value):,.{self._amount_scale_dp}f}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _format_ms(ms: float) -> str:
        if ms <= 0:
            return "0s"
        if ms < 1:
            return f"{ms * 1000:.0f}µs"
        if ms < 60_000:
            return f"{ms / 1000:.1f}s"
        m = int(ms // 60_000)
        s = int((ms % 60_000) // 1000)
        return f"{m}:{s:02d}"

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _log_line(self, markup: str) -> None:
        try:
            self.query_one("#event-log", RichLog).write(f"[dim]{self._ts()}[/] {markup}")
        except Exception:
            pass

    def _log_pipeline(self, markup: str) -> None:
        try:
            self.query_one("#pipeline-log", RichLog).write(f"[dim]{self._ts()}[/] {markup}")
        except Exception:
            pass

    def _log_books(self, markup: str) -> None:
        try:
            self.query_one("#books-log", RichLog).write(f"[dim]{self._ts()}[/] {markup}")
        except Exception:
            pass

    def _log_accounts(self, markup: str) -> None:
        try:
            self.query_one("#accounts-log", RichLog).write(f"[dim]{self._ts()}[/] {markup}")
        except Exception:
            pass

    def _set_banner(self, message: str) -> None:
        try:
            self.query_one("#banner", Banner).message = message
        except Exception:
            pass

    def _update_countdown(self) -> None:
        try:
            status = self.query_one("#status", StatusBar)
        except Exception:
            return

        if self._offline:
            status.countdown = ""
            return

        # Reconnect countdown takes priority when stream is down
        if self._reconnect_deadline is not None:
            remaining_s = max(0.0, self._reconnect_deadline - time.monotonic())
            status.countdown = f"Reconnect in: {self._format_ms(remaining_s * 1000)}"
            return

        if status.intake_frozen:
            status.countdown = f"Intake frozen: {self._format_ms(self._frozen_remaining_ms)}"
            return

        if status.run_mode == "paused":
            status.countdown = ""
            return

        now = time.monotonic()
        # Single-budget tick timing (spec 12/52/60): intake phase shows time to
        # intake close; processing phase shows remaining processing-slice time
        # within the SAME tick (not a new full-tick countdown).
        if self._in_intake and self._intake_countdown_start is not None and self._intake_countdown_ms > 0:
            elapsed_ms = (now - self._intake_countdown_start) * 1000
            remaining_ms = max(0.0, self._intake_countdown_ms - elapsed_ms)
            status.countdown = f"Intake closes: {self._format_ms(remaining_ms)}"
        elif not self._in_intake and self._tick_committed_at is not None and self._inter_tick_wait_ms > 0:
            elapsed_ms = (now - self._tick_committed_at) * 1000
            remaining_ms = max(0.0, self._inter_tick_wait_ms - elapsed_ms)
            status.countdown = f"Processing: {self._format_ms(remaining_ms)}" if remaining_ms > 0 else ""
        else:
            status.countdown = ""

    # ------------------------------------------------------------------ event dispatch

    def on_server_event(self, envelope: dict) -> None:
        event_type = envelope.get("event", "")
        data = envelope.get("data", {})

        if event_type == "state_snapshot":
            self._apply_snapshot(data)
            return

        status = self.query_one("#status", StatusBar)

        if event_type == "tick_committed":
            self._in_intake = False
            self._tick_committed_at = time.monotonic()
            self._inter_tick_wait_ms = int(data.get("inter_tick_wait_ms", 0))
            tick = data.get("tick_id", "?")
            sim_date = data.get("simulation_date")
            if sim_date:
                # Roll forward the date display immediately on tick commit so the
                # status bar doesn't lag a tick behind.
                status.simulation_date = sim_date
            date_str = f" [{sim_date}]" if sim_date else ""
            self._log_line(
                f"[cyan]tick_committed[/] T{tick}{date_str} "
                f"ob_acc={self._fmt_count(data.get('onboard_accepted', 0))} "
                f"tx_ok={self._fmt_count(data.get('transact_succeeded', 0))} "
                f"amt={self._fmt_amount(data.get('transact_amount', 0))} "
                f"proc_remaining={self._format_ms(self._inter_tick_wait_ms)}"
            )
        elif event_type == "tick_intake_window_opened":
            self._in_intake = True
            self._intake_countdown_start = time.monotonic()
            if "intake_window_ms" in data:
                self._intake_countdown_ms = data["intake_window_ms"]
            status.intake_open = True
            status.intake_frozen = False
            # If a snapshot hasn't landed yet after a fresh resume, the run_mode could still be stale.
            # The engine is clearly running if it is opening intake windows.
            if status.run_mode in ("paused", "idle"):
                status.run_mode = "running"
            self._log_line(f"[dim]intake_opened[/] T{data.get('tick_id')}")
        elif event_type == "tick_intake_window_closed":
            self._in_intake = False
            status.intake_open = False
            status.intake_frozen = False
            self._log_line(f"[dim]intake_closed[/] T{data.get('tick_id')}")
        elif event_type == "intake_countdown_paused":
            status.intake_frozen = True
            status.run_mode = "pause_pending"
            self._frozen_remaining_ms = int(data.get("remaining_ms", 0))
            self._log_line(
                f"[yellow]intake_countdown_paused[/] T{data.get('tick_id')} "
                f"remaining={self._format_ms(self._frozen_remaining_ms)}"
            )
        elif event_type == "intake_countdown_resumed":
            status.intake_frozen = False
            status.run_mode = "running"
            remaining_ms = int(data.get("remaining_ms", 0))
            # Re-base the countdown so the TUI counts from the remaining time
            self._intake_countdown_start = time.monotonic()
            self._intake_countdown_ms = remaining_ms
            self._log_line(
                f"[green]intake_countdown_resumed[/] T{data.get('tick_id')} "
                f"remaining={self._format_ms(remaining_ms)}"
            )
        elif event_type == "pause_requested":
            status.run_mode = "pause_pending"
            freeze = data.get("freeze_intake", False)
            self._log_line(
                f"[yellow]pause_requested[/] T{data.get('tick_id')} "
                f"{'(freeze_intake)' if freeze else '(pause_after_commit)'}"
            )
        elif event_type == "command_ack":
            cid = data.get("command_id", "")[:8]
            accepted = data.get("accepted")
            target = data.get("target_tick")
            color = "green" if accepted else "red"
            self._log_line(
                f"[{color}]command_ack[/] {cid}... accepted={accepted} target_tick={target}"
            )
            # `#ack-label` is a Static (see compose()); query with the correct
            # type. Guard the update so a missing/mismatched widget never
            # raises back into _sse_worker (which would mis-surface as a red
            # "SSE error: ..." transport-error line per spec 52 §Shutdown).
            try:
                self.query_one("#ack-label", Static).update(
                    f"ACK: {'OK' if accepted else 'REJECTED'} T{target}"
                )
            except Exception:
                pass
        elif event_type == "action_outcome":
            atype = data.get("action_type")
            s = data.get("status")
            color = "green" if s in ("accepted", "success") else "yellow"
            if atype == "Onboard":
                detail = f"acc={self._fmt_count(data.get('accepted_pop_count', 0))}"
            else:
                detail = (
                    f"txn={self._fmt_count(data.get('successful_txn_count', 0))} "
                    f"amt={self._fmt_amount(data.get('successful_total_amount', 0))}"
                )
            self._log_line(
                f"[{color}]{atype}[/] T{data.get('tick_id')} "
                f"pop={data.get('pop_id')} {detail} [{data.get('reason_code')}]"
            )
        elif event_type == "tick_user_inputs_processed":
            n = data.get("command_count", 0)
            if n:
                self._log_line(f"[magenta]inputs_processed[/] T{data.get('tick_id')} commands={n}")
        # ---- Pipeline tab events (spec 52 §Pipeline observability) ----
        elif event_type == "transaction_intent_event":
            stage = data.get("intent_stage", "routed_outgoing")
            root = data.get("root_intent_id", data.get("intent_id"))
            # Spec 33 §Transaction-intent log visibility: show original_incoming
            # and routed_outgoing distinctly, with shared root_intent_id column.
            if stage == "original_incoming":
                self._log_pipeline(
                    f"[bold cyan]intent[original][/] T{data.get('tick_id')} "
                    f"prof={data.get('pipeline_profile_id')} "
                    f"id={data.get('intent_id')} root={root} "
                    f"src={data.get('product_id')} "
                    f"n={data.get('txn_count')} amt={self._fmt_amount(data.get('amount'))}"
                )
            else:
                status = data.get("status", "executed")
                reason = data.get("reason_code", "OK")
                color = "cyan" if status == "executed" else "red"
                self._log_pipeline(
                    f"[{color}]intent[routed/{status}][/] T{data.get('tick_id')} "
                    f"prof={data.get('pipeline_profile_id')} "
                    f"id={data.get('intent_id')} root={root} "
                    f"src={data.get('product_id')} -> {data.get('destination_role')} "
                    f"({data.get('destination_product_id')}) "
                    f"n={data.get('txn_count')} amt={self._fmt_amount(data.get('amount'))} "
                    f"vd={data.get('value_date_policy')}={data.get('resolved_value_date')} "
                    f"reason={reason}"
                )
        elif event_type == "fee_accrual_event":
            self._log_pipeline(
                f"[yellow]fee[/] T{data.get('tick_id')} prof={data.get('pipeline_profile_id')} "
                f"id={data.get('fee_id')} trig={data.get('trigger_id')} "
                f"prod={data.get('product_id')} bene={data.get('beneficiary_role')}/"
                f"{data.get('beneficiary_product_id')} "
                f"fixed={self._fmt_amount(data.get('fixed_component'))} "
                f"pct={self._fmt_amount(data.get('percent_component'))} "
                f"total={self._fmt_amount(data.get('fee_amount'))} "
                f"due={data.get('settlement_due_date')} status={data.get('status')}"
            )
        elif event_type == "value_transfer_event":
            # Spec 60 §View D — Accounts: value-container movements.
            self._log_accounts(
                f"[green]xfer[/] T{data.get('tick_id')} prof={data.get('pipeline_profile_id')} "
                f"id={data.get('transfer_id')} trig={data.get('trigger_id')} "
                f"{data.get('source_container_path')} -> {data.get('destination_container_path')} "
                f"amt={self._fmt_amount(data.get('amount'))} status={data.get('status')}"
            )
            self._record_account_movement(data)
        elif event_type == "invoice_transaction_event":
            self._log_pipeline(
                f"[bold yellow]invoice[/] T{data.get('tick_id')} due={data.get('simulation_date')} "
                f"id={data.get('invoice_id')} fee={data.get('fee_id')} "
                f"amt={self._fmt_amount(data.get('amount'))} status={data.get('status')}"
            )
        # ---- Books tab events (spec 60 §View C — ledger hierarchy) ----
        elif event_type == "posting_entry_event":
            self._log_books(
                f"[cyan]post[/] T{data.get('tick_id')} prof={data.get('pipeline_profile_id')} "
                f"id={data.get('posting_id')} trig={data.get('trigger_id')} "
                f"{data.get('source_ledger_path')} -> {data.get('destination_ledger_path')} "
                f"amt={self._fmt_amount(data.get('amount'))} "
                f"vd={data.get('value_date_policy')}={data.get('resolved_value_date')}"
            )
            self._record_book_movement(data)
        elif event_type == "settlement_resolution_event":
            self._log_books(
                f"[bold green]settle[/] T{data.get('tick_id')} inv={data.get('invoice_id')} "
                f"fee={data.get('fee_id')} mode={data.get('mode')} "
                f"settled={self._fmt_amount(data.get('settled_amount'))} "
                f"residual={self._fmt_amount(data.get('residual_amount'))} "
                f"final={data.get('final_status')}"
            )
        elif event_type == "world_restarting":
            gen = data.get("world_generation")
            reason = data.get("reason", "unknown")
            self._set_banner(f"⟳  World restarting (generation {gen}, reason: {reason})...")
            self._log_line(f"[magenta]world_restarting[/] gen={gen} reason={reason}")
            status.run_mode = "restarting"
        elif event_type == "world_restarted":
            gen = data.get("world_generation")
            self._set_banner("")
            self._log_line(f"[green]world_restarted[/] gen={gen} tick={data.get('tick_id')}")
            # Fresh world → drop accumulated hierarchy state so the Books/Accounts
            # views don't carry over balances from the previous world generation.
            self._books_by_path.clear()
            self._accounts_by_path.clear()
            self._render_books_tree()
            self._render_accounts_tree()
            snap = data.get("snapshot")
            if snap:
                self._apply_snapshot(snap)
        elif event_type == "world_restart_failed":
            gen = data.get("world_generation")
            reason = data.get("rejection_reason", "unknown")
            codes = data.get("error_codes", [])
            self._set_banner("")
            self._log_line(
                f"[red]world_restart_failed[/] gen={gen} "
                f"codes={codes} reason={reason}"
            )
        elif event_type == "speed_changed":
            # Spec 51/52: server-authoritative speed update. Refresh local
            # state + button label; tick_committed's inter_tick_wait_ms is
            # already speed-adjusted on the next emission so countdown math
            # needs no changes here.
            new_speed = float(data.get("speed_multiplier", 1.0))
            prev = float(data.get("previous_multiplier", self._speed_multiplier))
            self._speed_multiplier = new_speed
            self._refresh_speed_button()
            self._log_line(
                f"[cyan]speed_changed[/] {prev:g}× → {new_speed:g}× "
                f"(intake={self._format_ms(int(data.get('effective_intake_window_ms', 0)))}, "
                f"tick={self._format_ms(int(data.get('effective_tick_wall_clock_base_ms', 0)))})"
            )
        elif event_type == "server_shutdown":
            self._server_shutdown_received = True
            reason = data.get("reason", "unknown")
            grace_ms = data.get("grace_period_ms", 0)
            reconnect_ms = data.get("reconnect_after_ms", 2000)
            will_restart = bool(data.get("will_restart", False))
            self._reconnect_after_ms = reconnect_ms
            self._server_will_restart = will_restart
            status.run_mode = "shutting_down"
            self._set_banner(
                f"⚠  Server shutdown: {reason}. "
                f"will_restart={will_restart}. "
                f"Reconnect hint: {self._format_ms(reconnect_ms)}"
            )
            self._log_line(
                f"[yellow]server_shutdown[/] reason={reason} "
                f"grace={self._format_ms(grace_ms)} "
                f"reconnect_after={self._format_ms(reconnect_ms)} "
                f"will_restart={will_restart}"
            )

    def _apply_snapshot(self, snap: dict) -> None:
        status = self.query_one("#status", StatusBar)
        status.tick_id = snap.get("tick_id", 0)
        status.run_mode = snap.get("run_mode", snap.get("engine_state", "idle"))
        status.intake_open = snap.get("intake_open", False)
        status.intake_frozen = snap.get("intake_frozen", False)
        status.world_generation = snap.get("world_generation", 0)
        # v2 foundations (spec 40): scenario time + currency context.
        status.simulation_date = snap.get("simulation_date") or ""
        status.default_currency = snap.get("default_currency") or ""

        if status.intake_frozen:
            rem = snap.get("intake_remaining_ms") or 0
            self._frozen_remaining_ms = int(rem)

        cfg = snap.get("config", {})
        if "intake_window_ms" in cfg:
            # Only seed the total if we're not already tracking a live countdown
            if self._intake_countdown_ms == 0:
                self._intake_countdown_ms = cfg["intake_window_ms"]
        if "amount_scale_dp" in cfg:
            self._amount_scale_dp = int(cfg["amount_scale_dp"])
        # Note: tick_wall_clock_base_ms in snapshot is informational only; the
        # TUI's "next tick" countdown uses inter_tick_wait_ms from tick_committed.

        # Speed pacing (spec 51/52). Snapshot carries server-authoritative
        # multiplier + effective durations — sync local state + button label.
        if "speed_multiplier" in snap:
            self._speed_multiplier = float(snap["speed_multiplier"])
            self._refresh_speed_button()

        # Vendor / product info (spec 60 §Numeric presentation: counts as
        # integers, amounts at configured scale).
        vendor_lines = []
        for vid, vdata in snap.get("vendors", {}).items():
            vendor_lines.append(
                f"[bold]{vdata['vendor_label']}[/] (operational={vdata['operational']})"
            )
            for pid, pdata in vdata.get("products", {}).items():
                ob_flag = "[green]Y[/]" if pdata["accepting_onboard"] else "[red]N[/]"
                tx_flag = "[green]Y[/]" if pdata["accepting_transact"] else "[red]N[/]"
                vendor_lines.append(
                    f"  {pdata['product_label']}  "
                    f"ob={ob_flag} tx={tx_flag}  "
                    f"onboarded={self._fmt_count(pdata['onboarded_pop_count'])}  "
                    f"txns={self._fmt_count(pdata['successful_transact_count'])}  "
                    f"amt={self._fmt_amount(pdata['successful_transact_amount'])}"
                )
        self.query_one("#vendor-info", Static).update("\n".join(vendor_lines) or "No vendors")

        # Agent-controls target list — rebuild from snapshot so reloads pick up
        # new vendor/product shape (spec 51 §Agent controls requires explicit target).
        self._refresh_agent_targets(snap)

        # Pop info
        pop_lines = []
        for pid, pdata in snap.get("pops", {}).items():
            pop_lines.append(
                f"[bold]{pdata['pop_label']}[/] "
                f"(count={self._fmt_count(pdata['pop_count'])})"
            )
            for link in pdata.get("product_links", []):
                if link["known"]:
                    pop_lines.append(
                        f"  → {link['vendor_id']}/{link['product_id']}  "
                        f"onboarded={self._fmt_count(link['onboarded_count'])}"
                    )
        self.query_one("#pop-info", Static).update("\n".join(pop_lines) or "No pops")

    # ------------------------------------------------------------------ Books / Accounts aggregation (spec 60 §Views C/D)

    def _record_book_movement(self, d: dict) -> None:
        """Update book hierarchy from a posting_entry_event.

        Books group by product_id -> ledger_ref -> path. We track aggregate
        debit totals per destination_path and credit totals per source_path
        so the tree view shows a running sum; full balance reconciliation lives
        in the engine SQLite store.
        """
        amount = d.get("amount") or {}
        amt_val = 0.0
        if isinstance(amount, dict):
            try:
                amt_val = float(amount.get("amount", 0))
            except (TypeError, ValueError):
                amt_val = 0.0
        currency = amount.get("currency") if isinstance(amount, dict) else None
        product = d.get("product_id") or "(unknown)"
        for path, ref, sign in (
            (d.get("source_ledger_path"), d.get("source_ledger_ref"), -1.0),
            (d.get("destination_ledger_path"), d.get("destination_ledger_ref"), +1.0),
        ):
            if not path:
                continue
            key = f"{product}::{path}"
            entry = self._books_by_path.setdefault(key, {
                "product_id": product,
                "ledger_ref": ref,
                "path": path,
                "currency": currency,
                "net": 0.0,
                "n": 0,
            })
            entry["net"] += sign * amt_val
            entry["n"] += 1
        self._render_books_tree()

    def _record_account_movement(self, d: dict) -> None:
        """Update account hierarchy from a value_transfer_event."""
        amount = d.get("amount") or {}
        amt_val = 0.0
        if isinstance(amount, dict):
            try:
                amt_val = float(amount.get("amount", 0))
            except (TypeError, ValueError):
                amt_val = 0.0
        currency = amount.get("currency") if isinstance(amount, dict) else None
        product = d.get("product_id") or "(unknown)"
        for path, ref, sign in (
            (d.get("source_container_path"), d.get("source_container_ref"), -1.0),
            (d.get("destination_container_path"), d.get("destination_container_ref"), +1.0),
        ):
            if not path:
                continue
            key = f"{product}::{path}"
            entry = self._accounts_by_path.setdefault(key, {
                "product_id": product,
                "container_ref": ref,
                "path": path,
                "currency": currency,
                "net": 0.0,
                "n": 0,
            })
            entry["net"] += sign * amt_val
            entry["n"] += 1
        self._render_accounts_tree()

    def _render_books_tree(self) -> None:
        """Render a product-grouped hierarchy of ledger paths + net balances."""
        try:
            widget = self.query_one("#books-tree", Static)
        except Exception:
            return
        if not self._books_by_path:
            widget.update("(no postings yet)")
            return
        by_product: dict[str, list[dict]] = {}
        for entry in self._books_by_path.values():
            by_product.setdefault(entry["product_id"], []).append(entry)
        lines: list[str] = []
        for pid in sorted(by_product):
            lines.append(f"[bold]{pid}[/]")
            for entry in sorted(by_product[pid], key=lambda e: e["path"]):
                ccy = entry["currency"] or ""
                lines.append(
                    f"  {entry['path']}  "
                    f"[dim]ref={entry['ledger_ref']} n={entry['n']}[/]  "
                    f"net={entry['net']:,.{self._amount_scale_dp}f} {ccy}".rstrip()
                )
        widget.update("\n".join(lines))

    def _render_accounts_tree(self) -> None:
        """Render a product-grouped hierarchy of container paths + net balances."""
        try:
            widget = self.query_one("#accounts-tree", Static)
        except Exception:
            return
        if not self._accounts_by_path:
            widget.update("(no transfers yet)")
            return
        by_product: dict[str, list[dict]] = {}
        for entry in self._accounts_by_path.values():
            by_product.setdefault(entry["product_id"], []).append(entry)
        lines: list[str] = []
        for pid in sorted(by_product):
            lines.append(f"[bold]{pid}[/]")
            for entry in sorted(by_product[pid], key=lambda e: e["path"]):
                ccy = entry["currency"] or ""
                lines.append(
                    f"  {entry['path']}  "
                    f"[dim]ref={entry['container_ref']} n={entry['n']}[/]  "
                    f"net={entry['net']:,.{self._amount_scale_dp}f} {ccy}".rstrip()
                )
        widget.update("\n".join(lines))

    def _refresh_agent_targets(self, snap: dict) -> None:
        """Populate the agent-controls target selector from snapshot vendors/products.

        Spec 51 §Agent controls: commands require explicit agent/product target
        context. The select widget enumerates every (vendor_id, product_id) pair
        and is the required input for gate-change commands.
        """
        targets: list[tuple[str, str, str]] = []
        for vid, vdata in snap.get("vendors", {}).items():
            vlabel = vdata.get("vendor_label", vid)
            for pid, pdata in vdata.get("products", {}).items():
                plabel = pdata.get("product_label", pid)
                targets.append((vid, pid, f"{vlabel} / {plabel}"))
        if targets == self._agent_targets:
            return
        self._agent_targets = targets
        try:
            select = self.query_one("#agent-target-select", Select)
        except Exception:
            return
        options = [(label, f"{vid}::{pid}") for vid, pid, label in targets]
        if not options:
            options = [("(no target)", "__none__")]
        select.set_options(options)
        # Preserve previous selection if still valid; otherwise pick the first.
        keys = {v for _, v in options}
        if self._selected_target_key not in keys:
            self._selected_target_key = options[0][1]
        select.value = self._selected_target_key

    def _resolve_target(self) -> tuple[str | None, str | None]:
        """Return (vendor_id, product_id) for the currently-selected target, or (None, None)."""
        try:
            select = self.query_one("#agent-target-select", Select)
        except Exception:
            return None, None
        val = select.value
        if not val or val == "__none__":
            return None, None
        self._selected_target_key = val
        try:
            vid, pid = val.split("::", 1)
            return vid, pid
        except ValueError:
            return None, None

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "agent-target-select":
            self._selected_target_key = event.value  # type: ignore[assignment]

    # ------------------------------------------------------------------ speed display

    def _refresh_speed_button(self) -> None:
        """Update the Run-strip speed button label + active highlight.

        Label format: "Speed: 2×" — integer-typed when the multiplier is a
        whole number, otherwise a compact decimal so arbitrary-scalar values
        set via API (per spec 51) are readable.
        """
        try:
            btn = self.query_one("#btn-speed", Button)
        except Exception:
            return
        m = self._speed_multiplier
        if abs(m - round(m)) < 1e-6:
            label = f"Speed: {int(round(m))}×"
        else:
            label = f"Speed: {m:g}×"
        btn.label = label
        # Variant acts as visual highlight: baseline 1× keeps the neutral look,
        # anything faster uses `warning` so operators notice they're off-default.
        btn.variant = "default" if abs(m - 1.0) < 1e-6 else "warning"

    # ------------------------------------------------------------------ button handlers

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        try:
            if bid == "btn-resume":
                r = await self._http.post("/control/resume")
                self._log_control_response("resume", r)
            elif bid == "btn-pause":
                r = await self._http.post("/control/pause")
                self._log_control_response("pause", r)
            elif bid == "btn-next-day":
                r = await self._http.post("/control/next_day")
                self._log_control_response("next_day", r)
            elif bid == "btn-reload":
                r = await self._http.post("/control/reload_config")
                self._log_control_response("reload_config", r)
            elif bid == "btn-shutdown":
                r = await self._http.post("/control/shutdown")
                self._log_control_response("shutdown", r)
            elif bid == "btn-speed":
                # Spec 51/52: cycle 1× → 2× → 3× → 1×. Compute next value from
                # the server-authoritative _speed_multiplier (updated via
                # speed_changed + state_snapshot), then POST.
                cycle = self._speed_cycle
                current = self._speed_multiplier
                try:
                    idx = cycle.index(current)
                    nxt = cycle[(idx + 1) % len(cycle)]
                except ValueError:
                    # Current speed isn't on the cycle (e.g., API-set arbitrary
                    # scalar). Snap to 1× to give the operator a known-good step.
                    nxt = cycle[0]
                r = await self._http.post("/control/speed", json={"multiplier": nxt})
                self._log_control_response("speed", r)
            elif bid in ("btn-open-ob", "btn-close-ob", "btn-open-tx", "btn-close-tx"):
                ctype = {
                    "btn-open-ob": "OpenOnboarding",
                    "btn-close-ob": "CloseOnboarding",
                    "btn-open-tx": "OpenTransacting",
                    "btn-close-tx": "CloseTransacting",
                }[bid]
                vid, pid = self._resolve_target()
                if vid is None or pid is None:
                    self._log_line(
                        f"[red]{ctype}[/] rejected locally: "
                        "no agent target selected (spec 51 §Agent controls)"
                    )
                    return
                await self._http.post("/command", json={
                    "command_id": str(uuid.uuid4()),
                    "command_type": ctype,
                    "vendor_id": vid,
                    "product_id": pid,
                })
        except httpx.RequestError as exc:
            self._log_line(f"[red]HTTP error: {exc}[/]")

    def _log_control_response(self, action: str, resp) -> None:
        try:
            body = resp.json()
        except Exception:
            body = {}
        effect = body.get("effect", "")
        mode = body.get("run_mode", "")
        reason = body.get("rejection_reason")
        if reason:
            self._log_line(f"[red]{action}[/] effect={effect} run_mode={mode} reason={reason}")
        else:
            self._log_line(f"[cyan]{action}[/] effect={effect} run_mode={mode}")

    async def on_unmount(self) -> None:
        await self._http.aclose()

    # Keyboard actions (spec 60 §Accessibility).

    def action_focus_log(self) -> None:
        try:
            self.query_one("#event-log", RichLog).focus()
        except Exception:
            pass

    def action_focus_controls(self) -> None:
        try:
            self.query_one("#btn-resume", Button).focus()
        except Exception:
            pass

    async def action_resume(self) -> None:
        try:
            r = await self._http.post("/control/resume")
            self._log_control_response("resume", r)
        except httpx.RequestError as exc:
            self._log_line(f"[red]HTTP error: {exc}[/]")

    async def action_pause(self) -> None:
        try:
            r = await self._http.post("/control/pause")
            self._log_control_response("pause", r)
        except httpx.RequestError as exc:
            self._log_line(f"[red]HTTP error: {exc}[/]")

    async def action_next_day(self) -> None:
        try:
            r = await self._http.post("/control/next_day")
            self._log_control_response("next_day", r)
        except httpx.RequestError as exc:
            self._log_line(f"[red]HTTP error: {exc}[/]")

    def _switch_tab(self, tab_id: str) -> None:
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            tabs.active = tab_id
        except Exception:
            pass

    def action_view_world(self) -> None:
        self._switch_tab("tab-world")

    def action_view_pipeline(self) -> None:
        self._switch_tab("tab-pipeline")

    def action_view_books(self) -> None:
        self._switch_tab("tab-books")

    def action_view_accounts(self) -> None:
        self._switch_tab("tab-accounts")

    def action_view_logs(self) -> None:
        self._switch_tab("tab-logs")

    async def action_shutdown_server(self) -> None:
        try:
            r = await self._http.post("/control/shutdown")
            self._log_control_response("shutdown", r)
        except httpx.RequestError as exc:
            self._log_line(f"[red]HTTP error: {exc}[/]")

    def _pick_copy_target(self) -> "RichLog | None":
        """Pick which RichLog to copy from (focused log, else active-tab log)."""
        focused = self.focused
        if isinstance(focused, RichLog):
            return focused
        try:
            active = self.query_one("#tabs", TabbedContent).active
        except Exception:
            active = ""
        tab_log = {
            "tab-logs": "event-log",
            "tab-pipeline": "pipeline-log",
            "tab-books": "books-log",
            "tab-accounts": "accounts-log",
        }.get(active, "event-log")
        for lid in (tab_log, "event-log", "pipeline-log", "books-log", "accounts-log"):
            try:
                return self.query_one(f"#{lid}", RichLog)
            except Exception:
                continue
        return None

    @staticmethod
    def _log_to_plain_text(target: "RichLog") -> str:
        """Collect the RichLog's text content as plain text, one line per entry.

        RichLog defers write() until the widget is sized — so a log in an
        inactive tab holds its lines in `_deferred_renders` and `lines` stays
        empty. For operator copy UX, we want both rendered + deferred content;
        fall back to the deferred buffer so Ctrl+C still produces something
        useful from an off-screen log.
        """
        # Prefer already-rendered strips (they carry the actual displayed text).
        rendered = []
        for strip in getattr(target, "lines", []) or []:
            text = getattr(strip, "text", None)
            rendered.append(text if text is not None else str(strip))
        if rendered:
            return "\n".join(rendered)
        # Fallback: drain the deferred write queue. Keeps Rich markup tokens
        # in the copied text — acceptable because operators typically paste
        # into tickets or chat where markup renders or is trivially stripped.
        deferred = []
        for dr in getattr(target, "_deferred_renders", []) or []:
            content = getattr(dr, "content", None)
            if content is None:
                continue
            deferred.append(str(content))
        return "\n".join(deferred)

    def action_copy_focused_log(self) -> None:
        """Copy the focused log's line selection (or full content) to clipboard.

        Ctrl+C copy priority (spec 60 §Accessibility: operator workflows remain
        keyboard-reachable):

          1. `SelectableRichLog.copy_text()` — precise line-range selection
             the operator picked with Up/Down + Shift+Up/Down (the ordinary
             case: "copy just THIS line please").
          2. The widget's mouse-driven `text_selection` if any — only fires on
             widgets whose container actually delivers drag-as-selection
             events; `ScrollableContainer`-rooted widgets usually don't, which
             is exactly why we added the keyboard line cursor.
          3. Full log buffer — last-resort dump. Operator probably wanted a
             single line; log which was used so they can retry with a
             selection.
        """
        target = self._pick_copy_target()
        if target is None:
            return
        text = ""
        mode = "empty"
        # 1. Keyboard-driven line selection on our custom widget.
        copy_text = getattr(target, "copy_text", None)
        if callable(copy_text):
            try:
                picked = copy_text()
                if picked:
                    text = picked
                    mode = "selection"
            except Exception:
                pass
        # 2. Generic widget text_selection (mouse-drag selection).
        if not text:
            try:
                selection = target.text_selection
                if selection is not None:
                    text = target.get_selection(selection) or ""
                    if text:
                        mode = "mouse-selection"
            except Exception:
                text = ""
        # 3. Whole log.
        if not text:
            text = self._log_to_plain_text(target)
            if text:
                mode = "full-log"
        if not text:
            return
        try:
            self.copy_to_clipboard(text)
        except Exception:
            return
        self._log_line(
            f"[dim]copied {len(text)} chars from #{target.id} "
            f"({mode}) to clipboard[/]"
        )


# ------------------------------------------------------------------ entrypoint

def main() -> None:
    parser = argparse.ArgumentParser(description="Payments Mogul TUI Client")
    parser.add_argument("--url", default=BASE_URL, help="Engine base URL")
    args = parser.parse_args()
    MogulApp(base_url=args.url).run()


if __name__ == "__main__":
    main()
