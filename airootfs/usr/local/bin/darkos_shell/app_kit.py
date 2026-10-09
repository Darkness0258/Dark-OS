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
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gio  # noqa: E402

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


def _attach_snap_layouts(win, button):
    """Hover-to-pick snap layouts on the maximize button."""
    try:
        import gi as _gi
        _gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
    except Exception:
        return

    try:
        popover = Gtk.Popover()
        popover.set_relative_to(button)
    except Exception:
        return
    try:
        popover.set_modal(False)
    except Exception:
        pass
    grid = Gtk.Grid()
    grid.set_column_spacing(4)
    grid.set_row_spacing(4)
    grid.set_border_width(8)

    def snap(side):
        popover.popdown()
        try:
            subprocess.Popen(
                ["python", "/usr/local/bin/darkos-window-fx.py", "--snap", side],
                start_new_session=True,
            )
        except OSError:
            pass

    cells = (
        (0, 0, 1, "top-left", "TL"),
        (1, 0, 1, "top-right", "TR"),
        (0, 1, 1, "bottom-left", "BL"),
        (1, 1, 1, "bottom-right", "BR"),
        (0, 2, 1, "left", "Left"),
        (1, 2, 1, "right", "Right"),
        (0, 3, 2, "maximize", "Maximize"),
    )
    for col, row, width, side, label in cells:
        cell = Gtk.Button(label=label)
        cell.set_tooltip_text(f"Snap {side.replace('-', ' ')}")
        cell.connect("clicked", lambda _b, value=side: snap(value))
        grid.attach(cell, col, row, width, 1)
    grid.show_all()
    popover.add(grid)
    pending = {"id": 0}

    def show():
        pending["id"] = 0
        popover.popup()
        return False

    def on_enter(_widget, _event):
        if pending["id"]:
            GLib.source_remove(pending["id"])
        pending["id"] = GLib.timeout_add(400, show)
        return False

    def on_leave(_widget, _event):
        if pending["id"]:
            GLib.source_remove(pending["id"])
            pending["id"] = 0
        return False

    button.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
    button.connect("enter-notify-event", on_enter)
    button.connect("leave-notify-event", on_leave)


def build_titlebar(win, title):
    """Windows-style custom title bar: title on the left, minimize/
    maximize/close on the right.

    Hyprland draws no server-side window decorations, and a plain
    Gtk.ApplicationWindow with no titlebar gets no CSD either — that's
    why every app window had no mouse-clickable close button at all
    (SUPER+C was the only way to close anything). A real Gtk.HeaderBar
    would normally fill this role, but its button set/order comes from
    the desktop's gtk-decoration-layout setting, which nothing on this
    session provides (no GNOME Settings Daemon) -- so we build the three
    buttons explicitly instead of trusting an ambient default that
    doesn't exist here. Unlike HeaderBar, a plain Gtk.Box has no built-in
    drag-to-move or double-click-to-maximize, so both are wired by hand
    below.
    """
    import gi
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk

    bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    add_class(bar, "app-titlebar")

    label = Gtk.Label(label=title or "", xalign=0.0)
    add_class(label, "app-titlebar-title")
    label.set_ellipsize(True)
    bar.pack_start(label, True, True, 0)

    def _toggle_maximize(_widget=None):
        if win.is_maximized():
            win.unmaximize()
        else:
            win.maximize()

    def _make_button(icon_name, tooltip, on_click, extra_class=None):
        button = Gtk.Button()
        button.add(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
        button.set_tooltip_text(tooltip)
        button.get_accessible().set_name(tooltip)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_focus_on_click(False)
        add_class(button, "app-titlebar-btn")
        if extra_class:
            add_class(button, extra_class)
        button.connect("clicked", on_click)
        return button

    controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
    controls.pack_start(
        _make_button("window-minimize-symbolic", "Minimize", lambda _b: win.iconify()),
        False, False, 0,
    )
    maximize_btn = _make_button(
        "window-maximize-symbolic",
        "Maximize. Hover for snap layouts.",
        lambda _b: _toggle_maximize(),
    )
    _attach_snap_layouts(win, maximize_btn)
    controls.pack_start(maximize_btn, False, False, 0)
    controls.pack_start(
        _make_button("window-close-symbolic", "Close", lambda _b: win.close(), "app-titlebar-btn-close"),
        False, False, 0,
    )
    bar.pack_end(controls, False, False, 4)

    bar.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)

    def _on_press(_widget, event):
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            _toggle_maximize()
            return True
        if event.button == 1:
            win.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return False

    bar.connect("button-press-event", _on_press)
    bar.show_all()
    return bar


def run_app(application_id, wm_class, build_window, *, multiple_instances=False):
    """Standard app bootstrap: prgname -> Gtk.Application -> apply_css ->
    build_window(app) on activate. build_window must return a shown-ready
    Gtk.ApplicationWindow; run_app calls show_all() on it, then gives it
    a titlebar (see build_titlebar) unless the window already set one."""
    GLib.set_prgname(wm_class)
    # File-opening apps opt in so D-Bus activation cannot discard their
    # arguments. State-owning hubs stay single-instance to avoid competing
    # in-memory copies of the same vault/calendar/preferences.
    flags = Gio.ApplicationFlags.NON_UNIQUE if multiple_instances else Gio.ApplicationFlags.DEFAULT_FLAGS
    app = Gtk.Application(application_id=application_id, flags=flags)

    def on_activate(_app):
        existing = _app.get_active_window()
        if existing is None and _app.get_windows():
            existing = _app.get_windows()[0]
        if existing is not None:
            existing.present()
            return
        apply_css()
        win = build_window(_app)
        if win.get_titlebar() is None:
            win.set_titlebar(build_titlebar(win, win.get_title()))
        win.show_all()

    app.connect("activate", on_activate)
    app.run([sys.argv[0]])
