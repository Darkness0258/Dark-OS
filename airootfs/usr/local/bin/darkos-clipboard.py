#!/usr/bin/env python3
"""DarkOS Clipboard Manager — recent clipboard text, click to re-copy.

Deliberate privacy choice: history is session-only (in memory), not written
to disk, because a clipboard can easily hold a password or token and a
silent persistent plaintext log of "everything ever copied" is a real
footgun on a security-focused OS. Pinning an entry explicitly saves *that*
text to ~/.local/share/darkos/clipboard-pinned.json — everything else
disappears when the app closes, matching what most people actually expect
from "clipboard history" until they ask to keep something.

Text only for v1 — image clipboard entries are a real follow-up, not
silently unsupported without saying so.
"""
import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, make_icon_button, run_app  # noqa: E402

APP_ID = "org.darkos.Clipboard"
WM_CLASS = "darkos-clipboard"
MAX_HISTORY = 50


def pinned_path():
    darkos_dir = os.path.join(GLib.get_user_data_dir(), "darkos")
    os.makedirs(darkos_dir, exist_ok=True)
    return os.path.join(darkos_dir, "clipboard-pinned.json")


def load_pinned():
    path = pinned_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_pinned(items):
    try:
        with open(pinned_path(), "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
    except OSError:
        pass


def preview(text, limit=80):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


class ClipboardWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Clipboard")
        self.set_default_size(420, 560)
        add_class(self, "app-window")

        self.history = []
        self.pinned = load_pinned()
        self.last_text = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        toolbar.pack_start(Gtk.Label(label="Clipboard", xalign=0), True, True, 8)
        toolbar.pack_start(make_icon_button("edit-clear-all-symbolic", "Clear history", self._clear_history), False, False, 0)
        root.pack_start(toolbar, False, False, 0)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(self.list_box, "sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.list_box)
        root.pack_start(scroller, True, True, 0)

        self.status_label = Gtk.Label(label="Watching clipboard…", xalign=0)
        add_class(self.status_label, "statusbar")
        root.pack_start(self.status_label, False, False, 0)

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.clipboard.connect("owner-change", self._on_owner_change)
        self._refresh_list()

    def _on_owner_change(self, clipboard, _event):
        clipboard.request_text(self._on_text_received)

    def _on_text_received(self, _clipboard, text):
        if not text or not text.strip() or text == self.last_text:
            return
        self.last_text = text
        self.history = [h for h in self.history if h != text]
        self.history.insert(0, text)
        self.history = self.history[:MAX_HISTORY]
        self._refresh_list()

    def _refresh_list(self):
        for child in list(self.list_box.get_children()):
            self.list_box.remove(child)

        if self.pinned:
            self._add_section_label("Pinned")
            for text in self.pinned:
                self._add_row(text, is_pinned=True)
        self._add_section_label("Recent" if self.pinned else None)
        for text in self.history:
            if text not in self.pinned:
                self._add_row(text, is_pinned=False)

        self.list_box.show_all()
        self.status_label.set_text(f"{len(self.pinned)} pinned, {len(self.history)} recent")

    def _add_section_label(self, text):
        if not text:
            return
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        label = Gtk.Label(label=text, xalign=0)
        label.set_margin_top(8)
        label.set_margin_start(8)
        label.get_style_context().add_class("path-crumb")
        row.add(label)
        self.list_box.add(row)

    def _add_row(self, text, is_pinned):
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_class(hbox, "sidebar-row")
        label = Gtk.Label(label=preview(text), xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        copy_evt = Gtk.EventBox()
        copy_evt.add(label)
        copy_evt.connect("button-press-event", lambda *_a, t=text: self._copy(t))
        hbox.pack_start(copy_evt, True, True, 4)
        pin_icon = "starred-symbolic" if is_pinned else "non-starred-symbolic"
        hbox.pack_start(make_icon_button(pin_icon, "Unpin" if is_pinned else "Pin", self._toggle_pin(text), Gtk.IconSize.MENU), False, False, 0)
        hbox.pack_start(make_icon_button("window-close-symbolic", "Remove", self._remove(text, is_pinned), Gtk.IconSize.MENU), False, False, 0)
        row.add(hbox)
        self.list_box.add(row)

    def _copy(self, text):
        self.clipboard.set_text(text, -1)
        self.status_label.set_text("Copied to clipboard")
        GLib.timeout_add(1500, self._restore_status)

    def _restore_status(self):
        self.status_label.set_text(f"{len(self.pinned)} pinned, {len(self.history)} recent")
        return False

    def _toggle_pin(self, text):
        def _toggle(*_):
            if text in self.pinned:
                self.pinned.remove(text)
            else:
                self.pinned.insert(0, text)
            save_pinned(self.pinned)
            self._refresh_list()
        return _toggle

    def _remove(self, text, is_pinned):
        def _do_remove(*_):
            if is_pinned and text in self.pinned:
                self.pinned.remove(text)
                save_pinned(self.pinned)
            elif text in self.history:
                self.history.remove(text)
            self._refresh_list()
        return _do_remove

    def _clear_history(self, *_):
        self.history = []
        self._refresh_list()


def build_window(app):
    return ClipboardWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
