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


if __name__ == "__main__":
    unittest.main(verbosity=2)
