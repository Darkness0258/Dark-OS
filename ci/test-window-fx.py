#!/usr/bin/env python3
"""Pure-function tests for darkos-window-fx.py. No GTK, no compositor."""
import datetime
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


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


class ActionSearchTests(unittest.TestCase):
    def test_blank_query_offers_no_actions(self):
        # With an empty query every item ties at score 1 and "action" sorts
        # alphabetically before "app": actions would crowd out the apps.
        self.assertEqual(fx.action_results(""), [])
        self.assertEqual(fx.action_results("   "), [])

    def test_matches_by_name_and_by_keyword(self):
        self.assertEqual([r["name"] for r in fx.action_results("lock")], ["Lock screen"])
        self.assertIn("Screenshot region", [r["name"] for r in fx.action_results("snip")])
        self.assertEqual([r["name"] for r in fx.action_results("phone")], ["Connect phone"])
        self.assertEqual(fx.action_results("zzzz-no-such-thing"), [])

    def test_catalog_keys_are_unique_and_each_name_finds_itself(self):
        keys = [entry[0] for entry in fx.ACTION_CATALOG]
        self.assertEqual(len(keys), len(set(keys)))
        for key, name, _keywords, argv in fx.ACTION_CATALOG:
            self.assertTrue(argv, key)
            hit = [r for r in fx.action_results(name) if r["action"] == key]
            self.assertTrue(hit, f"{name!r} cannot be found by its own name")
            self.assertEqual(hit[0]["score"], 100)

    def test_results_carry_a_copy_of_the_argv(self):
        result = fx.action_results("lock")[0]
        result["argv"].append("--mutated")
        self.assertNotIn("--mutated", fx.action_results("lock")[0]["argv"])

    def test_result_label_does_not_show_raw_search_keywords(self):
        label = fx.result_label(fx.action_results("lock")[0])
        self.assertEqual(label, "[Action] Lock screen")

    def test_apps_files_settings_and_actions_rank_together(self):
        apps = [{"kind": "app", "name": "Lockbox", "comment": "", "exec": ["lockbox"]}]
        ranked = fx.search_items("lock", apps, [], fx.settings_results("lock"), fx.action_results("lock"))
        kinds = {item["kind"] for item in ranked}
        self.assertIn("app", kinds)
        self.assertIn("action", kinds)
        scores = [item["score"] for item in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_search_items_still_works_without_actions(self):
        # Older callers pass four arguments.
        apps = [{"kind": "app", "name": "Notes", "comment": "", "exec": ["notes"]}]
        self.assertEqual(fx.search_items("notes", apps, [], [])[0]["name"], "Notes")

    def test_activating_an_action_launches_its_argv(self):
        item = fx.action_results("lock")[0]
        with patch.object(fx, "_launch_argv") as launch:
            self.assertEqual(fx.activate_result(item), 0)
        launch.assert_called_once_with(["loginctl", "lock-session"])

    def test_activating_an_action_without_argv_fails_cleanly(self):
        with patch.object(fx, "_launch_argv") as launch:
            self.assertEqual(fx.activate_result({"kind": "action", "argv": []}), 1)
        launch.assert_not_called()

    def test_every_self_referencing_action_uses_a_flag_main_accepts(self):
        # An action that points at a flag main() doesn't handle would show
        # up in search and then do nothing but print a usage error.
        script = "/usr/local/bin/darkos-window-fx.py"
        checked = 0
        for key, _name, _keywords, argv in fx.ACTION_CATALOG:
            if script not in argv:
                continue
            flags = argv[argv.index(script) + 1:]
            with patch.object(fx.sys, "argv", ["darkos-window-fx.py", *flags]), \
                 patch.object(fx, "run_snip", return_value=0), \
                 patch.object(fx, "run_overview", return_value=0), \
                 patch.object(fx, "run_zoom", return_value=0), \
                 patch.object(fx, "run_switcher", return_value=0), \
                 patch.object(fx, "run_search", return_value=0):
                self.assertEqual(fx.main(), 0, f"action {key!r} -> {flags} is not a valid command")
            checked += 1
        self.assertGreaterEqual(checked, 5)

    def test_every_launched_script_exists_in_the_image(self):
        bin_dir = Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin"
        for key, _name, _keywords, argv in fx.ACTION_CATALOG:
            for arg in argv:
                if arg.startswith("/usr/local/bin/"):
                    self.assertTrue((bin_dir / Path(arg).name).is_file(), f"{key}: {arg} is not shipped")


class SnipTests(unittest.TestCase):
    NOW = datetime.datetime(2026, 10, 11, 9, 8, 7)

    def test_screenshot_path_is_timestamped_under_pictures_screenshots(self):
        path = fx.screenshot_path(now=self.NOW, home="/home/u")
        self.assertEqual(path, os.path.join("/home/u", "Pictures", "Screenshots", "DarkOS-2026-10-11_09-08-07.png"))

    def test_grim_argv_with_and_without_a_region(self):
        self.assertEqual(fx.grim_argv("/x.png"), ["grim", "/x.png"])
        self.assertEqual(fx.grim_argv("/x.png", "1,2 3x4"), ["grim", "-g", "1,2 3x4", "/x.png"])

    def test_slurp_output_is_validated_strictly(self):
        self.assertEqual(fx.parse_slurp_geometry("100,200 640x480\n"), "100,200 640x480")
        self.assertEqual(fx.parse_slurp_geometry("-5,-6 10x10"), "-5,-6 10x10")  # second monitor to the left/above
        for bad in ("", None, "garbage", "1,2 0x5", "1,2 5x0", "1,2 3x4; rm -rf ~", "1,2 3x4\n5,6 7x8", "$(id)"):
            self.assertEqual(fx.parse_slurp_geometry(bad), "", repr(bad))

    def _snip(self, region, run, **kwargs):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        notify, copy, sleep = Mock(), Mock(return_value=True), Mock()
        code = fx.run_snip(region, home=home.name, now=self.NOW, run=run, sleep=sleep,
                           notify=notify, copy=copy, **kwargs)
        return code, home.name, notify, copy, sleep

    @staticmethod
    def _result(returncode=0, stdout="", stderr=""):
        return Mock(returncode=returncode, stdout=stdout, stderr=stderr)

    def test_full_screen_capture_saves_copies_and_notifies(self):
        run = Mock(return_value=self._result())
        code, home, notify, copy, _sleep = self._snip(False, run)
        path = os.path.join(home, "Pictures", "Screenshots", "DarkOS-2026-10-11_09-08-07.png")
        self.assertEqual(code, 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["grim", path])
        self.assertTrue(os.path.isdir(os.path.dirname(path)))
        copy.assert_called_once_with(path)
        self.assertEqual(notify.call_args.args[0], "Screenshot saved and copied")

    def test_region_capture_passes_the_selected_rectangle_to_grim(self):
        run = Mock(side_effect=[self._result(stdout="10,20 300x200\n"), self._result()])
        code, home, _notify, _copy, _sleep = self._snip(True, run)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args_list[0].args[0], ["slurp"])
        grim = run.call_args_list[1].args[0]
        self.assertEqual(grim[:3], ["grim", "-g", "10,20 300x200"])

    def test_cancelling_the_selection_is_not_an_error_and_captures_nothing(self):
        run = Mock(return_value=self._result(returncode=1))
        code, home, notify, copy, _sleep = self._snip(True, run)
        self.assertEqual(code, 0)
        run.assert_called_once()  # only slurp ran
        copy.assert_not_called()
        notify.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(home, "Pictures")))

    def test_garbled_selection_is_rejected_before_grim_runs(self):
        run = Mock(return_value=self._result(stdout="0,0 10x10; touch /tmp/pwned"))
        code, _home, _notify, copy, _sleep = self._snip(True, run)
        self.assertEqual(code, 1)
        run.assert_called_once()
        copy.assert_not_called()

    def test_missing_slurp_is_reported(self):
        run = Mock(side_effect=FileNotFoundError("slurp"))
        code, _home, notify, _copy, _sleep = self._snip(True, run)
        self.assertEqual(code, 1)
        self.assertEqual(notify.call_args.args[0], "Screenshot unavailable")

    def test_grim_failure_is_reported_and_nothing_is_copied(self):
        run = Mock(return_value=self._result(returncode=1, stderr="compositor doesn't support screencopy"))
        code, _home, notify, copy, _sleep = self._snip(False, run)
        self.assertEqual(code, 1)
        copy.assert_not_called()
        self.assertEqual(notify.call_args.args[0], "Screenshot failed")
        self.assertIn("screencopy", notify.call_args.args[1])

    def test_clipboard_failure_still_counts_as_a_saved_screenshot(self):
        home = tempfile.TemporaryDirectory(); self.addCleanup(home.cleanup)
        notify = Mock()
        code = fx.run_snip(False, home=home.name, now=self.NOW, run=Mock(return_value=self._result()),
                           sleep=Mock(), notify=notify, copy=Mock(return_value=False))
        self.assertEqual(code, 0)
        self.assertEqual(notify.call_args.args[0], "Screenshot saved")

    def test_waits_for_the_launching_overlay_to_close_first(self):
        run = Mock(return_value=self._result())
        _code, _home, _notify, _copy, sleep = self._snip(False, run, settle=0.5)
        sleep.assert_called_once_with(0.5)

    def test_main_dispatches_the_two_flags(self):
        for flag, region in (("--snip", True), ("--snip-screen", False)):
            with patch.object(fx.sys, "argv", ["darkos-window-fx.py", flag]), \
                 patch.object(fx, "run_snip", return_value=0) as run_snip:
                self.assertEqual(fx.main(), 0)
            run_snip.assert_called_once_with(region=region, settle=0.0)  # key binds capture at once

    def test_main_passes_the_delay_through(self):
        with patch.object(fx.sys, "argv", ["darkos-window-fx.py", "--snip-screen", "--delay", "1"]), \
             patch.object(fx, "run_snip", return_value=0) as run_snip:
            self.assertEqual(fx.main(), 0)
        run_snip.assert_called_once_with(region=False, settle=1.0)

    def test_delay_argument_is_clamped_and_forgiving(self):
        self.assertEqual(fx._delay_arg(["--snip"]), 0.0)
        self.assertEqual(fx._delay_arg(["--snip", "--delay", "1"]), 1.0)
        self.assertEqual(fx._delay_arg(["--snip", "--delay", "0.25"]), 0.25)
        self.assertEqual(fx._delay_arg(["--snip", "--delay", "-3"]), 0.0)
        self.assertEqual(fx._delay_arg(["--snip", "--delay", "9999"]), 5.0)
        self.assertEqual(fx._delay_arg(["--snip", "--delay", "soon"]), 0.0)
        self.assertEqual(fx._delay_arg(["--snip", "--delay"]), 0.0)

    def test_search_launched_screenshots_wait_for_the_search_box_to_close(self):
        for key in ("screenshot-region", "screenshot-screen"):
            argv = next(a for k, _n, _kw, a in fx.ACTION_CATALOG if k == key)
            self.assertEqual(argv[argv.index("--delay") + 1], fx.SNIP_SEARCH_DELAY)
        self.assertGreater(float(fx.SNIP_SEARCH_DELAY), 0.7)  # hyprland.conf: windowsOut 6 / fade 7

    def test_a_key_bound_full_screen_capture_does_not_wait_at_all(self):
        run = Mock(return_value=self._result())
        _code, _home, _notify, _copy, sleep = self._snip(False, run)
        sleep.assert_not_called()

    def test_region_capture_waits_for_the_selection_overlay_before_grim(self):
        order = []
        sleep = Mock(side_effect=lambda seconds: order.append(("sleep", seconds)))

        def run(argv, **_kwargs):
            order.append(("run", argv[0]))
            return self._result(stdout="1,2 30x40") if argv[0] == "slurp" else self._result()

        home = tempfile.TemporaryDirectory(); self.addCleanup(home.cleanup)
        code = fx.run_snip(True, home=home.name, now=self.NOW, run=run, sleep=sleep,
                           notify=Mock(), copy=Mock(return_value=True))
        self.assertEqual(code, 0)
        self.assertEqual(order, [("run", "slurp"), ("sleep", fx.SNIP_PICK_SETTLE_SECONDS), ("run", "grim")])

    def test_cancelling_never_waits(self):
        run = Mock(return_value=self._result(returncode=1))
        _code, _home, _notify, _copy, sleep = self._snip(True, run)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
