#!/usr/bin/env python3
"""GTK CSS stylesheet built from design tokens."""

from darkos_shell.tokens import (
    CAIRO_PRIMARY,
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_BG_ALT,
    COLOR_BG_ELEVATED,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SECONDARY,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    RADIUS_CONTROL,
    RADIUS_DIALOG,
    RADIUS_PANEL,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
)

CSS_STYLE = f"""
* {{
    font-family: Inter, "Noto Sans", sans-serif;
    font-size: 13px;
    color: {COLOR_TEXT};
}}

.darkos-window {{
    background-color: transparent;
}}

.glass-panel {{
    background-color: alpha({COLOR_BG_ELEVATED}, 0.78);
    border: 1px solid alpha({COLOR_TEXT}, 0.12);
    border-radius: {RADIUS_PANEL}px;
    box-shadow: 0 8px 24px alpha({COLOR_BG}, 0.55);
    padding: {SPACE_MD}px;
}}

.hud-stage {{
    background-color: transparent;
    padding: {SPACE_SM}px;
}}

.hud-wordmark {{
    color: {COLOR_TEXT};
    font-family: "Space Grotesk", Inter, "Noto Sans", sans-serif;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 2px;
}}

.section-title {{
    color: {COLOR_PRIMARY};
    font-family: "Space Grotesk", Inter, "Noto Sans", sans-serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}

.eyebrow {{
    color: {COLOR_TEXT_MUTED};
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}

.body-muted {{
    color: {COLOR_TEXT_MUTED};
}}

.status-text {{
    color: {COLOR_PRIMARY};
}}

.stub-text {{
    color: {COLOR_WARNING};
}}

.dock-bar {{
    background-color: alpha({COLOR_BG_ALT}, 0.82);
    border: 1px solid alpha({COLOR_PRIMARY}, 0.30);
    border-radius: {RADIUS_DIALOG}px;
    box-shadow: 0 8px 24px alpha({COLOR_PRIMARY}, 0.18);
    padding: {SPACE_XS}px {SPACE_MD}px;
}}

.icon-button, .dock-icon-button, .orb-button {{
    background-color: transparent;
    background-image: none;
    border: 1px solid transparent;
    border-radius: {RADIUS_CONTROL}px;
    box-shadow: none;
    color: {COLOR_TEXT_MUTED};
    padding: {SPACE_SM}px;
    text-shadow: none;
}}

.icon-button label, .dock-icon-button label, .orb-button label,
.action-button label, .toggle-button label {{
    color: inherit;
    font-family: Inter, "Noto Sans", sans-serif;
    text-shadow: none;
}}

.dock-icon-button {{
    color: {COLOR_PRIMARY};
    font-size: 20px;
}}

.dock-highlight {{
    background-color: alpha({COLOR_ACCENT}, 0.16);
    border: 1px solid alpha({COLOR_ACCENT}, 0.55);
    box-shadow: 0 0 12px 1px alpha({COLOR_ACCENT}, 0.35);
}}

.dock-label {{
    color: {COLOR_TEXT_MUTED};
    font-size: 10px;
    font-weight: 500;
    padding: 0;
}}

.media-art {{
    background-color: alpha({COLOR_BG}, 0.60);
    border: 1px solid alpha({COLOR_BORDER}, 0.30);
    border-radius: 12px;
    color: {COLOR_TEXT_MUTED};
}}

.media-progress {{
    background-color: alpha({COLOR_TEXT}, 0.10);
    border-radius: 4px;
    min-height: 4px;
}}

.media-progress-filled {{
    background-color: {COLOR_PRIMARY};
    border-radius: 4px;
    min-height: 4px;
}}

.orb-button {{
    background-color: alpha({COLOR_BG}, 0.30);
    border-color: alpha({COLOR_PRIMARY}, 0.42);
    border-radius: 999px;
    box-shadow: 0 0 16px alpha({COLOR_PRIMARY}, 0.30);
    padding: {SPACE_XS}px;
}}

.icon-button:hover, .dock-icon-button:hover, .orb-button:hover {{
    background-color: alpha({COLOR_PRIMARY}, 0.14);
    border-color: alpha({COLOR_PRIMARY}, 0.35);
    box-shadow: 0 0 16px alpha({COLOR_PRIMARY}, 0.34);
    color: {COLOR_PRIMARY};
}}

.icon-button:focus, .dock-icon-button:focus, .orb-button:focus,
.action-button:focus, .toggle-button:focus, entry:focus {{
    border-color: {COLOR_TEXT};
    box-shadow: 0 0 0 2px alpha({COLOR_PRIMARY}, 0.65);
}}

.rail {{
    background-color: alpha({COLOR_BG_ALT}, 0.82);
    border: 1px solid alpha({COLOR_TEXT}, 0.12);
    border-radius: {RADIUS_PANEL}px;
    padding: {SPACE_SM}px;
}}

.ai-entry, entry {{
    background-color: alpha({COLOR_BG}, 0.64);
    border: 1px solid alpha({COLOR_PRIMARY}, 0.40);
    border-radius: {RADIUS_CONTROL}px;
    color: {COLOR_TEXT};
    padding: {SPACE_SM}px {SPACE_MD}px;
}}

.action-button {{
    background-color: alpha({COLOR_PRIMARY}, 0.12);
    background-image: none;
    border: 1px solid alpha({COLOR_PRIMARY}, 0.40);
    border-radius: {RADIUS_CONTROL}px;
    box-shadow: none;
    color: {COLOR_PRIMARY};
    padding: {SPACE_SM}px {SPACE_MD}px;
    text-shadow: none;
}}

.action-button:hover {{
    background-color: alpha({COLOR_PRIMARY}, 0.22);
    border-color: {COLOR_PRIMARY};
}}

.toggle-button {{
    background-color: alpha({COLOR_TEXT}, 0.06);
    background-image: none;
    border: 1px solid alpha({COLOR_TEXT}, 0.12);
    border-radius: {RADIUS_CONTROL}px;
    box-shadow: none;
    color: {COLOR_TEXT};
    padding: {SPACE_SM}px;
    text-shadow: none;
}}

.toggle-button:checked {{
    background-color: alpha({COLOR_PRIMARY}, 0.20);
    border-color: {COLOR_PRIMARY};
    box-shadow: 0 0 12px alpha({COLOR_PRIMARY}, 0.32);
    color: {COLOR_PRIMARY};
}}

.toggle-button:disabled {{
    opacity: 0.40;
}}

.media-title {{
    color: {COLOR_TEXT};
    font-weight: 700;
}}

.calendar {{
    background-color: transparent;
    border: none;
    color: {COLOR_TEXT};
}}

.calendar button {{
    background-color: transparent;
    background-image: none;
    border-color: transparent;
    box-shadow: none;
    color: {COLOR_TEXT_MUTED};
    text-shadow: none;
}}

.calendar button:checked {{
    background-color: alpha({COLOR_PRIMARY}, 0.24);
    color: {COLOR_TEXT};
    border-radius: 999px;
}}

scale trough {{
    background-color: alpha({COLOR_TEXT}, 0.08);
    border-radius: {RADIUS_CONTROL}px;
    min-height: 6px;
}}

scale highlight {{
    background-color: {COLOR_PRIMARY};
    border-radius: {RADIUS_CONTROL}px;
}}

scale slider {{
    background-color: {COLOR_TEXT};
    border: 2px solid {COLOR_PRIMARY};
    border-radius: 50%;
    min-width: 14px;
    min-height: 14px;
}}

separator {{
    background-color: alpha({COLOR_TEXT}, 0.12);
    min-height: 1px;
}}
"""


def apply_css() -> None:
    """Load DarkOS GTK CSS into the default screen's style provider."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS_STYLE.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
