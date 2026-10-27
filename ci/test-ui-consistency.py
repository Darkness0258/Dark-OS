#!/usr/bin/env python3
"""UI consistency: no placeholder icons, and a Settings sidebar that is
grouped instead of one 17-row list.

    xvfb-run -a dbus-run-session -- python ci/test-ui-consistency.py

Rule 6 of docs/MASTER-PLAN.md section 5: one icon family, symbolic variants.
A name the icon theme doesn't have draws a generic placeholder, which is how
Performance, Icons and Themes ended up with the same blank tag in Settings.
"""
import glob
import importlib.util
import os
import re
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
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gio, Gtk

    GTK_AVAILABLE = Gtk.init_check()[0]
except (ImportError, ValueError):
    GTK_AVAILABLE = False

SYMBOLIC = re.compile(r'"([a-z][a-z0-9]*(?:-[a-z0-9]+)*-symbolic)"')


@unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
class IconTests(unittest.TestCase):
    def test_every_symbolic_icon_the_ui_names_exists_in_the_theme(self):
        theme = Gtk.IconTheme.get_default()
        sources = glob.glob(str(BIN / "*.py")) + glob.glob(str(BIN / "darkos_shell/*.py"))
        missing = {}
        for path in sources:
            for name in SYMBOLIC.findall(Path(path).read_text(encoding="utf-8")):
                if not theme.has_icon(name):
                    missing.setdefault(name, set()).add(os.path.basename(path))
        self.assertEqual(
            missing, {},
            "icons the theme doesn't have render as a generic placeholder: "
            + ", ".join(f"{n} ({', '.join(sorted(f))})" for n, f in sorted(missing.items())),
        )


@unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
class SettingsSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Gtk.Application(application_id="test.darkos.ui.ci", flags=Gio.ApplicationFlags.NON_UNIQUE)
        assert cls.app.register(None)
        spec = importlib.util.spec_from_file_location("darkos_settings_ui_test", BIN / "darkos-settings.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        from darkos_shell import user_settings

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = os.path.join(self.tmp.name, "settings.json")
        patcher = patch.object(user_settings, "settings_path", lambda: path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def window(self, tab=None):
        env = {"DARKOS_SETTINGS_TAB": tab} if tab is not None else {}
        with patch.dict(os.environ, env):
            if tab is None:
                os.environ.pop("DARKOS_SETTINGS_TAB", None)
            window = self.module.SettingsWindow(self.app)
        self.addCleanup(window.destroy)
        return window

    def rows(self, window):
        return window.sidebar.get_children()

    def test_headings_come_in_order_and_cannot_be_selected(self):
        rows = self.rows(self.window())
        headings = [r for r in rows if not hasattr(r, "category_id")]
        self.assertEqual(
            [r.get_child().get_text() for r in headings],
            ["APPEARANCE", "SYSTEM", "ACCESS & PRIVACY"],
        )
        for heading in headings:
            self.assertFalse(heading.get_selectable())
            self.assertFalse(heading.get_activatable())

    def test_every_page_is_reachable_exactly_once(self):
        window = self.window()
        ids = [r.category_id for r in self.rows(window) if hasattr(r, "category_id")]
        self.assertEqual(sorted(ids), sorted(cid for cid, _l, _i in self.module.CATEGORIES))
        self.assertEqual(len(ids), len(set(ids)))
        for cid in ids:
            self.assertIsNotNone(window.stack.get_child_by_name(cid), cid)

    def test_it_opens_on_a_real_page_never_on_a_heading(self):
        window = self.window()
        selected = window.sidebar.get_selected_row()
        self.assertTrue(hasattr(selected, "category_id"))
        self.assertEqual(selected.category_id, "themes")
        self.assertEqual(window.stack.get_visible_child_name(), "themes")

    def test_a_deep_link_from_the_launcher_selects_its_page(self):
        window = self.window("updates")
        self.assertEqual(window.sidebar.get_selected_row().category_id, "updates")

    def test_an_unknown_deep_link_falls_back_instead_of_crashing(self):
        window = self.window("no-such-page")
        self.assertEqual(window.sidebar.get_selected_row().category_id, "themes")

    def test_a_page_missing_from_every_group_still_appears_under_more(self):
        extra = ("brand-new", "Brand new", "computer-symbolic")
        with patch.object(self.module, "CATEGORIES", self.module.CATEGORIES + [extra]):
            groups = self.module.grouped_categories()
        self.assertEqual(groups[-1][0], "More")
        self.assertEqual([cid for cid, _l, _i in groups[-1][1]], ["brand-new"])

    def test_the_settings_page_names_match_the_launcher_catalogue(self):
        """darkos-window-fx's search overlay lists Settings pages by label; a
        renamed page must be renamed there too or search shows the old name."""
        text = (BIN / "darkos-window-fx.py").read_text(encoding="utf-8")
        for cid, label, _icon in self.module.CATEGORIES:
            match = re.search(rf'\("{cid}", "([^"]+)"', text)
            if match:
                self.assertEqual(match.group(1), label, cid)


if __name__ == "__main__":
    unittest.main(verbosity=1)
