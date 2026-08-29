#!/usr/bin/env python3
"""DarkOS Downloads Manager — a focused, newest-first view of ~/Downloads.

Honest scope: this is a specialized folder view with quick actions, not a
live download-progress tracker. Nothing in DarkOS currently exposes active
download events from the browser or other sources to hook into — building
a fake progress UI with no real data behind it would be worse than not
having one. When that integration exists, this is where it plugs in.
"""
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, make_icon_button, run_app  # noqa: E402

APP_ID = "org.darkos.Downloads"
WM_CLASS = "darkos-downloads"


def human_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


class DownloadsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Downloads")
        self.set_default_size(640, 560)
        add_class(self, "app-window")

        self.folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or \
            os.path.join(GLib.get_home_dir(), "Downloads")
        os.makedirs(self.folder, exist_ok=True)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        toolbar.pack_start(Gtk.Label(label="Downloads", xalign=0), True, True, 8)
        toolbar.pack_start(make_icon_button("folder-symbolic", "Open in Files", self._open_in_files), False, False, 0)
        toolbar.pack_start(make_icon_button("view-refresh-symbolic", "Refresh", lambda *_: self._reload()), False, False, 0)
        root.pack_start(toolbar, False, False, 0)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.connect("row-activated", self._on_row_activated)
        add_class(self.list_box, "sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.list_box)
        root.pack_start(scroller, True, True, 0)

        self.status_label = Gtk.Label(label="", xalign=0)
        add_class(self.status_label, "statusbar")
        root.pack_start(self.status_label, False, False, 0)

        self._reload()

    def _reload(self):
        for child in list(self.list_box.get_children()):
            self.list_box.remove(child)
        try:
            entries = []
            for name in os.listdir(self.folder):
                full = os.path.join(self.folder, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                entries.append((full, name, st.st_size, st.st_mtime, os.path.isdir(full)))
        except OSError as e:
            self.status_label.set_text(f"Can't read {self.folder}: {e.strerror}")
            return
        entries.sort(key=lambda e: e[3], reverse=True)
        for full, name, size, mtime, is_dir in entries:
            self.list_box.add(self._make_row(full, name, size, mtime, is_dir))
        self.list_box.show_all()
        self.status_label.set_text(f"{len(entries)} item{'s' if len(entries) != 1 else ''} in {self.folder}")

    def _make_row(self, full, name, size, mtime, is_dir):
        row = Gtk.ListBoxRow()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        add_class(hbox, "sidebar-row")
        hbox.set_margin_top(6)
        hbox.set_margin_bottom(6)

        icon_name = "folder" if is_dir else self._icon_for(full)
        hbox.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name_label = Gtk.Label(label=name, xalign=0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        detail = GLib.DateTime.new_from_unix_local(int(mtime)).format("%d %b %Y, %H:%M")
        if not is_dir:
            detail = f"{human_size(size)}  •  {detail}"
        detail_label = Gtk.Label(label=detail, xalign=0)
        add_class(detail_label, "path-crumb")
        info_box.pack_start(name_label, False, False, 0)
        info_box.pack_start(detail_label, False, False, 0)
        hbox.pack_start(info_box, True, True, 0)

        hbox.pack_start(make_icon_button("folder-symbolic", "Show in Files", self._show_in_files(full), Gtk.IconSize.MENU), False, False, 0)
        hbox.pack_start(make_icon_button("user-trash-symbolic", "Move to Trash", self._delete(full), Gtk.IconSize.MENU), False, False, 0)

        row.add(hbox)
        row.full_path = full
        return row

    def _icon_for(self, path):
        try:
            ctype, _u = Gio.content_type_guess(path, None)
            return Gio.content_type_get_generic_icon_name(ctype) or "text-x-generic"
        except GLib.Error:
            return "text-x-generic"

    def _on_row_activated(self, _list_box, row):
        if hasattr(row, "full_path"):
            self._open(row.full_path)

    def _open(self, path):
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        except GLib.Error as e:
            self.status_label.set_text(f"Couldn't open {os.path.basename(path)}: {e.message}")

    def _show_in_files(self, path):
        def _show(*_):
            subprocess.Popen(["/usr/local/bin/darkos-files.py", os.path.dirname(path)])
        return _show

    def _open_in_files(self, *_):
        subprocess.Popen(["/usr/local/bin/darkos-files.py", self.folder])

    def _delete(self, path):
        def _do_delete(*_):
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
                text=f'Move "{os.path.basename(path)}" to Trash?',
            )
            dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Move to Trash", Gtk.ResponseType.OK)
            response = dialog.run()
            dialog.destroy()
            if response == Gtk.ResponseType.OK:
                try:
                    Gio.File.new_for_path(path).trash()
                except GLib.Error as e:
                    self.status_label.set_text(f"Couldn't trash: {e.message}")
                self._reload()
        return _do_delete


def build_window(app):
    return DownloadsWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
