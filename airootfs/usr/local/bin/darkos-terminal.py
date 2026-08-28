#!/usr/bin/env python3
"""DarkOS Terminal ("The Void") — native GTK3 + VTE terminal.

Replaces the Phase 1 kitty wrapper. Real terminal emulation (PTY, ANSI,
scrollback) is VTE's job; this file only owns DarkOS chrome — tabs, glass
styling, keybinds. Every interactive control is a stock GTK3 widget (no
custom Cairo-drawn buttons) so AT-SPI can walk it like any other app —
see architecture.md's "AI control mechanism" section.

CLI contract matches the old the-void.sh, so existing callers keep working:
    darkos-terminal.py                  -> interactive shell
    darkos-terminal.py [-e] CMD [ARGS]  -> run CMD instead of the shell
"""
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, GLib, Gtk, Pango, Vte  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.css import apply_css  # noqa: E402

APP_ID = "org.darkos.Terminal"
WM_CLASS = "darkos-terminal"
DEFAULT_TITLE = "Shell"

# ANSI 0-15. Slots 0/2/4/5/6/12/13/14/15 map straight to design tokens;
# red/yellow/white get colors of their own because the token set doesn't
# define values that would read correctly in those ANSI slots (e.g. the
# warning-orange token in the "yellow" slot breaks tools that expect a
# real yellow for diffs/warnings).
PALETTE = [
    "#0d0f12", "#ff5f5f", "#22e07a", "#e5c07b",
    "#2d7bff", "#a855f7", "#00b8d4", "#9aa4ad",
    "#3a3f47", "#ff8a8a", "#5eff9f", "#ffd479",
    "#6fa8ff", "#c583ff", "#00e5ff", "#f2f5f7",
]
FOREGROUND = "#f2f5f7"
BACKGROUND = "#0a0c0f"


def add_class(widget, class_name):
    widget.get_style_context().add_class(class_name)
    return widget


def _rgba(hex_str):
    c = Gdk.RGBA()
    c.parse(hex_str)
    return c


def _default_shell():
    return os.environ.get("SHELL") or "/bin/bash"


class TerminalPage(Gtk.Box):
    """One VTE terminal, ready to drop into a Notebook page."""

    def __init__(self, window, command=None, cwd=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.font_size = 11

        self.vte = Vte.Terminal()
        self.vte.set_hexpand(True)
        self.vte.set_vexpand(True)
        self.vte.set_scrollback_lines(10000)
        self.vte.set_mouse_autohide(True)
        self.vte.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)
        self._apply_font()
        self.vte.set_colors(_rgba(FOREGROUND), _rgba(BACKGROUND),
                             [_rgba(c) for c in PALETTE])

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.vte)
        self.pack_start(scroller, True, True, 0)

        self.vte.connect("child-exited", self._on_child_exited)
        self.vte.connect("window-title-changed", self._on_title_changed)

        argv = [_default_shell()] if not command else list(command)
        self.vte.spawn_async(
            Vte.PtyFlags.DEFAULT,
            cwd or GLib.get_home_dir(),
            argv,
            None,
            GLib.SpawnFlags.SEARCH_PATH,
            None, None,
            -1, None,
            self._on_spawned, None,
        )

    def _apply_font(self):
        self.vte.set_font(Pango.FontDescription(f"JetBrains Mono {self.font_size}"))

    def zoom(self, delta=0, reset=False):
        self.font_size = 11 if reset else max(6, min(32, self.font_size + delta))
        self._apply_font()

    def _on_spawned(self, terminal, pid, error, _data):
        if error:
            terminal.feed(
                f"\r\n[darkos-terminal] failed to start: {error.message}\r\n".encode()
            )

    def _on_child_exited(self, terminal, status):
        self.window.close_page(self)

    def _on_title_changed(self, terminal):
        title = terminal.get_window_title() or DEFAULT_TITLE
        self.window.rename_page(self, title)


class TabLabel(Gtk.Box):
    def __init__(self, text, on_close):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.label = Gtk.Label(label=text)
        self.label.set_max_width_chars(18)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        close_btn = Gtk.Button()
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.add(Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU))
        close_btn.set_focus_on_click(False)
        close_btn.connect("clicked", on_close)
        add_class(close_btn, "icon-button")
        self.pack_start(self.label, True, True, 0)
        self.pack_start(close_btn, False, False, 0)
        self.show_all()

    def set_text(self, text):
        self.label.set_text(text)


class TerminalWindow(Gtk.ApplicationWindow):
    def __init__(self, app, command=None, cwd=None):
        super().__init__(application=app, title="The Void")
        self.set_default_size(920, 560)
        add_class(self, "app-window")
        self.default_cwd = cwd

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        add_class(self.notebook, "terminal-tabs")
        self.add(self.notebook)

        self.connect("key-press-event", self._on_key_press)
        self.new_tab(command=command, cwd=cwd)

    # -- tab management -------------------------------------------------
    def new_tab(self, command=None, cwd=None):
        page = TerminalPage(self, command=command, cwd=cwd or self.default_cwd)
        label = TabLabel(DEFAULT_TITLE, lambda *_: self.close_page(page))
        page._tab_label = label
        idx = self.notebook.append_page(page, label)
        self.notebook.set_tab_reorderable(page, True)
        page.show_all()
        self.notebook.set_current_page(idx)
        page.vte.grab_focus()
        return page

    def close_page(self, page):
        idx = self.notebook.page_num(page)
        if idx == -1:
            return
        self.notebook.remove_page(idx)
        if self.notebook.get_n_pages() == 0:
            self.destroy()

    def rename_page(self, page, title):
        if hasattr(page, "_tab_label"):
            page._tab_label.set_text(title)

    def current_page(self):
        idx = self.notebook.get_current_page()
        return self.notebook.get_nth_page(idx) if idx != -1 else None

    # -- keybinds ---------------------------------------------------------
    def _on_key_press(self, _widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        kv = event.keyval
        page = self.current_page()

        if ctrl and shift and kv in (Gdk.KEY_T, Gdk.KEY_t):
            self.new_tab()
            return True
        if ctrl and shift and kv in (Gdk.KEY_W, Gdk.KEY_w) and page:
            self.close_page(page)
            return True
        if ctrl and shift and kv in (Gdk.KEY_C, Gdk.KEY_c) and page:
            page.vte.copy_clipboard()
            return True
        if ctrl and shift and kv in (Gdk.KEY_V, Gdk.KEY_v) and page:
            page.vte.paste_clipboard()
            return True
        if ctrl and kv in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add) and page:
            page.zoom(1)
            return True
        if ctrl and kv in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract) and page:
            page.zoom(-1)
            return True
        if ctrl and kv in (Gdk.KEY_0, Gdk.KEY_KP_0) and page:
            page.zoom(reset=True)
            return True
        if ctrl and kv == Gdk.KEY_Page_Down:
            self.notebook.next_page()
            return True
        if ctrl and kv == Gdk.KEY_Page_Up:
            self.notebook.prev_page()
            return True
        return False


def parse_args(argv):
    """--cwd DIR is our own addition (used by darkos-files.py's "Open Terminal
    Here"). -e CMD [ARGS] mirrors the-void.sh's old contract so existing
    callers (darkos-tool-groups, etc.) keep working unchanged."""
    args = argv[1:]
    cwd = None
    if args[:1] == ["--cwd"] and len(args) >= 2:
        cwd = args[1]
        args = args[2:]
    if args[:1] == ["-e"]:
        args = args[1:]
    return cwd, (args or None)


def main():
    GLib.set_prgname(WM_CLASS)
    cwd, command = parse_args(sys.argv)
    app = Gtk.Application(application_id=APP_ID)

    def on_activate(_app):
        apply_css()
        win = TerminalWindow(_app, command=command, cwd=cwd)
        win.show_all()

    app.connect("activate", on_activate)
    # Pass only argv[0] through to GApplication — our own -e/CMD syntax
    # isn't a GTK option and would otherwise trip GLib's option parser.
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
