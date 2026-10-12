#!/usr/bin/env python3
"""ActivityDetector must never block the GTK main loop.

It polls every few seconds. Detection shells out (hyprctl, then -- as a last
resort -- a helper Python process that walks the AT-SPI tree). That used to
run on the GTK main thread, so on an empty desktop the whole shell (dock,
clock, hover, clicks) froze for up to ~3 s on every poll. These tests pin the
two fixes: detection runs on a worker thread, and the helper process is not
spawned when Hyprland answered but simply has nothing focused.

Needs PyGObject's GLib (no display, no GTK, no compositor).
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

BIN = Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin"
spec = importlib.util.spec_from_file_location(
    "activity_detector_under_test", BIN / "darkos_shell" / "activity_detector.py"
)
ad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ad)

try:
    from gi.repository import GLib

    GLIB_AVAILABLE = True
except ImportError:
    GLIB_AVAILABLE = False


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def fake_run(activewindow=None, clients=None, atspi=None):
    """Stand-in for subprocess.run. Each argument is a CompletedProcess or an
    exception to raise; None means "that command was not expected"."""
    calls = []

    def run(argv, **_kwargs):
        calls.append(list(argv))
        if argv[:2] == ["hyprctl", "activewindow"]:
            outcome = activewindow
        elif argv[:2] == ["hyprctl", "clients"]:
            outcome = clients
        elif argv[0] == "python3":
            outcome = atspi
        else:
            raise AssertionError(f"unexpected command {argv!r}")
        if outcome is None:
            raise AssertionError(f"command not expected in this scenario: {argv[:2]!r}")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    run.calls = calls
    return run


def helper_spawned(run):
    return any(call[0] == "python3" for call in run.calls)


class TitleLookupTests(unittest.TestCase):
    def lookup(self, run):
        with patch.object(ad.subprocess, "run", run):
            return ad.ActivityDetector._get_active_window_title()

    def test_focused_window_title_comes_straight_from_hyprctl(self):
        run = fake_run(activewindow=completed(json.dumps({"title": "System Monitor"})))
        self.assertEqual(self.lookup(run), "System Monitor")
        self.assertEqual(len(run.calls), 1)
        self.assertFalse(helper_spawned(run))

    def test_empty_hyprland_desktop_does_not_spawn_a_python_helper(self):
        # Hyprland answers fine (rc 0) but nothing is focused or open. This is
        # the state right after boot, polled every 3 s.
        run = fake_run(activewindow=completed("{}"), clients=completed("[]"))
        self.assertEqual(self.lookup(run), "")
        self.assertFalse(helper_spawned(run), "AT-SPI helper spawned although hyprctl answered")
        self.assertEqual([c[1] for c in run.calls], ["activewindow", "clients"])

    def test_clients_fallback_finds_a_visible_window_on_another_monitor(self):
        def client(title, focus_id, **flags):
            data = {"title": title, "class": "app", "mapped": True, "hidden": False,
                    "visible": True, "focusHistoryID": focus_id}
            data.update(flags)
            return data

        clients = [
            client("Hidden", 0, hidden=True),        # never wins: hidden
            client("Unmapped", 0, mapped=False),     # never wins: not mapped
            client("Offscreen", 0, visible=False),   # never wins: not visible
            client("Old window", 3),
            client("Notes", 1),                      # most recently focused of the eligible ones
        ]
        run = fake_run(activewindow=completed("{}"), clients=completed(json.dumps(clients)))
        self.assertEqual(self.lookup(run), "Notes")
        self.assertFalse(helper_spawned(run))

    def test_clients_fallback_uses_the_class_when_the_title_is_empty(self):
        clients = [{"title": "", "class": "kitty", "mapped": True, "hidden": False,
                    "visible": True, "focusHistoryID": 0}]
        run = fake_run(activewindow=completed("{}"), clients=completed(json.dumps(clients)))
        self.assertEqual(self.lookup(run), "kitty")

    def test_unparseable_hyprctl_output_still_counts_as_hyprland_answering(self):
        run = fake_run(activewindow=completed("not json"), clients=completed("also not json"))
        self.assertEqual(self.lookup(run), "")
        self.assertFalse(helper_spawned(run))

    def test_without_hyprctl_the_atspi_helper_is_the_fallback(self):
        # Non-Hyprland sessions keep working exactly as before.
        run = fake_run(
            activewindow=FileNotFoundError("hyprctl"),
            clients=FileNotFoundError("hyprctl"),
            atspi=completed("Some App\n"),
        )
        self.assertEqual(self.lookup(run), "Some App")
        self.assertTrue(helper_spawned(run))

    def test_hyprctl_failing_with_an_error_status_falls_back_to_atspi(self):
        # e.g. no HYPRLAND_INSTANCE_SIGNATURE: hyprctl exits non-zero.
        run = fake_run(
            activewindow=completed("", returncode=1),
            clients=completed("", returncode=1),
            atspi=completed("Terminal\n"),
        )
        self.assertEqual(self.lookup(run), "Terminal")
        self.assertTrue(helper_spawned(run))

    def test_hyprctl_timeout_falls_back_to_atspi(self):
        timeout = subprocess.TimeoutExpired(cmd="hyprctl", timeout=2)
        run = fake_run(activewindow=timeout, clients=timeout, atspi=completed("Browser\n"))
        self.assertEqual(self.lookup(run), "Browser")


def pump(predicate, timeout=3.0):
    """Run the default GLib main context until predicate() or timeout."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        context.iteration(False)
        time.sleep(0.005)
    return predicate()


@unittest.skipUnless(GLIB_AVAILABLE, "PyGObject (GLib) is not available")
class PollingTests(unittest.TestCase):
    def make_detector(self, detect):
        detector = ad.ActivityDetector()
        detector._running = True
        self.addCleanup(detector.stop)
        detector._detect_activity = detect
        notified = []
        detector.add_listener(lambda profile, _config: notified.append((profile, threading.get_ident())))
        return detector, notified

    def test_poll_returns_immediately_while_detection_is_slow(self):
        detector, notified = self.make_detector(lambda: (time.sleep(0.6), "coding")[1])
        started = time.perf_counter()
        detector._poll()
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.2, f"_poll blocked the caller for {elapsed:.2f}s")
        self.assertTrue(pump(lambda: bool(notified), timeout=3.0), "result never reached the listener")

    def test_listeners_run_on_the_main_thread_not_the_worker(self):
        detector, notified = self.make_detector(lambda: "coding")
        detector._poll()
        self.assertTrue(pump(lambda: bool(notified)))
        self.assertEqual(notified[0][0], "coding")
        self.assertEqual(notified[0][1], threading.get_ident())

    def test_polls_do_not_overlap(self):
        calls = []

        def slow_detect():
            calls.append(1)
            time.sleep(0.4)
            return "default"

        detector, _notified = self.make_detector(slow_detect)
        detector._poll()
        detector._poll()  # the first detection is still in flight
        time.sleep(0.1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(pump(lambda: not detector._detecting))

    def test_unchanged_profile_is_not_renotified(self):
        detector, notified = self.make_detector(lambda: detector.current_profile)
        detector._poll()
        self.assertTrue(pump(lambda: not detector._detecting))
        self.assertEqual(notified, [])

    def test_a_failing_detection_is_swallowed_and_does_not_wedge_polling(self):
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("AT-SPI not ready on first boot")
            return "coding"

        detector, notified = self.make_detector(flaky)
        detector._poll()
        self.assertTrue(pump(lambda: not detector._detecting), "detector stayed stuck after an exception")
        self.assertEqual(notified, [])
        detector._poll()
        self.assertTrue(pump(lambda: bool(notified)))
        self.assertEqual(notified[0][0], "coding")

    def test_a_stopped_detector_publishes_nothing(self):
        detector, notified = self.make_detector(lambda: (time.sleep(0.2), "coding")[1])
        detector._poll()
        detector.stop()
        self.assertTrue(pump(lambda: not detector._detecting))
        self.assertEqual(notified, [])

    def test_main_loop_keeps_ticking_while_detection_blocks(self):
        # The user-visible symptom: the loop must keep servicing timers.
        detector, _notified = self.make_detector(lambda: (time.sleep(0.8), "default")[1])
        ticks = []
        GLib.timeout_add(20, lambda: (ticks.append(time.monotonic()), True)[1])
        detector._poll()
        deadline = time.monotonic() + 0.7
        context = GLib.MainContext.default()
        while time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(0.005)
        self.assertGreaterEqual(len(ticks), 15, f"main loop starved: only {len(ticks)} ticks in 0.7s")
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        self.assertLess(max(gaps), 0.15, f"main loop stalled for {max(gaps):.2f}s")


if __name__ == "__main__":
    unittest.main(verbosity=2)
