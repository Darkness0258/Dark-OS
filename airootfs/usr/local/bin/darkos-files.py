#!/usr/bin/env python3
"""DarkOS File Explorer — native GTK3 file manager with archive support.

Replaces the Phase 1 "ranger in a terminal" stopgap. Every control is a
stock GTK3 widget (TreeView, ListBox, buttons) so AT-SPI can drive it
generically, same reasoning as darkos-terminal.py — see architecture.md's
"AI control mechanism".

Archive scope (v1, deliberately not full in-archive navigation): double-
click a .zip/.tar* to preview its file list and extract it; select files
and hit Compress to zip them. Browsing *inside* an archive like a folder
is a real feature but a materially bigger one — flagged as a follow-up,
not silently half-built.
"""
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.css import apply_css  # noqa: E402

APP_ID = "org.darkos.Files"
WM_CLASS = "darkos-files"

ARCHIVE_EXTS = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
COL_ICON, COL_NAME, COL_SIZE, COL_MTIME, COL_PATH, COL_IS_DIR, COL_SIZE_B, COL_MTIME_TS, COL_IS_ARCHIVE = range(9)


def add_class(widget, class_name):
    widget.get_style_context().add_class(class_name)
    return widget


def make_icon_button(icon_name, tooltip, callback):
    button = Gtk.Button()
    button.add(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR))
    button.set_tooltip_text(tooltip)
    button.get_accessible().set_name(tooltip)
    add_class(button, "icon-button")
    button.connect("clicked", callback)
    return button


def human_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def format_time(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def is_archive(name):
    lower = name.lower()
    return any(lower.endswith(ext) for ext in ARCHIVE_EXTS)


def archive_basename(path):
    name = os.path.basename(path)
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return os.path.splitext(name)[0]


def list_archive(path):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            return z.namelist()
    with tarfile.open(path) as t:
        return t.getnames()


def extract_archive(path, dest):
    os.makedirs(dest, exist_ok=True)
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            z.extractall(dest)
    else:
        with tarfile.open(path) as t:
            # filter="data" (PEP 706): refuse absolute paths / ../ escapes
            # and device files when extracting an archive of unknown origin.
            t.extractall(dest, filter="data")


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


class FileExplorerWindow(Gtk.ApplicationWindow):
    def __init__(self, app, start_path=None):
        super().__init__(application=app, title="Files")
        self.set_default_size(1000, 620)
        add_class(self, "app-window")

        self.show_hidden = False
        self.clipboard_paths = []
        self.clipboard_mode = None
        self.history = []
        self.history_index = -1

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        root.pack_start(self._build_toolbar(), False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.pack_start(self._build_sidebar(), False, False, 0)
        body.pack_start(self._build_list(), True, True, 0)
        root.pack_start(body, True, True, 0)

        self.status_label = Gtk.Label(label="", xalign=0)
        add_class(self.status_label, "statusbar")
        root.pack_start(self.status_label, False, False, 0)

        self.connect("key-press-event", self._on_key_press)
        self.go_to(start_path or GLib.get_home_dir())

    # -- toolbar / path bar ----------------------------------------------
    def _build_toolbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        add_class(bar, "toolbar")

        self.back_btn = make_icon_button("go-previous-symbolic", "Back", self.go_back)
        self.forward_btn = make_icon_button("go-next-symbolic", "Forward", self.go_forward)
        up_btn = make_icon_button("go-up-symbolic", "Up", self.go_up)
        refresh_btn = make_icon_button("view-refresh-symbolic", "Refresh", lambda *_: self.refresh())
        new_folder_btn = make_icon_button("folder-new-symbolic", "New Folder", self._new_folder)
        copy_btn = make_icon_button("edit-copy-symbolic", "Copy", self._copy_selected)
        cut_btn = make_icon_button("edit-cut-symbolic", "Cut", self._cut_selected)
        paste_btn = make_icon_button("edit-paste-symbolic", "Paste", self._paste)
        rename_btn = make_icon_button("edit-symbolic", "Rename", self._rename_selected)
        delete_btn = make_icon_button("user-trash-symbolic", "Move to Trash", self._delete_selected)
        compress_btn = make_icon_button("package-x-generic-symbolic", "Compress selection", self._compress_selected)
        terminal_btn = make_icon_button("utilities-terminal-symbolic", "Open Terminal Here", self._open_terminal_here)
        for b in (self.back_btn, self.forward_btn, up_btn, refresh_btn, new_folder_btn):
            bar.pack_start(b, False, False, 0)
        bar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        for b in (copy_btn, cut_btn, paste_btn, rename_btn, delete_btn, compress_btn, terminal_btn):
            bar.pack_start(b, False, False, 0)

        self.path_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.path_entry = Gtk.Entry()
        self.path_entry.connect("activate", self._on_path_entry_activate)
        self.path_entry.connect("key-press-event", self._on_path_entry_key)

        self.path_stack = Gtk.Stack()
        add_class(self.path_stack, "path-bar")
        self.path_stack.set_hexpand(True)
        self.path_stack.add_named(self.path_box, "crumbs")
        self.path_stack.add_named(self.path_entry, "entry")
        bar.pack_start(self.path_stack, True, True, 4)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Filter this folder…")
        self.search_entry.set_width_chars(16)
        self.search_entry.connect("search-changed", lambda *_: self.filter_model.refilter())
        bar.pack_start(self.search_entry, False, False, 0)

        hidden_btn = Gtk.ToggleButton()
        hidden_btn.add(Gtk.Image.new_from_icon_name("view-reveal-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
        hidden_btn.set_tooltip_text("Show hidden files (Ctrl+H)")
        add_class(hidden_btn, "toggle-button")
        hidden_btn.connect("toggled", self._on_hidden_toggled)
        self.hidden_btn = hidden_btn
        bar.pack_start(hidden_btn, False, False, 0)
        return bar

    def _build_sidebar(self):
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(listbox, "sidebar")

        def add_row(label, path, icon):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            box.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            add_class(box, "sidebar-row")
            row.add(box)
            row.target_path = path
            listbox.add(row)

        add_row("Home", GLib.get_home_dir(), "user-home-symbolic")
        for label, dir_id in [
            ("Desktop", GLib.UserDirectory.DIRECTORY_DESKTOP),
            ("Documents", GLib.UserDirectory.DIRECTORY_DOCUMENTS),
            ("Downloads", GLib.UserDirectory.DIRECTORY_DOWNLOAD),
            ("Pictures", GLib.UserDirectory.DIRECTORY_PICTURES),
            ("Music", GLib.UserDirectory.DIRECTORY_MUSIC),
            ("Videos", GLib.UserDirectory.DIRECTORY_VIDEOS),
        ]:
            path = GLib.get_user_special_dir(dir_id)
            if path:
                add_row(label, path, f"folder-{label.lower()}-symbolic")

        sep_row = Gtk.ListBoxRow(selectable=False, activatable=False)
        sep_row.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        listbox.add(sep_row)
        add_row("Trash", os.path.join(GLib.get_user_data_dir(), "Trash", "files"), "user-trash-symbolic")
        add_row("Filesystem", "/", "drive-harddisk-symbolic")

        listbox.connect("row-activated", self._on_sidebar_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_size_request(190, -1)
        scroller.add(listbox)
        return scroller

    def _build_list(self):
        self.store = Gtk.ListStore(str, str, str, str, str, bool, int, float, bool)
        self.filter_model = self.store.filter_new()
        self.filter_model.set_visible_func(self._row_visible)
        self.sort_model = Gtk.TreeModelSort.new_with_model(self.filter_model)
        self._install_sort_funcs()

        self.treeview = Gtk.TreeView(model=self.sort_model)
        self.treeview.set_headers_visible(True)
        add_class(self.treeview, "darkos-list")
        self.selection = self.treeview.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)

        name_col = Gtk.TreeViewColumn("Name")
        name_col.set_expand(True)
        name_col.set_sort_column_id(COL_NAME)
        icon_r = Gtk.CellRendererPixbuf()
        name_col.pack_start(icon_r, False)
        name_col.add_attribute(icon_r, "icon-name", COL_ICON)
        text_r = Gtk.CellRendererText()
        text_r.set_property("ellipsize", Pango.EllipsizeMode.END)
        name_col.pack_start(text_r, True)
        name_col.add_attribute(text_r, "text", COL_NAME)
        self.treeview.append_column(name_col)

        size_col = Gtk.TreeViewColumn("Size", Gtk.CellRendererText(xalign=1.0), text=COL_SIZE)
        size_col.set_sort_column_id(COL_SIZE)
        size_col.set_fixed_width(90)
        self.treeview.append_column(size_col)

        mtime_col = Gtk.TreeViewColumn("Modified", Gtk.CellRendererText(), text=COL_MTIME)
        mtime_col.set_sort_column_id(COL_MTIME)
        mtime_col.set_fixed_width(150)
        self.treeview.append_column(mtime_col)

        self.treeview.connect("row-activated", self._on_row_activated)
        self.treeview.connect("key-press-event", self._on_list_key_press)
        self.treeview.connect("button-press-event", self._on_button_press)

        scroller = Gtk.ScrolledWindow()
        scroller.add(self.treeview)
        return scroller

    def _install_sort_funcs(self):
        def cmp(model, it_a, it_b, col):
            dir_a = model.get_value(it_a, COL_IS_DIR)
            dir_b = model.get_value(it_b, COL_IS_DIR)
            if dir_a != dir_b:
                return -1 if dir_a else 1
            a, b = model.get_value(it_a, col), model.get_value(it_b, col)
            return (a > b) - (a < b)

        self.sort_model.set_sort_func(COL_NAME, cmp, COL_NAME)
        self.sort_model.set_sort_func(COL_SIZE, cmp, COL_SIZE_B)
        self.sort_model.set_sort_func(COL_MTIME, cmp, COL_MTIME_TS)
        self.sort_model.set_sort_column_id(COL_NAME, Gtk.SortType.ASCENDING)

    def _row_visible(self, model, it, _data):
        query = self.search_entry.get_text().strip().lower()
        if not query:
            return True
        name = (model.get_value(it, COL_NAME) or "").lower()
        return query in name

    # -- navigation --------------------------------------------------------
    def go_to(self, path, push_history=True):
        path = os.path.normpath(path)
        if not os.path.isdir(path):
            self._show_error(f"Can't open {path} — it doesn't exist or isn't a folder.")
            return
        if push_history:
            self.history = self.history[: self.history_index + 1]
            self.history.append(path)
            self.history_index = len(self.history) - 1
        self.current_path = path
        self.refresh()
        self._update_path_bar()
        self.back_btn.set_sensitive(self.history_index > 0)
        self.forward_btn.set_sensitive(self.history_index < len(self.history) - 1)

    def go_back(self, *_):
        if self.history_index > 0:
            self.history_index -= 1
            self.current_path = self.history[self.history_index]
            self.refresh()
            self._update_path_bar()
            self.back_btn.set_sensitive(self.history_index > 0)
            self.forward_btn.set_sensitive(True)

    def go_forward(self, *_):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.current_path = self.history[self.history_index]
            self.refresh()
            self._update_path_bar()
            self.forward_btn.set_sensitive(self.history_index < len(self.history) - 1)
            self.back_btn.set_sensitive(True)

    def go_up(self, *_):
        parent = os.path.dirname(self.current_path.rstrip("/")) or "/"
        self.go_to(parent)

    def _update_path_bar(self):
        self.path_stack.set_visible_child_name("crumbs")
        for child in list(self.path_box.get_children()):
            self.path_box.remove(child)
        segments = [("/", "/")]
        if self.current_path != "/":
            accum = ""
            for part in self.current_path.strip("/").split("/"):
                accum += "/" + part
                segments.append((part, accum))
        for idx, (label, full) in enumerate(segments):
            btn = Gtk.Button(label=label)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            add_class(btn, "path-crumb")
            if idx == len(segments) - 1:
                add_class(btn, "path-crumb-current")
            btn.connect("clicked", lambda _b, p=full: self.go_to(p))
            self.path_box.pack_start(btn, False, False, 0)
        self.path_box.show_all()

    def _on_path_entry_activate(self, entry):
        target = entry.get_text().strip() or "/"
        self.go_to(os.path.expanduser(target))

    def _on_path_entry_key(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self.path_stack.set_visible_child_name("crumbs")
            return True
        return False

    # -- listing -------------------------------------------------------------
    def refresh(self):
        self.store.clear()
        try:
            entries = os.listdir(self.current_path)
        except OSError as e:
            self._show_error(f"Can't read {self.current_path}: {e.strerror}")
            return
        if not self.show_hidden:
            entries = [e for e in entries if not e.startswith(".")]
        shown = 0
        for name in entries:
            full = os.path.join(self.current_path, name)
            is_dir = os.path.isdir(full)
            try:
                st = os.stat(full) if is_dir else os.lstat(full)
            except OSError:
                continue
            size = 0 if is_dir else st.st_size
            archive = (not is_dir) and is_archive(name)
            icon = "folder" if is_dir else ("package-x-generic" if archive else self._icon_for(full))
            self.store.append([
                icon, name,
                "--" if is_dir else human_size(size),
                format_time(st.st_mtime),
                full, is_dir, size, st.st_mtime, archive,
            ])
            shown += 1
        self.status_label.set_text(f"{shown} item{'s' if shown != 1 else ''}")

    def _icon_for(self, path):
        try:
            ctype, _uncertain = Gio.content_type_guess(path, None)
            return Gio.content_type_get_generic_icon_name(ctype) or "text-x-generic"
        except GLib.Error:
            return "text-x-generic"

    def _on_hidden_toggled(self, btn):
        self.show_hidden = btn.get_active()
        self.refresh()

    def _on_sidebar_activated(self, _box, row):
        target = getattr(row, "target_path", None)
        if target and os.path.isdir(target):
            self.go_to(target)

    # -- selection / row actions ----------------------------------------------
    def _selected_paths(self):
        model, tree_paths = self.selection.get_selected_rows()
        return [model[p][COL_PATH] for p in tree_paths]

    def _on_row_activated(self, _view, tree_path, _col):
        model = self.treeview.get_model()
        it = model.get_iter(tree_path)
        full, is_dir, archive = (
            model.get_value(it, COL_PATH),
            model.get_value(it, COL_IS_DIR),
            model.get_value(it, COL_IS_ARCHIVE),
        )
        if is_dir:
            self.go_to(full)
        elif archive:
            self._show_archive_contents(full)
        else:
            self._open_with_default(full)

    def _open_with_default(self, path):
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        except GLib.Error as e:
            self._show_error(f"Couldn't open {os.path.basename(path)}: {e.message}")

    def _on_button_press(self, _widget, event):
        if event.button == 3:
            path_info = self.treeview.get_path_at_pos(int(event.x), int(event.y))
            if path_info and not self.selection.path_is_selected(path_info[0]):
                self.selection.unselect_all()
                self.selection.select_path(path_info[0])
            self._show_context_menu(event)
            return True
        return False

    def _show_context_menu(self, event):
        menu = Gtk.Menu()
        paths = self._selected_paths()

        def item(label, callback, sensitive=True):
            mi = Gtk.MenuItem(label=label)
            mi.set_sensitive(sensitive)
            mi.connect("activate", callback)
            menu.append(mi)

        item("Open", lambda *_: self._on_row_activated(self.treeview, self.selection.get_selected_rows()[1][0], None), bool(paths))
        item("Rename", self._rename_selected, len(paths) == 1)
        item("Copy", self._copy_selected, bool(paths))
        item("Cut", self._cut_selected, bool(paths))
        item("Paste", self._paste, bool(self.clipboard_paths))
        item("Compress", self._compress_selected, bool(paths))
        item("Move to Trash", self._delete_selected, bool(paths))
        if len(paths) == 1 and is_archive(os.path.basename(paths[0])):
            item("Extract Here", lambda *_: self._extract_here(paths[0]))
        menu.append(Gtk.SeparatorMenuItem())
        item("Open Terminal Here", self._open_terminal_here)
        menu.append(Gtk.SeparatorMenuItem())
        item("New Folder", self._new_folder)
        menu.show_all()
        menu.popup_at_pointer(event)

    def _on_list_key_press(self, _widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        kv = event.keyval
        if kv == Gdk.KEY_Delete:
            self._delete_selected()
            return True
        if kv == Gdk.KEY_F2:
            self._rename_selected()
            return True
        if kv == Gdk.KEY_F5:
            self.refresh()
            return True
        if kv == Gdk.KEY_BackSpace:
            self.go_up()
            return True
        if ctrl and kv in (Gdk.KEY_c, Gdk.KEY_C):
            self._copy_selected()
            return True
        if ctrl and kv in (Gdk.KEY_x, Gdk.KEY_X):
            self._cut_selected()
            return True
        if ctrl and kv in (Gdk.KEY_v, Gdk.KEY_V):
            self._paste()
            return True
        return False

    def _on_key_press(self, _widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        kv = event.keyval
        if ctrl and kv in (Gdk.KEY_h, Gdk.KEY_H):
            self.hidden_btn.set_active(not self.hidden_btn.get_active())
            return True
        if ctrl and kv in (Gdk.KEY_l, Gdk.KEY_L):
            self.path_entry.set_text(self.current_path)
            self.path_stack.set_visible_child_name("entry")
            self.path_entry.grab_focus()
            return True
        return False

    # -- file operations -------------------------------------------------------
    def _new_folder(self, *_):
        name = self._prompt("New Folder", "Create", "New Folder")
        if name:
            try:
                os.mkdir(os.path.join(self.current_path, name))
                self.refresh()
            except OSError as e:
                self._show_error(str(e))

    def _rename_selected(self, *_):
        paths = self._selected_paths()
        if len(paths) != 1:
            return
        old = paths[0]
        new_name = self._prompt("Rename", "Rename", os.path.basename(old))
        if new_name and new_name != os.path.basename(old):
            try:
                os.rename(old, os.path.join(os.path.dirname(old), new_name))
                self.refresh()
            except OSError as e:
                self._show_error(str(e))

    def _prompt(self, title, action_label, default_text):
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, action_label, Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=default_text)
        entry.set_activates_default(True)
        entry.select_region(0, -1)
        box = dialog.get_content_area()
        box.set_border_width(12)
        box.pack_start(entry, True, True, 0)
        dialog.show_all()
        result = None
        if dialog.run() == Gtk.ResponseType.OK:
            text = entry.get_text().strip()
            result = text or None
        dialog.destroy()
        return result

    def _copy_selected(self, *_):
        paths = self._selected_paths()
        if paths:
            self.clipboard_paths, self.clipboard_mode = paths, "copy"

    def _cut_selected(self, *_):
        paths = self._selected_paths()
        if paths:
            self.clipboard_paths, self.clipboard_mode = paths, "cut"

    def _paste(self, *_):
        if not self.clipboard_paths:
            return
        errors = []
        for src in self.clipboard_paths:
            if not os.path.exists(src):
                continue
            dest = unique_path(os.path.join(self.current_path, os.path.basename(src)))
            try:
                if self.clipboard_mode == "cut":
                    shutil.move(src, dest)
                elif os.path.isdir(src):
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
            except OSError as e:
                errors.append(f"{os.path.basename(src)}: {e}")
        if self.clipboard_mode == "cut":
            self.clipboard_paths = []
        self.refresh()
        if errors:
            self._show_error("Some items couldn't be pasted:\n" + "\n".join(errors))

    def _delete_selected(self, *_):
        paths = self._selected_paths()
        if not paths:
            return
        msg = (
            f'Move "{os.path.basename(paths[0])}" to Trash?'
            if len(paths) == 1
            else f"Move {len(paths)} items to Trash?"
        )
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text=msg,
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Move to Trash", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        errors = []
        for p in paths:
            try:
                Gio.File.new_for_path(p).trash()
            except GLib.Error as e:
                errors.append(f"{os.path.basename(p)}: {e.message}")
        self.refresh()
        if errors:
            self._show_error(
                "Some items couldn't be trashed (some filesystems don't support "
                "Trash — try Shift+Delete style permanent removal manually):\n"
                + "\n".join(errors)
            )

    def _compress_selected(self, *_):
        paths = self._selected_paths()
        if not paths:
            return
        default_name = (os.path.basename(paths[0]) if len(paths) == 1 else "Archive") + ".zip"
        dest = unique_path(os.path.join(self.current_path, default_name))
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for p in paths:
                    if os.path.isdir(p):
                        base = os.path.dirname(p)
                        for root, _dirs, files in os.walk(p):
                            for f in files:
                                full = os.path.join(root, f)
                                z.write(full, os.path.relpath(full, base))
                    else:
                        z.write(p, os.path.basename(p))
            self.refresh()
        except OSError as e:
            self._show_error(f"Couldn't create archive: {e}")

    def _open_terminal_here(self, *_):
        subprocess.Popen(["/usr/local/bin/darkos-terminal.py", "--cwd", self.current_path])

    # -- archives --------------------------------------------------------------
    def _extract_here(self, archive_path):
        dest = os.path.join(os.path.dirname(archive_path), archive_basename(archive_path))
        try:
            extract_archive(archive_path, dest)
            self.refresh()
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as e:
            self._show_error(f"Couldn't extract: {e}")

    def _show_archive_contents(self, archive_path):
        dialog = Gtk.Dialog(title=os.path.basename(archive_path), transient_for=self, modal=True)
        dialog.set_default_size(480, 420)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.add_button("Extract To…", Gtk.ResponseType.OK)
        dialog.add_button("Extract Here", Gtk.ResponseType.APPLY)

        scroller = Gtk.ScrolledWindow()
        scroller.set_size_request(-1, 320)
        listing = Gtk.TextView()
        listing.set_editable(False)
        listing.set_monospace(True)
        buf = listing.get_buffer()
        try:
            names = list_archive(archive_path)
            buf.set_text("\n".join(names) if names else "(empty archive)")
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as e:
            buf.set_text(f"Couldn't read archive:\n{e}")
        scroller.add(listing)
        box = dialog.get_content_area()
        box.set_border_width(8)
        box.pack_start(scroller, True, True, 0)
        dialog.show_all()

        response = dialog.run()
        if response == Gtk.ResponseType.APPLY:
            self._extract_here(archive_path)
        elif response == Gtk.ResponseType.OK:
            chooser = Gtk.FileChooserDialog(
                title="Extract to…", transient_for=self,
                action=Gtk.FileChooserAction.SELECT_FOLDER,
            )
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
            chooser.set_current_folder(self.current_path)
            if chooser.run() == Gtk.ResponseType.OK:
                try:
                    extract_archive(archive_path, chooser.get_filename())
                    self.refresh()
                except (OSError, tarfile.TarError, zipfile.BadZipFile) as e:
                    self._show_error(f"Couldn't extract: {e}")
            chooser.destroy()
        dialog.destroy()

    # -- misc --------------------------------------------------------------
    def _show_error(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dialog.run()
        dialog.destroy()


def main():
    GLib.set_prgname(WM_CLASS)
    start_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = Gtk.Application(application_id=APP_ID)

    def on_activate(_app):
        apply_css()
        win = FileExplorerWindow(_app, start_path=start_path)
        win.show_all()

    app.connect("activate", on_activate)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
