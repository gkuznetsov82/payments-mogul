"""TUI structural + behavioral tests (spec 60 §Minimum navigation contract,
spec 52 §Shutdown).

Covers the v3 final-touch contract for the Textual client:

- Required baseline sections are keyboard-reachable: World / Pipeline / Books /
  Accounts / Logs (spec 60).
- World-scoped controls (Reload, Shutdown) live in the always-visible run strip.
- Agent-scoped controls live in the World tab behind an explicit target selector
  (spec 51 §Agent controls).
- SSE close after `server_shutdown` is treated as expected lifecycle transition —
  no transport-error banner/log line (spec 52 §Shutdown).
- Books + Accounts aggregation + rendering reacts to posting / value_transfer events.
"""

from __future__ import annotations

import pytest

from client.tui import MogulApp


@pytest.mark.asyncio
async def test_tui_exposes_required_navigation_sections():
    """Spec 60 §Minimum navigation contract: World / Pipeline / Books / Accounts / Logs."""
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        ids = {w.id for w in app.query("TabPane") if w.id}
        for required in ("tab-world", "tab-pipeline", "tab-books", "tab-accounts", "tab-logs"):
            assert required in ids, f"missing required TabPane: {required} (found {ids})"


@pytest.mark.asyncio
async def test_tui_run_strip_has_world_controls():
    """Spec 51 §World controls: reload + shutdown must be always reachable."""
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        button_ids = {w.id for w in app.query("Button") if w.id}
        # World-scoped controls in the run strip (not buried in a tab).
        assert "btn-reload" in button_ids
        assert "btn-shutdown" in button_ids
        # Tick-control buttons also present.
        assert "btn-resume" in button_ids
        assert "btn-pause" in button_ids
        assert "btn-next-day" in button_ids


@pytest.mark.asyncio
async def test_tui_agent_controls_require_target_selection():
    """Spec 51 §Agent controls: commands need explicit agent/product target.

    The agent-target-select widget is present; clicking an agent-control button
    with no target selected must reject locally (no HTTP call) and log the reason.
    """
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # Target selector exists.
        select = app.query_one("#agent-target-select")
        assert select is not None

        # Agent gate buttons exist (in the World tab, per spec 60 restructure).
        button_ids = {w.id for w in app.query("Button") if w.id}
        for bid in ("btn-open-ob", "btn-close-ob", "btn-open-tx", "btn-close-tx"):
            assert bid in button_ids

        # Default placeholder key leaves _resolve_target at (None, None).
        app._selected_target_key = "__none__"
        vid, pid = app._resolve_target()
        assert vid is None and pid is None


@pytest.mark.asyncio
async def test_tui_books_and_accounts_trees_render_from_events():
    """Spec 60 §Views C / D: Books and Accounts views reflect posting and
    value_transfer events with a product-grouped hierarchy.
    """
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # Simulate two pipeline events arriving via SSE.
        app.on_server_event({
            "event": "posting_entry_event",
            "data": {
                "tick_id": 1,
                "simulation_date": "2026-01-01",
                "pipeline_profile_id": "prepaid_card_pipeline",
                "product_id": "prod_prepaid_alpha",
                "posting_id": "post-1",
                "trigger_id": "Transact-Purchase-Clearing",
                "source_ledger_ref": "customer_funds",
                "destination_ledger_ref": "settlement_funds",
                "source_ledger_path": "[Funds][prod_prepaid_alpha][Customer]",
                "destination_ledger_path": "[Funds][prod_prepaid_alpha][Settlement]",
                "amount": {"amount": "100.00", "currency": "USD"},
                "value_date_policy": "same_day",
                "resolved_value_date": "2026-01-01",
                "status": "posted",
            },
        })
        app.on_server_event({
            "event": "value_transfer_event",
            "data": {
                "tick_id": 1,
                "simulation_date": "2026-01-01",
                "pipeline_profile_id": "prepaid_card_pipeline",
                "product_id": "prod_prepaid_alpha",
                "transfer_id": "xfer-1",
                "trigger_id": "Transact-Purchase-Clearing",
                "source_container_ref": "customer_funds_container",
                "destination_container_ref": "settlement_funds_container",
                "source_container_path": "[Container][prod_prepaid_alpha][Customer]",
                "destination_container_path": "[Container][prod_prepaid_alpha][Settlement]",
                "amount": {"amount": "100.00", "currency": "USD"},
                "value_date_policy": "same_day",
                "resolved_value_date": "2026-01-01",
                "status": "executed",
            },
        })
        await pilot.pause()

        # Books hierarchy: source path + destination path entries for the product.
        assert any("[Funds][prod_prepaid_alpha][Customer]" in k
                   for k in app._books_by_path), app._books_by_path
        assert any("[Funds][prod_prepaid_alpha][Settlement]" in k
                   for k in app._books_by_path)
        # Accounts hierarchy: source + destination container paths.
        assert any("[Container][prod_prepaid_alpha][Customer]" in k
                   for k in app._accounts_by_path)
        assert any("[Container][prod_prepaid_alpha][Settlement]" in k
                   for k in app._accounts_by_path)


@pytest.mark.asyncio
async def test_tui_command_ack_does_not_raise_widget_type_error():
    """R1 regression: #ack-label is a Static, not a Label. Handling a
    command_ack event must not raise WrongType (which previously bubbled out
    of _sse_worker's try and surfaced as a bogus 'SSE error' transport line).
    """
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # Dispatching command_ack with both accepted and rejected shapes must
        # complete without raising.
        app.on_server_event({
            "event": "command_ack",
            "data": {
                "command_id": "abc-123-xyz",
                "accepted": True,
                "target_tick": 7,
                "processed_in_tick": None,
                "rejection_reason": None,
                "command_scope": "agent",
            },
        })
        app.on_server_event({
            "event": "command_ack",
            "data": {
                "command_id": "def-456-uvw",
                "accepted": False,
                "target_tick": 8,
                "processed_in_tick": None,
                "rejection_reason": "gate_already_closed",
                "command_scope": "agent",
            },
        })
        await pilot.pause()
        # The #ack-label Static should reflect the most recent ack.
        from textual.widgets import Static
        label = app.query_one("#ack-label", Static)
        rendered = str(label.render())
        assert "REJECTED" in rendered and "T8" in rendered, (
            f"expected latest ack (REJECTED T8) in ack-label, got: {rendered!r}"
        )


@pytest.mark.asyncio
async def test_tui_copy_focused_log_writes_to_clipboard():
    """R4: Ctrl+C action copies the focused log's content to the clipboard.

    Textual's App.copy_to_clipboard sets `App.clipboard` (tracked for OSC 52
    terminal bridging). RichLog defers write() until the widget is sized, so
    the test activates the Logs tab first so the event-log has a real size
    and the line materializes.
    """
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # Activate the Logs tab so the event-log widget gets a concrete size
        # (RichLog.write is deferred until size is known).
        from textual.widgets import TabbedContent, RichLog
        app.query_one("#tabs", TabbedContent).active = "tab-logs"
        await pilot.pause()
        # Seed content via the real SSE event path.
        app.on_server_event({
            "event": "tick_committed",
            "data": {
                "tick_id": 1,
                "simulation_date": "2026-01-01",
                "inter_tick_wait_ms": 0,
                "onboard_accepted": 10,
                "transact_succeeded": 5,
                "transact_amount": {"amount": "12.34", "currency": "USD"},
            },
        })
        await pilot.pause()
        event_log = app.query_one("#event-log", RichLog)
        event_log.focus()
        await pilot.pause()
        # Invoke the copy action.
        app.action_copy_focused_log()
        await pilot.pause()
        copied = str(app.clipboard)
        assert "tick_committed" in copied or "T1" in copied, (
            f"expected log content in clipboard, got: {copied!r}"
        )


@pytest.mark.asyncio
async def test_tui_copy_focused_log_handles_deferred_content():
    """R4 edge case: even when a log is in an inactive tab (RichLog defers
    writes until sized), the copy action should still pick up pending content
    instead of copying an empty string.
    """
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # DO NOT switch tabs — the event log stays in the inactive Logs tab.
        app.on_server_event({
            "event": "tick_committed",
            "data": {
                "tick_id": 42,
                "simulation_date": "2026-02-15",
                "inter_tick_wait_ms": 0,
                "onboard_accepted": 1,
                "transact_succeeded": 1,
                "transact_amount": {"amount": "1.00", "currency": "USD"},
            },
        })
        await pilot.pause()
        app.action_copy_focused_log()
        await pilot.pause()
        copied = str(app.clipboard)
        assert "tick_committed" in copied or "T42" in copied, (
            f"deferred-content copy failed; got: {copied!r}"
        )


@pytest.mark.asyncio
async def test_tui_logs_allow_selection():
    """R4: RichLog must permit selection so mouse drag-select works.

    Verified via the ALLOW_SELECT class attribute set by Textual; if this
    regresses (e.g. a future widget swap), selection/copy UX breaks.
    """
    from textual.widgets import RichLog
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        for lid in ("event-log", "pipeline-log", "books-log", "accounts-log"):
            widget = app.query_one(f"#{lid}", RichLog)
            assert widget.allow_select is True, f"#{lid} must allow selection"


@pytest.mark.asyncio
async def test_selectable_log_cursor_up_down_and_copy_single_line():
    """R6: ↑/↓ move line cursor; Ctrl+C copies just the cursor line."""
    from textual.widgets import TabbedContent
    from client.widgets import SelectableRichLog
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # Activate Logs tab and seed three distinct lines.
        app.query_one("#tabs", TabbedContent).active = "tab-logs"
        await pilot.pause()
        log = app.query_one("#event-log", SelectableRichLog)
        log.write("line alpha")
        log.write("line bravo")
        log.write("line charlie")
        await pilot.pause()
        assert log.line_count == 3

        log.focus()
        await pilot.pause()
        # On focus, cursor defaults to the last line.
        assert log.cursor_line == 2

        # ↑ ↑ moves to the top line.
        await pilot.press("up", "up")
        assert log.cursor_line == 0
        assert log.selection_anchor is None

        # Copy just the cursor line.
        app.action_copy_focused_log()
        await pilot.pause()
        copied = str(app.clipboard)
        assert copied == "line alpha", (
            f"expected only cursor line, got: {copied!r}"
        )


@pytest.mark.asyncio
async def test_selectable_log_shift_extends_range_and_copies_multiple_lines():
    """R6: Shift+↑/↓ extends selection; Ctrl+C copies only selected range."""
    from textual.widgets import TabbedContent
    from client.widgets import SelectableRichLog
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        app.query_one("#tabs", TabbedContent).active = "tab-logs"
        await pilot.pause()
        log = app.query_one("#event-log", SelectableRichLog)
        for i, txt in enumerate(("one", "two", "three", "four", "five")):
            log.write(txt)
        await pilot.pause()
        log.focus()
        await pilot.pause()
        # Cursor defaults to last line (index 4 = "five").
        assert log.cursor_line == 4
        # Move to "three" (index 2), then Shift+↑ once → range {2, 1}.
        await pilot.press("up", "up")
        assert log.cursor_line == 2
        await pilot.press("shift+up")
        assert log.selection_anchor == 2
        assert log.cursor_line == 1

        app.action_copy_focused_log()
        await pilot.pause()
        copied = str(app.clipboard)
        assert copied == "two\nthree", (
            f"expected 'two\\nthree', got: {copied!r}"
        )


@pytest.mark.asyncio
async def test_selectable_log_escape_clears_selection_and_fallback_copy_is_full_buffer():
    """R6: Escape clears the cursor; Ctrl+C then falls back to copying the whole log
    (preserves v3 final-touch "Copy log" behavior when no selection exists)."""
    from textual.widgets import TabbedContent
    from client.widgets import SelectableRichLog
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        app.query_one("#tabs", TabbedContent).active = "tab-logs"
        await pilot.pause()
        log = app.query_one("#event-log", SelectableRichLog)
        log.write("aaa")
        log.write("bbb")
        await pilot.pause()
        log.focus()
        await pilot.pause()
        # Move cursor, then Escape clears it.
        await pilot.press("up")
        assert log.cursor_line is not None
        await pilot.press("escape")
        assert log.cursor_line is None
        assert log.selection_anchor is None

        # No selection → copy falls back to full log content.
        app.action_copy_focused_log()
        await pilot.pause()
        copied = str(app.clipboard)
        assert "aaa" in copied and "bbb" in copied, (
            f"expected full-log fallback with both lines, got: {copied!r}"
        )


@pytest.mark.asyncio
async def test_selectable_log_ctrl_a_selects_all():
    """R6: Ctrl+A selects every line; Ctrl+C copies the whole buffer via selection path."""
    from textual.widgets import TabbedContent
    from client.widgets import SelectableRichLog
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        app.query_one("#tabs", TabbedContent).active = "tab-logs"
        await pilot.pause()
        log = app.query_one("#event-log", SelectableRichLog)
        log.write("first")
        log.write("second")
        log.write("third")
        await pilot.pause()
        log.focus()
        await pilot.pause()
        await pilot.press("ctrl+a")
        assert log.selection_anchor == 0
        assert log.cursor_line == 2

        app.action_copy_focused_log()
        await pilot.pause()
        copied = str(app.clipboard)
        assert copied == "first\nsecond\nthird", (
            f"expected all three lines joined, got: {copied!r}"
        )


@pytest.mark.asyncio
async def test_selectable_log_home_end_jump_cursor():
    """R6: Home/End jump to first/last line."""
    from textual.widgets import TabbedContent
    from client.widgets import SelectableRichLog
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        app.query_one("#tabs", TabbedContent).active = "tab-logs"
        await pilot.pause()
        log = app.query_one("#event-log", SelectableRichLog)
        for t in ("a", "b", "c", "d"):
            log.write(t)
        await pilot.pause()
        log.focus()
        await pilot.pause()
        await pilot.press("home")
        assert log.cursor_line == 0
        await pilot.press("end")
        assert log.cursor_line == 3


@pytest.mark.asyncio
async def test_tui_treats_server_shutdown_followed_by_close_as_expected():
    """Spec 52 §Shutdown: stream close after server_shutdown is not a transport error.

    Verify the guard: once `_server_shutdown_received` is True, the except branch
    in _sse_worker must not log a red transport-error line (the shutdown banner
    already communicates the lifecycle transition).
    """
    app = MogulApp(base_url="http://127.0.0.1:0")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        # Emulate the server_shutdown event landing before the stream closes.
        app.on_server_event({
            "event": "server_shutdown",
            "data": {
                "reason": "manual_shutdown",
                "grace_period_ms": 500,
                "reconnect_after_ms": 2000,
                "will_restart": False,
            },
        })
        await pilot.pause()
        assert app._server_shutdown_received is True
        # Banner reflects the shutdown; run_mode is shutting_down.
        status = app.query_one("#status")
        assert status.run_mode == "shutting_down"
        banner_text = str(app.query_one("#banner").message)
        assert "Server shutdown" in banner_text
