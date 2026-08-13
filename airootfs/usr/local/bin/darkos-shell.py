#!/usr/bin/env python3
"""DarkOS core shell chrome built with GTK3 and gtk-layer-shell."""

import argparse
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell

    HAS_LAYER_SHELL = True
except (ImportError, ValueError):
    HAS_LAYER_SHELL = False


# Design tokens mirror ui-tokens.md. Alpha variants derive from these values.
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

CAIRO_PRIMARY = (0.0, 0.898, 1.0)
CAIRO_SECONDARY = (0.176, 0.482, 1.0)
CAIRO_ACCENT = (0.659, 0.333, 0.969)
CAIRO_TEXT = (0.949, 0.961, 0.969)
CAIRO_MUTED = (0.604, 0.643, 0.678)
CAIRO_DANGER = (1.0, 0.231, 0.231)

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 32
RADIUS_CONTROL = 8
RADIUS_PANEL = 16
RADIUS_DIALOG = 24


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

.section-title {{
    color: {COLOR_PRIMARY};
    font-family: Inter, "Noto Sans", sans-serif;
    font-size: 15px;
    font-weight: 700;
}}

.eyebrow {{
    color: {COLOR_TEXT_MUTED};
    font-size: 13px;
    font-weight: 600;
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
    font-family: "JetBrainsMono Nerd Font", "Font Awesome 7 Free", Inter,
        "Noto Sans", sans-serif;
    text-shadow: none;
}}

.dock-icon-button {{
    color: {COLOR_PRIMARY};
    font-size: 20px;
}}

.icon-button:hover, .dock-icon-button:hover, .orb-button:hover {{
    background-color: alpha({COLOR_PRIMARY}, 0.14);
    border-color: alpha({COLOR_PRIMARY}, 0.35);
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

.calendar:selected {{
    background-color: alpha({COLOR_PRIMARY}, 0.24);
    color: {COLOR_TEXT};
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


def add_class(widget, class_name):
    widget.get_style_context().add_class(class_name)
    return widget


def make_label(text, class_name=None, align=Gtk.Align.START, wrap=False):
    widget = Gtk.Label(label=text)
    widget.set_halign(align)
    widget.set_xalign(0.0 if align == Gtk.Align.START else 0.5)
    widget.set_line_wrap(wrap)
    if wrap:
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if class_name:
        add_class(widget, class_name)
    return widget


def make_icon_button(icon, name, callback, class_name="icon-button", size=40):
    button = Gtk.Button(label=icon)
    add_class(button, class_name)
    button.set_tooltip_text(name)
    button.set_size_request(size, size)
    button.get_accessible().set_name(name)
    button.connect("clicked", callback)
    return button


def apply_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS_STYLE.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def launch(command):
    """Start a fixed command without invoking a shell."""
    try:
        subprocess.Popen(command, start_new_session=True)
        return True
    except OSError as error:
        print(f"DarkOS: could not launch {command[0]}: {error}", file=sys.stderr)
        return False


def command_output(command, timeout=1.5):
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def configure_layer_window(
    window,
    namespace,
    layer,
    anchors,
    margins=None,
    exclusive_zone=0,
    keyboard=False,
):
    if not HAS_LAYER_SHELL:
        return
    GtkLayerShell.init_for_window(window)
    GtkLayerShell.set_namespace(window, namespace)
    GtkLayerShell.set_layer(window, layer)
    for edge in anchors:
        GtkLayerShell.set_anchor(window, edge, True)
    for edge, value in (margins or {}).items():
        GtkLayerShell.set_margin(window, edge, value)
    if exclusive_zone:
        GtkLayerShell.set_exclusive_zone(window, exclusive_zone)
    if keyboard and hasattr(GtkLayerShell, "KeyboardMode"):
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.ON_DEMAND)


class AIOrbCanvas(Gtk.DrawingArea):
    """AI Orb with the five motion states defined by ui-rules.md."""

    def __init__(self, size=56):
        super().__init__()
        self.set_size_request(size, size)
        self.state = "sleeping"
        self.anim_phase = 0.0
        self.connect("draw", self.on_draw)
        GLib.timeout_add(33, self.on_animate)

    def on_animate(self):
        speed = {
            "sleeping": 0.035,
            "listening": 0.10,
            "thinking": 0.16,
            "speaking": 0.13,
            "error": 0.20,
        }.get(self.state, 0.035)
        self.anim_phase = (self.anim_phase + speed) % (math.pi * 200)
        self.queue_draw()
        return True

    def set_state(self, new_state):
        self.state = new_state
        self.queue_draw()

    def on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cx, cy = width / 2.0, height / 2.0
        radius = min(cx, cy) - 7.0

        state_style = {
            "sleeping": (CAIRO_PRIMARY, 0.50, 0.03, 1.5),
            "listening": (CAIRO_PRIMARY, 0.82, 0.08, 3.0),
            "thinking": (CAIRO_SECONDARY, 0.88, 0.05, 5.0),
            "speaking": (CAIRO_ACCENT, 0.88, 0.12, 4.0),
            "error": (CAIRO_DANGER, 0.94, 0.09, 6.0),
        }
        color, alpha, amount, frequency = state_style.get(
            self.state, state_style["sleeping"]
        )
        pulse = 1.0 + amount * abs(math.sin(self.anim_phase * frequency))
        radius *= pulse

        for index in range(5, 0, -1):
            cr.arc(cx, cy, radius + index * 2.5, 0, 2 * math.pi)
            cr.set_source_rgba(*color, alpha * 0.10 * (6 - index))
            cr.fill()

        gradient = cairo.RadialGradient(cx, cy, 2.0, cx, cy, radius)
        gradient.add_color_stop_rgba(0.0, *CAIRO_TEXT, 0.96)
        gradient.add_color_stop_rgba(0.42, *color, 0.92)
        gradient.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.42)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.set_source(gradient)
        cr.fill()

        if self.state != "sleeping":
            cr.set_line_width(2.0)
            cr.set_source_rgba(*color, 0.86)
            start = self.anim_phase * 1.8
            cr.arc(cx, cy, radius + 4, start, start + math.pi * 0.72)
            cr.stroke()
        return False


class AIRadarCanvas(Gtk.DrawingArea):
    """Central ring-language HUD with activity-linked motion and luminance."""

    def __init__(self):
        super().__init__()
        self.set_size_request(420, 330)
        self.rotation = 0.0
        self.activity = "idle"
        self.connect("draw", self.on_draw)
        GLib.timeout_add(33, self.on_animate)

    def set_activity(self, activity):
        self.activity = activity
        self.queue_draw()

    def on_animate(self):
        speed = {
            "idle": 0.010,
            "listening": 0.025,
            "thinking": 0.050,
            "speaking": 0.035,
            "error": 0.065,
        }.get(self.activity, 0.010)
        self.rotation = (self.rotation + speed) % (math.pi * 200)
        self.queue_draw()
        return True

    @staticmethod
    def draw_centered_text(cr, text, x, y, size, color, alpha=1.0):
        cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(size)
        extents = cr.text_extents(text)
        cr.move_to(x - extents.width / 2.0, y)
        cr.set_source_rgba(*color, alpha)
        cr.show_text(text)

    def on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cx, cy = width / 2.0, height / 2.0 - 8
        active = self.activity != "idle"
        intensity = 0.88 if active else 0.46
        ring_color = CAIRO_DANGER if self.activity == "error" else CAIRO_PRIMARY

        for index, radius in enumerate((54, 88, 122)):
            cr.save()
            cr.set_line_width(2.0 if active and index == 1 else 1.5)
            color = ring_color if index % 2 == 0 else CAIRO_SECONDARY
            cr.set_source_rgba(*color, intensity - index * 0.07)
            offset = self.rotation * (24.0 if index % 2 == 0 else -18.0)
            cr.set_dash((12.0, 6.0), offset)
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.stroke()
            cr.restore()

        cr.save()
        for angle in range(0, 360, 15):
            radians = math.radians(angle) + self.rotation * 0.45
            inner = 110 if angle % 45 == 0 else 114
            outer = 124 if angle % 45 == 0 else 121
            cr.move_to(cx + inner * math.cos(radians), cy + inner * math.sin(radians))
            cr.line_to(cx + outer * math.cos(radians), cy + outer * math.sin(radians))
            cr.set_source_rgba(*ring_color, intensity if angle % 45 == 0 else 0.26)
            cr.set_line_width(2.0 if angle % 45 == 0 else 1.0)
            cr.stroke()
        cr.restore()

        pulse = 20 + (5 if active else 3) * math.sin(self.rotation * 4.0)
        cr.arc(cx, cy, pulse + 12, 0, 2 * math.pi)
        cr.set_source_rgba(*ring_color, 0.18 if active else 0.10)
        cr.fill()
        cr.arc(cx, cy, pulse, 0, 2 * math.pi)
        cr.set_source_rgba(*ring_color, 0.88 if active else 0.66)
        cr.fill()

        self.draw_centered_text(cr, "OBSERVE", cx, cy - 138, 11, CAIRO_MUTED, 0.88)
        self.draw_centered_text(cr, "REASON", cx - 142, cy + 4, 11, CAIRO_MUTED, 0.88)
        self.draw_centered_text(cr, "ACT", cx + 142, cy + 4, 11, CAIRO_MUTED, 0.88)
        self.draw_centered_text(
            cr,
            self.activity.upper(),
            cx,
            cy + 6,
            11,
            CAIRO_TEXT,
            0.96,
        )
        return False


class WaveformCanvas(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(-1, 44)
        self.phase = 0.0
        self.active = False
        self.connect("draw", self.on_draw)
        GLib.timeout_add(40, self.on_animate)

    def set_active(self, active):
        self.active = active

    def on_animate(self):
        self.phase = (self.phase + (0.18 if self.active else 0.04)) % (math.pi * 200)
        self.queue_draw()
        return True

    def on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        midpoint = height / 2.0
        bars = 26
        gap = width / max(bars, 1)
        cr.set_line_width(2.0)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(*CAIRO_PRIMARY, 0.82 if self.active else 0.42)
        for index in range(bars):
            wave = abs(math.sin(self.phase + index * 0.42))
            amplitude = 4 + wave * (15 if self.active else 7)
            x = gap * (index + 0.5)
            cr.move_to(x, midpoint - amplitude)
            cr.line_to(x, midpoint + amplitude)
            cr.stroke()
        return False


class RingGauge(Gtk.DrawingArea):
    def __init__(self, name, color):
        super().__init__()
        self.name = name
        self.color = color
        self.value = None
        self.set_size_request(92, 92)
        self.connect("draw", self.on_draw)

    def set_value(self, value):
        self.value = None if value is None else max(0.0, min(100.0, value))
        self.queue_draw()

    def on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cx, cy = width / 2.0, height / 2.0
        radius = min(cx, cy) - 9
        start = -math.pi / 2.0

        cr.set_line_width(5.0)
        cr.set_source_rgba(*CAIRO_TEXT, 0.08)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        if self.value is not None:
            cr.set_source_rgba(*self.color, 0.92)
            cr.arc(cx, cy, radius, start, start + 2 * math.pi * self.value / 100.0)
            cr.stroke()

        cr.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(15)
        value_text = "--" if self.value is None else f"{self.value:.0f}%"
        extents = cr.text_extents(value_text)
        cr.move_to(cx - extents.width / 2.0, cy + 2)
        cr.set_source_rgba(*CAIRO_TEXT, 0.96)
        cr.show_text(value_text)
        cr.set_font_size(11)
        extents = cr.text_extents(self.name)
        cr.move_to(cx - extents.width / 2.0, cy + 20)
        cr.set_source_rgba(*CAIRO_MUTED, 0.94)
        cr.show_text(self.name)
        return False


class SystemSampler:
    def __init__(self):
        self.last_cpu = None
        self.last_network = None
        self.last_time = None

    def cpu_percent(self):
        try:
            first_line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
            fields = first_line.split()
            values = [int(value) for value in fields[1:]]
        except (OSError, IndexError, ValueError):
            return None
        if len(values) < 7 or fields[0] != "cpu":
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        current = (idle, total)
        if self.last_cpu is None:
            self.last_cpu = current
            return 0.0
        idle_delta = idle - self.last_cpu[0]
        total_delta = total - self.last_cpu[1]
        self.last_cpu = current
        if total_delta <= 0:
            return 0.0
        return 100.0 * (1.0 - idle_delta / total_delta)

    @staticmethod
    def memory_percent():
        values = {}
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0])
        except (OSError, ValueError, IndexError):
            return None
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        return 100.0 * (total - available) / total if total else None

    @staticmethod
    def storage_percent():
        try:
            usage = shutil.disk_usage("/")
        except OSError:
            return None
        return 100.0 * usage.used / usage.total if usage.total else None

    @staticmethod
    def gpu_percent():
        for path in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
            try:
                return float(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
        return None

    def network_rates(self):
        received = 0
        transmitted = 0
        try:
            lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
            for line in lines:
                interface, values = line.split(":", 1)
                if interface.strip() == "lo":
                    continue
                fields = values.split()
                received += int(fields[0])
                transmitted += int(fields[8])
        except (OSError, ValueError, IndexError):
            return None, None

        now = time.monotonic()
        if self.last_network is None or self.last_time is None:
            self.last_network = (received, transmitted)
            self.last_time = now
            return 0.0, 0.0
        elapsed = max(now - self.last_time, 0.001)
        down = max(0, received - self.last_network[0]) / elapsed
        up = max(0, transmitted - self.last_network[1]) / elapsed
        self.last_network = (received, transmitted)
        self.last_time = now
        return down, up


def format_rate(bytes_per_second):
    if bytes_per_second is None:
        return "--"
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.1f} MiB/s"
    return f"{bytes_per_second / 1024:.0f} KiB/s"


class DarkOSDockWindow(Gtk.Window):
    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.orb_cycle_index = 0
        self.set_title("DarkOS Dock")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-dock",
            GtkLayerShell.Layer.TOP if HAS_LAYER_SHELL else None,
            (GtkLayerShell.Edge.BOTTOM,) if HAS_LAYER_SHELL else (),
            {GtkLayerShell.Edge.BOTTOM: 14} if HAS_LAYER_SHELL else {},
            exclusive_zone=82,
            keyboard=True,
        )

        dock = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        add_class(dock, "dock-bar")
        dock.set_halign(Gtk.Align.CENTER)

        left_apps = (
            ("󰋜", "Files", ["kitty", "-e", "ranger"]),
            ("󰞷", "Terminal", ["/usr/local/bin/the-void.sh"]),
            ("󰈹", "Browser", ["firefox"]),
        )
        right_apps = (
            ("󰠮", "Notes", ["kitty", "-e", "nvim"]),
            ("󰄨", "Store", ["wofi", "--show", "drun"]),
            ("󰒓", "Settings", ["wofi", "--show", "drun"]),
        )

        for icon, name, command in left_apps:
            dock.pack_start(
                make_icon_button(
                    icon,
                    name,
                    lambda _button, selected=command: launch(selected),
                    "dock-icon-button",
                    44,
                ),
                False,
                False,
                0,
            )

        orb_button = Gtk.Button()
        add_class(orb_button, "orb-button")
        orb_button.set_tooltip_text("Cycle DarkOS AI preview state")
        orb_button.get_accessible().set_name("DarkOS AI preview state")
        self.ai_orb = AIOrbCanvas(size=58)
        orb_button.add(self.ai_orb)
        orb_button.connect("clicked", self.on_orb_click)
        dock.pack_start(orb_button, False, False, SPACE_SM)

        for icon, name, command in right_apps:
            dock.pack_start(
                make_icon_button(
                    icon,
                    name,
                    lambda _button, selected=command: launch(selected),
                    "dock-icon-button",
                    44,
                ),
                False,
                False,
                0,
            )

        self.add(dock)
        self.show_all()

    def on_orb_click(self, _button):
        states = ("sleeping", "listening", "thinking", "speaking", "error")
        self.orb_cycle_index = (self.orb_cycle_index + 1) % len(states)
        state = states[self.orb_cycle_index]
        self.ai_orb.set_state(state)
        self.application.set_ai_activity(state)
        if state == "error":
            GLib.timeout_add(900, self.finish_error_pulse)

    def finish_error_pulse(self):
        if self.ai_orb.state == "error":
            self.ai_orb.set_state("sleeping")
            self.application.set_ai_activity("idle")
            self.orb_cycle_index = 0
        return False


class DarkOSHUDOverlay(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("DarkOS AI Core")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-hud",
            GtkLayerShell.Layer.TOP if HAS_LAYER_SHELL else None,
            (GtkLayerShell.Edge.TOP,) if HAS_LAYER_SHELL else (),
            {GtkLayerShell.Edge.TOP: 76} if HAS_LAYER_SHELL else {},
        )

        stage = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(stage, "hud-stage")
        stage.set_halign(Gtk.Align.CENTER)
        self.radar = AIRadarCanvas()
        stage.pack_start(self.radar, False, False, 0)

        tagline = make_label("CONTROL EVERYTHING", "section-title", Gtk.Align.CENTER)
        tagline.set_xalign(0.5)
        stage.pack_start(tagline, False, False, 0)
        state = make_label("AI CORE  /  PREVIEW MODE", "eyebrow", Gtk.Align.CENTER)
        state.set_xalign(0.5)
        stage.pack_start(state, False, False, 0)
        self.add(stage)
        self.show_all()


class DarkOSIconRail(Gtk.Window):
    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.set_title("DarkOS App Rail")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-rail",
            GtkLayerShell.Layer.TOP if HAS_LAYER_SHELL else None,
            (
                GtkLayerShell.Edge.TOP,
                GtkLayerShell.Edge.BOTTOM,
                GtkLayerShell.Edge.LEFT,
            )
            if HAS_LAYER_SHELL
            else (),
            {
                GtkLayerShell.Edge.TOP: 58,
                GtkLayerShell.Edge.BOTTOM: 96,
                GtkLayerShell.Edge.LEFT: 12,
            }
            if HAS_LAYER_SHELL
            else {},
            exclusive_zone=68,
            keyboard=True,
        )

        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_XS)
        add_class(rail, "rail")
        rail.set_valign(Gtk.Align.CENTER)
        actions = (
            ("󰚩", "AI", "ai"),
            ("󰉋", "Files", "files"),
            ("󰆍", "Terminal", "terminal"),
            ("󰒓", "Settings", "settings"),
            ("󰈹", "Browser", "browser"),
            ("󰄄", "Gallery", "gallery"),
            ("󰏓", "Store", "store"),
            ("󰠮", "Notes", "notes"),
            ("󰎈", "Music", "music"),
            ("󰊗", "Gaming", "gaming"),
        )
        for icon, name, action in actions:
            rail.pack_start(
                make_icon_button(
                    icon,
                    name,
                    lambda _button, selected=action: self.application.handle_rail_action(
                        selected
                    ),
                ),
                False,
                False,
                0,
            )
        self.add(rail)
        self.show_all()


class DarkOSLeftPanels(Gtk.Window):
    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.sampler = SystemSampler()
        self.set_title("DarkOS Left Panels")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-left",
            GtkLayerShell.Layer.TOP if HAS_LAYER_SHELL else None,
            (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.LEFT)
            if HAS_LAYER_SHELL
            else (),
            {GtkLayerShell.Edge.TOP: 16, GtkLayerShell.Edge.LEFT: 16}
            if HAS_LAYER_SHELL
            else {},
            keyboard=True,
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        root.set_size_request(330, -1)
        root.pack_start(self.build_chat_panel(), False, False, 0)
        root.pack_start(self.build_weather_panel(), False, False, 0)
        root.pack_start(self.build_system_panel(), False, False, 0)
        self.add(root)
        self.show_all()
        self.refresh_system()
        GLib.timeout_add_seconds(2, self.refresh_system)

    def build_chat_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("AI CHAT", "section-title"), False, False, 0)
        panel.pack_start(
            make_label("Good to see you. What should we explore?", wrap=True),
            False,
            False,
            0,
        )
        self.waveform = WaveformCanvas()
        panel.pack_start(self.waveform, False, False, 0)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        self.entry = Gtk.Entry()
        add_class(self.entry, "ai-entry")
        self.entry.set_placeholder_text("Ask DarkOS AI...")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self.on_submit)
        entry_row.pack_start(self.entry, True, True, 0)
        submit = make_icon_button("󰄬", "Submit AI preview request", self.on_submit)
        entry_row.pack_start(submit, False, False, 0)
        panel.pack_start(entry_row, False, False, 0)

        self.response = make_label(
            "Preview only: the AI backend is not connected.",
            "stub-text",
            wrap=True,
        )
        panel.pack_start(self.response, False, False, 0)
        return panel

    @staticmethod
    def build_weather_panel():
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_XS)
        add_class(panel, "glass-panel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        header.pack_start(make_label("WEATHER", "section-title"), True, True, 0)
        header.pack_end(make_label("󰖐  --", "status-text"), False, False, 0)
        panel.pack_start(header, False, False, 0)
        panel.pack_start(
            make_label(
                "Forecast unavailable: no weather service is connected.",
                "stub-text",
                wrap=True,
            ),
            False,
            False,
            0,
        )
        return panel

    def build_system_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("SYSTEM OVERVIEW", "section-title"), False, False, 0)
        grid = Gtk.Grid()
        grid.set_row_spacing(SPACE_XS)
        grid.set_column_spacing(SPACE_XS)
        grid.set_column_homogeneous(True)
        self.gauges = {
            "CPU": RingGauge("CPU", CAIRO_PRIMARY),
            "GPU": RingGauge("GPU", CAIRO_SECONDARY),
            "RAM": RingGauge("RAM", CAIRO_ACCENT),
            "DISK": RingGauge("DISK", CAIRO_PRIMARY),
        }
        for index, gauge in enumerate(self.gauges.values()):
            grid.attach(gauge, index % 2, index // 2, 1, 1)
        panel.pack_start(grid, False, False, 0)
        self.network_label = make_label("↓ 0 KiB/s    ↑ 0 KiB/s", "body-muted")
        panel.pack_start(self.network_label, False, False, 0)
        return panel

    def on_submit(self, _widget):
        request_text = self.entry.get_text().strip()
        if not request_text:
            return
        self.entry.set_text("")
        self.response.set_text(f"Preview request: {request_text}")
        add_class(self.response, "status-text")
        self.waveform.set_active(True)
        self.application.set_ai_activity("thinking")
        GLib.timeout_add(800, self.finish_preview)

    def finish_preview(self):
        self.response.set_text(
            "Not executed: connect an AI backend before using assistant actions."
        )
        self.response.get_style_context().remove_class("status-text")
        add_class(self.response, "stub-text")
        self.waveform.set_active(False)
        self.application.set_ai_activity("idle")
        return False

    def show_stub(self, message):
        self.response.set_text(message)
        self.response.get_style_context().remove_class("status-text")
        add_class(self.response, "stub-text")

    def refresh_system(self):
        self.gauges["CPU"].set_value(self.sampler.cpu_percent())
        self.gauges["GPU"].set_value(self.sampler.gpu_percent())
        self.gauges["RAM"].set_value(self.sampler.memory_percent())
        self.gauges["DISK"].set_value(self.sampler.storage_percent())
        down, up = self.sampler.network_rates()
        self.network_label.set_text(f"↓ {format_rate(down)}    ↑ {format_rate(up)}")
        return True


class DarkOSRightPanels(Gtk.Window):
    def __init__(self, application):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.syncing_toggles = False
        self.media_active = False
        self.set_title("DarkOS Right Panels")
        self.set_decorated(False)
        self.set_app_paintable(True)
        add_class(self, "darkos-window")
        configure_layer_window(
            self,
            "darkos-right",
            GtkLayerShell.Layer.TOP if HAS_LAYER_SHELL else None,
            (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.RIGHT)
            if HAS_LAYER_SHELL
            else (),
            {GtkLayerShell.Edge.TOP: 16, GtkLayerShell.Edge.RIGHT: 14}
            if HAS_LAYER_SHELL
            else {},
            keyboard=True,
        )

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_overlay_scrolling(True)
        screen = Gdk.Screen.get_default()
        screen_height = screen.get_height() if screen is not None else 1080
        panel_height = max(480, min(760, screen_height - 158))
        scroller.set_propagate_natural_height(False)
        scroller.set_min_content_height(panel_height)
        scroller.set_max_content_height(panel_height)
        scroller.set_size_request(360, panel_height)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        root.set_size_request(340, -1)
        root.pack_start(self.build_notifications(), False, False, 0)
        root.pack_start(self.build_connectivity(), False, False, 0)
        root.pack_start(self.build_media(), False, False, 0)
        root.pack_start(self.build_calendar(), False, False, 0)
        scroller.add(root)
        self.add(scroller)
        self.application.register_state_listener(self)
        self.sync_from_application()
        self.show_all()
        # Use a 5s interval (not 2s) so overlapping playerctl calls can't
        # stack if a slow player hangs near the 1.5s command_output timeout.
        GLib.timeout_add(5000, self.refresh_media)

    def build_notifications(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_SM)
        header.pack_start(make_label("NOTIFICATIONS", "section-title"), True, True, 0)
        clear_button = Gtk.Button(label="󰆴  Clear All")
        add_class(clear_button, "action-button")
        clear_button.set_tooltip_text("Dismiss visible Mako notifications")
        clear_button.connect("clicked", self.clear_notifications)
        header.pack_end(clear_button, False, False, 0)
        panel.pack_start(header, False, False, 0)
        panel.pack_start(make_label("SYSTEM", "eyebrow"), False, False, 0)
        panel.pack_start(
            make_label("No system notification feed is connected.", "stub-text", wrap=True),
            False,
            False,
            0,
        )
        panel.pack_start(Gtk.Separator(), False, False, 0)
        panel.pack_start(make_label("RECENT", "eyebrow"), False, False, 0)
        self.notification_status = make_label(
            "Mako popups remain live; history integration is not connected.",
            "stub-text",
            wrap=True,
        )
        panel.pack_start(self.notification_status, False, False, 0)
        return panel

    def build_connectivity(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("CONNECTIVITY", "section-title"), False, False, 0)
        grid = Gtk.Grid()
        grid.set_column_spacing(SPACE_SM)
        grid.set_row_spacing(SPACE_SM)
        grid.set_column_homogeneous(True)
        toggle_specs = (
            ("wifi", "󰤨  Wi-Fi"),
            ("bluetooth", "󰂯  Bluetooth"),
            ("dark_mode", "󰔎  Dark Mode"),
            ("night_light", "󰌵  Night Light"),
            ("focus", "󰍦  Focus"),
            ("airplane", "󰀝  Airplane"),
        )
        self.toggle_buttons = {}
        for index, (name, label) in enumerate(toggle_specs):
            button = Gtk.ToggleButton(label=label)
            add_class(button, "toggle-button")
            button.connect("toggled", self.on_toggle, name)
            button.get_accessible().set_name(label.replace("  ", " "))
            grid.attach(button, index % 2, index // 2, 1, 1)
            self.toggle_buttons[name] = button
        self.toggle_buttons["dark_mode"].set_sensitive(False)
        self.toggle_buttons["dark_mode"].set_tooltip_text(
            "Dark is the only shell theme in Phase 2"
        )
        panel.pack_start(grid, False, False, 0)

        self.volume_scale = self.add_scale(panel, "Audio volume", 0, 100, 5, 75)
        self.volume_scale.connect("value-changed", self.on_volume_changed)
        self.brightness_scale = self.add_scale(
            panel, "Display brightness", 10, 100, 5, 80
        )
        self.brightness_scale.connect("value-changed", self.on_brightness_changed)
        self.control_status = make_label(
            "Night Light and Focus are preview controls only.",
            "stub-text",
            wrap=True,
        )
        panel.pack_start(self.control_status, False, False, 0)
        return panel

    @staticmethod
    def add_scale(panel, title, minimum, maximum, step, initial):
        label = make_label(title, "body-muted")
        panel.pack_start(label, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimum, maximum, step)
        scale.set_draw_value(False)
        scale.set_value(initial)
        panel.pack_start(scale, False, False, 0)
        return scale

    def build_media(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("NOW PLAYING", "section-title"), False, False, 0)
        self.media_title = make_label("No active media", "media-title", wrap=True)
        self.media_artist = make_label("Start a player to populate this widget.", "body-muted", wrap=True)
        panel.pack_start(self.media_title, False, False, 0)
        panel.pack_start(self.media_artist, False, False, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_MD)
        controls.set_halign(Gtk.Align.CENTER)
        self.media_buttons = (
            make_icon_button(
                "󰒮", "Previous track", lambda _button: launch(["playerctl", "previous"])
            ),
            make_icon_button(
                "󰏤", "Play or pause", lambda _button: launch(["playerctl", "play-pause"])
            ),
            make_icon_button(
                "󰒭", "Next track", lambda _button: launch(["playerctl", "next"])
            ),
        )
        for button in self.media_buttons:
            button.set_sensitive(False)
            controls.pack_start(button, False, False, 0)
        panel.pack_start(controls, False, False, 0)
        return panel

    @staticmethod
    def build_calendar():
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SPACE_SM)
        add_class(panel, "glass-panel")
        panel.pack_start(make_label("CALENDAR", "section-title"), False, False, 0)
        calendar_widget = Gtk.Calendar()
        add_class(calendar_widget, "calendar")
        calendar_widget.set_hexpand(True)
        panel.pack_start(calendar_widget, False, False, 0)
        return panel

    def sync_from_application(self):
        self.syncing_toggles = True
        for name, button in self.toggle_buttons.items():
            button.set_active(bool(self.application.toggle_state.get(name, False)))
        self.syncing_toggles = False

    def on_toggle(self, button, name):
        if self.syncing_toggles:
            return
        self.application.set_toggle(name, button.get_active())

    def set_control_status(self, message, is_stub=False):
        self.control_status.set_text(message)
        context = self.control_status.get_style_context()
        context.remove_class("status-text")
        context.remove_class("stub-text")
        add_class(self.control_status, "stub-text" if is_stub else "status-text")

    def on_volume_changed(self, scale):
        value = str(int(scale.get_value()))
        if not launch(["pamixer", "--set-volume", value]):
            self.set_control_status("Volume change failed: pamixer is unavailable.", True)

    def on_brightness_changed(self, scale):
        value = f"{int(scale.get_value())}%"
        if not launch(["brightnessctl", "set", value]):
            self.set_control_status(
                "Brightness change failed: no compatible backlight was found.", True
            )

    def clear_notifications(self, _button):
        if launch(["makoctl", "dismiss", "--all"]):
            self.notification_status.set_text("Visible Mako notifications dismissed.")
            self.notification_status.get_style_context().remove_class("stub-text")
            add_class(self.notification_status, "status-text")
        else:
            self.notification_status.set_text("Could not reach Mako notification control.")

    def refresh_media(self):
        metadata = command_output(
            ["playerctl", "metadata", "--format", "{{title}}\t{{artist}}"]
        )
        status = command_output(["playerctl", "status"])
        active = metadata is not None and status is not None
        if active:
            title, separator, artist = metadata.partition("\t")
            self.media_title.set_text(title or "Untitled media")
            self.media_artist.set_text(artist if separator and artist else status)
        else:
            self.media_title.set_text("No active media")
            self.media_artist.set_text("Start a player to populate this widget.")
        if active != self.media_active:
            self.media_active = active
            for button in self.media_buttons:
                button.set_sensitive(active)
        return True


class DarkOSApplication(Gtk.Application):
    """Single-instance controller and shared shell state owner."""

    def __init__(self):
        super().__init__(
            application_id="org.darkos.Shell",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.dock = None
        self.hud = None
        self.rail = None
        self.left = None
        self.right = None
        self.installer_visibility = None
        self.state_listeners = []
        self.current_theme = "dark"
        self.toggle_state = {
            "wifi": self.query_wifi(),
            "bluetooth": self.query_bluetooth(),
            "dark_mode": True,
            "night_light": False,
            "focus": False,
            "airplane": False,
        }

    @staticmethod
    def query_wifi():
        value = command_output(["nmcli", "radio", "wifi"])
        return value == "enabled" if value is not None else False

    @staticmethod
    def query_bluetooth():
        value = command_output(["bluetoothctl", "show"])
        return bool(value and "Powered: yes" in value)

    def register_state_listener(self, listener):
        self.state_listeners.append(listener)

    def notify_state_listeners(self):
        for listener in self.state_listeners:
            listener.sync_from_application()

    def do_activate(self):
        if self.dock is not None:
            return
        apply_css()
        self.dock = DarkOSDockWindow(self)
        self.hud = DarkOSHUDOverlay()
        self.rail = DarkOSIconRail(self)
        self.left = DarkOSLeftPanels(self)
        self.right = DarkOSRightPanels(self)
        for window in (self.dock, self.hud, self.rail, self.left, self.right):
            self.add_window(window)

    @staticmethod
    def toggle(window):
        if window.is_visible():
            window.hide()
        else:
            window.show_all()

    def set_ai_activity(self, state):
        radar_state = "idle" if state == "sleeping" else state
        if self.hud is not None:
            self.hud.radar.set_activity(radar_state)

    def set_toggle(self, name, enabled):
        self.toggle_state[name] = enabled
        if name == "wifi":
            launch(["nmcli", "radio", "wifi", "on" if enabled else "off"])
            self.right.set_control_status(
                f"Wi-Fi {'enabled' if enabled else 'disabled'} via NetworkManager."
            )
        elif name == "bluetooth":
            launch(["bluetoothctl", "power", "on" if enabled else "off"])
            self.right.set_control_status(
                f"Bluetooth {'enabled' if enabled else 'disabled'}."
            )
        elif name == "airplane":
            launch(["nmcli", "radio", "all", "off" if enabled else "on"])
            launch(["bluetoothctl", "power", "off" if enabled else "on"])
            self.toggle_state["wifi"] = not enabled
            self.toggle_state["bluetooth"] = not enabled
            self.right.set_control_status(
                f"Airplane mode {'enabled' if enabled else 'disabled'}."
            )
        elif name in ("night_light", "focus"):
            display_name = "Night Light" if name == "night_light" else "Focus"
            self.right.set_control_status(
                f"Preview only: {display_name} has no system backend yet.", True
            )
        self.notify_state_listeners()

    def handle_rail_action(self, action):
        commands = {
            "files": ["kitty", "-e", "ranger"],
            "terminal": ["/usr/local/bin/the-void.sh"],
            "settings": ["wofi", "--show", "drun"],
            "browser": ["firefox"],
            "store": ["wofi", "--show", "drun"],
            "notes": ["kitty", "-e", "nvim"],
        }
        if action == "ai":
            if not self.left.is_visible():
                self.left.show_all()
            self.left.entry.grab_focus()
            return
        if action in commands:
            launch(commands[action])
            return
        phase = {"gallery": "4", "music": "7", "gaming": "7"}.get(action, "later")
        self.left.show_stub(
            f"Not opened: {action.title()} is a Phase {phase} surface and is not built yet."
        )

    def set_installer_mode(self, enabled):
        overlays = (self.dock, self.hud, self.rail, self.left, self.right)
        if enabled:
            if self.installer_visibility is None:
                self.installer_visibility = tuple(
                    window.is_visible() for window in overlays
                )
            for window in overlays:
                window.hide()
            return
        if self.installer_visibility is None:
            return
        for window, was_visible in zip(overlays, self.installer_visibility):
            if was_visible:
                window.show_all()
            else:
                window.hide()
        self.installer_visibility = None

    def do_command_line(self, command_line):
        parser = argparse.ArgumentParser(description="DarkOS Shell Controller")
        parser.add_argument("--toggle-hud", action="store_true")
        parser.add_argument("--toggle-ai", action="store_true")
        parser.add_argument("--toggle-side-panels", action="store_true")
        parser.add_argument("--toggle-control", action="store_true")
        parser.add_argument("--toggle-left", action="store_true")
        parser.add_argument("--toggle-rail", action="store_true")
        parser.add_argument("--lock", action="store_true")
        parser.add_argument("--installer-mode", choices=("on", "off"))
        try:
            args = parser.parse_args(command_line.get_arguments()[1:])
        except SystemExit as error:
            return int(error.code or 0)

        self.activate()
        if args.installer_mode:
            self.set_installer_mode(args.installer_mode == "on")
        if args.toggle_side_panels:
            self.toggle(self.left)
            self.toggle(self.right)
        if args.toggle_control:
            self.toggle(self.right)
        if args.toggle_left:
            self.toggle(self.left)
        if args.toggle_rail:
            self.toggle(self.rail)
        if args.toggle_hud:
            self.toggle(self.hud)
        if args.toggle_ai:
            if not self.left.is_visible():
                self.left.show_all()
            self.left.entry.grab_focus()
        if args.lock:
            launch(["loginctl", "lock-session"])
        return 0


def main():
    application = DarkOSApplication()
    return application.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
