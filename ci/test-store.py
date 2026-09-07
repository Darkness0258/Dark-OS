#!/usr/bin/env python3
"""Read-only Store backend and asynchronous job regressions without GTK."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch


gi = types.ModuleType("gi")
gi.require_version = lambda *_: None
repository = types.ModuleType("gi.repository")
repository.Gtk = types.SimpleNamespace(ApplicationWindow=object)
repository.GLib = types.SimpleNamespace(idle_add=Mock())
kit = types.ModuleType("darkos_shell.app_kit")
kit.add_class = kit.run_app = Mock()
spec = importlib.util.spec_from_file_location(
    "darkos_store_tested", Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin/darkos-store.py"
)
store = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository, "darkos_shell.app_kit": kit}):
    spec.loader.exec_module(store)


class StoreTests(unittest.TestCase):
    def test_failed_commands_are_not_empty_success(self):
        for code, stdout, stderr in ((1, "", ""), (1, "", "network failure"), (2, "", "bad option")):
            with self.subTest(code=code, stderr=stderr):
                with patch.object(store.subprocess, "run", return_value=subprocess.CompletedProcess([], code, stdout, stderr)):
                    ok, output = store.run_tool(["flatpak", "search", "anything"])
                self.assertFalse(ok)
                self.assertIn(f"exit code {code}", output)

    def test_only_explicit_empty_search_exit_is_accepted(self):
        for stdout, stderr, expected in (("", "", True), ("", "failure", False), ("partial result", "", False)):
            with patch.object(store.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout, stderr)):
                self.assertEqual(store.run_tool(["pacman", "-Ss", "query"], empty_exit_one=True)[0], expected)

    def test_spawn_and_timeout_errors(self):
        for error in (FileNotFoundError(), PermissionError("denied"), subprocess.TimeoutExpired("pacman", 8)):
            with patch.object(store.subprocess, "run", side_effect=error):
                self.assertFalse(store.run_tool(["pacman", "-Q"])[0])

    def test_aur_errors_and_invalid_shapes(self):
        for payload in ({"type": "error", "error": "Query too short"}, [], {"results": "bad"}, {"results": [1]}):
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read1.side_effect = [json.dumps(payload).encode(), b""]
            with patch.object(store.urllib.request, "urlopen", return_value=response):
                self.assertFalse(store.aur_search("x")[0])

    def test_aur_success_and_exact_response_size_boundary(self):
        payload = json.dumps({"results": [{"Name": "test-package"}]}).encode()
        with patch.object(store.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
            with patch.object(store, "AUR_RESPONSE_LIMIT", len(payload)):
                self.assertEqual(store.aur_search("test"), (True, [{"Name": "test-package"}]))

    def test_aur_oversized_response_is_stopped_before_json_parse(self):
        response = io.BytesIO(b"x" * 1000)
        with patch.object(store.urllib.request, "urlopen", return_value=response):
            with patch.object(store, "AUR_RESPONSE_LIMIT", 32), patch.object(store.json, "loads") as parse:
                ok, detail = store.aur_search("test")
        self.assertFalse(ok)
        self.assertIn("size limit", detail)
        self.assertTrue(response.closed)
        parse.assert_not_called()

    def test_aur_slow_trickle_cannot_extend_total_deadline(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read1.return_value = b" "
        # A byte arrives before each socket timeout, but the total deadline
        # still expires while the response is being received.
        with patch.object(store.urllib.request, "urlopen", return_value=response):
            with patch.object(store.time, "monotonic", side_effect=[0, 1, 2, 3, 13]):
                ok, detail = store.aur_search("test")
        self.assertFalse(ok)
        self.assertIn("time limit", detail)
        self.assertEqual(response.read1.call_count, 2)
        response.read.assert_not_called()
        response.__exit__.assert_called_once()

    def test_aur_connection_time_counts_toward_deadline(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(store.urllib.request, "urlopen", return_value=response):
            with patch.object(store.time, "monotonic", side_effect=[0, 13]):
                self.assertFalse(store.aur_search("test")[0])
        response.read1.assert_not_called()

    def test_pacman_search_preserves_option_like_query(self):
        with patch.object(store, "run_tool", return_value=(True, "extra/app 1.0\n    description\n")) as run:
            result = store.StoreWindow._search_pacman(None, "--help")
        run.assert_called_once_with(["pacman", "-Ss", "--color", "never", "--", "--help"], empty_exit_one=True)
        self.assertEqual(result, (True, [("extra/app", "extra/app")], None))

    def window(self):
        window = object.__new__(store.StoreWindow)
        window._closed = False
        window._job_tokens = {}
        window._queued_jobs = {}
        window._running_jobs = set()
        return window

    def test_refresh_queue_is_bounded_and_coalesces(self):
        window = self.window()
        with patch.object(store.threading, "Thread") as thread:
            for index in range(10):
                window._submit_job("search", Mock(name=str(index)), Mock())
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(len(window._queued_jobs), 1)
        self.assertEqual(window._queued_jobs["search"][0], 10)

    def test_stale_and_closed_results_are_ignored(self):
        window = self.window()
        window._job_tokens["search"] = 2
        apply_result = Mock()
        window._finish_job("search", 1, apply_result, True, "old")
        apply_result.assert_not_called()
        window._closed = True
        window._finish_job("search", 2, apply_result, True, "new")
        apply_result.assert_not_called()

    def test_compatibility_never_executes_proton(self):
        with patch.object(store, "run_tool", return_value=(False, "unavailable")) as run:
            with patch.object(store.shutil, "which", return_value="/opt/proton"):
                result = store.StoreWindow._collect_compatibility(None)
        self.assertIn("not executed", result[0])
        self.assertEqual([call.args[0] for call in run.call_args_list], [["wine", "--version"], ["waydroid", "status"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
