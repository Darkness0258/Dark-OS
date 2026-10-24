#!/usr/bin/env python3
"""GTK CSS stylesheet built from design tokens ("Calm Dark").

Rules this file follows (docs/MASTER-PLAN.md section 5):
* three tonal surfaces; the accent only on fills, the active item and focus
* 1px low-contrast borders; shadows only on floating things; no glow except
  the keyboard-focus ring
* type only from the 12/14/16/20/28 scale, spacing from 4/8/16/32/48
* no CSS transitions: motion is the compositor's job

The stylesheet is a string.Template so the CSS stays readable (no doubled
braces); build_css() fills it from the palette and tokens.
"""
import string

from darkos_shell import tokens as _tokens

_CSS_TEMPLATE = string.Template(r"""
* {
    font-family: ${FONT_BODY};
    font-size: ${FS_BODY}px;
    color: ${TEXT};
}

selection {
    background-color: alpha(${ACCENT}, 0.40);
    color: ${TEXT};
}

.darkos-window {
    background-color: transparent;
}

/* ── Type scale ── */
.display { font-size: ${FS_DISPLAY}px; font-weight: 700; }
.title { font-size: ${FS_TITLE}px; font-weight: 600; }
.lead { font-size: ${FS_LEAD}px; font-weight: 500; }
.caption { color: ${TEXT_MUTED}; font-size: ${FS_CAPTION}px; }

.section-title {
    color: ${TEXT};
    font-size: ${FS_LEAD}px;
    font-weight: 600;
}

.eyebrow {
    color: ${TEXT_MUTED};
    font-size: ${FS_CAPTION}px;
    font-weight: 600;
    letter-spacing: 0.5px;
}

.body-muted { color: ${TEXT_MUTED}; }
.status-text { color: ${ACCENT_TEXT}; }
.stub-text { color: ${TEXT_MUTED}; }
.flag-text { color: ${WARNING}; font-weight: 600; }

/* ── Surfaces ── */
.app-window { background-color: ${BASE}; }

.card, .glass-panel {
    background-color: ${RAISED};
    border: 1px solid alpha(${TEXT}, 0.08);
    border-radius: ${RADIUS_PANEL}px;
    padding: ${SPACE_MD}px;
}

/* Floating, so it is the one thing here that gets a shadow. */
.command-center {
    background-color: ${OVERLAY};
    border: 1px solid alpha(${TEXT}, 0.10);
    border-radius: ${RADIUS_PANEL}px;
    box-shadow: 0 12px 32px alpha(${BLACK}, 0.50);
}

.cc-section { padding: ${SPACE_MD}px; }

.cc-divider {
    background-color: alpha(${TEXT}, 0.08);
    min-height: 1px;
}

.cc-empty {
    color: ${TEXT_MUTED};
    padding: ${SPACE_SM}px 0;
}

.cc-notification {
    background-color: ${RAISED};
    border-radius: ${RADIUS_CONTROL}px;
    padding: ${SPACE_SM}px ${SPACE_MD}px;
}

/* Compact resource rows (CPU / memory / disk): a label, a thin bar, a value. */
.resource-label { color: ${TEXT_MUTED}; font-size: ${FS_CAPTION}px; }
.resource-value { font-size: ${FS_CAPTION}px; font-weight: 600; }

.resource-bar trough {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${BASE};
    border-radius: 999px;
    min-height: 6px;
}

.resource-bar progress {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${ACCENT};
    border-radius: 999px;
    min-height: 6px;
}

.resource-bar.warn progress { background-color: ${WARNING}; }
.resource-bar.crit progress { background-color: ${DANGER}; }

/* ── Dock ── (frosted: the compositor blurs what is behind it) */
.dock-bar {
    background-color: alpha(${OVERLAY}, ${DOCK_ALPHA});
    border: 1px solid alpha(${TEXT}, 0.10);
    border-radius: ${RADIUS_DIALOG}px;
    box-shadow: 0 8px 24px alpha(${BLACK}, 0.45);
    padding: ${SPACE_XS}px ${SPACE_SM}px;
}

.dock-bar.vertical {
    padding: ${SPACE_SM}px ${SPACE_XS}px;
}

/* The GTK theme gives every button a 24px min-height, so without this a
   "compact" dock could never get shorter than the default one. */
.dock-bar.compact .dock-icon-button {
    min-width: 0;
    min-height: 0;
    padding: ${SPACE_XS}px;
}

/* Only the thin side is fixed (1px); the long side fills the dock, so the
   divider never forces the dock wider or taller than its buttons. */
.dock-separator {
    background-color: alpha(${TEXT}, 0.14);
    min-width: 1px;
    min-height: 0;
    margin: ${SPACE_SM}px ${SPACE_XS}px;
}

.dock-bar.vertical .dock-separator {
    min-width: 0;
    min-height: 1px;
    margin: ${SPACE_XS}px ${SPACE_SM}px;
}

.dock-label {
    color: ${TEXT_MUTED};
    font-size: ${FS_CAPTION}px;
    padding: 0;
}

.dock-running-dot {
    background-color: alpha(${TEXT}, 0.28);
    border-radius: 999px;
    min-width: 4px;
    min-height: 4px;
}

.dock-running-dot.running {
    background-color: ${ACCENT};
}

.media-art {
    background-color: ${BASE};
    border: 1px solid alpha(${TEXT}, 0.10);
    border-radius: ${RADIUS_CONTROL}px;
    color: ${TEXT_MUTED};
}

.media-title { color: ${TEXT}; font-weight: 600; }

.media-progress trough {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${BASE};
    border-radius: 999px;
    min-height: 4px;
}

.media-progress progress {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${ACCENT};
    border-radius: 999px;
    min-height: 4px;
}

/* ── Buttons ── (reset the stock gradient, then one rule per variant) */
.icon-button, .dock-icon-button, .action-button, .toggle-button,
.app-titlebar-btn, .path-crumb {
    background-image: none;
    box-shadow: none;
    text-shadow: none;
}

.icon-button label, .dock-icon-button label,
.action-button label, .toggle-button label {
    color: inherit;
    text-shadow: none;
}

.icon-button, .dock-icon-button {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: ${RADIUS_CONTROL}px;
    color: ${TEXT};
    padding: ${SPACE_SM}px;
}

.icon-button:hover, .dock-icon-button:hover {
    background-color: alpha(${TEXT}, 0.10);
}

.icon-button:active, .dock-icon-button:active {
    background-color: alpha(${TEXT}, 0.16);
}

.action-button {
    background-color: alpha(${TEXT}, 0.06);
    border: 1px solid alpha(${TEXT}, 0.16);
    border-radius: ${RADIUS_CONTROL}px;
    color: ${TEXT};
    padding: ${SPACE_SM}px ${SPACE_MD}px;
}

.action-button:hover { background-color: alpha(${TEXT}, 0.12); }
.action-button:active { background-color: alpha(${TEXT}, 0.18); }

/* The one filled accent button per screen. */
.action-button.primary, .action-button.suggested-action {
    background-color: ${ACCENT};
    border-color: ${ACCENT};
    color: ${ON_ACCENT};
    font-weight: 600;
}

.action-button.primary:hover, .action-button.suggested-action:hover {
    background-color: ${ACCENT_HOVER};
    border-color: ${ACCENT_HOVER};
}

.action-button.primary:active, .action-button.suggested-action:active {
    background-color: ${ACCENT_PRESSED};
    border-color: ${ACCENT_PRESSED};
}

.action-button.destructive {
    color: ${DANGER};
    border-color: alpha(${DANGER}, 0.55);
}

.action-button.destructive:hover { background-color: alpha(${DANGER}, 0.14); }

.action-button:disabled, .icon-button:disabled, .dock-icon-button:disabled {
    opacity: 0.45;
}

.toggle-button {
    background-color: alpha(${TEXT}, 0.06);
    border: 1px solid alpha(${TEXT}, 0.12);
    border-radius: ${RADIUS_CONTROL}px;
    color: ${TEXT};
    padding: ${SPACE_SM}px;
}

.toggle-button:hover { background-color: alpha(${TEXT}, 0.12); }

.toggle-button:checked {
    background-color: ${ACCENT};
    border-color: ${ACCENT};
    color: ${ON_ACCENT};
}

.toggle-button:disabled { opacity: 0.45; }

/* Keyboard focus is the only place glow is allowed. */
.icon-button:focus, .dock-icon-button:focus, .action-button:focus,
.toggle-button:focus, .app-titlebar-btn:focus, .path-crumb:focus,
combobox button:focus {
    box-shadow: 0 0 0 2px alpha(${ACCENT}, 0.80);
}

entry {
    background-color: ${BASE};
    border: 1px solid ${BORDER_CONTROL};
    border-radius: ${RADIUS_CONTROL}px;
    caret-color: ${TEXT};
    color: ${TEXT};
    padding: ${SPACE_SM}px ${SPACE_MD}px;
}

entry:focus {
    border-color: ${ACCENT};
    box-shadow: 0 0 0 2px alpha(${ACCENT}, 0.35);
}

entry:disabled { opacity: 0.55; }

/* Stock-light widgets: GTK paints its own light trough/background under
   these, so each needs an opaque dark colour, not a low-alpha overlay. */
textview, textview text {
    background-color: ${BASE};
    color: ${TEXT};
}

.calendar {
    background-color: transparent;
    border: none;
    color: ${TEXT};
}

.calendar button {
    background-color: transparent;
    background-image: none;
    border-color: transparent;
    box-shadow: none;
    color: ${TEXT_MUTED};
    text-shadow: none;
}

.calendar button:checked {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
    border-radius: 999px;
}

scale trough {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${BASE};
    border-radius: 999px;
    min-height: 6px;
}

scale highlight {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${ACCENT};
    border-radius: 999px;
}

scale slider {
    background-color: ${TEXT};
    border: 2px solid ${ACCENT};
    border-radius: 50%;
    min-width: 14px;
    min-height: 14px;
}

levelbar trough {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${BASE};
    border-radius: 999px;
    min-height: 6px;
}

levelbar block.filled {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${ACCENT};
    border-radius: 999px;
}

levelbar block.empty { background-color: transparent; }

progressbar trough {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${BASE};
    border-radius: 999px;
}

progressbar progress {
    border: none;
    box-shadow: none;
    background-image: none;
    background-color: ${ACCENT};
    border-radius: 999px;
}

switch {
    background-color: ${BASE};
    border: 1px solid ${BORDER_CONTROL};
    border-radius: 999px;
}

switch:checked {
    background-color: ${ACCENT};
    border-color: ${ACCENT};
}

switch slider {
    background-color: ${TEXT};
    border-radius: 50%;
}

switch:checked slider { background-color: ${ON_ACCENT}; }

list { background-color: transparent; }

row {
    background-color: transparent;
    color: ${TEXT};
    border-radius: ${RADIUS_CONTROL}px;
}

row:hover { background-color: alpha(${TEXT}, 0.06); }

row:selected {
    background-color: alpha(${ACCENT}, 0.18);
    color: ${TEXT};
}

separator {
    background-color: alpha(${TEXT}, 0.10);
    min-height: 1px;
}

scrollbar { background-color: transparent; }

scrollbar trough { background-color: transparent; }

scrollbar slider {
    background-color: alpha(${TEXT}, 0.30);
    border-radius: 999px;
    min-width: 6px;
    min-height: 6px;
}

scrollbar slider:hover { background-color: alpha(${TEXT}, 0.50); }

tooltip, tooltip.background {
    background-color: ${OVERLAY};
    border: 1px solid alpha(${TEXT}, 0.12);
    border-radius: ${RADIUS_CONTROL}px;
}

tooltip label { color: ${TEXT}; }

/* ── App windows (Files, Void, Settings ...) — normal floating windows, not
   layer-shell. Rounding and shadow come from Hyprland's compositor. ── */
.app-titlebar {
    background-color: ${RAISED};
    border-bottom: 1px solid alpha(${TEXT}, 0.08);
    min-height: 40px;
    padding: 0 ${SPACE_XS}px 0 ${SPACE_MD}px;
}

.app-titlebar-title {
    color: ${TEXT};
    font-weight: 600;
}

.app-titlebar-btn {
    background-color: transparent;
    border: none;
    border-radius: ${RADIUS_CONTROL}px;
    color: ${TEXT_MUTED};
    min-width: 32px;
    min-height: 32px;
    padding: 0;
}

.app-titlebar-btn:hover {
    background-color: alpha(${TEXT}, 0.10);
    color: ${TEXT};
}

.app-titlebar-btn-close:hover {
    background-color: ${DANGER};
    color: ${ON_DANGER};
}

.toolbar {
    background-color: ${RAISED};
    border-bottom: 1px solid alpha(${TEXT}, 0.08);
    padding: ${SPACE_XS}px ${SPACE_SM}px;
}

.sidebar {
    background-color: ${RAISED};
    border-right: 1px solid alpha(${TEXT}, 0.08);
    padding: ${SPACE_SM}px;
}

.sidebar-row {
    border-radius: ${RADIUS_CONTROL}px;
    color: ${TEXT_MUTED};
    padding: ${SPACE_XS}px ${SPACE_SM}px;
}

.sidebar-row:hover {
    background-color: alpha(${TEXT}, 0.06);
    color: ${TEXT};
}

/* The active item is where the accent belongs. */
.sidebar-row.active {
    background-color: alpha(${ACCENT}, 0.16);
    box-shadow: inset 3px 0 0 ${ACCENT};
    color: ${TEXT};
}

.sidebar-heading {
    color: ${TEXT_MUTED};
    font-size: ${FS_CAPTION}px;
    font-weight: 600;
    letter-spacing: 0.5px;
    padding: ${SPACE_MD}px ${SPACE_SM}px ${SPACE_XS}px ${SPACE_SM}px;
}

.path-bar {
    background-color: ${BASE};
    border: 1px solid ${BORDER_CONTROL};
    border-radius: ${RADIUS_CONTROL}px;
    padding: 2px ${SPACE_XS}px;
}

.path-crumb {
    background-color: transparent;
    border: none;
    color: ${TEXT_MUTED};
    padding: ${SPACE_XS}px ${SPACE_SM}px;
}

.path-crumb:hover { color: ${TEXT}; }

.path-crumb-current {
    color: ${TEXT};
    font-weight: 600;
}

treeview.darkos-list {
    background-color: transparent;
    color: ${TEXT};
}

treeview.darkos-list:selected {
    background-color: alpha(${ACCENT}, 0.20);
    color: ${TEXT};
}

treeview.darkos-list header button {
    background-color: ${RAISED};
    background-image: none;
    border: none;
    border-bottom: 1px solid alpha(${TEXT}, 0.10);
    box-shadow: none;
    color: ${TEXT_MUTED};
    font-weight: 600;
    padding: ${SPACE_SM}px;
}

notebook.terminal-tabs > header {
    background-color: ${RAISED};
    border-bottom: 1px solid alpha(${TEXT}, 0.08);
    padding: 0 ${SPACE_XS}px;
}

notebook.terminal-tabs tab {
    background-color: transparent;
    border: none;
    color: ${TEXT_MUTED};
    padding: ${SPACE_XS}px ${SPACE_MD}px;
}

notebook.terminal-tabs tab:checked {
    background-color: alpha(${ACCENT}, 0.12);
    border-bottom: 2px solid ${ACCENT};
    color: ${TEXT};
}

/* GtkNotebook's page area, GtkCalendar and GtkTextView's text node are themed
   independently of their ancestors and render stock-light unless targeted. */
notebook, notebook stack {
    background-color: ${BASE};
    color: ${TEXT};
}

.statusbar {
    background-color: ${RAISED};
    border-top: 1px solid alpha(${TEXT}, 0.08);
    color: ${TEXT_MUTED};
    font-size: ${FS_CAPTION}px;
    padding: ${SPACE_XS}px ${SPACE_MD}px;
}

calendar {
    background-color: ${BASE};
    color: ${TEXT};
    border: none;
}

calendar.header {
    background-color: ${RAISED};
    color: ${TEXT};
}

calendar.button {
    background-color: transparent;
    background-image: none;
    border: none;
    color: ${TEXT_MUTED};
}

calendar.button:hover { color: ${TEXT}; }

calendar:selected {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
    border-radius: ${RADIUS_CONTROL}px;
}

calendar.view {
    background-color: ${BASE};
    color: ${TEXT};
}

/* Drop-downs (Gtk.ComboBoxText) and their pop-up menus. */
combobox button, combobox button.combo {
    background-color: ${BASE};
    background-image: none;
    border: 1px solid ${BORDER_CONTROL};
    border-radius: ${RADIUS_CONTROL}px;
    box-shadow: none;
    color: ${TEXT};
    padding: ${SPACE_SM}px ${SPACE_MD}px;
    text-shadow: none;
}

combobox button:hover { border-color: ${ACCENT}; }

combobox arrow { color: ${TEXT_MUTED}; }

menu, .menu, popover, popover.background {
    background-color: ${OVERLAY};
    border: 1px solid alpha(${TEXT}, 0.12);
    border-radius: ${RADIUS_CONTROL}px;
    color: ${TEXT};
}

menuitem {
    background-color: transparent;
    color: ${TEXT};
    padding: ${SPACE_SM}px ${SPACE_MD}px;
}

menuitem label { color: ${TEXT}; }

menuitem:hover { background-color: alpha(${ACCENT}, 0.18); }

menuitem:disabled label { color: ${TEXT_DISABLED}; }
""")

# High Contrast: opaque, hard borders, no translucency or shadow. Layered on
# top of the normal sheet (the palette is already the 7:1 one).
_HC_TEMPLATE = string.Template(r"""
.app-window, .card, .glass-panel, .command-center, .dock-bar, .sidebar,
.toolbar, .app-titlebar {
    background-color: ${BLACK};
    border: 2px solid ${TEXT};
    box-shadow: none;
}
entry, textview, list, treeview, .sidebar-row, combobox button {
    background-color: ${BLACK};
    color: ${TEXT};
    border: 2px solid ${TEXT};
}
button, .icon-button, .action-button, .toggle-button, .dock-icon-button {
    background-color: ${BLACK};
    color: ${TEXT};
    border: 2px solid ${TEXT};
}
.action-button.primary, .toggle-button:checked {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
}
""")


def _values(palette):
    t = _tokens
    p = palette
    return {
        "FONT_BODY": t.FONT_BODY,
        "FS_CAPTION": t.FONT_SIZE_CAPTION,
        "FS_BODY": t.FONT_SIZE_BODY,
        "FS_LEAD": t.FONT_SIZE_LEAD,
        "FS_TITLE": t.FONT_SIZE_TITLE,
        "FS_DISPLAY": t.FONT_SIZE_DISPLAY,
        "SPACE_XS": t.SPACE_XS, "SPACE_SM": t.SPACE_SM, "SPACE_MD": t.SPACE_MD,
        "RADIUS_CONTROL": t.RADIUS_CONTROL,
        "RADIUS_PANEL": t.RADIUS_PANEL,
        "RADIUS_DIALOG": t.RADIUS_DIALOG,
        "BASE": p["bg_base"], "RAISED": p["bg_raised"], "OVERLAY": p["bg_overlay"],
        "TEXT": p["text"], "TEXT_MUTED": p["text_muted"], "TEXT_DISABLED": p["text_disabled"],
        "BORDER_CONTROL": p["border_control"],
        "ACCENT": p["accent"], "ACCENT_HOVER": p["accent_hover"],
        "ACCENT_PRESSED": p["accent_pressed"], "ACCENT_TEXT": p["accent_text"],
        "ON_ACCENT": p["on_accent"],
        "WARNING": p["warning"], "DANGER": p["danger"], "ON_DANGER": p["on_danger"],
        "BLACK": p["black"],
        # Frosted dock; fully opaque in High Contrast.
        "DOCK_ALPHA": "1.0" if p["bg_base"] == p["bg_overlay"] else "0.86",
    }


def build_css(palette=None, high_contrast=None):
    """Return the stylesheet for `palette` (default: the live tokens)."""
    palette = palette or _tokens.PALETTE
    if high_contrast is None:
        high_contrast = _tokens.HIGH_CONTRAST
    values = _values(palette)
    css = _CSS_TEMPLATE.substitute(values)
    if high_contrast:
        css += _HC_TEMPLATE.substitute(values)
    return css


CSS_STYLE = build_css()
# Kept for callers that import the name; the High Contrast rules are part of
# build_css() now that the palette itself switches.
HIGH_CONTRAST_CSS = _HC_TEMPLATE.substitute(_values(_tokens.PALETTE))


def css_parse_errors(css):
    """GTK silently drops rules it can't parse; return them as strings so a
    test (or a developer) can see them."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    errors = []
    provider = Gtk.CssProvider()
    provider.connect(
        "parsing-error",
        lambda _p, section, error: errors.append(
            f"line {section.get_start_line() + 1}: {error.message}"
        ),
    )
    try:
        provider.load_from_data(css.encode())
    except Exception as error:  # GLib.Error on a fatal parse failure
        errors.append(str(error))
    return errors


def apply_css() -> None:
    """Load DarkOS GTK CSS into the default screen's style provider."""
    import sys

    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk

    for message in css_parse_errors(CSS_STYLE):
        print(f"DarkOS CSS: {message}", file=sys.stderr)
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS_STYLE.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
