#!/usr/bin/env python3
"""Regressions for darkos-security.py's Quarantine tab -- the real
SecurityWindow class, real GTK widgets, real quarantine.py calls. Needs a
display (run under xvfb-run in CI, same as the rest of this project's GTK
tests); skips cleanly if GTK/Gtk-3.0 isn't available rather than failing
the whole suite for an unrelated reason."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False


@unittest.skipUnless(GTK_AVAILABLE, "GTK 3 not available in this environment")
class QuarantineTabTests(unittest.TestCase):
    def setUp(self) -> None:
        from darkos_shell import user_settings

        settings_home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, settings_home, ignore_errors=True)
        settings_file = Path(settings_home) / "settings.json"
        self.settings_patcher = patch.object(
            user_settings, "settings_path", return_value=str(settings_file)
        )
        self.settings_patcher.start()
        self.addCleanup(self.settings_patcher.stop)

        spec = importlib.util.spec_from_file_location(
            "darkos_security_test_target", BIN / "darkos-security.py"
        )
        assert spec is not None and spec.loader is not None
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

        from darkos_shell import quarantine

        self.quarantine = quarantine
        self.fake_dir = Path(tempfile.mkdtemp()) / "quarantine-store"
        self.patcher = patch.object(quarantine, "QUARANTINE_DIR", self.fake_dir)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        self.workdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)

        app = Gtk.Application(application_id="test.darkos.security.ci")
        app.register()
        self.win = self.mod.SecurityWindow(app)
        self.addCleanup(self.win.destroy)

    def _drop(self, name: str, reason: str):
        path = self.workdir / name
        path.write_bytes(b"x")
        return self.quarantine.quarantine_file(path, reason=reason)

    def test_empty_state_shows_placeholder_not_a_blank_list(self) -> None:
        self.win._refresh_quarantine_list()
        rows = self.win._quarantine_list.get_children()
        self.assertEqual(len(rows), 1)
        # Gtk.ListBox.add() auto-wraps a bare widget in a ListBoxRow -- the
        # actual placeholder Label is get_child() of that wrapper, not the
        # row itself. Found by running this, not assumed.
        self.assertIsInstance(rows[0].get_child(), Gtk.Label)

    def test_real_entries_render_as_real_rows(self) -> None:
        self._drop("a.exe", "Test.One")
        self._drop("b.exe", "Test.Two")
        self.win._refresh_quarantine_list()
        self.assertEqual(len(self.win._quarantine_list.get_children()), 2)

    def test_restore_button_handler_restores_and_refreshes(self) -> None:
        entry = self._drop("a.exe", "Test.One")
        self.win._refresh_quarantine_list()
        self.win._restore_entry(entry.id)
        self.assertTrue((self.workdir / "a.exe").exists())
        self.assertIn("Restored", self.win._quarantine_status.get_text())
        self.assertEqual(self.quarantine.list_quarantine(), [])

    def test_delete_button_handler_deletes_permanently_and_refreshes(self) -> None:
        entry = self._drop("a.exe", "Test.One")
        self.win._refresh_quarantine_list()
        self.win._delete_entry(entry.id)
        self.assertFalse(entry.blob_path().exists())
        self.assertIn("Deleted", self.win._quarantine_status.get_text())

    def test_row_metadata_is_ellipsized_not_left_to_overflow(self) -> None:
        # regression for a real bug this suite would have caught: an
        # unellipsized long path pushed the Restore/Delete buttons off
        # the visible row entirely, found by actually rendering it.
        entry = self._drop("a.exe", "Test.One")
        row = self.win._quarantine_row(entry)
        row.show_all()
        labels = [w for w in row.get_child().get_children()[0].get_children()
                  if isinstance(w, Gtk.Label)]
        meta_label = labels[-1]
        from gi.repository import Pango
        self.assertNotEqual(meta_label.get_ellipsize(), Pango.EllipsizeMode.NONE)


class ProtectionToggleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

        from darkos_shell import user_settings

        self.user_settings = user_settings
        # patch settings_path directly, not $HOME: GLib.get_user_config_dir()
        # caches its result for the process's lifetime after the first
        # call, so a later os.environ change is silently ignored -- see
        # ci/test-continuous-protection.py's ReconcileToggleTests for the
        # full story of how this was actually found.
        settings_file = Path(self.home) / "settings.json"
        self.path_patcher = patch.object(
            user_settings, "settings_path", return_value=str(settings_file)
        )
        self.path_patcher.start()
        self.addCleanup(self.path_patcher.stop)

        spec = importlib.util.spec_from_file_location(
            "darkos_security_test_target2", BIN / "darkos-security.py"
        )
        assert spec is not None and spec.loader is not None
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

        app = Gtk.Application(application_id="test.darkos.security.toggle.ci")
        app.register()
        self.win = self.mod.SecurityWindow(app)
        self.addCleanup(self.win.destroy)

    def test_switch_reflects_saved_setting_on_build(self) -> None:
        self.assertTrue(self.win._protection_switch.get_active())

    def test_toggling_off_writes_real_settings_file(self) -> None:
        self.win._on_protection_toggled(self.win._protection_switch, False)
        self.assertFalse(self.user_settings.load_settings()["shield_protection_enabled"])

    def test_toggling_back_on_writes_true(self) -> None:
        self.win._on_protection_toggled(self.win._protection_switch, False)
        self.win._on_protection_toggled(self.win._protection_switch, True)
        self.assertTrue(self.user_settings.load_settings()["shield_protection_enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
