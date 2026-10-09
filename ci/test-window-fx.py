#!/usr/bin/env python3
"""Pure-function tests for darkos-window-fx.py. No GTK, no compositor."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock


BIN = Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin"
spec = importlib.util.spec_from_file_location("darkos_window_fx", BIN / "darkos-window-fx.py")
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)


class SwitcherTests(unittest.TestCase):
    def test_hides_empty_special_and_overlay_windows(self):
        clients = [
            {"title": "", "address": "0x1", "class": "kitty"},
            {"title": "Term", "address": "", "class": "kitty"},
            {"title": "HUD", "address": "0x2", "class": "darkos-switcher"},
            {"title": "Wofi", "address": "0x3", "class": "wofi"},
            {"title": "Hidden", "address": "0x4", "class": "notes", "hidden": True},
            {"title": "Scratch", "address": "0x5", "class": "kitty", "workspace": {"name": "special:scratch"}},
            {"title": "Files", "address": "0x6", "class": "darkos-files", "focusHistoryID": 0},
            {"title": "Notes", "address": "0x7", "class": "darkos-notes", "focusHistoryID": 1},
        ]
        visible = fx.visible_clients(clients)
        self.assertEqual([c["title"] for c in visible], ["Files", "Notes"])

    def test_alt_tab_selects_previously_focused_window_first(self):
        clients = [
            {"title": "A", "address": "0xa", "class": "a", "focusHistoryID": 0},
            {"title": "B", "address": "0xb", "class": "b", "focusHistoryID": 1},
            {"title": "C", "address": "0xc", "class": "c", "focusHistoryID": 2},
        ]
        ordered = fx.ordered_switcher_clients(clients)
        self.assertEqual([c["title"] for c in ordered], ["B", "C", "A"])

    def test_grim_geometry_rejects_tiny_or_broken_windows(self):
        self.assertIsNone(fx.grim_geometry({"at": [0, 0], "size": [10, 10]}))
        self.assertIsNone(fx.grim_geometry({}))
        self.assertEqual(fx.grim_geometry({"at": [10, 20], "size": [800, 600]}), "10,20 800x600")

    def test_capture_thumbnail_requires_grim_success_and_file(self):
        client = {"at": [0, 0], "size": [800, 600]}
        runner = Mock(side_effect=FileNotFoundError("grim"))
        self.assertIsNone(fx.capture_thumbnail(client, "/tmp/nope.png", runner=runner))


class SnapTests(unittest.TestCase):
    def test_half_and_quadrant_rects(self):
        self.assertEqual(fx.snap_rect(0, 0, 1920, 1080, "left"), (0, 0, 960, 1080))
        self.assertEqual(fx.snap_rect(0, 0, 1920, 1080, "right"), (960, 0, 960, 1080))
        self.assertEqual(fx.snap_rect(0, 0, 1920, 1080, "top-left"), (0, 0, 960, 540))
        self.assertEqual(fx.snap_rect(0, 0, 1920, 1080, "bottom-right"), (960, 540, 960, 540))
        self.assertEqual(fx.snap_rect(0, 0, 1920, 1080, "maximize"), (0, 0, 1920, 1080))
        self.assertIsNone(fx.snap_rect(0, 0, 1920, 1080, "diagonal"))

    def test_unknown_snap_side_is_usage_error(self):
        self.assertEqual(fx.run_snap("nope"), 2)

    def test_monitor_logical_rect_undoes_hyprctl_scale(self):
        rect = fx.monitor_logical_rect({"x": 0, "y": 0, "width": 3840, "height": 2160, "scale": 2})
        self.assertEqual(rect, {"x": 0, "y": 0, "w": 1920, "h": 1080})


class SearchTests(unittest.TestCase):
    def test_desktop_parser_skips_hidden_and_strips_field_codes(self):
        hidden = "[Desktop Entry]\nType=Application\nName=Spy\nExec=spy\nNoDisplay=true\n"
        self.assertIsNone(fx.parse_desktop_file(hidden))
        shown = (
            "[Desktop Entry]\nType=Application\nName=Files\n"
            "Exec=/usr/local/bin/darkos-files.py %U\nComment=Browse files\n"
        )
        parsed = fx.parse_desktop_file(shown)
        self.assertEqual(parsed["name"], "Files")
        self.assertEqual(parsed["exec"], ["/usr/local/bin/darkos-files.py"])
        self.assertEqual(parsed["kind"], "app")

    def test_match_score_ranks_exact_prefix_and_substring(self):
        self.assertEqual(fx.match_score("files", "Files"), 100)
        self.assertGreater(fx.match_score("set", "Settings"), fx.match_score("set", "Reset network"))
        self.assertEqual(fx.match_score("", "anything"), 1)
        self.assertEqual(fx.match_score("zzz", "Files"), 0)

    def test_settings_catalog_finds_accessibility(self):
        hits = fx.settings_results("magnifier")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["tab"], "accessibility")
        self.assertEqual(hits[0]["kind"], "setting")

    def test_recent_files_and_search_mix(self):
        xbel = """
        <bookmark href="file:///home/darkos/Documents/report.pdf"/>
        <bookmark href="file:///home/darkos/Downloads/photo.png"/>
        """
        recents = fx.parse_recently_used(xbel)
        self.assertEqual(recents[0].endswith("report.pdf"), True)
        files = fx.file_results("report", home="/home/darkos", recent_paths=recents, extra_paths=[])
        self.assertEqual(files[0]["kind"], "file")
        self.assertEqual(files[0]["name"], "report.pdf")

        apps = [fx.parse_desktop_file(
            "[Desktop Entry]\nType=Application\nName=Files\nExec=/usr/local/bin/darkos-files.py\n"
        )]
        mixed = fx.search_items("file", apps, files, fx.settings_results("file"))
        kinds = {item["kind"] for item in mixed}
        self.assertIn("app", kinds)

    def test_result_label_includes_kind(self):
        label = fx.result_label({"kind": "setting", "name": "Accessibility", "tab": "accessibility"})
        self.assertTrue(label.startswith("[Setting]"))


class ZoomTests(unittest.TestCase):
    def test_zoom_clamps_and_toggles(self):
        self.assertEqual(fx.next_zoom(1.0, "in"), 1.25)
        self.assertEqual(fx.next_zoom(1.0, "out"), 1.0)
        self.assertEqual(fx.next_zoom(1.0, "on"), 2.0)
        self.assertEqual(fx.next_zoom(2.0, "toggle"), 1.0)
        self.assertEqual(fx.next_zoom(1.0, "toggle"), 2.0)
        self.assertEqual(fx.next_zoom(3.9, "in"), 4.0)
        self.assertEqual(fx.next_zoom("bad", "reset"), 1.0)

    def test_a11y_apply_reads_saved_magnifier_flag(self):
        applied = []
        original = fx.apply_zoom
        fx.apply_zoom = lambda factor, option=None: applied.append(factor) or 0
        try:
            fx.run_a11y_apply({"a11y_magnifier": True})
            fx.run_a11y_apply({"a11y_magnifier": False})
        finally:
            fx.apply_zoom = original
        self.assertEqual(applied, [fx.ZOOM_ON, fx.ZOOM_MIN])


class OverviewTests(unittest.TestCase):
    def test_groups_windows_by_workspace_id(self):
        clients = [
            {"title": "A", "address": "0xa", "class": "a", "workspace": {"id": 2}},
            {"title": "B", "address": "0xb", "class": "b", "workspace": {"id": 1}},
            {"title": "C", "address": "0xc", "class": "c", "workspace": {"id": 2}},
        ]
        groups = fx.group_clients_by_workspace(clients)
        self.assertEqual(list(groups.keys()), [1, 2])
        self.assertEqual([c["title"] for c in groups[2]], ["A", "C"])


class UsageTests(unittest.TestCase):
    def test_main_rejects_unknown_flags(self):
        original = fx.sys.argv
        fx.sys.argv = ["darkos-window-fx.py"]
        try:
            self.assertEqual(fx.main(), 2)
        finally:
            fx.sys.argv = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
