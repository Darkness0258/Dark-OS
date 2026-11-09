#!/usr/bin/env python3
"""Display settings: parsing, rules, verified apply, safe persistence, then the Settings page.

    xvfb-run -a dbus-run-session -- python3 ci/test-display.py

hyprctl is never run: FakeHypr answers the two commands the code uses, and can
imitate the failure H1 in docs/MASTER-PLAN.md warns about (says "ok", changes nothing).
"""
import importlib.util
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

from darkos_shell import display  # noqa: E402  (GTK-free)

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk  # noqa: E402

    GTK = Gtk.init_check()[0]
except (ImportError, ValueError):
    GTK = False


def laptop(**over):
    base = {
        "name": "eDP-1", "description": "Chimei Innolux Corporation 0x1450 (eDP-1)",
        "width": 1920, "height": 1080, "refreshRate": 60.00099, "x": 0, "y": 0, "scale": 1.0,
        "transform": 0, "focused": True, "disabled": False,
        "availableModes": ["1920x1080@60.00Hz", "1920x1080@48.01Hz", "1680x1050@59.88Hz",
                           "1280x720@60.00Hz", "1920x1080@60.00Hz"],
    }
    base.update(over)
    return base


def external(**over):
    base = {
        "name": "HDMI-A-1", "description": "Dell Inc. DELL U2720Q (HDMI-A-1)",
        "width": 3840, "height": 2160, "refreshRate": 59.94, "x": 1920, "y": 0, "scale": 1.5,
        "transform": 0, "focused": False, "disabled": False,
        "availableModes": ["3840x2160@60.00Hz", "3840x2160@59.94Hz", "3840x2160@30.00Hz",
                           "2560x1440@59.95Hz", "1920x1080@60.00Hz"],
    }
    base.update(over)
    return base


class FakeHypr:
    """hyprctl stand-in. mode: works | noop (H1) | error | down. lag: reads before a change shows."""

    def __init__(self, monitors, mode="works", lag=0):
        self.state = {m["name"]: dict(m) for m in monitors}
        self.mode = mode
        self.lag = lag
        self.queued = None
        self.calls = []

    def __call__(self, argv, timeout=3):
        self.calls.append(list(argv))
        if self.mode == "down":
            return 127, ""
        if argv[:3] == ["hyprctl", "-j", "monitors"]:
            if self.queued:
                self.queued[0] -= 1
                if self.queued[0] < 0:
                    self.state[self.queued[1]].update(self.queued[2])
                    self.queued = None
            return 0, json.dumps(list(self.state.values()))
        if argv[:3] == ["hyprctl", "keyword", "monitor"]:
            if self.mode == "error":
                return 0, "monitor: invalid mode"
            if self.mode == "noop":
                return 0, "ok"
            name, token, pos, scale, _t, transform = argv[3].split(",")[:6]
            size, _, rate = token.partition("@")
            w, _, h = size.partition("x")
            change = {"width": int(w), "height": int(h), "refreshRate": float(rate),
                      "scale": float(scale), "transform": int(transform)}
            if self.lag:
                self.queued = [self.lag, name, change]
            else:
                self.state[name].update(change)
            return 0, "ok"
        return 1, ""

    def keyword_calls(self):
        return [c[3] for c in self.calls if c[:3] == ["hyprctl", "keyword", "monitor"]]


def no_sleep(_seconds):
    pass


class ParsingTests(unittest.TestCase):
    def test_monitors_modes_and_order(self):
        monitors = display.parse_monitors(json.dumps([external(), laptop()]))
        self.assertEqual([m.name for m in monitors], ["eDP-1", "HDMI-A-1"], "the focused screen is first")
        edp = monitors[0]
        self.assertEqual(edp.current_mode().token(), "1920x1080@60.00")
        self.assertEqual([m.token() for m in edp.modes],
                         ["1920x1080@60.00", "1920x1080@48.01", "1680x1050@59.88", "1280x720@60.00"],
                         "duplicates dropped, largest first")
        self.assertEqual(display.resolutions(edp), [(1920, 1080), (1680, 1050), (1280, 720)])
        self.assertEqual([m.refresh_label() for m in display.refresh_rates(edp, 1920, 1080)], ["60 Hz", "48.01 Hz"])

    def test_names_that_could_inject_config_are_dropped(self):
        evil = [laptop(name="DP-1\nmonitor = ,preferred,auto,9"), laptop(name="DP-2,transform,3"),
                laptop(name=""), laptop(name="ok-1")]
        self.assertEqual([m.name for m in display.parse_monitors(json.dumps(evil))], ["ok-1"])

    def test_garbage_from_hyprctl_is_an_error_not_a_crash(self):
        for text in ("", "not json", "{}", "null"):
            with self.assertRaises(display.DisplayError, msg=text):
                display.parse_monitors(text)

    def test_a_screen_that_lists_no_modes_offers_only_its_current_one(self):
        m = display.parse_monitors(json.dumps([laptop(availableModes=[])]))[0]
        self.assertEqual(display.resolutions(m), [(1920, 1080)])
        self.assertEqual(len(display.refresh_rates(m, 1920, 1080)), 1)

    def test_valid_scales_need_a_whole_logical_size(self):
        self.assertEqual(display.valid_scales(1920, 1080), [1.0, 1.25, 1.5, 2.0, 2.5, 3.0])
        self.assertEqual(display.valid_scales(1366, 768), [1.0, 2.0], "1.25 would give 1092.8 pixels")
        self.assertNotIn(1.75, display.valid_scales(3840, 2160))

    def test_not_running_under_hyprland_is_a_clear_message(self):
        with self.assertRaises(display.DisplayError) as ctx:
            display.list_monitors(FakeHypr([laptop()], mode="down"))
        self.assertIn("Hyprland is not running", str(ctx.exception))
        # ...and the real runner behaves the same where hyprctl does not exist (this sandbox).
        if not any(os.access(os.path.join(p, "hyprctl"), os.X_OK) for p in os.environ["PATH"].split(":")):
            with self.assertRaises(display.DisplayError):
                display.list_monitors()


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.edp = display.parse_monitors(json.dumps([laptop()]))[0]

    def test_rule_text_and_round_trip(self):
        rule = display.build_rule(self.edp, display.Mode(1920, 1080, 60.0), 1.25, 0)
        self.assertEqual(rule, "eDP-1,1920x1080@60.00,0x0,1.25,transform,0")
        name, mode, x, y, scale, transform = display.parse_rule(rule)
        self.assertEqual((name, mode.token(), x, y, scale, transform), ("eDP-1", "1920x1080@60.00", 0, 0, 1.25, 0))

    def test_position_defaults_to_where_the_screen_already_is(self):
        ext = display.parse_monitors(json.dumps([external()]))[0]
        self.assertIn(",1920x0,", display.build_rule(ext, display.Mode(2560, 1440, 59.95), 1.0))

    def test_unsafe_or_absurd_values_are_refused(self):
        mode = display.Mode(1920, 1080, 60.0)
        bad_name = display.Monitor("a,b", "", 1, 1, 1.0, 0, 0, 1.0, 0, False, False, ())
        cases = [
            lambda: display.build_rule(bad_name, mode, 1.0),
            lambda: display.build_rule(self.edp, mode, 0.1),
            lambda: display.build_rule(self.edp, mode, 9.0),
            lambda: display.build_rule(self.edp, mode, 1.0, transform=7),
            lambda: display.build_rule(self.edp, display.Mode(0, 1080, 60.0), 1.0),
            lambda: display.build_rule(self.edp, display.Mode(99999, 1080, 60.0), 1.0),
            lambda: display.build_rule(self.edp, display.Mode(1920, 1080, 0), 1.0),
        ]
        for case in cases:
            with self.assertRaises(ValueError):
                case()

    def test_unreadable_rules_are_rejected(self):
        for rule in ("", "nonsense", "eDP-1,wide,0x0,1", "bad name,1920x1080@60,0x0,1"):
            with self.assertRaises(ValueError, msg=rule):
                display.parse_rule(rule)

    def test_plan_pairs_the_change_with_exactly_what_is_on_screen_now(self):
        rotated = display.parse_monitors(json.dumps([laptop(scale=1.25, transform=1)]))[0]
        new, old = display.plan_change(rotated, display.Mode(1280, 720, 60.0), 1.0, 0)
        self.assertEqual(new, "eDP-1,1280x720@60.00,0x0,1,transform,0")
        self.assertEqual(old, "eDP-1,1920x1080@60.00,0x0,1.25,transform,1")


class ApplyTests(unittest.TestCase):
    def rule(self, **kw):
        return "eDP-1,1920x1080@60.00,0x0,%s,transform,0" % kw.get("scale", 1.5)

    def test_applied_means_read_back_not_exit_code(self):
        hypr = FakeHypr([laptop()])
        ok, message = display.apply_rule(self.rule(), hypr, sleep=no_sleep)
        self.assertEqual((ok, message), (True, "Applied."))
        self.assertEqual(hypr.state["eDP-1"]["scale"], 1.5)

    def test_a_slow_compositor_is_waited_for(self):
        hypr = FakeHypr([laptop()], lag=2)
        sleeps = []
        ok, _ = display.apply_rule(self.rule(), hypr, sleep=sleeps.append)
        self.assertTrue(ok)
        self.assertEqual(len(sleeps), 2, "it polled until the change showed up")

    def test_h1_silent_noop_is_reported_as_failure(self):
        hypr = FakeHypr([laptop()], mode="noop")
        sleeps = []
        ok, message = display.apply_rule(self.rule(), hypr, sleep=sleeps.append, tries=4)
        self.assertFalse(ok)
        self.assertIn("did not change", message)
        self.assertEqual(len(sleeps), 3)

    def test_an_error_answer_is_passed_through(self):
        ok, message = display.apply_rule(self.rule(), FakeHypr([laptop()], mode="error"), sleep=no_sleep)
        self.assertEqual((ok, message), (False, "monitor: invalid mode"))

    def test_no_answer_at_all(self):
        ok, message = display.apply_rule(self.rule(), FakeHypr([laptop()], mode="down"), sleep=no_sleep)
        self.assertEqual((ok, message), (False, "Hyprland did not answer."))

    def test_an_invalid_rule_never_reaches_hyprctl(self):
        hypr = FakeHypr([laptop()])
        self.assertFalse(display.apply_rule("garbage", hypr, sleep=no_sleep)[0])
        self.assertEqual(hypr.calls, [])


class PersistTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "hypr", "conf.d", "monitors.conf")

    def tearDown(self):
        self._tmp.cleanup()

    def lines(self):
        return Path(self.path).read_text().splitlines()

    def test_creates_the_file_with_a_header_and_the_rule(self):
        display.persist_rule("eDP-1,1920x1080@60.00,0x0,1.25,transform,0", self.path)
        self.assertTrue(self.lines()[0].startswith("# Written by DarkOS Settings"))
        self.assertEqual(self.lines()[-1], "monitor = eDP-1,1920x1080@60.00,0x0,1.25,transform,0")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)

    def test_replaces_only_this_screen_and_keeps_everything_else(self):
        os.makedirs(os.path.dirname(self.path))
        Path(self.path).write_text("# my note\nmonitor = HDMI-A-1,2560x1440@59.95,1920x0,1,transform,0\n"
                                   "monitor = eDP-1,1280x720@60.00,0x0,1,transform,0\nmonitor = eDP-1,old,dup\n")
        display.persist_rule("eDP-1,1920x1080@60.00,0x0,2,transform,0", self.path)
        self.assertEqual(self.lines(), [
            "# my note",
            "monitor = HDMI-A-1,2560x1440@59.95,1920x0,1,transform,0",
            "monitor = eDP-1,1920x1080@60.00,0x0,2,transform,0",
        ])

    def test_leaves_no_temp_files_and_survives_an_unsafe_rule(self):
        display.persist_rule("eDP-1,1920x1080@60.00,0x0,1,transform,0", self.path)
        before = Path(self.path).read_text()
        with self.assertRaises(ValueError):
            display.persist_rule("eDP-1\nexec = rm -rf ~,1920x1080@60.00,0x0,1", self.path)
        self.assertEqual(Path(self.path).read_text(), before)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["monitors.conf"])

    def test_the_shipped_session_creates_and_sources_the_file(self):
        conf = (ROOT / "airootfs/etc/xdg/hypr/hyprland.conf").read_text(encoding="utf-8")
        self.assertEqual(conf.count("source = ~/.config/hypr/conf.d/monitors.conf"), 1)
        start = (BIN / "start-hyprland").read_text(encoding="utf-8")
        self.assertIn('conf.d/monitors.conf', start)
        self.assertLess(start.index("monitors.conf"), start.index("exec /usr/bin/start-hyprland"))


def pump(until, timeout=4.0):
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
class DisplayPageTests(unittest.TestCase):
    def setUp(self):
        from darkos_shell.display_page import DisplayPage
        self.DisplayPage = DisplayPage
        self._tmp = tempfile.TemporaryDirectory()
        self.conf = os.path.join(self._tmp.name, "monitors.conf")
        self.saved = []
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.destroy()
        self._tmp.cleanup()

    def make(self, hypr, countdown=15):
        def persist(rule):
            self.saved.append(rule)
            return display.persist_rule(rule, self.conf)

        page = self.DisplayPage(run=hypr, persist=persist, countdown=countdown, sleep=no_sleep)
        self.pages.append(page)
        page.refresh()
        self.assertTrue(pump(lambda: page.cards or "Hyprland" in page.status.get_text()))
        return page

    def pick(self, combo, text):
        model = combo.get_model()
        for i, row in enumerate(model):
            if row[0] == text:
                combo.set_active(i)
                return
        self.fail(f"{text!r} not offered: {[r[0] for r in model]}")

    def test_cards_appear_for_each_screen_with_the_current_values_and_apply_is_off(self):
        page = self.make(FakeHypr([external(), laptop()]))
        self.assertEqual(list(page.cards), ["eDP-1", "HDMI-A-1"])
        card = page.cards["eDP-1"]
        self.assertEqual(card.res_combo.get_active_text(), "1920 \u00d7 1080")
        self.assertEqual(card.rate_combo.get_active_text(), "60 Hz")
        self.assertEqual(card.scale_combo.get_active_text(), "100%")
        self.assertEqual(card.turn_combo.get_active_text(), "Normal")
        self.assertFalse(card.apply_btn.get_sensitive())
        self.assertEqual(page.cards["HDMI-A-1"].scale_combo.get_active_text(), "150%")

    def test_outside_hyprland_the_page_explains_instead_of_showing_dead_controls(self):
        page = self.make(FakeHypr([laptop()], mode="down"))
        self.assertEqual(page.cards, {})
        self.assertIn("Hyprland is not running", page.status.get_text())

    def test_changing_resolution_offers_only_valid_scales_and_real_refresh_rates(self):
        page = self.make(FakeHypr([laptop(availableModes=["1920x1080@60.00Hz", "1366x768@60.00Hz",
                                                          "1366x768@40.00Hz"])]))
        card = page.cards["eDP-1"]
        self.pick(card.res_combo, "1366 \u00d7 768")
        self.assertEqual([r[0] for r in card.scale_combo.get_model()], ["100%", "200%"])
        self.assertEqual([r[0] for r in card.rate_combo.get_model()], ["60 Hz", "40 Hz"])
        self.assertTrue(card.apply_btn.get_sensitive())
        card.reset_btn.clicked()
        self.assertEqual(card.res_combo.get_active_text(), "1920 \u00d7 1080")
        self.assertFalse(card.apply_btn.get_sensitive())

    def test_apply_goes_live_but_is_not_saved_until_kept(self):
        hypr = FakeHypr([laptop()])
        page = self.make(hypr)
        card = page.cards["eDP-1"]
        self.pick(card.scale_combo, "125%")
        card.apply_btn.clicked()
        self.assertTrue(pump(lambda: page.pending is not None))
        self.assertEqual(hypr.state["eDP-1"]["scale"], 1.25, "applied live")
        self.assertTrue(page.banner.get_visible())
        self.assertIn("Reverting in 15 s", page.banner_label.get_text())
        self.assertEqual(self.saved, [], "nothing is saved before the user keeps it")
        self.assertFalse(os.path.exists(self.conf))
        page.keep_btn.clicked()
        self.assertEqual(self.saved, ["eDP-1,1920x1080@60.00,0x0,1.25,transform,0"])
        self.assertIn("monitor = eDP-1,1920x1080@60.00,0x0,1.25,transform,0", Path(self.conf).read_text())
        self.assertFalse(page.banner.get_visible())
        self.assertTrue(pump(lambda: page.cards["eDP-1"].scale_combo.get_active_text() == "125%"),
                        "the page re-reads and shows the kept values")

    def test_revert_restores_the_previous_mode_and_saves_nothing(self):
        hypr = FakeHypr([laptop()])
        page = self.make(hypr)
        card = page.cards["eDP-1"]
        self.pick(card.res_combo, "1280 \u00d7 720")
        card.apply_btn.clicked()
        self.assertTrue(pump(lambda: page.pending is not None))
        self.assertEqual(hypr.state["eDP-1"]["width"], 1280)
        page.revert_btn.clicked()
        self.assertTrue(pump(lambda: hypr.state["eDP-1"]["width"] == 1920))
        self.assertEqual(hypr.state["eDP-1"]["scale"], 1.0)
        self.assertEqual(self.saved, [])
        self.assertTrue(pump(lambda: page.status.get_text() != "Restoring..."))

    def test_no_answer_reverts_by_itself_when_the_countdown_ends(self):
        hypr = FakeHypr([laptop()])
        page = self.make(hypr, countdown=2)
        card = page.cards["eDP-1"]
        self.pick(card.res_combo, "1280 \u00d7 720")
        card.apply_btn.clicked()
        self.assertTrue(pump(lambda: page.pending is not None))
        self.assertTrue(pump(lambda: page.pending is None, timeout=5), "the countdown must end")
        self.assertTrue(pump(lambda: hypr.state["eDP-1"]["width"] == 1920))
        self.assertEqual(self.saved, [])
        self.assertTrue(pump(lambda: "No answer" in page.status.get_text()))

    def test_h1_silent_noop_shows_not_applied_and_changes_nothing(self):
        hypr = FakeHypr([laptop()], mode="noop")
        page = self.make(hypr)
        card = page.cards["eDP-1"]
        self.pick(card.scale_combo, "200%")
        card.apply_btn.clicked()
        self.assertTrue(pump(lambda: "Not applied" in page.status.get_text()))
        self.assertIsNone(page.pending)
        self.assertFalse(page.banner.get_visible())
        self.assertEqual(self.saved, [])
        self.assertTrue(card.res_combo.get_sensitive(), "controls come back after a failure")

    def test_an_error_from_hyprland_is_shown(self):
        page = self.make(FakeHypr([laptop()], mode="error"))
        card = page.cards["eDP-1"]
        self.pick(card.scale_combo, "200%")
        card.apply_btn.clicked()
        self.assertTrue(pump(lambda: "invalid mode" in page.status.get_text()))

    def test_closing_settings_with_an_unanswered_change_puts_the_screen_back(self):
        hypr = FakeHypr([laptop()])
        page = self.make(hypr)
        card = page.cards["eDP-1"]
        self.pick(card.res_combo, "1280 \u00d7 720")
        card.apply_btn.clicked()
        self.assertTrue(pump(lambda: page.pending is not None))
        page.destroy()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and hypr.state["eDP-1"]["width"] != 1920:
            time.sleep(0.02)
        self.assertEqual(hypr.state["eDP-1"]["width"], 1920)
        self.assertEqual(self.saved, [])

    def test_a_save_failure_is_reported_but_the_change_stays_applied(self):
        hypr = FakeHypr([laptop()])

        def broken(rule):
            raise OSError("disk full")

        page = self.DisplayPage(run=hypr, persist=broken, countdown=15, sleep=no_sleep)
        self.pages.append(page)
        page.refresh()
        self.assertTrue(pump(lambda: page.cards))
        card = page.cards["eDP-1"]
        self.pick(card.scale_combo, "200%")
        card.apply_btn.clicked()
        self.assertTrue(pump(lambda: page.pending is not None))
        page.keep_btn.clicked()
        self.assertIn("could not be saved", page.status.get_text())
        self.assertEqual(hypr.state["eDP-1"]["scale"], 2.0)

    def test_hyprctl_is_only_asked_on_worker_threads(self):
        main = threading.main_thread()
        threads = set()

        class Spy(FakeHypr):
            def __call__(self, argv, timeout=3):
                threads.add(threading.current_thread())
                return super().__call__(argv, timeout)

        page = self.make(Spy([laptop()]))
        card = page.cards["eDP-1"]
        self.pick(card.scale_combo, "200%")
        card.apply_btn.clicked()
        self.assertTrue(pump(lambda: page.pending is not None))
        page.keep_btn.clicked()
        self.assertTrue(pump(lambda: bool(page.cards)))
        self.assertNotIn(main, threads, "hyprctl must never run on the GTK thread")

    def test_settings_lists_display_in_the_system_group_and_opens_it_lazily(self):
        spec = importlib.util.spec_from_file_location("darkos_settings_for_display", BIN / "darkos-settings.py")
        module = importlib.util.module_from_spec(spec)
        sys.argv = [str(BIN / "darkos-settings.py")]
        spec.loader.exec_module(module)
        groups = dict((heading, [cid for cid, _l, _i in members]) for heading, members in module.grouped_categories())
        self.assertIn("display", groups["System"])
        source = (BIN / "darkos-settings.py").read_text(encoding="utf-8")
        self.assertIn('"display": self._build_display_tab', source)
        self.assertIn('elif row.category_id == "display":\n                self.display_page.refresh()', source)


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
