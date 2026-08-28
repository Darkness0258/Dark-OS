"""Shared helpers for DarkOS standalone apps (Notes, Calendar, Clock,
Calculator, and later additions). Kept intentionally tiny: importing this
pulls in the whole darkos_shell package the same way darkos-files.py and
darkos-terminal.py already do (see their module docstrings for why that's
fine on the real target) — so nothing here should add a new hard dependency
beyond what the shell already requires.

darkos-files.py and darkos-terminal.py predate this module and still carry
their own local copies of add_class/make_icon_button — deliberately left
alone rather than retrofitted, since both are already Xvfb-verified and
touching them again would mean re-verifying for a purely cosmetic gain.
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib  # noqa: E402

from darkos_shell.css import apply_css  # noqa: E402


def add_class(widget, class_name):
    widget.get_style_context().add_class(class_name)
    return widget


def make_icon_button(icon_name, tooltip, callback, icon_size=Gtk.IconSize.LARGE_TOOLBAR):
    button = Gtk.Button()
    button.add(Gtk.Image.new_from_icon_name(icon_name, icon_size))
    button.set_tooltip_text(tooltip)
    button.get_accessible().set_name(tooltip)
    add_class(button, "icon-button")
    button.connect("clicked", callback)
    return button


def run_app(application_id, wm_class, build_window):
    """Standard app bootstrap: prgname -> Gtk.Application -> apply_css ->
    build_window(app) on activate. build_window must return a shown-ready
    Gtk.ApplicationWindow; run_app calls show_all() on it."""
    GLib.set_prgname(wm_class)
    app = Gtk.Application(application_id=application_id)

    def on_activate(_app):
        apply_css()
        win = build_window(_app)
        win.show_all()

    app.connect("activate", on_activate)
    app.run([sys.argv[0]])
