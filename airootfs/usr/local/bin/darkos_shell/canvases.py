#!/usr/bin/env python3
"""GTK DrawingArea widgets for the shell: ring gauges."""

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


__all__ = [
    "GLOW_STROKES_OUTSIDE_IN",
    "RingGauge",
    "stroke_glow",
]


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
