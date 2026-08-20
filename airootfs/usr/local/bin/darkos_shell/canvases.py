#!/usr/bin/env python3
"""GTK DrawingArea widgets for the shell: AI Orb, waveform, ring gauges."""

import math

import cairo
from gi.repository import GLib, Gtk

from darkos_shell.tokens import (
    CAIRO_ACCENT,
    CAIRO_DANGER,
    CAIRO_MUTED,
    CAIRO_PRIMARY,
    CAIRO_SECONDARY,
    CAIRO_TEXT,
    GLOW_STROKES_OUTSIDE_IN,
)


def stroke_glow(cr, color, alpha=1.0, width_scale=1.0):
    """Stroke the current Cairo path: outer haze, mid glow, crisp core."""
    final_index = len(GLOW_STROKES_OUTSIDE_IN) - 1
    for index, (line_width, alpha_scale) in enumerate(GLOW_STROKES_OUTSIDE_IN):
        cr.set_line_width(line_width * width_scale)
        cr.set_source_rgba(*color, min(1.0, alpha * alpha_scale))
        if index == final_index:
            cr.stroke()
        else:
            cr.stroke_preserve()


class AIOrbCanvas(Gtk.DrawingArea):
    """AI Orb with the five motion states defined by ui-rules.md."""

    def __init__(self, size=56):
        super().__init__()
        self.set_size_request(size, size)
        self.state = "sleeping"
        self.anim_phase = 0.0
        self._frame_count = 0
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
        self._frame_count += 1
        # Sleeping is a slow breathing glow — redrawing every 3rd tick
        # (~11fps) looks identical to every tick (~30fps) but cuts the
        # Cairo cost for the state the orb sits in almost all the time.
        # Phase still advances every tick so active states stay smooth
        # and don't visually "jump" on the next redraw.
        if self.state != "sleeping" or self._frame_count % 3 == 0:
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

        cr.arc(cx, cy, radius + 3, 0, 2 * math.pi)
        stroke_glow(cr, color, alpha * 0.72)

        if self.state != "sleeping":
            start = self.anim_phase * 1.8
            cr.arc(cx, cy, radius + 5, start, start + math.pi * 0.72)
            stroke_glow(cr, color, 0.86)
        return False


class WaveformCanvas(Gtk.DrawingArea):
    """Audio waveform bar visualizer for the AI chat card."""

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
    """Circular progress gauge for system metrics (CPU, GPU, RAM, Disk)."""

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
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(*CAIRO_TEXT, 0.08)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        if self.value is not None:
            cr.arc(cx, cy, radius, start, start + 2 * math.pi * self.value / 100.0)
            stroke_glow(cr, self.color, 0.92)

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
