#!/usr/bin/env python3
"""Design tokens mirroring ui-tokens.md.

Both CSS hex strings and Cairo (r,g,b) tuples live here so no component
hardcodes a value. Import this module, never copy a literal.

Accent color, corner radius, and reduce-motion are user-configurable via
Settings (darkos-settings.py) — see user_settings.py. They're read once at
import time, so a change takes effect on the next shell restart.
"""
from darkos_shell.user_settings import load_settings

_settings = load_settings()


def _hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


# ── Color ────────────────────────────────────────────────────────────
COLOR_BG = "#000000"
COLOR_BG_ALT = "#0d0f12"
COLOR_BG_ELEVATED = "#16181c"
COLOR_TEXT = "#f2f5f7"
COLOR_TEXT_MUTED = "#9aa4ad"
COLOR_PRIMARY = _settings.get("accent_color") or "#00e5ff"
COLOR_SECONDARY = "#2d7bff"
COLOR_ACCENT = "#a855f7"
COLOR_WARNING = "#ff8a00"
COLOR_DANGER = "#ff3b3b"
COLOR_SUCCESS = "#22e07a"
COLOR_BORDER = "#ffffff"

CAIRO_PRIMARY = _hex_to_rgb(COLOR_PRIMARY)
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
RADIUS_PANEL = int(_settings.get("corner_radius") or 16)
RADIUS_DIALOG = 24

# ── Motion ───────────────────────────────────────────────────────────
# Consulted by animation call sites that have been wired to check it
# (see surfaces.py's _HUDCanvas); not yet threaded through every animated
# surface in the shell — a real incremental follow-up, not a silent gap.
REDUCE_MOTION = bool(_settings.get("reduce_motion"))

# ── Typography ───────────────────────────────────────────────────────
FONT_BODY = "Inter, \"SF Pro Display\", sans-serif"
FONT_HEADING = "\"Space Grotesk\", sans-serif"
FONT_MONO = "\"JetBrains Mono\", \"Fira Code\", monospace"

