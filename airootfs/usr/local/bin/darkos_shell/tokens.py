#!/usr/bin/env python3
"""Design tokens mirroring ui-tokens.md.

Both CSS hex strings and Cairo (r,g,b) tuples live here so no component
hardcodes a value. Import this module, never copy a literal.
"""

# ── Color ────────────────────────────────────────────────────────────
COLOR_BG = "#000000"
COLOR_BG_ALT = "#0d0f12"
COLOR_BG_ELEVATED = "#16181c"
COLOR_TEXT = "#f2f5f7"
COLOR_TEXT_MUTED = "#9aa4ad"
COLOR_PRIMARY = "#00e5ff"
COLOR_SECONDARY = "#2d7bff"
COLOR_ACCENT = "#a855f7"
COLOR_WARNING = "#ff8a00"
COLOR_DANGER = "#ff3b3b"
COLOR_SUCCESS = "#22e07a"
COLOR_BORDER = "#ffffff"

CAIRO_PRIMARY = (0.0, 0.898, 1.0)
CAIRO_SECONDARY = (0.176, 0.482, 1.0)
CAIRO_ACCENT = (0.659, 0.333, 0.969)
CAIRO_TEXT = (0.949, 0.961, 0.969)
CAIRO_MUTED = (0.604, 0.643, 0.678)
CAIRO_DANGER = (1.0, 0.231, 0.231)

# ── Glow ─────────────────────────────────────────────────────────────
# Three strokes painted outside-in: outer haze, mid glow, sharp core.
# Alpha decreases away from the source.
GLOW_STROKES_OUTSIDE_IN = (
    (10.0, 0.12),
    (5.0, 0.40),
    (2.0, 1.0),
)

# ── Spacing ──────────────────────────────────────────────────────────
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 32
SPACE_XL = 48

# ── Radius ───────────────────────────────────────────────────────────
RADIUS_CONTROL = 8
RADIUS_PANEL = 16
RADIUS_DIALOG = 24

# ── Typography ───────────────────────────────────────────────────────
FONT_BODY = "Inter, \"SF Pro Display\", sans-serif"
FONT_HEADING = "\"Space Grotesk\", sans-serif"
FONT_MONO = "\"JetBrains Mono\", \"Fira Code\", monospace"
