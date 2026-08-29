#!/usr/bin/env python3
"""DarkOS Reader — PDF viewer built on Poppler (page rendering only; no
attempt to re-implement PDF parsing). Page navigation, zoom, and an Open
dialog. Scope is PDF only for v1 — EPUB/CBZ would each need their own
rendering pipeline and are real follow-ups, not silently missing features.
"""
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Poppler", "0.18")
from gi.repository import Gdk, Gio, GLib, Gtk, Poppler  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, make_icon_button, run_app  # noqa: E402

APP_ID = "org.darkos.Reader"
WM_CLASS = "darkos-reader"
ZOOM_STEP = 1.15
ZOOM_MIN, ZOOM_MAX = 0.25, 5.0


class ReaderWindow(Gtk.ApplicationWindow):
    def __init__(self, app, path=None):
        super().__init__(application=app, title="Reader")
        self.set_default_size(760, 760)
        add_class(self, "app-window")

        self.document = None
        self.page_index = 0
        self.zoom = 1.0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        toolbar.pack_start(make_icon_button("document-open-symbolic", "Open PDF", self._open_dialog), False, False, 0)
        toolbar.pack_start(make_icon_button("go-previous-symbolic", "Previous page", self._prev_page), False, False, 0)
        self.page_label = Gtk.Label(label="No document")
        toolbar.pack_start(self.page_label, True, True, 8)
        toolbar.pack_start(make_icon_button("go-next-symbolic", "Next page", self._next_page), False, False, 0)
        toolbar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        toolbar.pack_start(make_icon_button("zoom-out-symbolic", "Zoom out", self._zoom_out), False, False, 0)
        toolbar.pack_start(make_icon_button("zoom-in-symbolic", "Zoom in", self._zoom_in), False, False, 0)
        root.pack_start(toolbar, False, False, 0)

        self.scroller = Gtk.ScrolledWindow()
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.connect("draw", self._on_draw)
        viewport = Gtk.Viewport()
        viewport.add(self.drawing_area)
        self.scroller.add(viewport)
        root.pack_start(self.scroller, True, True, 0)

        self.status_label = Gtk.Label(label="", xalign=0)
        add_class(self.status_label, "statusbar")
        root.pack_start(self.status_label, False, False, 0)

        self.connect("key-press-event", self._on_key_press)
        if path:
            self._load(path)

    def _load(self, path):
        try:
            uri = Gio.File.new_for_path(os.path.abspath(path)).get_uri()
            self.document = Poppler.Document.new_from_file(uri, None)
        except GLib.Error as e:
            self._show_error(f"Couldn't open {os.path.basename(path)}: {e.message}")
            return
        self.page_index = 0
        self.set_title(f"Reader — {os.path.basename(path)}")
        self.status_label.set_text(f"{self.document.get_n_pages()} pages")
        self._render_current()

    def _open_dialog(self, *_):
        chooser = Gtk.FileChooserDialog(title="Open PDF", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        pdf_filter = Gtk.FileFilter()
        pdf_filter.set_name("PDF documents")
        pdf_filter.add_pattern("*.pdf")
        chooser.add_filter(pdf_filter)
        if chooser.run() == Gtk.ResponseType.OK:
            self._load(chooser.get_filename())
        chooser.destroy()

    def _render_current(self):
        if not self.document:
            return
        page = self.document.get_page(self.page_index)
        w, h = page.get_size()
        self.drawing_area.set_size_request(int(w * self.zoom), int(h * self.zoom))
        self.page_label.set_text(f"Page {self.page_index + 1} of {self.document.get_n_pages()}")
        self.drawing_area.queue_draw()

    def _on_draw(self, _widget, cr):
        if not self.document:
            return False
        page = self.document.get_page(self.page_index)
        w, h = page.get_size()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, w * self.zoom, h * self.zoom)
        cr.fill()
        cr.save()
        cr.scale(self.zoom, self.zoom)
        page.render(cr)
        cr.restore()
        return False

    def _prev_page(self, *_):
        if self.document and self.page_index > 0:
            self.page_index -= 1
            self._render_current()

    def _next_page(self, *_):
        if self.document and self.page_index < self.document.get_n_pages() - 1:
            self.page_index += 1
            self._render_current()

    def _zoom_in(self, *_):
        self._set_zoom(self.zoom * ZOOM_STEP)

    def _zoom_out(self, *_):
        self._set_zoom(self.zoom / ZOOM_STEP)

    def _set_zoom(self, value):
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, value))
        self._render_current()

    def _on_key_press(self, _widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if event.keyval in (Gdk.KEY_Page_Down, Gdk.KEY_space):
            self._next_page()
            return True
        if event.keyval == Gdk.KEY_Page_Up:
            self._prev_page()
            return True
        if ctrl and event.keyval in (Gdk.KEY_plus, Gdk.KEY_equal):
            self._zoom_in()
            return True
        if ctrl and event.keyval == Gdk.KEY_minus:
            self._zoom_out()
            return True
        return False

    def _show_error(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dialog.run()
        dialog.destroy()


def build_window(app):
    start_path = sys.argv[1] if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]) else None
    return ReaderWindow(app, path=start_path)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
