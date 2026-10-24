#!/usr/bin/env python3
"""Design tokens: the source of truth for colors, type, spacing, radii and motion.

"Calm Dark" (docs/MASTER-PLAN.md section 5). Colours are *generated* by
darkos_shell/palette.py from the accent seed, so the surfaces, the text
colours and the accent text/label colours always meet the contrast rules.
Both CSS hex strings and Cairo (r,g,b) tuples live here so no component
hardcodes a value. Import this module, never copy a literal.

Accent color, corner radius, reduce-motion and high-contrast are
user-configurable via Settings (darkos-settings.py) -- see user_settings.py.
They're read once at import time, so a change takes effect on the next shell
restart (the Settings page says so). Only the dock position/size are applied
live.

Old names (COLOR_BG, COLOR_BG_ALT, COLOR_PRIMARY, COLOR_SECONDARY ...) are kept
as aliases so every app keeps working; new code should use the SURFACE_*,
ACCENT and TEXT_* names.
"""
from collections import namedtuple

from darkos_shell import palette as _palette
from darkos_shell.user_settings import CHOICES, load_settings

_settings = load_settings()

# ── Modes ────────────────────────────────────────────────────────────
# REDUCE_MOTION is consulted by the animation call sites that have been
# wired to check it; the shell itself no longer animates anything of its
# own (motion budget: compositor animations only, see hyprland.conf).
REDUCE_MOTION = bool(_settings.get("reduce_motion"))
HIGH_CONTRAST = bool(_settings.get("high_contrast"))

# ── Color ────────────────────────────────────────────────────────────
PALETTE = _palette.generate_palette(
    _settings.get("accent_color") or "#00e5ff", high_contrast=HIGH_CONTRAST
)

# Three tonal surfaces. base = windows and page background, raised = cards,
# sidebars, toolbars and title bars, overlay = menus, popovers, dialogs and
# the dock.
SURFACE_BASE = PALETTE["bg_base"]
SURFACE_RAISED = PALETTE["bg_raised"]
SURFACE_OVERLAY = PALETTE["bg_overlay"]

TEXT = PALETTE["text"]
TEXT_MUTED = PALETTE["text_muted"]
TEXT_DISABLED = PALETTE["text_disabled"]
BORDER_CONTROL = PALETTE["border_control"]  # >= 3:1 on every surface

# One accent. ACCENT is for fills, the focus ring and the active item;
# ACCENT_TEXT is the same hue adjusted to be readable as text; ON_ACCENT is
# the label colour on a filled accent button.
ACCENT = PALETTE["accent"]
ACCENT_HOVER = PALETTE["accent_hover"]
ACCENT_PRESSED = PALETTE["accent_pressed"]
ACCENT_TEXT = PALETTE["accent_text"]
ON_ACCENT = PALETTE["on_accent"]

SUCCESS = PALETTE["success"]
WARNING = PALETTE["warning"]
DANGER = PALETTE["danger"]
ON_DANGER = PALETTE["on_danger"]

# Legacy names (aliases).
COLOR_BG = SURFACE_BASE
COLOR_BG_ALT = SURFACE_RAISED
COLOR_BG_ELEVATED = SURFACE_OVERLAY
COLOR_TEXT = TEXT
COLOR_TEXT_MUTED = TEXT_MUTED
COLOR_PRIMARY = ACCENT
COLOR_SECONDARY = ACCENT  # one accent: the old blue and purple are gone
COLOR_ACCENT = ACCENT
COLOR_WARNING = WARNING
COLOR_DANGER = DANGER
COLOR_SUCCESS = SUCCESS
COLOR_BORDER = BORDER_CONTROL

CAIRO_PRIMARY = _palette.to_rgb_floats(ACCENT)
CAIRO_SECONDARY = CAIRO_PRIMARY
CAIRO_ACCENT = CAIRO_PRIMARY
CAIRO_TEXT = _palette.to_rgb_floats(TEXT)
CAIRO_MUTED = _palette.to_rgb_floats(TEXT_MUTED)
CAIRO_DANGER = _palette.to_rgb_floats(DANGER)
CAIRO_WARNING = _palette.to_rgb_floats(WARNING)
CAIRO_BASE = _palette.to_rgb_floats(SURFACE_BASE)

# ── Spacing ──────────────────────────────────────────────────────────
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 32
SPACE_XL = 48

# ── Radius ───────────────────────────────────────────────────────────
RADIUS_CONTROL = 8
RADIUS_PANEL = max(0, min(32, int(_settings.get("corner_radius") or 16)))
RADIUS_DIALOG = 24

# ── Motion ───────────────────────────────────────────────────────────
# Budget: compositor animations only, brief, never looping, nothing animates
# while hidden. These are the targets hyprland.conf is tuned to (ms).
MOTION_WINDOW_MS = 200
MOTION_WORKSPACE_MS = 250
MOTION_PANEL_MS = 200
MOTION_HOVER_MS = 150

# ── Dock ─────────────────────────────────────────────────────────────
# Position and size are user settings (Settings > Designer). The geometry
# below is pure so it can be tested without GTK or a compositor; the dock
# window (surfaces.py) applies it live. DOCK_CLEARANCE is the spare space
# reserved past the dock itself: the old fixed 108px zone was a 14px edge
# margin + the dock's ~75px thickness + 19px, so the default look keeps
# reserving what it always did.
DOCK_POSITIONS = CHOICES["dock_position"]
DOCK_SIZES = CHOICES["dock_size"]
DOCK_BUTTON_PX = {"compact": 32, "default": 40, "large": 52}
DOCK_EDGE_MARGIN = 14
DOCK_CLEARANCE = 19

DockLayout = namedtuple(
    "DockLayout", "position size vertical button_px show_labels edge_margin"
)


def dock_layout(position, size):
    """Resolve a (position, size) pair to concrete dock geometry.

    Unknown values fall back to bottom/default, so a hand-edited or stale
    settings file can never produce an unusable dock. Labels are dropped on
    the compact size and on vertical docks (a left/right dock would
    otherwise be as wide as its longest label); every icon keeps its
    tooltip and accessible name either way.
    """
    if position not in DOCK_POSITIONS:
        position = "bottom"
    if size not in DOCK_SIZES:
        size = "default"
    vertical = position in ("left", "right")
    return DockLayout(
        position=position,
        size=size,
        vertical=vertical,
        button_px=DOCK_BUTTON_PX[size],
        show_labels=(size != "compact" and not vertical),
        edge_margin=DOCK_EDGE_MARGIN,
    )


def dock_exclusive_zone(layout, thickness):
    """Pixels the compositor should keep clear along the dock's edge, given
    the dock's *measured* thickness (height when horizontal, width when
    vertical). Measured, not hard-coded, because font metrics differ per
    machine and a fixed number would overlap or leave gaps."""
    return layout.edge_margin + int(thickness) + DOCK_CLEARANCE


# ── Typography ───────────────────────────────────────────────────────
# One UI family (Inter ships in the package list; Space Grotesk never did, so
# it silently fell back) and one mono family. The Nerd Font family name is
# listed first because that is what ttf-jetbrains-mono-nerd registers.
FONT_BODY = "Inter, \"Noto Sans\", sans-serif"
FONT_HEADING = FONT_BODY
FONT_MONO = "\"JetBrainsMono Nerd Font\", \"JetBrains Mono\", \"Fira Code\", monospace"

# Type scale: caption / body / lead / title / display. CSS may only use these.
FONT_SIZE_CAPTION = 12
FONT_SIZE_BODY = 14
FONT_SIZE_LEAD = 16
FONT_SIZE_TITLE = 20
FONT_SIZE_DISPLAY = 28
TYPE_SCALE = (
    FONT_SIZE_CAPTION,
    FONT_SIZE_BODY,
    FONT_SIZE_LEAD,
    FONT_SIZE_TITLE,
    FONT_SIZE_DISPLAY,
)
