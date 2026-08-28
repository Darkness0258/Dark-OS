#!/usr/bin/env python3
"""DarkOS Notes (+ Editor) — a notes list backed by plain .txt files, plus
general small-file text editing (pass a path as argv[1] to open it directly,
e.g. from File Explorer's default-app handoff for text/markdown files).

Notes live in ~/Documents/DarkOS Notes/ as ordinary .txt files — visible
and editable from darkos-files.py too, deliberately not a proprietary format.
Autosaves 600ms after typing stops; no explicit Save button needed for notes
opened from the sidebar. A file opened directly via argv[1] instead gets an
explicit Save/Save As, since it may not be inside the notes folder.
"""
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, make_icon_button, run_app  # noqa: E402

APP_ID = "org.darkos.Notes"
WM_CLASS = "darkos-notes"


def notes_dir():
    docs = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS) or \
        os.path.join(GLib.get_home_dir(), "Documents")
    path = os.path.join(docs, "DarkOS Notes")
    os.makedirs(path, exist_ok=True)
    return path


def unique_note_path(title):
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip() or "Untitled"
    path = os.path.join(notes_dir(), safe + ".txt")
    n = 2
    base = path
    while os.path.exists(path):
        path = base[:-4] + f" {n}.txt"
        n += 1
    return path


class NotesWindow(Gtk.ApplicationWindow):
    def __init__(self, app, open_path=None):
        super().__init__(application=app, title="Notes")
        self.set_default_size(880, 560)
        add_class(self, "app-window")

        self.current_path = None
        self.dirty = False
        self.save_timeout_id = None
        self.standalone_mode = bool(open_path)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(body)

        if not self.standalone_mode:
            side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            add_class(toolbar, "toolbar")
            toolbar.pack_start(Gtk.Label(label="Notes", xalign=0), True, True, 8)
            toolbar.pack_start(make_icon_button("document-new-symbolic", "New note", self._new_note), False, False, 0)
            toolbar.pack_start(make_icon_button("user-trash-symbolic", "Delete note", self._delete_note), False, False, 0)
            side.pack_start(toolbar, False, False, 0)

            self.note_list = Gtk.ListBox()
            add_class(self.note_list, "sidebar")
            self.note_list.connect("row-selected", self._on_note_selected)
            scroller = Gtk.ScrolledWindow()
            scroller.set_size_request(220, -1)
            scroller.add(self.note_list)
            side.pack_start(scroller, True, True, 0)
            body.pack_start(side, False, False, 0)
            body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        editor_box.set_hexpand(True)

        edit_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(edit_toolbar, "toolbar")
        self.title_label = Gtk.Label(label="No note selected", xalign=0)
        self.title_label.set_margin_start(8)
        edit_toolbar.pack_start(self.title_label, True, True, 0)
        if self.standalone_mode:
            edit_toolbar.pack_start(make_icon_button("document-save-symbolic", "Save", self._manual_save), False, False, 0)
        else:
            edit_toolbar.pack_start(make_icon_button("edit-symbolic", "Rename note", self._rename_note), False, False, 0)
        editor_box.pack_start(edit_toolbar, False, False, 0)

        self.textview = Gtk.TextView()
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD)
        self.textview.set_border_width(16)
        self.textview.set_sensitive(False)
        self.buffer = self.textview.get_buffer()
        self.buffer.connect("changed", self._on_text_changed)
        scroller2 = Gtk.ScrolledWindow()
        scroller2.add(self.textview)
        editor_box.pack_start(scroller2, True, True, 0)

        self.status_label = Gtk.Label(label="", xalign=0)
        add_class(self.status_label, "statusbar")
        editor_box.pack_start(self.status_label, False, False, 0)
        body.pack_start(editor_box, True, True, 0)

        if self.standalone_mode:
            self._load_file(open_path)
        else:
            self._reload_note_list()

    # -- notes sidebar -------------------------------------------------------
    def _reload_note_list(self, select_path=None):
        for child in list(self.note_list.get_children()):
            self.note_list.remove(child)
        try:
            files = sorted(f for f in os.listdir(notes_dir()) if f.lower().endswith(".txt"))
        except OSError:
            files = []
        first_row = None
        for fname in files:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=fname[:-4], xalign=0)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            label.set_margin_start(8)
            add_class(label, "sidebar-row")
            row.add(label)
            row.note_path = os.path.join(notes_dir(), fname)
            self.note_list.add(row)
            if select_path and row.note_path == select_path:
                first_row = row
            elif first_row is None and not select_path:
                first_row = row
        self.note_list.show_all()
        if first_row:
            self.note_list.select_row(first_row)
        else:
            self.textview.set_sensitive(False)
            self.title_label.set_text("No note selected")
            self.buffer.set_text("")

    def _on_note_selected(self, _box, row):
        if row is None:
            return
        self._load_file(row.note_path, is_note=True)

    def _new_note(self, *_):
        path = unique_note_path("Untitled Note")
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
        self._reload_note_list(select_path=path)

    def _rename_note(self, *_):
        if not self.current_path:
            return
        dialog = Gtk.Dialog(title="Rename Note", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Rename", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=os.path.basename(self.current_path)[:-4])
        entry.set_activates_default(True)
        entry.select_region(0, -1)
        box = dialog.get_content_area()
        box.set_border_width(12)
        box.pack_start(entry, True, True, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            new_name = entry.get_text().strip()
            if new_name:
                new_path = unique_note_path(new_name)
                os.rename(self.current_path, new_path)
                self._reload_note_list(select_path=new_path)
        dialog.destroy()

    def _delete_note(self, *_):
        if not self.current_path:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text=f'Delete "{os.path.basename(self.current_path)[:-4]}"?',
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            try:
                os.remove(self.current_path)
            except OSError:
                pass
            self.current_path = None
            self._reload_note_list()

    # -- editing ---------------------------------------------------------------
    def _load_file(self, path, is_note=False):
        self._flush_pending_save()
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            text = ""
            self.status_label.set_text(f"Couldn't read file: {e}")
        self.current_path = path
        self.buffer.handler_block_by_func(self._on_text_changed)
        self.buffer.set_text(text)
        self.buffer.handler_unblock_by_func(self._on_text_changed)
        self.textview.set_sensitive(True)
        title = os.path.basename(path)
        self.title_label.set_text(title[:-4] if is_note and title.lower().endswith(".txt") else title)
        self._update_status(text)
        self.dirty = False

    def _on_text_changed(self, buf):
        self.dirty = True
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self._update_status(text)
        if self.save_timeout_id:
            GLib.source_remove(self.save_timeout_id)
        self.save_timeout_id = GLib.timeout_add(600, self._autosave)

    def _update_status(self, text):
        words = len(text.split())
        chars = len(text)
        self.status_label.set_text(f"{words} words, {chars} characters" + ("  •  unsaved" if self.dirty else ""))

    def _autosave(self):
        self.save_timeout_id = None
        if not self.standalone_mode:
            self._write_current()
        return False

    def _manual_save(self, *_):
        self._write_current()

    def _flush_pending_save(self):
        if self.save_timeout_id:
            GLib.source_remove(self.save_timeout_id)
            self.save_timeout_id = None
            self._write_current()

    def _write_current(self):
        if not self.current_path:
            return
        text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False)
        try:
            with open(self.current_path, "w", encoding="utf-8") as f:
                f.write(text)
            self.dirty = False
            self._update_status(text)
        except OSError as e:
            self.status_label.set_text(f"Couldn't save: {e}")


def build_window_for(open_path):
    def build_window(app):
        return NotesWindow(app, open_path=open_path)
    return build_window


if __name__ == "__main__":
    arg_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_app(APP_ID, WM_CLASS, build_window_for(arg_path))
