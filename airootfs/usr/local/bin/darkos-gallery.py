#!/usr/bin/env python3
"""DarkOS Gallery — thumbnail grid + full-size viewer for a folder of images.

Thumbnails load synchronously via GdkPixbuf's own scale-during-decode
(new_from_file_at_scale), which is reasonably fast for a normal photo
folder. A folder with thousands of large images would want async/lazy
loading — a real follow-up, not attempted here.
"""
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, make_icon_button, run_app  # noqa: E402

APP_ID = "org.darkos.Gallery"
WM_CLASS = "darkos-gallery"
THUMB_SIZE = 160
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")


def is_image(name):
    return name.lower().endswith(IMAGE_EXTS)


class GalleryWindow(Gtk.ApplicationWindow):
    def __init__(self, app, folder=None):
        super().__init__(application=app, title="Gallery")
        self.set_default_size(880, 620)
        add_class(self, "app-window")

        self.folder = folder or GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) \
            or os.path.join(GLib.get_home_dir(), "Pictures")
        os.makedirs(self.folder, exist_ok=True)
        self.images = []
        self.current_index = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        self.back_btn = make_icon_button("go-previous-symbolic", "Back to grid", self._show_grid)
        self.back_btn.set_sensitive(False)
        toolbar.pack_start(self.back_btn, False, False, 0)
        self.path_label = Gtk.Label(label=self.folder, xalign=0)
        self.path_label.set_ellipsize(Pango.EllipsizeMode.END)
        toolbar.pack_start(self.path_label, True, True, 8)
        toolbar.pack_start(make_icon_button("folder-open-symbolic", "Choose folder", self._choose_folder), False, False, 0)
        toolbar.pack_start(make_icon_button("view-refresh-symbolic", "Refresh", lambda *_: self._reload()), False, False, 0)
        root.pack_start(toolbar, False, False, 0)

        self.stack = Gtk.Stack()
        add_class(self.stack, "app-window")

        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_border_width(8)
        self.flow.set_row_spacing(8)
        self.flow.set_column_spacing(8)
        grid_scroller = Gtk.ScrolledWindow()
        grid_scroller.add(self.flow)
        self.stack.add_named(grid_scroller, "grid")

        viewer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER, spacing=8)
        nav.pack_start(make_icon_button("go-previous-symbolic", "Previous", self._prev_image), False, False, 0)
        self.big_image = Gtk.Image()
        self.filename_label = Gtk.Label(label="")
        nav.pack_start(self.filename_label, False, False, 12)
        nav.pack_start(make_icon_button("go-next-symbolic", "Next", self._next_image), False, False, 0)
        viewer_scroller = Gtk.ScrolledWindow()
        viewer_scroller.set_hexpand(True)
        viewer_scroller.set_vexpand(True)
        viewer_scroller.add(self.big_image)
        viewer.pack_start(viewer_scroller, True, True, 0)
        viewer.pack_start(nav, False, False, 8)
        self.stack.add_named(viewer, "viewer")

        root.pack_start(self.stack, True, True, 0)
        self.status_label = Gtk.Label(label="", xalign=0)
        add_class(self.status_label, "statusbar")
        root.pack_start(self.status_label, False, False, 0)

        self._reload()

    def _reload(self):
        try:
            files = sorted(f for f in os.listdir(self.folder) if is_image(f))
        except OSError as e:
            self.status_label.set_text(f"Can't read {self.folder}: {e.strerror}")
            files = []
        self.images = [os.path.join(self.folder, f) for f in files]
        self.path_label.set_text(self.folder)
        self._populate_grid()
        self._show_grid()

    def _populate_grid(self):
        for child in list(self.flow.get_children()):
            self.flow.remove(child)
        for idx, path in enumerate(self.images):
            self.flow.add(self._make_thumb(idx, path))
        self.flow.show_all()
        self.status_label.set_text(f"{len(self.images)} image{'s' if len(self.images) != 1 else ''} in {os.path.basename(self.folder) or self.folder}")

    def _make_thumb(self, idx, path):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_size_request(THUMB_SIZE, THUMB_SIZE + 24)
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, THUMB_SIZE, THUMB_SIZE, True)
            image = Gtk.Image.new_from_pixbuf(pixbuf)
        except GLib.Error:
            image = Gtk.Image.new_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
        btn = Gtk.Button()
        btn.set_relief(Gtk.ReliefStyle.NONE)
        add_class(btn, "icon-button")
        btn.add(image)
        btn.connect("clicked", lambda *_: self._show_image(idx))
        box.pack_start(btn, True, True, 0)
        name_label = Gtk.Label(label=os.path.basename(path))
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.set_max_width_chars(18)
        box.pack_start(name_label, False, False, 0)
        return box

    def _show_grid(self, *_):
        self.stack.set_visible_child_name("grid")
        self.back_btn.set_sensitive(False)
        self.current_index = None

    def _show_image(self, idx):
        self.current_index = idx
        path = self.images[idx]
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
            max_dim = 900
            w, h = pixbuf.get_width(), pixbuf.get_height()
            if w > max_dim or h > max_dim:
                scale = max_dim / max(w, h)
                pixbuf = pixbuf.scale_simple(int(w * scale), int(h * scale), GdkPixbuf.InterpType.BILINEAR)
            self.big_image.set_from_pixbuf(pixbuf)
        except GLib.Error as e:
            self.big_image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
            self.status_label.set_text(f"Couldn't load {os.path.basename(path)}: {e.message}")
        self.filename_label.set_text(f"{os.path.basename(path)}  ({idx + 1}/{len(self.images)})")
        self.stack.set_visible_child_name("viewer")
        self.back_btn.set_sensitive(True)

    def _prev_image(self, *_):
        if self.current_index is not None and self.images:
            self._show_image((self.current_index - 1) % len(self.images))

    def _next_image(self, *_):
        if self.current_index is not None and self.images:
            self._show_image((self.current_index + 1) % len(self.images))

    def _choose_folder(self, *_):
        chooser = Gtk.FileChooserDialog(
            title="Choose a folder", transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        chooser.set_current_folder(self.folder)
        if chooser.run() == Gtk.ResponseType.OK:
            self.folder = chooser.get_filename()
            self._reload()
        chooser.destroy()


def build_window(app):
    start_folder = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
    return GalleryWindow(app, folder=start_folder)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
