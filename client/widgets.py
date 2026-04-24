"""TUI widgets with first-class terminal support for line selection + copy.

Background: Textual's `RichLog` inherits from `ScrollableContainer`. Terminal
mouse drag inside a scrollable container isn't reliably delivered as selection
events — the scrollable widget consumes drag for scrolling, and terminals may
also claim drag for their own selection ahead of Textual. Net effect: operators
can't pick specific log lines with the mouse even though `ALLOW_SELECT=True`.

`SelectableRichLog` is a keyboard-driven alternative: focus the log, press
up/down (or j/k) to move a line cursor, shift+up/down to extend a range,
ctrl+a to select all, escape to clear. The cursor / selected lines render in
reverse-video so the active selection is unambiguous. `copy_text()` returns
just the selected line(s) — not the whole buffer — so the app-level Ctrl+C
handler can push a precise selection to the clipboard via OSC 52.

Spec anchor: spec 60 §Accessibility and operability — "Active section content
and logs view are independently focusable scroll regions" + mandate that
operator workflows remain keyboard-reachable. This subclass is what lets
"copy just this line" actually work in a terminal.
"""

from __future__ import annotations

from rich.style import Style
from textual.binding import Binding
from textual.reactive import reactive
from textual.strip import Strip
from textual.widgets import RichLog


class SelectableRichLog(RichLog):
    """RichLog with keyboard-driven line cursor + range selection.

    Navigation (when focused):
        up / k          move cursor up 1 line (clears range)
        down / j        move cursor down 1 line (clears range)
        home / g        jump to first line
        end / G         jump to last line
        shift+up        extend selection upward
        shift+down      extend selection downward
        ctrl+a          select all lines
        escape          clear cursor + selection
        enter           no-op (reserved for future drill-down)

    App-level `ctrl+c` binding calls `copy_text()`; this widget's `copy_text()`
    returns the currently selected line(s) joined by newlines, or the cursor
    line if no range is active, or "" if no cursor is set (in which case the
    app falls back to copying the full log content — the v3 final-touch
    "Copy log" behavior).
    """

    ALLOW_SELECT = True
    can_focus = True

    # Selection state. `cursor_line` is the line index the cursor is on;
    # `selection_anchor` is the other end of a shift-extended range.
    cursor_line: reactive[int | None] = reactive(None)
    selection_anchor: reactive[int | None] = reactive(None)

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("home", "cursor_home", "Top", show=False),
        Binding("g", "cursor_home", "Top", show=False),
        Binding("end", "cursor_end", "Bottom", show=False),
        Binding("G", "cursor_end", "Bottom", show=False),
        Binding("shift+up", "extend_up", "Select up", show=False),
        Binding("shift+down", "extend_down", "Select down", show=False),
        Binding("ctrl+a", "select_all", "Select all", show=False),
        Binding("escape", "clear_selection", "Clear", show=False),
    ]

    # ------------------------------------------------------------------ cursor navigation

    def _ensure_cursor(self) -> int:
        """Guarantee `cursor_line` is set to a valid index.

        Defaults to the last line when the log has content (mirrors operator
        expectation: "the interesting stuff is at the bottom").
        """
        last = max(self.line_count - 1, 0)
        if self.cursor_line is None or not (0 <= self.cursor_line <= last):
            self.cursor_line = last
        return self.cursor_line  # type: ignore[return-value]

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def _refresh_lines(self, *lines: int) -> None:
        """Refresh the given absolute line indices (ignore out-of-range)."""
        for y in lines:
            if 0 <= y < self.line_count:
                self.refresh_line(y)

    def _move_cursor(self, new_idx: int, extend: bool) -> None:
        last = max(self.line_count - 1, 0)
        if last < 0:
            return
        new_idx = max(0, min(last, new_idx))
        prev_cursor = self.cursor_line
        prev_anchor = self.selection_anchor

        if extend:
            # On first extend, plant the anchor where the cursor currently sits.
            if self.selection_anchor is None:
                self.selection_anchor = prev_cursor if prev_cursor is not None else new_idx
        else:
            # Non-extending move clears any in-progress range.
            self.selection_anchor = None

        self.cursor_line = new_idx
        # Keep the cursor line in view.
        self.scroll_to(y=max(0, new_idx - (self.size.height // 2) + 1), animate=False)

        # Repaint the old + new cursor lines (and the anchor gap, cheaply by
        # repainting the full visible region when a range changes).
        if extend:
            self.refresh()
        else:
            indices = {i for i in (prev_cursor, prev_anchor, new_idx) if i is not None}
            self._refresh_lines(*indices)

    def action_cursor_up(self) -> None:
        cur = self._ensure_cursor()
        self._move_cursor(cur - 1, extend=False)

    def action_cursor_down(self) -> None:
        cur = self._ensure_cursor()
        self._move_cursor(cur + 1, extend=False)

    def action_cursor_home(self) -> None:
        self._ensure_cursor()
        self._move_cursor(0, extend=False)

    def action_cursor_end(self) -> None:
        self._ensure_cursor()
        self._move_cursor(max(self.line_count - 1, 0), extend=False)

    def action_extend_up(self) -> None:
        cur = self._ensure_cursor()
        self._move_cursor(cur - 1, extend=True)

    def action_extend_down(self) -> None:
        cur = self._ensure_cursor()
        self._move_cursor(cur + 1, extend=True)

    def action_select_all(self) -> None:
        if self.line_count == 0:
            return
        self.selection_anchor = 0
        self.cursor_line = self.line_count - 1
        self.refresh()

    def action_clear_selection(self) -> None:
        self.cursor_line = None
        self.selection_anchor = None
        self.refresh()

    # ------------------------------------------------------------------ selection helpers

    def _selected_range(self) -> tuple[int, int] | None:
        """Return (lo, hi) inclusive bounds of the current selection, or None."""
        if self.cursor_line is None:
            return None
        if self.selection_anchor is None:
            return self.cursor_line, self.cursor_line
        lo, hi = sorted((self.cursor_line, self.selection_anchor))
        return lo, hi

    def copy_text(self) -> str:
        """Return the plain-text content of the currently selected line(s).

        Returns "" if no cursor is set. Caller (typically `App`) falls back to
        copying the full log buffer in that case.
        """
        bounds = self._selected_range()
        if bounds is None:
            return ""
        lo, hi = bounds
        out: list[str] = []
        for i in range(lo, hi + 1):
            if 0 <= i < self.line_count:
                strip = self.lines[i]
                text = getattr(strip, "text", None)
                out.append(text if text is not None else str(strip))
        return "\n".join(out)

    # ------------------------------------------------------------------ render

    def render_line(self, y: int) -> Strip:
        # Ask the parent to produce the content strip for this visible row,
        # then reverse-style it if the corresponding absolute line index is
        # inside the selection.
        strip = super().render_line(y)
        scroll_x, scroll_y = self.scroll_offset
        abs_line = scroll_y + y
        bounds = self._selected_range()
        if bounds is not None:
            lo, hi = bounds
            if lo <= abs_line <= hi:
                # `reverse` swaps fg/bg and is universally supported in terminals;
                # it works alongside existing Rich styling without conflict.
                return strip.apply_style(Style(reverse=True))
        return strip

    # Re-render cursor line on focus transitions so the indicator appears/goes.
    def on_focus(self) -> None:
        self._ensure_cursor()
        self.refresh()

    def on_blur(self) -> None:
        # Keep the selection alive across blur — operators may click into the
        # clipboard/ack-label area and want their selection preserved. Only
        # explicit escape clears.
        pass
