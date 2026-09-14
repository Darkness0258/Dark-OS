#!/usr/bin/env python3
"""Regressions for continuous_watch.py and the full watch -> scan ->
quarantine loop. Real inotify, real ClamAV (a harmless local signature,
same pattern as ci/test-shield.py), real file moves -- nothing mocked
except quarantine.QUARANTINE_DIR, redirected to a temp dir so this never
touches a real user's actual quarantine store."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

from darkos_shell.continuous_watch import ContinuousWatcher, InotifyUnavailable  # noqa: E402
from darkos_shell import shield, quarantine  # noqa: E402


def _wait_until(predicate, timeout=10.0, interval=0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class ContinuousWatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.watchdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.watchdir, ignore_errors=True)
        self.seen: list[Path] = []
        self.lock = threading.Lock()
        self.watcher = ContinuousWatcher(
            [self.watchdir], lambda p: self._record(p)
        )
        self.watcher.start()
        self.addCleanup(self.watcher.stop)

    def _record(self, path: Path) -> None:
        with self.lock:
            self.seen.append(path)

    def _seen_copy(self) -> list[Path]:
        with self.lock:
            return list(self.seen)

    def test_detects_a_real_file_write_with_correct_path(self) -> None:
        target = self.watchdir / "dropped.txt"
        target.write_bytes(b"hello")
        self.assertTrue(_wait_until(lambda: len(self._seen_copy()) == 1))
        self.assertEqual(self._seen_copy(), [target])

    def test_many_writes_then_one_close_fires_exactly_once(self) -> None:
        target = self.watchdir / "multi-write.txt"
        with open(target, "wb") as f:
            for _ in range(20):
                f.write(b"chunk ")
        self.assertTrue(_wait_until(lambda: len(self._seen_copy()) >= 1))
        time.sleep(0.3)
        self.assertEqual(len(self._seen_copy()), 1)

    def test_unwatched_directory_produces_nothing(self) -> None:
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        (other / "irrelevant.txt").write_bytes(b"x")
        time.sleep(1.5)
        self.assertEqual(self._seen_copy(), [])

    def test_rescan_picks_up_a_directory_created_after_start(self) -> None:
        late = self.watchdir / "not-there-yet"
        watcher = ContinuousWatcher([late], self._record)
        watcher.start()
        self.addCleanup(watcher.stop)
        late.mkdir()
        watcher.rescan()
        (late / "later.txt").write_bytes(b"x")
        self.assertTrue(_wait_until(lambda: (late / "later.txt") in self._seen_copy()))


@unittest.skipUnless(shutil.which("clamscan"), "clamscan not installed")
class FullLoopTests(unittest.TestCase):
    """The real engine, real inotify, real quarantine -- end to end."""

    def setUp(self) -> None:
        self.watchdir = Path(tempfile.mkdtemp())
        self.quarantine_dir = Path(tempfile.mkdtemp()) / "store"
        self.addCleanup(shutil.rmtree, self.watchdir, ignore_errors=True)
        self.payload = b"DARKOS_CI_FULL_LOOP_TEST_PAYLOAD"
        self.database = Path(tempfile.mkdtemp()) / "ci-loop-test.ndb"
        self.database.write_text(
            f"DarkOS.CiFullLoopTest:0:*:{self.payload.hex()}\n", encoding="ascii"
        )
        self.events: list[tuple[Path, str, list[str]]] = []
        self.lock = threading.Lock()

    def _on_file_ready(self, path: Path) -> None:
        result, actions = shield.scan_and_quarantine(
            path, threading.Event(), database=self.database
        )
        with self.lock:
            self.events.append((path, result.outcome, actions))

    def test_dropped_malicious_file_is_detected_and_quarantined_clean_file_is_not(self) -> None:
        with patch.object(quarantine, "QUARANTINE_DIR", self.quarantine_dir):
            watcher = ContinuousWatcher([self.watchdir], self._on_file_ready)
            watcher.start()
            self.addCleanup(watcher.stop)

            dropped = self.watchdir / "bad.bin"
            dropped.write_bytes(self.payload)
            clean = self.watchdir / "clean.txt"
            clean.write_bytes(b"nothing interesting here")

            self.assertTrue(_wait_until(lambda: len(self.events) >= 2, timeout=20))

            by_path = {p: (outcome, actions) for p, outcome, actions in self.events}
            detected_outcome, detected_actions = by_path[dropped]
            self.assertEqual(detected_outcome, "detected")
            self.assertEqual(len(detected_actions), 1)
            self.assertTrue(detected_actions[0].startswith("quarantined:"))
            self.assertFalse(dropped.exists())

            clean_outcome, clean_actions = by_path[clean]
            self.assertEqual((clean_outcome, clean_actions), ("clean", []))
            self.assertTrue(clean.exists())

            self.assertEqual(len(quarantine.list_quarantine()), 1)


class ReconcileToggleTests(unittest.TestCase):
    """darkos-protect.py's _reconcile: the settings.json toggle actually
    starts/stops the real watcher, not just a flag nobody reads."""

    def setUp(self) -> None:
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

        from darkos_shell import user_settings

        self.user_settings = user_settings
        # NOT env-var HOME patching: GLib.get_user_config_dir() (which
        # settings_path() calls) caches its result for the process's
        # whole lifetime after the first call, so a later os.environ
        # change is silently ignored -- discovered by this exact test
        # intermittently reading real, unrelated settings state instead
        # of its own isolated temp dir. Patching settings_path itself
        # sidesteps the cache entirely.
        settings_file = Path(self.home) / "settings.json"
        self.path_patcher = patch.object(
            user_settings, "settings_path", return_value=str(settings_file)
        )
        self.path_patcher.start()
        self.addCleanup(self.path_patcher.stop)

        spec = importlib.util.spec_from_file_location(
            "darkos_protect_test_target", BIN / "darkos-protect.py"
        )
        assert spec is not None and spec.loader is not None
        self.protect = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.protect)

        self.watchdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.watchdir, ignore_errors=True)
        self.seen: list[Path] = []
        self.watcher = ContinuousWatcher(
            [self.watchdir], lambda p: self.seen.append(p)
        )

    def tearDown(self) -> None:
        self.watcher.stop()

    def test_off_by_setting_reconcile_never_starts_it(self) -> None:
        self.user_settings.save_settings({"shield_protection_enabled": False})
        running = self.protect._reconcile(self.watcher, running=False)
        self.assertFalse(running)
        (self.watchdir / "dropped.txt").write_bytes(b"x")
        time.sleep(1.0)
        self.assertEqual(self.seen, [])

    def test_toggled_on_then_off_actually_starts_and_stops_the_watcher(self) -> None:
        self.user_settings.save_settings({"shield_protection_enabled": True})
        running = self.protect._reconcile(self.watcher, running=False)
        self.assertTrue(running)
        target = self.watchdir / "dropped.txt"
        target.write_bytes(b"x")
        self.assertTrue(_wait_until(lambda: self.seen == [target]))

        self.seen.clear()
        self.user_settings.save_settings({"shield_protection_enabled": False})
        running = self.protect._reconcile(self.watcher, running=running)
        self.assertFalse(running)
        (self.watchdir / "dropped-after-off.txt").write_bytes(b"x")
        time.sleep(1.0)
        self.assertEqual(self.seen, [], "must not still be catching files once turned off")


class MountDiscoveryTests(unittest.TestCase):
    """discover_mount_dirs and add_watch_path against real directories
    under /run/media/$USER -- a temp username, cleaned up after, not the
    real user's actual mount namespace."""

    def setUp(self) -> None:
        self.test_user = f"darkos-ci-{uuid.uuid4().hex[:8]}"
        self.home = tempfile.mkdtemp()  # isolates settings.json --
        # NOT via env-var HOME patching: GLib.get_user_config_dir() caches
        # its result for the whole process after the first call, so a
        # later os.environ change is silently ignored (see
        # ReconcileToggleTests.setUp's longer note -- same fix here).
        self.env_patcher = patch.dict("os.environ", {"USER": self.test_user})
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.run_media = Path("/run/media") / self.test_user
        self.addCleanup(shutil.rmtree, self.run_media, ignore_errors=True)

        from darkos_shell import continuous_watch, user_settings

        self.discover_mount_dirs = continuous_watch.discover_mount_dirs
        settings_file = Path(self.home) / "settings.json"
        self.path_patcher = patch.object(
            user_settings, "settings_path", return_value=str(settings_file)
        )
        self.path_patcher.start()
        self.addCleanup(self.path_patcher.stop)

    def test_empty_before_anything_mounted(self) -> None:
        self.assertEqual(self.discover_mount_dirs(), [])

    def test_finds_a_real_new_mount_directory(self) -> None:
        self.run_media.mkdir(parents=True)
        usb = self.run_media / "TEST_DRIVE"
        usb.mkdir()
        self.assertEqual(self.discover_mount_dirs(), [usb])

    def test_returns_empty_not_an_error_when_parent_is_absent(self) -> None:
        # e.g. udisks2 isn't installed -- a real, separate prerequisite
        # this function doesn't provide, and shouldn't pretend to.
        self.assertFalse(self.run_media.exists())
        self.assertEqual(self.discover_mount_dirs(), [])

    def test_reconcile_discovers_and_genuinely_watches_a_new_mount(self) -> None:
        self.run_media.mkdir(parents=True)
        watchdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, watchdir, ignore_errors=True)
        seen: list[Path] = []
        watcher = ContinuousWatcher([watchdir], lambda p: seen.append(p))
        self.addCleanup(watcher.stop)

        spec = importlib.util.spec_from_file_location(
            "darkos_protect_mount_test", BIN / "darkos-protect.py"
        )
        assert spec is not None and spec.loader is not None
        protect = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(protect)

        running = protect._reconcile(watcher, running=False)
        usb = self.run_media / "TEST_DRIVE"
        usb.mkdir()
        protect._reconcile(watcher, running=running)

        target = usb / "dropped.txt"
        target.write_bytes(b"x")
        self.assertTrue(_wait_until(lambda: seen == [target]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
