#!/usr/bin/env python3
"""
DarkOS - Core Desktop Shell Chrome & AI HUD
GTK3 + Layer Shell Desktop Overlay
"""
import sys
import os
import math
import time
import argparse

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango

try:
    gi.require_version('GtkLayerShell', '0.1')
    from gi.repository import GtkLayerShell
    HAS_LAYER_SHELL = True
except Exception:
    HAS_LAYER_SHELL = False

# --- Design Tokens ---
COLOR_BG = (0.0, 0.0, 0.0, 0.65)
COLOR_CYAN = (0.0, 0.898, 1.0, 1.0)
COLOR_CYAN_GLOW = (0.0, 0.898, 1.0, 0.3)
COLOR_BLUE = (0.176, 0.482, 1.0, 1.0)
COLOR_PURPLE = (0.659, 0.333, 0.969, 1.0)
COLOR_TEXT = (0.949, 0.961, 0.969, 1.0)
COLOR_TEXT_MUTED = (0.604, 0.643, 0.678, 1.0)
COLOR_SURFACE = (1.0, 1.0, 1.0, 0.06)

# --- Dynamic CSS Injection ---
CSS_STYLE = """
* {
    font-family: 'Inter', 'Space Grotesk', 'JetBrainsMono Nerd Font', sans-serif;
}

.darkos-window {
    background-color: transparent;
}

.glass-panel {
    background-color: rgba(10, 14, 23, 0.75);
    border: 1px solid rgba(0, 229, 255, 0.25);
    border-radius: 16px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
    padding: 16px;
}

.glass-card {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 12px;
}

.dock-bar {
    background-color: rgba(5, 8, 15, 0.82);
    border: 1px solid rgba(0, 229, 255, 0.3);
    border-radius: 24px;
    padding: 6px 16px;
    box-shadow: 0 10px 40px rgba(0, 229, 255, 0.2);
}

.dock-icon-btn {
    background-color: transparent;
    border: none;
    border-radius: 16px;
    padding: 8px 12px;
    color: #00e5ff;
    font-size: 18px;
    transition: all 0.2s ease;
}

.dock-icon-btn:hover {
    background-color: rgba(0, 229, 255, 0.2);
    box-shadow: 0 0 12px rgba(0, 229, 255, 0.4);
}

.ai-entry {
    background-color: rgba(0, 0, 0, 0.5);
    border: 1px solid rgba(0, 229, 255, 0.4);
    border-radius: 12px;
    color: #f2f5f7;
    padding: 8px 14px;
    font-size: 14px;
}

.ai-entry:focus {
    border-color: #00e5ff;
    box-shadow: 0 0 14px rgba(0, 229, 255, 0.5);
}

.icon-rail-btn {
    background-color: transparent;
    border: none;
    border-radius: 10px;
    color: #9aa4ad;
    padding: 10px;
    font-size: 16px;
}

.icon-rail-btn:hover {
    color: #00e5ff;
    background-color: rgba(0, 229, 255, 0.15);
}

.toggle-btn {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    color: #f2f5f7;
    padding: 8px 12px;
}

.toggle-btn.active {
    background-color: rgba(0, 229, 255, 0.2);
    border-color: #00e5ff;
    color: #00e5ff;
    box-shadow: 0 0 8px rgba(0, 229, 255, 0.3);
}
"""

def apply_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS_STYLE.encode('utf-8'))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

# --- Drawing Utilities ---
class AIOrbCanvas(Gtk.DrawingArea):
    """Interactive AI Orb canvas with 5 visual states"""
    def __init__(self, size=54):
        super().__init__()
        self.set_size_request(size, size)
        self.state = "sleeping"  # sleeping, listening, thinking, speaking, error
        self.anim_phase = 0.0
        self.connect("draw", self.on_draw)
        GLib.timeout_add(33, self.on_animate)

    def on_animate(self):
        self.anim_phase += 0.05
        if self.anim_phase > math.pi * 200:
            self.anim_phase = 0.0
        self.queue_draw()
        return True

    def set_state(self, new_state):
        self.state = new_state
        self.queue_draw()

    def on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cx, cy = width / 2.0, height / 2.0
        radius = min(cx, cy) - 6.0

        # State-based parameters
        if self.state == "listening":
            pulse = 1.0 + 0.08 * math.sin(self.anim_phase * 3.0)
            glow_color = (0.0, 0.898, 1.0, 0.8)
        elif self.state == "thinking":
            pulse = 1.0 + 0.05 * math.sin(self.anim_phase * 5.0)
            glow_color = (0.176, 0.482, 1.0, 0.85)
        elif self.state == "speaking":
            pulse = 1.0 + 0.12 * abs(math.sin(self.anim_phase * 4.0))
            glow_color = (0.659, 0.333, 0.969, 0.85)
        elif self.state == "error":
            pulse = 1.0 + 0.04 * math.sin(self.anim_phase * 6.0)
            glow_color = (1.0, 0.23, 0.23, 0.9)
        else: # sleeping
            pulse = 1.0 + 0.03 * math.sin(self.anim_phase * 1.5)
            glow_color = (0.0, 0.898, 1.0, 0.5)

        r = radius * pulse

        # Outer Glow
        cr.save()
        for i in range(5, 0, -1):
            cr.arc(cx, cy, r + i * 2.5, 0, 2 * math.pi)
            cr.set_source_rgba(glow_color[0], glow_color[1], glow_color[2], glow_color[3] * 0.12 * (6 - i))
            cr.fill()

        # Core Orb Gradient
        pattern = cairo_create_radial(cr, cx, cy, 2.0, cx, cy, r)
        pattern.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.95)
        pattern.add_color_stop_rgba(0.4, glow_color[0], glow_color[1], glow_color[2], 0.9)
        pattern.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.4)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source(pattern)
        cr.fill()

        # Rotating Outer Ring (Thinking / Listening)
        if self.state in ["thinking", "listening"]:
            cr.set_line_width(2.0)
            cr.set_source_rgba(glow_color[0], glow_color[1], glow_color[2], 0.8)
            angle_start = self.anim_phase * 2.0
            cr.arc(cx, cy, r + 4, angle_start, angle_start + math.pi * 0.7)
            cr.stroke()

        cr.restore()
        return False

def cairo_create_radial(cr, cx, cy, r1, cx2, cy2, r2):
    import cairo
    return cairo.RadialGradient(cx, cy, r1, cx2, cy2, r2)


class AIRadarCanvas(Gtk.DrawingArea):
    """Central AI HUD Radar / Dial Display"""
    def __init__(self):
        super().__init__()
        self.set_size_request(380, 260)
        self.rotation = 0.0
        self.connect("draw", self.on_draw)
        GLib.timeout_add(40, self.on_animate)

    def on_animate(self):
        self.rotation += 0.015
        self.queue_draw()
        return True

    def on_draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        cx, cy = w / 2.0, h / 2.0 - 15

        # Concentric Rings
        radii = [50, 85, 115]
        for i, r in enumerate(radii):
            cr.save()
            cr.set_line_width(1.5)
            if i % 2 == 0:
                cr.set_source_rgba(0.0, 0.898, 1.0, 0.4)
            else:
                cr.set_source_rgba(0.176, 0.482, 1.0, 0.35)

            # Dashed arc effect
            dashes = [12.0, 6.0]
            cr.set_dash(dashes, self.rotation * (10.0 if i % 2 == 0 else -8.0))
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            cr.restore()

        # Segmented Dial Ticks
        cr.save()
        for angle in range(0, 360, 15):
            rad = math.radians(angle) + self.rotation * 0.5
            x1 = cx + 105 * math.cos(rad)
            y1 = cy + 105 * math.sin(rad)
            x2 = cx + 113 * math.cos(rad)
            y2 = cy + 113 * math.sin(rad)
            cr.set_source_rgba(0.0, 0.898, 1.0, 0.6 if angle % 45 == 0 else 0.25)
            cr.set_line_width(2.0 if angle % 45 == 0 else 1.0)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()
        cr.restore()

        # Inner Pulsing Core
        pulse_r = 18 + 3 * math.sin(self.rotation * 3.0)
        cr.save()
        cr.arc(cx, cy, pulse_r, 0, 2 * math.pi)
        cr.set_source_rgba(0.0, 0.898, 1.0, 0.7)
        cr.fill()
        cr.arc(cx, cy, pulse_r + 8, 0, 2 * math.pi)
        cr.set_source_rgba(0.0, 0.898, 1.0, 0.2)
        cr.fill()
        cr.restore()

        return False


# --- Shell Overlay Windows ---
class DarkOSDockWindow(Gtk.Window):
    """Floating Glass Dock at screen bottom with AI Orb"""
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("DarkOS Dock")
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.get_style_context().add_class("darkos-window")

        if HAS_LAYER_SHELL:
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 14)
            GtkLayerShell.set_exclusive_zone(self, 70)

        # Outer Dock Container
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.get_style_context().add_class("dock-bar")
        box.set_halign(Gtk.Align.CENTER)

        # Dock Launchers
        left_apps = [
            ("󰋜", "Files", "kitty -e ranger"),
            ("󰞷", "Terminal", "sh /usr/local/bin/the-void.sh"),
            ("󰈹", "Browser", "firefox"),
        ]

        right_apps = [
            ("󰠮", "Notes", "kitty -e nvim"),
            ("󰄨", "Store", "wofi --show drun"),
            ("󰒓", "Settings", "wofi --show drun"),
        ]

        for icon, name, cmd in left_apps:
            btn = Gtk.Button(label=icon)
            btn.get_style_context().add_class("dock-icon-btn")
            btn.set_tooltip_text(name)
            btn.connect("clicked", lambda b, c=cmd: os.system(f"{c} &"))
            box.pack_start(btn, False, False, 0)

        # Center Enlarged AI Orb
        orb_box = Gtk.EventBox()
        self.ai_orb = AIOrbCanvas(size=56)
        orb_box.add(self.ai_orb)
        orb_box.set_tooltip_text("DarkOS AI Assistant (Click to Talk)")
        orb_box.connect("button-press-event", self.on_orb_click)
        box.pack_start(orb_box, False, False, 6)

        for icon, name, cmd in right_apps:
            btn = Gtk.Button(label=icon)
            btn.get_style_context().add_class("dock-icon-btn")
            btn.set_tooltip_text(name)
            btn.connect("clicked", lambda b, c=cmd: os.system(f"{c} &"))
            box.pack_start(btn, False, False, 0)

        self.add(box)
        self.show_all()

    def on_orb_click(self, widget, event):
        # Toggle AI Orb state
        states = ["sleeping", "listening", "thinking", "speaking"]
        curr_idx = states.index(self.ai_orb.state) if self.ai_orb.state in states else 0
        next_state = states[(curr_idx + 1) % len(states)]
        self.ai_orb.set_state(next_state)


class DarkOSHUDOverlay(Gtk.Window):
    """Central AI Radar HUD and Action Surface"""
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("DarkOS AI HUD")
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.get_style_context().add_class("darkos-window")

        if HAS_LAYER_SHELL:
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 90)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.get_style_context().add_class("glass-panel")
        main_box.set_halign(Gtk.Align.CENTER)
        main_box.set_size_request(440, -1)

        # AI Radar Dial
        self.radar = AIRadarCanvas()
        main_box.pack_start(self.radar, False, False, 0)

        # Tagline
        tag = Gtk.Label()
        tag.set_markup("<span color='#00e5ff' font='14' weight='bold'>CONTROL EVERYTHING</span>")
        main_box.pack_start(tag, False, False, 0)

        subtitle = Gtk.Label()
        subtitle.set_markup("<span color='#9aa4ad' font='11'>Ask AI to launch apps, adjust settings, or inspect system</span>")
        main_box.pack_start(subtitle, False, False, 0)

        # Input Prompt Entry
        entry_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.entry = Gtk.Entry()
        self.entry.get_style_context().add_class("ai-entry")
        self.entry.set_placeholder_text("Type a command or ask DarkOS AI...")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self.on_submit)
        entry_box.pack_start(self.entry, True, True, 0)

        submit_btn = Gtk.Button(label="󰄬")
        submit_btn.get_style_context().add_class("dock-icon-btn")
        submit_btn.connect("clicked", self.on_submit)
        entry_box.pack_start(submit_btn, False, False, 0)

        main_box.pack_start(entry_box, False, False, 6)

        # Response Feedback Card
        self.response_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.response_card.get_style_context().add_class("glass-card")
        self.response_label = Gtk.Label()
        self.response_label.set_markup("<span color='#00e5ff'><b>AI Assistant:</b> Ready and monitoring session.</span>")
        self.response_label.set_line_wrap(True)
        self.response_card.pack_start(self.response_label, False, False, 0)
        main_box.pack_start(self.response_card, False, False, 0)

        self.add(main_box)
        self.show_all()

    def on_submit(self, widget):
        text = self.entry.get_text().strip()
        if not text:
            return
        self.response_label.set_markup(f"<span color='#00e5ff'><b>Processing:</b></span> <span color='#f2f5f7'>{text}</span>")
        self.entry.set_text("")
        
        # Stub response handler
        GLib.timeout_add(800, lambda: self.response_label.set_markup(
            f"<span color='#22e07a'><b>AI Result:</b></span> <span color='#f2f5f7'>Executed command '{text}' successfully.</span>"
        ))


class DarkOSSidePanels(Gtk.Window):
    """Floating Glass Side Panels (Control Center & Notifications)"""
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("DarkOS Quick Controls")
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.get_style_context().add_class("darkos-window")

        if HAS_LAYER_SHELL:
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 54)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 14)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        panel.get_style_context().add_class("glass-panel")
        panel.set_size_request(320, -1)

        # Title
        hdr = Gtk.Label()
        hdr.set_markup("<span color='#00e5ff' font='13' weight='bold'>CONTROL CENTER</span>")
        hdr.set_halign(Gtk.Align.START)
        panel.pack_start(hdr, False, False, 0)

        # Quick Toggles Grid
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        grid.set_column_homogeneous(True)

        toggles = [
            ("󰤨  Wi-Fi", True),
            ("󰂯  Bluetooth", True),
            ("󰔎  Dark Mode", True),
            ("󰌵  Night Light", False),
            ("󰍦  Focus Mode", False),
            ("󰀝  Airplane", False),
        ]

        for i, (name, active) in enumerate(toggles):
            btn = Gtk.ToggleButton(label=name)
            btn.get_style_context().add_class("toggle-btn")
            btn.set_active(active)
            if active:
                btn.get_style_context().add_class("active")
            grid.attach(btn, i % 2, i // 2, 1, 1)

        panel.pack_start(grid, False, False, 0)

        # Volume Slider
        vol_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vol_lbl = Gtk.Label()
        vol_lbl.set_markup("<span color='#9aa4ad' font='11'>Audio Volume</span>")
        vol_lbl.set_halign(Gtk.Align.START)
        vol_box.pack_start(vol_lbl, False, False, 0)

        vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        vol_scale.set_value(75)
        vol_scale.connect("value-changed", lambda s: os.system(f"pamixer --set-volume {int(s.get_value())}"))
        vol_box.pack_start(vol_scale, False, False, 0)
        panel.pack_start(vol_box, False, False, 0)

        # Brightness Slider
        br_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        br_lbl = Gtk.Label()
        br_lbl.set_markup("<span color='#9aa4ad' font='11'>Display Brightness</span>")
        br_lbl.set_halign(Gtk.Align.START)
        br_box.pack_start(br_lbl, False, False, 0)

        br_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 5)
        br_scale.set_value(80)
        br_scale.connect("value-changed", lambda s: os.system(f"brightnessctl set {int(s.get_value())}%"))
        br_box.pack_start(br_scale, False, False, 0)
        panel.pack_start(br_box, False, False, 0)

        # Media Widget Card
        media_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        media_card.get_style_context().add_class("glass-card")
        media_title = Gtk.Label()
        media_title.set_markup("<span color='#00e5ff'><b>󰎈 Synthwave Cyber HUD</b></span>")
        media_artist = Gtk.Label()
        media_artist.set_markup("<span color='#9aa4ad' font='10'>DarkOS System Audio Engine</span>")
        media_card.pack_start(media_title, False, False, 0)
        media_card.pack_start(media_artist, False, False, 0)

        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ctrl_box.set_halign(Gtk.Align.CENTER)
        prev_btn = Gtk.Button(label="󰒮")
        play_btn = Gtk.Button(label="󰏤")
        next_btn = Gtk.Button(label="xd")

        for b in (prev_btn, play_btn, next_btn):
            b.get_style_context().add_class("dock-icon-btn")
        ctrl_box.pack_start(prev_btn, False, False, 0)
        ctrl_box.pack_start(play_btn, False, False, 0)
        ctrl_box.pack_start(next_btn, False, False, 0)
        media_card.pack_start(ctrl_box, False, False, 0)

        panel.pack_start(media_card, False, False, 0)

        self.add(panel)
        self.show_all()


# --- Main Application Controller ---
def main():
    parser = argparse.ArgumentParser(description="DarkOS Shell Controller")
    parser.add_argument("--toggle-hud", action="store_true", help="Toggle AI HUD Radar Overlay")
    parser.add_argument("--toggle-ai", action="store_true", help="Focus AI Prompt")
    parser.add_argument("--toggle-side-panels", action="store_true", help="Toggle Quick Control Panel")
    parser.add_argument("--toggle-control", action="store_true", help="Toggle Control Center")
    args = parser.parse_args()

    apply_css()

    dock = DarkOSDockWindow()
    hud = DarkOSHUDOverlay()
    controls = DarkOSSidePanels()

    # Toggle handlers for CLI triggers
    if args.toggle_side_panels or args.toggle_control:
        if controls.is_visible():
            controls.hide()
        else:
            controls.show_all()
            
    if args.toggle_hud or args.toggle_ai:
        if hud.is_visible():
            hud.hide()
        else:
            hud.show_all()

    Gtk.main()

if __name__ == "__main__":
    main()
