# Design Tokens

**Status:** Draft

## Purpose

Industrial/command-center visual system: Tailwind-oriented tokens.

## Contents (to complete)

- Color palette (slate, charcoal, cold grays; alert accents)
- Typography (JetBrains Mono / Berkeley Mono strategy)
- Radii / borders (sharp; avoid plastic)
- Spacing, focus rings, motion (if any)

---

## TUI layout and accessibility tokens (prototype)

- `tui.viewport.baseline_cols`: `120`
- `tui.viewport.baseline_rows`: `36`
- `tui.viewport.compact_cols`: `100`
- `tui.viewport.min_supported_cols`: `80`
- `tui.viewport.min_supported_rows`: `24`
- `tui.control_pane.min_cols`: `26`
- `tui.control_pane.max_cols`: `32`
- `tui.event_log.min_rows`: `8`
- `tui.focus.ring_style`: high-contrast solid
- `tui.scroll.hint_style`: visible top/bottom overflow markers

These values define defaults for text-UI scaling behavior; implementation may tune exact numbers if equivalent accessibility/visibility guarantees from **`12-ui-ux-spec.md`** and **`60-screen-specs.md`** are preserved.
