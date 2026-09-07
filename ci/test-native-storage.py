#!/usr/bin/env python3
"""Temporary-directory-only archive, backup, and calendar regressions."""
import ast
from datetime import date
import io
import json
import ntpath
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

try:
    from gi.repository import Gio, GLib
except ImportError:
    Gio = GLib = None

BIN = Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin"


def helpers(name):
    namespace = dict(globals())
    tree = ast.parse((BIN / f"darkos-{name}.py").read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    exec(compile(tree, f"darkos-{name}.py", "exec"), namespace)
    return namespace


backup, calendar, files = helpers("backup"), helpers("calendar"), helpers("files")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="darkos-storage-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        calendar["data_path"] = lambda: str(self.root / "calendar.json")
        backup["manifest_path"] = lambda: str(self.root / "manifest.json")

    def test_same_second_backups_are_unique_and_restore_without_overwriting(self):
        source = self.root / "source"
        source.mkdir()
        (source / "empty").mkdir()
        (source / "file.txt").write_text("original")
        destination = source / "backups"
        with patch.object(time, "strftime", return_value="20260906-000000"):
            first = backup["create_backup"](source, destination)
            second = backup["create_backup"](source, destination)
        self.assertNotEqual(first["archive"], second["archive"])
        self.assertEqual(first["file_count"], 1)
        with tarfile.open(first["archive"]) as archive:
            self.assertIn("source/empty", archive.getnames())
            self.assertFalse(any("backups" in item for item in archive.getnames()))
        (source / "file.txt").write_text("existing content")
        restored = Path(backup["restore_backup"](first["archive"], self.root))
        self.assertEqual((restored / "source/file.txt").read_text(), "original")
        self.assertEqual((source / "file.txt").read_text(), "existing content")

    def test_failed_backup_is_not_published_as_success(self):
        source, destination = self.root / "source", self.root / "backups"
        source.mkdir()
        with patch.object(tarfile.TarFile, "add", side_effect=PermissionError("unreadable file")):
            with self.assertRaises(PermissionError):
                backup["create_backup"](source, destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_malicious_tar_restore_is_cleaned_up(self):
        archive = self.root / "hostile.tar.gz"
        with tarfile.open(archive, "w:gz") as target:
            member = tarfile.TarInfo("../escape.txt")
            member.size = 1
            target.addfile(member, io.BytesIO(b"x"))
        with self.assertRaises(tarfile.TarError):
            backup["restore_backup"](archive, self.root)
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertFalse(list(self.root.glob("darkos-restored-*")))

    def test_calendar_and_manifest_failed_writes_preserve_previous_data(self):
        for namespace, save, load, value in (
            (calendar, "save_events", "load_events", {"2026-09-06": ["Meeting"]}),
            (backup, "save_manifest", "load_manifest", []),
        ):
            namespace[save](value)
            with patch.object(os, "replace", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    namespace[save](value)
            self.assertEqual(namespace[load](), value)
        self.assertFalse(list(self.root.glob(".calendar-*")))
        self.assertFalse(list(self.root.glob(".manifest-*")))

    def test_corrupt_saved_data_is_not_silently_reset(self):
        for filename, function in (("calendar.json", calendar["load_events"]), ("manifest.json", backup["load_manifest"])):
            path = self.root / filename
            path.write_text("{broken data")
            with self.assertRaises(ValueError):
                function()
            self.assertEqual(path.read_text(), "{broken data")

    def test_zip_extraction_refuses_existing_destination(self):
        archive = self.root / "sample.zip"
        with zipfile.ZipFile(archive, "w") as target:
            target.writestr("file.txt", "archive content")
        destination = self.root / "extracted"
        files["extract_archive"](str(archive), str(destination))
        self.assertEqual((destination / "file.txt").read_text(), "archive content")
        with self.assertRaises(FileExistsError):
            files["extract_archive"](str(archive), str(destination))

    def test_archive_and_child_path_traversal_is_rejected(self):
        for name in ("../escape", "/absolute", "C:\\windows", "dir/../../escape"):
            with self.assertRaises(ValueError):
                files["validate_archive_name"](name)
        for name in ("..", "../escape", "a/b", "a\\b"):
            with self.assertRaises(ValueError):
                files["child_path"](str(self.root), name)

    def test_zip_failure_leaves_no_partial_extraction(self):
        archive = self.root / "hostile.zip"
        with zipfile.ZipFile(archive, "w") as target:
            target.writestr("../outside", "unsafe")
        with self.assertRaises(ValueError):
            files["extract_archive"](str(archive), str(self.root / "out"))
        self.assertFalse((self.root / "out").exists())
        self.assertFalse(list(self.root.glob(".darkos-extract-*")))

    @unittest.skipUnless(Gio is not None, "GIO requires the Linux test environment")
    def test_copy_and_move_never_overwrite_a_racing_destination(self):
        source, destination = self.root / "source.txt", self.root / "destination.txt"
        source.write_text("source")
        destination.write_text("preserve")
        for move in (False, True):
            with self.assertRaises(GLib.Error):
                files["paste_entry"](str(source), str(destination), move=move)
            self.assertEqual(destination.read_text(), "preserve")
            self.assertEqual(source.read_text(), "source")

    def test_paste_inside_source_is_rejected(self):
        source = self.root / "folder"
        source.mkdir()
        with self.assertRaises(ValueError):
            files["paste_entry"](str(source), str(source / "nested"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
