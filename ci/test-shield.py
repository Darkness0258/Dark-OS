#!/usr/bin/env python3
"""Run scanner regressions; real engine tests use a harmless local signature."""

from __future__ import annotations

import importlib.util
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "darkos_shield_test_target", ROOT / "airootfs/usr/local/bin/darkos_shell/shield.py"
)
assert SPEC is not None and SPEC.loader is not None
shield = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = shield
SPEC.loader.exec_module(shield)

QSPEC = importlib.util.spec_from_file_location(
    "darkos_quarantine_test_target", ROOT / "airootfs/usr/local/bin/darkos_shell/quarantine.py"
)
assert QSPEC is not None and QSPEC.loader is not None
quarantine = importlib.util.module_from_spec(QSPEC)
sys.modules[QSPEC.name] = quarantine
QSPEC.loader.exec_module(quarantine)


class ScannerTests(unittest.TestCase):
    """Failures and unsafe targets must never produce a clean verdict."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="darkos-shield-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "--option-like name.txt"
        self.target.write_text("Harmless test content.\n", encoding="utf-8")
        self.cancel = threading.Event()

    def simulate(self, code: int, report: bytes) -> tuple[object, list[str]]:
        captured: list[str] = []

        class Process:
            returncode = code
            stdout = Mock()

            def __enter__(self) -> Process:
                return self

            def __exit__(self, *_args: object) -> None:
                pass

            def poll(self) -> int:
                return self.returncode

            def wait(self, timeout: float) -> int:
                return self.returncode

        def start(argv: list[str], **kwargs: object) -> Process:
            captured.extend(argv)
            self.assertEqual(kwargs["stdout"], subprocess.PIPE)
            self.assertEqual(kwargs["bufsize"], 0)
            self.assertNotIn("preexec_fn", kwargs)
            self.assertEqual(kwargs["env"]["LC_ALL"], "C")
            return Process()

        with patch.object(shield.shutil, "which", return_value="/usr/bin/clamscan"):
            with patch.object(shield.subprocess, "Popen", side_effect=start):
                oversized = len(report) > shield.REPORT_LIMIT
                collected = (report[:shield.REPORT_LIMIT], "error" if oversized else None,
                             "Scan report size limit reached" if oversized else "")
                with patch.object(shield, "collect_report", return_value=collected):
                    result = shield.scan_path(self.target, self.cancel)
        Process.stdout.close.assert_called_once()
        return result, captured

    def test_clean_and_safe_arguments(self) -> None:
        result, argv = self.simulate(0, b"Scanned files: 1\nInfected files: 0\n")
        self.assertEqual(result.outcome, "clean")
        self.assertEqual(argv[-2:], ["--", str(self.target.resolve())])
        self.assertIn("--follow-dir-symlinks=0", argv)
        self.assertIn("--follow-file-symlinks=0", argv)
        self.assertIn("--alert-encrypted=yes", argv)
        self.assertIn("--alert-exceeds-max=yes", argv)
        self.assertNotIn("--remove", argv)

    def test_detection(self) -> None:
        result, _ = self.simulate(1, b"sample: Synthetic.Test FOUND\nScanned files: 1\n")
        self.assertEqual(result.outcome, "detected")

    def test_parse_infected_files_extracts_path_and_signature(self) -> None:
        hit_path = self.root / "hit.txt"
        hit_path.write_text("x", encoding="utf-8")
        detail = f"{hit_path}: Synthetic.Test-1 FOUND\nScanned files: 1\n"
        hits = shield.parse_infected_files(detail)
        self.assertEqual(hits, [(hit_path.resolve(), "Synthetic.Test-1")])

    def test_parse_infected_files_handles_colon_in_path(self) -> None:
        hit_path = self.root / "weird:name.txt"
        hit_path.write_text("x", encoding="utf-8")
        detail = f"{hit_path}: Synthetic.Test-2 FOUND\n"
        hits = shield.parse_infected_files(detail)
        self.assertEqual(hits, [(hit_path.resolve(), "Synthetic.Test-2")])

    def test_parse_infected_files_skips_files_gone_since_scan(self) -> None:
        gone = self.root / "already-deleted.txt"
        detail = f"{gone}: Synthetic.Test-3 FOUND\n"
        self.assertEqual(shield.parse_infected_files(detail), [])

    def test_parse_infected_files_ignores_non_matching_lines(self) -> None:
        detail = "----------- SCAN SUMMARY -----------\nScanned files: 4\nInfected files: 0\n"
        self.assertEqual(shield.parse_infected_files(detail), [])

    def test_errors_and_empty_scans_fail_closed(self) -> None:
        for code, report in (
            (2, b"ERROR: no databases found\n"),
            (-9, b""),
            (0, b"Scanned files: 0\n"),
            (0, b"ERROR: permission denied\nScanned files: 1\n"),
            (0, b"unexpected output without scan summary"),
        ):
            with self.subTest(code=code, report=report):
                self.assertEqual(self.simulate(code, report)[0].outcome, "error")

    def test_truncated_output_cannot_hide_errors(self) -> None:
        result, _ = self.simulate(0, b"ERROR: unreadable\n" + b"x" * 140000 + b"\nScanned files: 2\n")
        self.assertEqual(result.outcome, "error")
        self.assertLess(len(result.detail), 132000)

    def test_missing_engine(self) -> None:
        with patch.object(shield.shutil, "which", return_value=None):
            self.assertEqual(shield.scan_path(self.target, self.cancel).outcome, "error")

    def test_cancelled_before_start(self) -> None:
        self.cancel.set()
        with patch.object(shield.subprocess, "Popen") as process:
            self.assertEqual(shield.scan_path(self.target, self.cancel).outcome, "cancelled")
            process.assert_not_called()

    def test_invalid_timeout(self) -> None:
        for timeout in (0, -1, float("nan"), float("inf")):
            self.assertEqual(shield.scan_path(self.target, self.cancel, timeout).outcome, "error")

    def test_untrusted_target_type(self) -> None:
        with patch.object(shield.shutil, "which", return_value="clamscan"):
            self.assertEqual(shield.scan_path(self.root / "missing", self.cancel).outcome, "error")
            with patch.object(Path, "is_symlink", return_value=True):
                self.assertEqual(shield.scan_path(self.target, self.cancel).outcome, "error")

    def test_pipe_collector_rejects_excess_output_before_storing_it(self) -> None:
        process = Mock()
        process.stdout.fileno.return_value = 123
        process.poll.return_value = 0
        watcher = Mock()
        watcher.__enter__ = Mock(return_value=watcher)
        watcher.__exit__ = Mock(return_value=False)
        watcher.select.return_value = [(None, shield.selectors.EVENT_READ)]
        with patch.object(shield.selectors, "DefaultSelector", return_value=watcher):
            with patch.object(shield.os, "set_blocking"), patch.object(shield.os, "read", return_value=b"x" * 33) as read:
                with patch.object(shield, "REPORT_LIMIT", 32):
                    report, outcome, detail = shield.collect_report(process, self.cancel, 2)
        self.assertEqual(report, b"x" * 32)
        self.assertEqual(outcome, "error")
        self.assertIn("size limit", detail)
        read.assert_called_once_with(123, 33)

    def test_pipe_collector_drains_complete_output_after_process_exit(self) -> None:
        process = Mock()
        process.stdout.fileno.return_value = 123
        process.poll.return_value = 0
        watcher = Mock()
        watcher.__enter__ = Mock(return_value=watcher)
        watcher.__exit__ = Mock(return_value=False)
        watcher.select.return_value = [(None, shield.selectors.EVENT_READ)]
        with patch.object(shield.selectors, "DefaultSelector", return_value=watcher):
            with patch.object(shield.os, "set_blocking"), patch.object(shield.os, "read", side_effect=[b"Scanned files: 1\n", b""]):
                self.assertEqual(shield.collect_report(process, self.cancel, 2), (b"Scanned files: 1\n", None, ""))
        watcher.unregister.assert_called_once_with(123)

    def test_pipe_collector_accepts_exact_limit_followed_by_eof(self) -> None:
        process = Mock()
        process.stdout.fileno.return_value = 123
        process.poll.return_value = 0
        watcher = Mock()
        watcher.__enter__ = Mock(return_value=watcher)
        watcher.__exit__ = Mock(return_value=False)
        watcher.select.return_value = [(None, shield.selectors.EVENT_READ)]
        with patch.object(shield.selectors, "DefaultSelector", return_value=watcher):
            with patch.object(shield.os, "set_blocking"), patch.object(shield.os, "read", side_effect=[b"x" * 32, b""]) as read:
                with patch.object(shield, "REPORT_LIMIT", 32):
                    self.assertEqual(shield.collect_report(process, self.cancel, 2), (b"x" * 32, None, ""))
        self.assertEqual(read.call_args_list[-1].args, (123, 1))

    def test_empty_pipe_eof_does_not_bypass_live_process_timeout(self) -> None:
        process = Mock()
        process.stdout.fileno.return_value = 123
        process.poll.return_value = None
        watcher = Mock()
        watcher.__enter__ = Mock(return_value=watcher)
        watcher.__exit__ = Mock(return_value=False)
        watcher.select.return_value = [(None, shield.selectors.EVENT_READ)]
        with patch.object(shield.selectors, "DefaultSelector", return_value=watcher):
            with patch.object(shield.os, "set_blocking"), patch.object(shield.os, "read", return_value=b"") as read:
                with patch.object(shield.time, "monotonic", side_effect=[0, 0.1, 2.1]):
                    report, outcome, detail = shield.collect_report(process, self.cancel, 2)
        self.assertEqual(report, b"")
        self.assertEqual(outcome, "error")
        self.assertIn("Time limit", detail)
        read.assert_called_once()
        watcher.unregister.assert_called_once_with(123)

    def test_pipe_read_failure_terminates_reaps_and_closes_scanner(self) -> None:
        process = Mock()
        process.stdout.fileno.return_value = 123
        process.poll.return_value = None
        process.wait.return_value = -15
        watcher = Mock()
        watcher.__enter__ = Mock(return_value=watcher)
        watcher.__exit__ = Mock(return_value=False)
        watcher.select.return_value = [(None, shield.selectors.EVENT_READ)]
        with patch.object(shield.shutil, "which", return_value="clamscan"):
            with patch.object(shield.subprocess, "Popen", return_value=process):
                with patch.object(shield.selectors, "DefaultSelector", return_value=watcher):
                    with patch.object(shield.os, "set_blocking"), patch.object(shield.os, "read", side_effect=OSError("pipe read failed")):
                        result = shield.scan_path(self.target, self.cancel)
        self.assertEqual(result.outcome, "error")
        self.assertIn("pipe read failed", result.detail)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)
        process.stdout.close.assert_called_once()

    def test_scanner_ignoring_terminate_is_killed_and_reaped(self) -> None:
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("clamscan", 3), -9]
        shield.stop_scanner(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    @unittest.skipUnless(os.name == "posix", "Linux/POSIX pipe selector regression")
    def test_timeout_and_running_cancellation_reap_process(self) -> None:
        real_popen = subprocess.Popen
        for cancel_running in (False, True):
            processes: list[subprocess.Popen[bytes]] = []

            def start(_argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
                process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
                processes.append(process)
                if cancel_running:
                    self.cancel.set()
                return process

            self.cancel.clear()
            with patch.object(shield.shutil, "which", return_value="clamscan"):
                with patch.object(shield.subprocess, "Popen", side_effect=start):
                    result = shield.scan_path(self.target, self.cancel, timeout=0.1)
            self.assertEqual(result.outcome, "cancelled" if cancel_running else "error")
            self.assertIsNotNone(processes[0].poll())

    @unittest.skipUnless(os.name == "posix", "Linux/POSIX pipe selector regression")
    def test_real_noisy_process_is_stopped_at_output_cap_and_reaped(self) -> None:
        real_popen = subprocess.Popen
        processes = []

        def start(_argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
            process = real_popen([
                sys.executable, "-c",
                "import os\nblock = b'x' * 65536\nwhile True:\n    os.write(1, block)\n",
            ], **kwargs)
            processes.append(process)
            return process

        started = time.monotonic()
        with patch.object(shield.shutil, "which", return_value="clamscan"):
            with patch.object(shield.subprocess, "Popen", side_effect=start):
                result = shield.scan_path(self.target, self.cancel, timeout=15)
        self.assertEqual(result.outcome, "error")
        self.assertIn("report size limit", result.detail)
        self.assertLessEqual(len(result.detail), shield.REPORT_LIMIT + 200)
        self.assertLess(time.monotonic() - started, 8)
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)


@unittest.skipUnless(shutil.which("clamscan"), "ClamAV is not installed")
class RealEngineTests(unittest.TestCase):
    """Integration tests never download definitions or alter user files."""

    setUp = ScannerTests.setUp

    def test_real_clean_detection_and_empty_database(self) -> None:
        payload = b"DARKOS_SYNTHETIC_SCANNER_TEST_PAYLOAD_1234567890"
        database = self.root / "test.ndb"
        database.write_text(f"DarkOS.HarmlessTest:0:*:{payload.hex()}\n", encoding="ascii")
        result = shield.scan_path(self.target, self.cancel, database=database)
        self.assertEqual(result.outcome, "clean", result.detail)
        self.target.write_bytes(payload)
        result = shield.scan_path(self.target, self.cancel, database=database)
        self.assertEqual(result.outcome, "detected", result.detail)
        self.assertEqual(self.target.read_bytes(), payload)
        empty = self.root / "empty"
        empty.mkdir()
        result = shield.scan_path(empty, self.cancel, database=database)
        self.assertEqual(result.outcome, "error", result.detail)
        result = shield.scan_path(self.target, self.cancel, database=empty)
        self.assertEqual(result.outcome, "error", result.detail)

    def test_real_detection_parses_and_quarantines_correctly(self) -> None:
        """End-to-end against the real engine: detect, parse the real
        clamscan output (not a mocked string), quarantine, confirm the
        original is gone and the quarantine record is byte-correct."""
        payload = b"DARKOS_SYNTHETIC_SCANNER_TEST_PAYLOAD_QUARANTINE"
        database = self.root / "quarantine-test.ndb"
        database.write_text(f"DarkOS.QuarantineTest:0:*:{payload.hex()}\n", encoding="ascii")
        self.target.write_bytes(payload)
        original_sha = hashlib.sha256(payload).hexdigest()

        result = shield.scan_path(self.target, self.cancel, database=database)
        self.assertEqual(result.outcome, "detected", result.detail)

        hits = shield.parse_infected_files(result.detail)
        self.assertEqual(len(hits), 1, result.detail)
        hit_path, signature = hits[0]
        self.assertEqual(hit_path, self.target.resolve())
        # ClamAV appends ".UNOFFICIAL" for signatures from a non-official
        # database (learned by running this for real, not assumed) --
        # checking the prefix is correct and more robust than pinning the
        # exact suffix to one ClamAV version's behavior.
        self.assertTrue(signature.startswith("DarkOS.QuarantineTest"), signature)

        fake_quarantine_dir = self.root / "quarantine-store"
        with patch.object(quarantine, "QUARANTINE_DIR", fake_quarantine_dir):
            entry = quarantine.quarantine_file(hit_path, reason=signature)
            self.assertFalse(self.target.exists(), "original must be gone after quarantine")
            self.assertEqual(entry.sha256, original_sha)
            listed = quarantine.list_quarantine()
            self.assertEqual(len(listed), 1)
            self.assertTrue(listed[0].reason.startswith("DarkOS.QuarantineTest"))
            ok, _msg = quarantine.restore(entry.id)
            self.assertTrue(ok)
            self.assertEqual(self.target.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
