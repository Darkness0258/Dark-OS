#!/usr/bin/env python3
"""Welcome app: the first-run decisions, then the window driven with fake services.

Run under xvfb for the GTK half (the logic half needs nothing):
    xvfb-run -a dbus-run-session -- python3 ci/test-welcome.py
"""
import importlib.util
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

from darkos_shell import welcome  # noqa: E402  (GTK-free)

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gio, GLib, Gtk  # noqa: E402

    GTK = Gtk.init_check()[0]
except (ImportError, ValueError):
    GTK = False

PROFILES = """\
* balanced:
    CpuDriver:\tintel_pstate
    PlatformDriver:\tplaceholder

  performance:
    CpuDriver:\tintel_pstate
    PlatformDriver:\tplaceholder
    Degraded:\tno

  power-saver:
    CpuDriver:\tintel_pstate
    PlatformDriver:\tplaceholder
"""


class WelcomeLogicTests(unittest.TestCase):
    def test_config_dir_honours_xdg_then_home(self):
        self.assertEqual(welcome.config_dir({"XDG_CONFIG_HOME": "/x/cfg", "HOME": "/h"}), "/x/cfg/darkos")
        self.assertEqual(welcome.config_dir({"HOME": "/h"}), "/h/.config/darkos")

    def test_should_show_truth_table(self):
        show = welcome.should_show
        self.assertTrue(show(first_run=False, live=False, done=True))    # opened from the launcher
        self.assertTrue(show(first_run=True, live=False, done=False))    # first login
        self.assertFalse(show(first_run=True, live=False, done=True))    # already seen
        self.assertTrue(show(first_run=True, live=True, done=True))      # live: install entry, every boot

    def test_live_gets_one_page_and_installed_gets_the_tour(self):
        self.assertEqual(welcome.pages_for(True), ("welcome",))
        self.assertEqual(welcome.pages_for(False), ("welcome", "look", "power", "tools", "finish"))

    def test_markers_round_trip_and_report_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "darkos")
            self.assertFalse(welcome.is_done(cfg))
            self.assertTrue(welcome.write_marker(welcome.DONE_NAME, cfg))
            self.assertTrue(welcome.is_done(cfg))
            blocker = os.path.join(tmp, "file")
            Path(blocker).write_text("x")
            self.assertFalse(welcome.write_marker(welcome.DONE_NAME, os.path.join(blocker, "sub")))

    def test_old_first_boot_answers_are_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(welcome.performance_pending(tmp))
            self.assertTrue(welcome.tools_pending(tmp))
            welcome.write_marker("firstboot-performance.declined", tmp)
            welcome.write_marker("firstboot-tools.done", tmp)
            self.assertFalse(welcome.performance_pending(tmp))
            self.assertFalse(welcome.tools_pending(tmp))

    def test_profiles_are_parsed_from_real_powerprofilesctl_output(self):
        self.assertEqual(welcome.parse_profiles(PROFILES),
                         [("performance", "Performance"), ("balanced", "Balanced"),
                          ("power-saver", "Power saver")])
        self.assertEqual(welcome.active_profile(PROFILES), "balanced")

    def test_a_daemon_that_offers_nothing_yields_nothing(self):
        self.assertEqual(welcome.parse_profiles(""), [])
        self.assertEqual(welcome.parse_profiles("Error: daemon not running"), [])
        self.assertIsNone(welcome.active_profile(""))

    def test_only_offered_profiles_are_listed(self):
        partial = "* balanced:\n    CpuDriver:\tx\n\n  power-saver:\n    CpuDriver:\tx\n"
        self.assertEqual([p for p, _ in welcome.parse_profiles(partial)], ["balanced", "power-saver"])

    def test_tools_command_creates_the_done_marker_only_after_sudo_succeeds(self):
        argv = welcome.tools_argv(cfg="/home/u/.config/darkos")
        self.assertEqual(argv[0], welcome.VOID_BIN)
        self.assertIn(welcome.TOOL_GROUPS_BIN, argv)
        self.assertEqual(argv[-1], "/home/u/.config/darkos/firstboot-tools.done")
        script = argv[argv.index("-c") + 1]
        self.assertLess(script.index('sudo "$1"'), script.index("&&"))
        self.assertLess(script.index("&&"), script.index('touch "$3"'))

    def test_build_id_is_trimmed_and_missing_file_is_empty(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("0123456789abcdef0123\n")
        try:
            self.assertEqual(welcome.build_id(f.name), "0123456789ab")
        finally:
            os.unlink(f.name)
        self.assertEqual(welcome.build_id("/nonexistent/build"), "")


def load_app_module():
    spec = importlib.util.spec_from_file_location("darkos_welcome_app", BIN / "darkos-welcome.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeServices:
    """Stands in for Services: nothing touches the real system."""

    def __init__(self, cfg, live=False, profiles_output=PROFILES):
        self.cfg = cfg
        self.live = live
        self.profiles_output = profiles_output
        self.settings = {"wallpaper_path": "", "effects": "auto", "dock_position": "bottom"}
        self.saved = []
        self.spawned = []
        self.profile_calls = []
        self.wallpaper_calls = []
        self.profile_done = threading.Event()
        self.wallpaper_done = threading.Event()

    def list_profiles(self):
        return self.profiles_output

    def set_profile(self, profile):
        self.profile_calls.append(profile)
        self.profile_done.set()
        return True

    def apply_wallpaper(self, path):
        self.wallpaper_calls.append(path)
        self.wallpaper_done.set()
        return True, path

    def spawn(self, argv):
        self.spawned.append(list(argv))
        return True

    def load_settings(self):
        return dict(self.settings)

    def save_settings(self, data):
        self.settings = dict(data)
        self.saved.append(dict(data))
        return True


def pump(until, timeout=3.0):
    """Run the GLib main loop until `until()` is true (idle callbacks, signals)."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        while ctx.iteration(False):
            pass
        if until():
            return True
        time.sleep(0.01)
    return until()


@unittest.skipUnless(GTK, "no display (run under xvfb-run)")
class WelcomeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_app_module()
        cls.app = Gtk.Application(application_id="org.darkos.WelcomeTest",
                                  flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self._tmp.name, "darkos")
        self.svc = FakeServices(self.cfg)

    def tearDown(self):
        for win in list(self.app.get_windows()):
            win.destroy()
        self._tmp.cleanup()

    def window(self, **kw):
        svc = kw.pop("svc", self.svc)
        win = self.mod.WelcomeWindow(self.app, svc)
        win.show_all()
        return win

    def test_installed_tour_has_five_pages_and_walks_to_done(self):
        win = self.window()
        self.assertEqual(win.pages, ["welcome", "look", "power", "tools", "finish"])
        self.assertFalse(win.back_btn.get_sensitive())
        self.assertEqual(win.next_btn.get_label(), "Next")
        seen = [win.current()]
        for _ in range(4):
            win.next_btn.clicked()
            seen.append(win.current())
        self.assertEqual(seen, win.pages)
        self.assertEqual(win.next_btn.get_label(), "Done")
        self.assertFalse(win.skip_btn.get_visible())
        win.next_btn.clicked()  # Done
        self.assertTrue(welcome.is_done(self.cfg))
        self.assertNotIn(win, self.app.get_windows())

    def test_back_walks_backwards_and_stops_at_the_first_page(self):
        win = self.window()
        win.next_btn.clicked()
        win.next_btn.clicked()
        win.back_btn.clicked()
        self.assertEqual(win.current(), "look")
        win.back_btn.clicked()
        self.assertEqual(win.current(), "welcome")
        self.assertFalse(win.back_btn.get_sensitive())
        self.assertEqual(win.progress.get_text(), "1 of 5")

    def test_skip_marks_it_seen_and_closes(self):
        win = self.window()
        win.skip_btn.clicked()
        self.assertTrue(welcome.is_done(self.cfg))
        self.assertNotIn(win, self.app.get_windows())

    def test_closing_with_the_window_button_also_counts_as_seen(self):
        win = self.window()
        win.destroy()
        self.assertTrue(welcome.is_done(self.cfg))

    def test_old_first_boot_answers_remove_those_pages(self):
        welcome.write_marker("firstboot-performance.done", self.cfg)
        welcome.write_marker("firstboot-tools.declined", self.cfg)
        win = self.window()
        self.assertEqual(win.pages, ["welcome", "look", "finish"])

    def test_live_session_is_one_page_with_an_install_button(self):
        svc = FakeServices(self.cfg, live=True)
        win = self.window(svc=svc)
        self.assertEqual(win.pages, ["welcome"])
        self.assertFalse(win.back_btn.get_visible())
        self.assertFalse(win.skip_btn.get_visible())
        self.assertFalse(win.next_btn.get_visible())
        win.install_btn.clicked()
        self.assertEqual(svc.spawned, [[welcome.INSTALLER_BIN]])
        self.assertNotIn(win, self.app.get_windows())
        self.assertFalse(welcome.is_done(self.cfg), "the live session must not write a marker")

    def test_look_page_saves_settings_and_applies_the_wallpaper_off_the_main_thread(self):
        win = self.window()
        win.next_btn.clicked()
        self.assertEqual(win.current(), "look")
        win.effect_buttons["lite"].set_active(True)
        self.assertEqual(self.svc.settings["effects"], "lite")
        win.dock_buttons["left"].set_active(True)
        self.assertEqual(self.svc.settings["dock_position"], "left")
        paths = list(win.wallpaper_buttons)
        self.assertEqual(len(paths), 9)
        target = paths[3]
        win.wallpaper_buttons[target].set_active(True)
        self.assertTrue(self.svc.wallpaper_done.wait(3))
        self.assertEqual(self.svc.wallpaper_calls, [target])
        self.assertEqual(self.svc.settings["wallpaper_path"], target)

    def test_opening_the_look_page_changes_nothing(self):
        win = self.window()
        win.next_btn.clicked()
        pump(lambda: False, 0.2)
        self.assertEqual(self.svc.saved, [], "initial radio state must not write settings")
        self.assertEqual(self.svc.wallpaper_calls, [])

    def test_power_page_offers_real_profiles_and_sets_the_chosen_one(self):
        win = self.window()
        for _ in range(2):
            win.next_btn.clicked()
        self.assertEqual(win.current(), "power")
        self.assertTrue(pump(lambda: bool(win.profile_buttons)))
        self.assertEqual(sorted(win.profile_buttons), ["balanced", "performance", "power-saver"])
        self.assertTrue(win.profile_buttons["balanced"].get_active())
        self.assertEqual(self.svc.profile_calls, [], "showing the current profile must not set it")
        win.profile_buttons["performance"].set_active(True)
        self.assertTrue(self.svc.profile_done.wait(3))
        self.assertEqual(self.svc.profile_calls, ["performance"])
        self.assertTrue(pump(lambda: welcome.marker_exists(welcome.PERFORMANCE_DONE, self.cfg)))

    def test_power_page_with_no_daemon_says_so_and_offers_no_buttons(self):
        svc = FakeServices(self.cfg, profiles_output="")
        win = self.window(svc=svc)
        for _ in range(2):
            win.next_btn.clicked()
        self.assertTrue(pump(lambda: "nothing to choose" in win.profile_status.get_text()))
        self.assertEqual(win.profile_buttons, {})

    def test_tools_page_opens_the_picker_or_declines_for_good(self):
        win = self.window()
        for _ in range(3):
            win.next_btn.clicked()
        self.assertEqual(win.current(), "tools")
        win.choose_tools_btn.clicked()
        self.assertEqual(self.svc.spawned[-1], welcome.tools_argv(cfg=self.cfg))
        self.assertFalse(welcome.marker_exists(welcome.TOOLS_DECLINED, self.cfg))
        win.decline_tools_btn.clicked()
        self.assertTrue(welcome.marker_exists(welcome.TOOLS_DECLINED, self.cfg))
        self.assertFalse(welcome.tools_pending(self.cfg))

    def test_finish_page_launchers_point_at_scripts_that_exist(self):
        win = self.window()
        for _ in range(4):
            win.next_btn.clicked()
        for name, path in self.mod.QUICK_LAUNCH:
            self.assertTrue((ROOT / "airootfs" / path.lstrip("/")).is_file(), f"{name}: {path}")
            win.launch_buttons[name].clicked()
            self.assertEqual(self.svc.spawned[-1], ["python", path])

    def test_autostart_exits_quietly_once_seen_and_shows_otherwise(self):
        calls = []
        self.mod.run_app = lambda *a, **k: calls.append(a)
        self.mod.welcome.is_live = lambda *a, **k: False
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name
        try:
            self.assertEqual(self.mod.main(["--first-run"]), 0)
            self.assertEqual(len(calls), 1, "first login must show the tour")
            welcome.write_marker(welcome.DONE_NAME)
            self.assertEqual(self.mod.main(["--first-run"]), 0)
            self.assertEqual(len(calls), 1, "after it was seen, autostart must not show it")
            self.assertEqual(self.mod.main([]), 0)
            self.assertEqual(len(calls), 2, "the launcher always shows it")
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    def test_nothing_in_the_shipped_wiring_still_points_at_the_old_prompts(self):
        conf = (ROOT / "airootfs/etc/xdg/hypr/hyprland.conf").read_text(encoding="utf-8")
        autostart = [l for l in conf.splitlines() if l.startswith("exec-once") and "welcome" in l]
        self.assertEqual(len(autostart), 1)
        self.assertIn("--first-run", autostart[0])
        self.assertNotIn("exec-once = sh -c 'sleep 10; exec /usr/local/bin/darkos-firstboot-tools'", conf)
        desktop = (ROOT / "airootfs/usr/share/applications/darkos-welcome.desktop").read_text(encoding="utf-8")
        self.assertIn("Exec=/usr/local/bin/darkos-welcome.py", desktop)


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
