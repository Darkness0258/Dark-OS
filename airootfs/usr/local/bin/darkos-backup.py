#!/usr/bin/env python3
"""DarkOS Backup / Recovery — back up a folder to a .tar.gz, restore it later.

Plain file-based backup (Python's tarfile), not a Btrfs-snapshot tool —
this sandbox's filesystem is ext2/ext3, not Btrfs, so a snapshot-based
approach couldn't be verified here even if built, and build-plan.md's spec
for this item doesn't specify one over the other. A manifest at
~/.local/share/darkos/backups/manifest.json tracks what was backed up,
when, from where, and how big it was.
"""
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.Backup"
WM_CLASS = "darkos-backup"


def human_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def manifest_path():
    d = os.path.join(GLib.get_user_data_dir(), "darkos", "backups")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "manifest.json")


def load_manifest():
    try:
        with open(manifest_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not all(isinstance(entry, dict)
                and all(isinstance(entry.get(key), str) for key in ("archive", "source", "timestamp"))
                and all(type(entry.get(key)) is int and entry[key] >= 0
                        for key in ("size", "file_count")) for entry in data):
            raise ValueError("Backup history has an invalid format; it was left unchanged.")
        return data
    except FileNotFoundError:
        return []


def save_manifest(entries):
    path = manifest_path()
    descriptor, staged = tempfile.mkstemp(prefix=".manifest-", dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def create_backup(source, destination):
    """Create a unique complete archive, excluding a nested backup destination."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir() or source == destination:
        raise ValueError("Choose an existing source folder and a different backup destination.")
    destination.mkdir(parents=True, exist_ok=True)
    name = source.name or "root"
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    excluded = None
    if destination.is_relative_to(source):
        excluded = (PurePosixPath(name) / destination.relative_to(source).as_posix()).as_posix()
    file_count = 0

    def include(member):
        nonlocal file_count
        if excluded and (member.name == excluded or member.name.startswith(excluded + "/")):
            return None
        if member.isfile():
            file_count += 1
        return member

    descriptor, archive = tempfile.mkstemp(prefix=f"{name}-{timestamp}-", suffix=".tar.gz", dir=destination)
    try:
        with os.fdopen(descriptor, "wb") as output:
            with tarfile.open(fileobj=output, mode="w:gz") as tar:
                # Recursive add preserves empty directories and symlinks. Any
                # unreadable member fails the backup instead of claiming success.
                tar.add(source, arcname=name, filter=include)
            output.flush()
            os.fsync(output.fileno())
        return {"archive": archive, "source": str(source), "timestamp": timestamp,
                "size": os.path.getsize(archive), "file_count": file_count}
    except BaseException:
        os.unlink(archive)
        raise


def restore_backup(archive, destination):
    """Restore into a fresh private folder, leaving existing files untouched."""
    restored = tempfile.mkdtemp(prefix="darkos-restored-", dir=destination)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                name = PurePosixPath(member.name.replace("\\", "/"))
                if name.is_absolute() or ".." in name.parts:
                    raise tarfile.ExtractError(f"Unsafe archive path: {member.name}")
            tar.extractall(restored, filter="data")
        return restored
    except BaseException:
        shutil.rmtree(restored)
        raise


class BackupWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Backup / Recovery")
        self.set_default_size(680, 540)
        add_class(self, "app-window")

        self.source_path = GLib.get_home_dir()
        self.dest_dir = os.path.join(GLib.get_user_data_dir(), "darkos", "backups")

        notebook = Gtk.Notebook()
        add_class(notebook, "terminal-tabs")
        notebook.append_page(self._build_backup_tab(), Gtk.Label(label="Back Up"))
        notebook.append_page(self._build_history_tab(), Gtk.Label(label="History / Restore"))
        self.add(notebook)

    # -- Back Up -----------------------------------------------------------------
    def _build_backup_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(20)
        box.pack_start(Gtk.Label(label="<b>Back Up a Folder</b>", xalign=0, use_markup=True), False, False, 0)

        self.source_label = Gtk.Label(label=self.source_path, xalign=0)
        source_btn = Gtk.Button(label="Choose Source Folder…")
        add_class(source_btn, "icon-button")
        source_btn.connect("clicked", self._choose_source)
        box.pack_start(source_btn, False, False, 4)
        box.pack_start(self.source_label, False, False, 0)

        self.dest_label = Gtk.Label(label=self.dest_dir, xalign=0)
        dest_btn = Gtk.Button(label="Choose Destination…")
        add_class(dest_btn, "icon-button")
        dest_btn.connect("clicked", self._choose_dest)
        box.pack_start(dest_btn, False, False, 4)
        box.pack_start(self.dest_label, False, False, 0)

        backup_btn = Gtk.Button(label="Back Up Now")
        add_class(backup_btn, "action-button")
        backup_btn.set_halign(Gtk.Align.START)
        backup_btn.connect("clicked", self._run_backup)
        box.pack_start(backup_btn, False, False, 8)

        self.backup_status_label = Gtk.Label(label="", xalign=0, wrap=True)
        box.pack_start(self.backup_status_label, False, False, 0)
        return box

    def _choose_source(self, *_):
        chooser = Gtk.FileChooserDialog(title="Choose source folder", transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        chooser.set_current_folder(self.source_path)
        if chooser.run() == Gtk.ResponseType.OK:
            self.source_path = chooser.get_filename()
            self.source_label.set_text(self.source_path)
        chooser.destroy()

    def _choose_dest(self, *_):
        chooser = Gtk.FileChooserDialog(title="Choose destination folder", transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        chooser.set_current_folder(self.dest_dir)
        if chooser.run() == Gtk.ResponseType.OK:
            self.dest_dir = chooser.get_filename()
            self.dest_label.set_text(self.dest_dir)
        chooser.destroy()

    def _run_backup(self, *_):
        if not os.path.isdir(self.source_path):
            self.backup_status_label.set_text(f"Source folder doesn't exist: {self.source_path}")
            return
        try:
            os.makedirs(self.dest_dir, exist_ok=True)
        except OSError as e:
            self.backup_status_label.set_text(f"Can't use destination: {e}")
            return

        try:
            entry = create_backup(self.source_path, self.dest_dir)
        except (OSError, ValueError, tarfile.TarError) as e:
            self.backup_status_label.set_text(f"Backup failed: {e}")
            return
        try:
            manifest = load_manifest()
            manifest.insert(0, entry)
            save_manifest(manifest)
        except (OSError, ValueError) as e:
            self.backup_status_label.set_text(f"Archive saved to {entry['archive']}, but history could not be saved: {e}")
            return
        self.backup_status_label.set_text(
            f"Backed up {entry['file_count']} files ({human_size(entry['size'])}) to {entry['archive']}"
        )
        self._refresh_history()

    # -- History / Restore -----------------------------------------------------
    def _build_history_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        toolbar.pack_start(Gtk.Label(label="Backup History", xalign=0), True, True, 8)
        refresh_btn = Gtk.Button(label="Refresh")
        add_class(refresh_btn, "icon-button")
        refresh_btn.connect("clicked", lambda *_: self._refresh_history())
        toolbar.pack_start(refresh_btn, False, False, 0)
        box.pack_start(toolbar, False, False, 0)

        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_class(self.history_list, "sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.history_list)
        box.pack_start(scroller, True, True, 0)
        self._refresh_history()
        return box

    def _refresh_history(self):
        for child in list(self.history_list.get_children()):
            self.history_list.remove(child)
        try:
            manifest = load_manifest()
        except (OSError, ValueError) as error:
            self.history_list.add(Gtk.Label(label=f"Could not read backup history: {error}", xalign=0, wrap=True))
            self.history_list.show_all()
            return
        if not manifest:
            row = Gtk.ListBoxRow(selectable=False)
            row.add(Gtk.Label(label="No backups yet.", xalign=0))
            self.history_list.add(row)
        for idx, entry in enumerate(manifest):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            add_class(row, "sidebar-row")
            exists = os.path.exists(entry["archive"])
            label_text = f'{entry["source"]}  —  {entry["timestamp"]}  —  {human_size(entry["size"])}, {entry["file_count"]} files'
            if not exists:
                label_text += "  (archive missing)"
            row.pack_start(Gtk.Label(label=label_text, xalign=0), True, True, 0)
            restore_btn = Gtk.Button(label="Restore")
            add_class(restore_btn, "icon-button")
            restore_btn.set_sensitive(exists)
            restore_btn.connect("clicked", self._make_restorer(entry))
            row.pack_start(restore_btn, False, False, 0)
            del_btn = Gtk.Button(label="Delete")
            add_class(del_btn, "icon-button")
            del_btn.connect("clicked", self._make_history_deleter(entry["archive"]))
            row.pack_start(del_btn, False, False, 0)
            self.history_list.add(row)
        self.history_list.show_all()

    def _make_restorer(self, entry):
        def _restore(*_):
            chooser = Gtk.FileChooserDialog(title="Restore to…", transient_for=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
            chooser.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
            if chooser.run() == Gtk.ResponseType.OK:
                dest = chooser.get_filename()
                try:
                    restored = restore_backup(entry["archive"], dest)
                    self._show_message(f"Restored to {restored}")
                except (OSError, tarfile.TarError) as e:
                    self._show_message(f"Restore failed: {e}", error=True)
            chooser.destroy()
        return _restore

    def _show_message(self, message, error=False):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text=message,
        )
        dialog.run()
        dialog.destroy()

    def _make_history_deleter(self, archive):
        def _delete(*_):
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE, text="Delete this backup archive permanently?",
            )
            dialog.format_secondary_text(archive)
            dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete Backup", Gtk.ResponseType.OK)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return
            try:
                manifest = load_manifest()
            except (OSError, ValueError) as error:
                self._show_message(f"Could not read backup history: {error}", error=True)
                return
            if any(entry["archive"] == archive for entry in manifest):
                try:
                    if os.path.lexists(archive):
                        os.remove(archive)
                    save_manifest([entry for entry in manifest if entry["archive"] != archive])
                except OSError as e:
                    self._show_message(f"Could not delete backup or update history: {e}", error=True)
                self._refresh_history()
        return _delete


def build_window(app):
    return BackupWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
