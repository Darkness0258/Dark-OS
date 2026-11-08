#!/usr/bin/env python3
"""AC/battery idle timings: detection, rendering, applying, the watcher, the page.

    xvfb-run -a dbus-run-session -- python3 ci/test-power.py
"""
import importlib.util
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

from darkos_shell import power, user_settings  # noqa: E402

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk  # noqa: E402

    GTK = Gtk.init_check()[0]
except (ImportError, ValueError):
    GTK = False


def supply(root, name, kind, online=None, scope=None):
    d = Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "type").write_text(kind + "\n")
    if online is not None:
        (d / "online").write_text(f"{online}\n")
    if scope is not None:
        (d / "scope").write_text(scope + "\n")


class DetectTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_laptop_plugged_in(self):
        supply(self.root, "BAT0", "Battery")
        supply(self.root, "AC", "Mains", online=1)
        self.assertEqual(power.detect(self.root), power.PowerState("ac", True))

    def test_laptop_unplugged(self):
        supply(self.root, "BAT0", "Battery")
        supply(self.root, "ADP1", "Mains", online=0)
        self.assertEqual(power.detect(self.root), power.PowerState("battery", True))

    def test_usb_c_charger_counts_as_ac(self):
        supply(self.root, "BAT0", "Battery")
        supply(self.root, "ucsi-source-psy-USBC000:001", "USB", online=1)
        self.assertEqual(power.detect(self.root).source, "ac")

    def test_a_desktop_has_no_battery_and_is_always_ac(self):
        supply(self.root, "AC", "Mains", online=0)       # even a flaky 0 must not mean battery
        self.assertEqual(power.detect(self.root), power.PowerState("ac", False))
        self.assertEqual(power.detect(os.path.join(self.root, "missing")), power.PowerState("ac", False))

    def test_a_battery_with_no_mains_entry_at_all_is_on_battery(self):
        supply(self.root, "BAT0", "Battery")
        self.assertEqual(power.detect(self.root), power.PowerState("battery", True))

    def test_a_wireless_mouse_battery_is_not_the_computers(self):
        supply(self.root, "hidpp_battery_0", "Battery", scope="Device")
        self.assertEqual(power.detect(self.root), power.PowerState("ac", False))

    def test_unreadable_entries_are_skipped(self):
        supply(self.root, "BAT0", "Battery")
        (Path(self.root) / "broken").mkdir()              # no type file
        supply(self.root, "AC", "Mains")                  # no online file
        self.assertEqual(power.detect(self.root).source, "battery")


class TimingTests(unittest.TestCase):
    def test_defaults_ac_matches_the_shipped_hypridle_and_battery_is_shorter(self):
        d = dict(user_settings.DEFAULTS)
        self.assertEqual(power.timings_for(d, "ac"), (5, 30))
        self.assertEqual(power.timings_for(d, "battery"), (3, 15))
        shipped = (ROOT / "airootfs/etc/xdg/hypr/hypridle.conf").read_text(encoding="utf-8")
        self.assertEqual(power.parse_timeouts(shipped),
                         [(300, "loginctl lock-session"), (1800, "systemctl suspend")],
                         "AC defaults must reproduce what the ISO ships today")

    def test_invalid_values_fall_back_to_the_default(self):
        bad = {"idle_ac_lock": 7, "idle_ac_suspend": "30", "idle_battery_lock": True, "idle_battery_suspend": -5}
        self.assertEqual(power.timings_for(bad, "ac"), (5, 30))
        self.assertEqual(power.timings_for(bad, "battery"), (3, 15))
        with self.assertRaises(ValueError):
            power.timings_for({}, "solar")

    def test_suspend_must_come_after_lock(self):
        self.assertEqual(power.normalize(10, 30)[:2], (10, 30))
        lock, suspend, notes = power.normalize(15, 10)
        self.assertEqual((lock, suspend), (15, 20))
        self.assertIn("20 minutes", notes[0])
        self.assertEqual(power.normalize(30, 30)[:2], (30, 45))
        self.assertEqual(power.normalize(0, 5)[:2], (0, 5), "no lock timing: nothing to order against")
        self.assertEqual(power.normalize(10, 0)[:2], (10, 0), "never suspend is always fine")

    def test_labels(self):
        self.assertEqual([power.minutes_label(m) for m in (0, 1, 5, 60, 120)],
                         ["Never", "1 minute", "5 minutes", "1 hour", "2 hours"])

    def test_settings_keys_are_validated_by_the_shared_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["XDG_CONFIG_HOME"] = tmp
            try:
                data = user_settings.load_settings()
                data["idle_battery_lock"] = 10
                self.assertTrue(user_settings.save_settings(data))
                self.assertEqual(user_settings.load_settings()["idle_battery_lock"], 10)
                Path(user_settings.settings_path()).write_text('{"idle_battery_lock": 7, "idle_ac_suspend": 999}')
                loaded = user_settings.load_settings()
                self.assertEqual((loaded["idle_battery_lock"], loaded["idle_ac_suspend"]), (3, 30))
            finally:
                os.environ.pop("XDG_CONFIG_HOME", None)


class RenderTests(unittest.TestCase):
    def test_the_generated_config_keeps_every_rule_verify_iso_enforces(self):
        text = power.render_hypridle(5, 30, "ac")
        for required in ("lock_cmd = pidof hyprlock || /usr/local/bin/darkos-lock",
                         "before_sleep_cmd = loginctl lock-session",
                         "on-timeout = loginctl lock-session"):
            self.assertIn(required, text)
        self.assertNotIn("dpms off", text, "hypridle must not turn outputs off under hyprlock")
        self.assertIn("ignore_systemd_inhibit = false", text)

    def test_timings_become_listeners_and_never_means_no_listener(self):
        self.assertEqual(power.parse_timeouts(power.render_hypridle(3, 15, "battery")),
                         [(180, "loginctl lock-session"), (900, "systemctl suspend")])
        self.assertEqual(power.parse_timeouts(power.render_hypridle(0, 30)), [(1800, "systemctl suspend")])
        self.assertEqual(power.parse_timeouts(power.render_hypridle(10, 0)), [(600, "loginctl lock-session")])
        self.assertEqual(power.parse_timeouts(power.render_hypridle(0, 0)), [])

    def test_the_verify_iso_rules_are_still_what_this_test_assumes(self):
        verify = (ROOT / "ci/verify-iso.sh").read_text(encoding="utf-8")
        self.assertIn("hyprctl dispatch dpms off", verify)
        self.assertIn("hypridle must not disable outputs", verify)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "hypr", "hypridle.conf")
        self.restarts = []
        self.settings = dict(user_settings.DEFAULTS)

    def tearDown(self):
        self._tmp.cleanup()

    def apply(self, source):
        return power.apply_idle_config(self.settings, source, self.path, restart=lambda p: self.restarts.append(p) or True)

    def test_first_apply_writes_the_file_and_restarts_hypridle_once(self):
        result = self.apply("ac")
        self.assertTrue(result.changed and result.restarted)
        self.assertEqual(self.restarts, [self.path])
        self.assertEqual(power.parse_timeouts(Path(self.path).read_text()),
                         [(300, "loginctl lock-session"), (1800, "systemctl suspend")])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)

    def test_applying_the_same_thing_again_does_not_restart_anything(self):
        self.apply("ac")
        result = self.apply("ac")
        self.assertFalse(result.changed)
        self.assertEqual(len(self.restarts), 1, "an idle restart resets the user's idle timer: only on change")

    def test_switching_source_rewrites_with_that_sources_timings(self):
        self.apply("ac")
        result = self.apply("battery")
        self.assertTrue(result.changed)
        self.assertEqual(len(self.restarts), 2)
        self.assertEqual(power.parse_timeouts(Path(self.path).read_text()),
                         [(180, "loginctl lock-session"), (900, "systemctl suspend")])

    def test_a_changed_setting_is_applied_for_the_active_source(self):
        self.apply("battery")
        self.settings["idle_battery_suspend"] = 0
        self.apply("battery")
        self.assertEqual(power.parse_timeouts(Path(self.path).read_text()), [(180, "loginctl lock-session")])

    def test_the_source_defaults_to_the_detected_one(self):
        with tempfile.TemporaryDirectory() as sysfs:
            supply(sysfs, "BAT0", "Battery")
            supply(sysfs, "AC", "Mains", online=0)
            result = power.apply_idle_config(self.settings, None, self.path, restart=lambda p: True, sysfs=sysfs)
        self.assertEqual(result.source, "battery")

    def test_no_temp_files_are_left_and_a_failed_restart_is_reported_not_raised(self):
        result = power.apply_idle_config(self.settings, "ac", self.path, restart=lambda p: False)
        self.assertTrue(result.changed)
        self.assertFalse(result.restarted)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["hypridle.conf"])

    def test_an_unwritable_location_raises_oserror_for_the_caller_to_report(self):
        blocker = os.path.join(self._tmp.name, "file")
        Path(blocker).write_text("x")
        with self.assertRaises(OSError):
            power.apply_idle_config(self.settings, "ac", os.path.join(blocker, "x", "hypridle.conf"),
                                    restart=lambda p: True)

    def test_a_suspend_that_precedes_lock_is_corrected_before_it_is_written(self):
        self.settings.update(idle_ac_lock=15, idle_ac_suspend=10)
        result = self.apply("ac")
        self.assertEqual((result.lock, result.suspend), (15, 20))
        self.assertTrue(result.notes)

    def test_hypridle_is_restarted_on_the_generated_file(self):
        calls = []
        orig_run, orig_popen = power.subprocess.run, power.subprocess.Popen
        power.subprocess.run = lambda argv, **kw: calls.append(("run", argv))
        power.subprocess.Popen = lambda argv, **kw: calls.append(("popen", argv))
        orig_sleep, power.time.sleep = power.time.sleep, lambda s: None
        try:
            self.assertTrue(power.restart_hypridle("/x/hypridle.conf"))
        finally:
            power.subprocess.run, power.subprocess.Popen, power.time.sleep = orig_run, orig_popen, orig_sleep
        self.assertEqual(calls, [("run", ["pkill", "-x", "hypridle"]),
                                 ("popen", ["hypridle", "-c", "/x/hypridle.conf"])])


def load_watcher():
    spec = importlib.util.spec_from_file_location("darkos_power_watch", BIN / "darkos-power-watch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.w = load_watcher()

    def run_with(self, sequence, **kw):
        applied, sleeps = [], []
        states = iter(sequence)
        self.w.run(detect=lambda: power.PowerState(next(states), True),
                   apply=lambda settings, source: applied.append(source),
                   load=lambda: {}, sleep=sleeps.append, iterations=len(sequence), **kw)
        return applied, sleeps

    def test_it_applies_at_start_and_then_only_when_the_source_changes(self):
        applied, sleeps = self.run_with(["ac", "ac", "ac", "battery", "battery", "ac"])
        self.assertEqual(applied, ["ac", "battery", "ac"])
        self.assertEqual(sleeps, [self.w.POLL_SECONDS] * 5)

    def test_a_write_failure_is_logged_and_does_not_stop_the_watcher(self):
        calls = []

        def failing(settings, source):
            calls.append(source)
            raise OSError("read-only file system")

        states = iter(["ac", "battery"])
        self.w.run(detect=lambda: power.PowerState(next(states), True), apply=failing,
                   load=lambda: {}, sleep=lambda s: None, iterations=2)
        self.assertEqual(calls, ["ac", "battery"])

    def test_a_second_copy_exits_quietly(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.w.single_instance(tmp)
            self.assertIsNotNone(first)
            self.assertIsNone(self.w.single_instance(tmp))
            os.close(first)
            again = self.w.single_instance(tmp)
            self.assertIsNotNone(again, "the lock is released when the first copy exits")
            os.close(again)

    def test_it_is_started_once_per_session_and_never_touches_gtk(self):
        conf = (ROOT / "airootfs/etc/xdg/hypr/hyprland.conf").read_text(encoding="utf-8")
        self.assertEqual(conf.count("darkos-power-watch.py"), 1)
        self.assertIn("exec-once = sh -c 'sleep 5; exec python /usr/local/bin/darkos-power-watch.py'", conf)
        import ast
        tree = ast.parse((BIN / "darkos-power-watch.py").read_text(encoding="utf-8"))
        imported = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imported |= {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertNotIn("gi", imported, "a background daemon must not import GTK")


def pump(until, timeout=3.0):
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
class PowerPageTests(unittest.TestCase):
    def setUp(self):
        from darkos_shell.power_page import PowerPage
        self.PowerPage = PowerPage
        self.settings = dict(user_settings.DEFAULTS)
        self.saved = []
        self.applied = []
        self.pages = []
        self.state = power.PowerState("ac", True)
        self.save_ok = True

    def tearDown(self):
        for page in self.pages:
            page.destroy()

    def page(self):
        def save(data):
            if not self.save_ok:
                return False
            self.settings = dict(data)
            self.saved.append(dict(data))
            return True

        def apply(settings):
            self.applied.append(dict(settings))
            lock, suspend, notes = power.normalize(*power.timings_for(settings, self.state.source))
            return power.Applied(True, self.state.source, lock, suspend, notes)

        page = self.PowerPage(load=lambda: dict(self.settings), save=save, detect=lambda: self.state, apply=apply)
        self.pages.append(page)
        return page

    def pick(self, combo, minutes):
        text = power.minutes_label(minutes)
        for i, row in enumerate(combo.get_model()):
            if row[0] == text:
                combo.set_active(i)
                return
        self.fail(f"{text} not offered")

    def test_it_shows_the_saved_timings_for_both_sources(self):
        page = self.page()
        ac, bat = page.sections["ac"], page.sections["battery"]
        self.assertEqual(ac.values(), (5, 30))
        self.assertEqual(bat.values(), (3, 15))
        self.assertEqual(ac.lock_combo.get_active_text(), "5 minutes")
        self.assertEqual(ac.suspend_combo.get_active_text(), "30 minutes")

    def test_opening_the_page_saves_and_applies_nothing(self):
        page = self.page()
        page.refresh()
        self.assertTrue(pump(lambda: page.state is not None))
        pump(lambda: False, 0.2)
        self.assertEqual((self.saved, self.applied), ([], []))

    def test_a_computer_without_a_battery_shows_only_the_ac_card(self):
        self.state = power.PowerState("ac", False)
        page = self.page()
        page.show_all()
        page.refresh()
        self.assertTrue(pump(lambda: page.state is not None))
        self.assertTrue(page.sections["ac"].lock_combo.is_visible())
        self.assertFalse(page.sections["battery"].get_visible())
        self.assertFalse(page.sections["battery"].lock_combo.is_visible())
        self.assertIn("no battery", page.current.get_text())

    def test_a_laptop_shows_both_and_says_which_is_in_use(self):
        self.state = power.PowerState("battery", True)
        page = self.page()
        page.show_all()
        page.refresh()
        self.assertTrue(pump(lambda: page.state is not None))
        self.assertTrue(page.sections["battery"].get_visible())
        self.assertIn("on battery", page.current.get_text())
        for source in ("ac", "battery"):
            section = page.sections[source]
            for child in (section.lock_combo, section.suspend_combo):
                self.assertTrue(child.is_visible(), f"{source}: a dropdown inside the card is not on screen")
        self.assertFalse(page.sections["ac"].note.is_visible(), "an empty note takes no space")

    def test_changing_a_timing_saves_it_and_applies_it_off_the_main_thread(self):
        page = self.page()
        self.pick(page.sections["ac"].lock_combo, 10)
        self.assertEqual(self.saved[-1]["idle_ac_lock"], 10)
        self.assertEqual(self.saved[-1]["idle_battery_lock"], 3, "the other source is untouched")
        self.assertTrue(pump(lambda: bool(self.applied)))
        self.assertTrue(pump(lambda: "applied" in page.status.get_text()))

    def test_changing_the_other_sources_timing_says_when_it_will_take_effect(self):
        page = self.page()
        self.pick(page.sections["battery"].suspend_combo, 30)
        self.assertTrue(pump(lambda: "plugged in" in page.status.get_text() or "on battery" in page.status.get_text()))
        self.assertIn("when the computer is on battery", page.status.get_text())

    def test_a_suspend_before_lock_is_corrected_and_explained(self):
        page = self.page()
        section = page.sections["ac"]
        self.pick(section.lock_combo, 15)
        self.pick(section.suspend_combo, 10)
        self.assertEqual(section.values(), (15, 20))
        self.assertEqual(self.saved[-1]["idle_ac_suspend"], 20)
        self.assertTrue(section.note.get_visible())
        self.assertIn("after the screen locks", section.note.get_text())

    def test_a_failed_save_is_reported_and_nothing_is_applied(self):
        page = self.page()
        self.save_ok = False
        self.pick(page.sections["ac"].lock_combo, 10)
        self.assertIn("Could not save", page.status.get_text())
        pump(lambda: False, 0.2)
        self.assertEqual(self.applied, [])

    def test_never_is_offered_for_both_timings(self):
        page = self.page()
        for combo in (page.sections["ac"].lock_combo, page.sections["ac"].suspend_combo):
            self.assertEqual(combo.get_model()[0][0], "Never")

    def test_settings_lists_power_in_the_system_group_and_opens_it_lazily(self):
        spec = importlib.util.spec_from_file_location("darkos_settings_for_power", BIN / "darkos-settings.py")
        module = importlib.util.module_from_spec(spec)
        sys.argv = [str(BIN / "darkos-settings.py")]
        spec.loader.exec_module(module)
        groups = dict((heading, [cid for cid, _l, _i in members]) for heading, members in module.grouped_categories())
        self.assertIn("power", groups["System"])
        source = (BIN / "darkos-settings.py").read_text(encoding="utf-8")
        self.assertIn('"power": self._build_power_tab', source)
        self.assertIn('elif row.category_id == "power":\n                self.power_page.refresh()', source)


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=1))
