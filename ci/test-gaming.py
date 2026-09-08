#!/usr/bin/env python3
"""Headless regression checks for Gaming Hub discovery and Waydroid requests.

Only GTK imports are stubbed. The real discovery, command construction, error
handling, and callback guards run with local subprocess boundaries mocked, so
these checks work on the Windows development host without launching game apps.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch


def load_hub():
    source = Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin/darkos-gaming.py"
    gi = types.ModuleType("gi")
    gi.require_version = lambda *_args: None
    repository = types.ModuleType("gi.repository")
    repository.Gtk = types.SimpleNamespace(ApplicationWindow=object)
    repository.GLib = types.SimpleNamespace(idle_add=Mock())
    app_kit = types.ModuleType("darkos_shell.app_kit")
    app_kit.add_class = Mock()
    app_kit.run_app = Mock()
    spec = importlib.util.spec_from_file_location("darkos_gaming_tests", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "gi": gi, "gi.repository": repository,
        "darkos_shell.app_kit": app_kit, spec.name: module,
    }):
        spec.loader.exec_module(module)
    return module


hub = load_hub()


class GamingDiscoveryTests(unittest.TestCase):
    def test_steam_refresh_only_queries_package_metadata(self):
        with patch.object(hub.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"), \
                patch.object(hub, "_run_probe", return_value=(True, "steam 1.0.0.83-1")) as probe:
            status = hub._probe_launcher(hub.LAUNCHER_BY_KEY["steam"])
        self.assertTrue(status.available)
        probe.assert_called_once_with("/usr/bin/pacman", ("-Q", "steam"))

    def test_standalone_proton_is_never_executed(self):
        with patch.object(hub.shutil, "which", return_value="/opt/proton/proton"), \
                patch.object(hub, "_steam_proton_version", return_value="Proton 10"), \
                patch.object(hub, "_run_probe") as probe:
            status = hub._probe_proton()
        self.assertTrue(status.available)
        self.assertIn("Proton 10", status.summary)
        probe.assert_not_called()

    def test_bottles_flatpak_detection_provides_real_launch_command(self):
        with patch.object(hub.shutil, "which", side_effect=lambda name: "/usr/bin/flatpak" if name == "flatpak" else None), \
                patch.object(hub, "_run_probe", return_value=(True, "67.2")) as probe:
            status = hub._probe_launcher(hub.LAUNCHER_BY_KEY["bottles"])
        probe.assert_called_once_with("/usr/bin/flatpak", ("info", "--show-version", "com.usebottles.bottles"))
        self.assertTrue(status.available)
        self.assertEqual(status.executable, "/usr/bin/flatpak")
        self.assertEqual(status.launch_arguments, ("run", "com.usebottles.bottles"))

        window = types.SimpleNamespace(
            _statuses={"bottles": status}, _start_command=Mock(return_value=True),
            _summary_label=Mock(),
        )
        hub.GamingWindow._launch(window, "bottles")
        window._start_command.assert_called_once_with(
            "Bottles", "/usr/bin/flatpak", ("run", "com.usebottles.bottles"),
        )

    def test_flatpak_installed_without_bottles_stays_unavailable(self):
        with patch.object(hub.shutil, "which", side_effect=lambda name: "/usr/bin/flatpak" if name == "flatpak" else None), \
                patch.object(hub, "_run_probe", return_value=(False, "app is not installed")):
            status = hub._probe_launcher(hub.LAUNCHER_BY_KEY["bottles"])
        self.assertFalse(status.available)
        self.assertIsNone(status.executable)

    def test_native_launcher_remains_available_without_package_metadata(self):
        with patch.object(hub.shutil, "which", side_effect=lambda name: "/opt/bottles" if name == "bottles" else None), \
                patch.object(hub, "_run_probe") as probe:
            status = hub._probe_launcher(hub.LAUNCHER_BY_KEY["bottles"])
        self.assertTrue(status.available)
        self.assertEqual(status.launch_arguments, ())
        probe.assert_not_called()


class WaydroidRequestTests(unittest.TestCase):
    def test_stopped_session_gives_guidance_without_starting_it(self):
        with patch.object(hub, "_run_probe", return_value=(True, "Session: STOPPED")) as probe:
            success, output = hub._run_waydroid_action("/usr/bin/waydroid")
        self.assertFalse(success)
        self.assertIn("sudo waydroid init", output)
        self.assertIn("waydroid session start", output)
        probe.assert_called_once_with("/usr/bin/waydroid", ("status",))

    def test_status_error_does_not_start_ui(self):
        with patch.object(hub, "_run_probe", return_value=(False, "Waydroid is not initialized")) as probe:
            success, output = hub._run_waydroid_action("/usr/bin/waydroid")
        self.assertFalse(success)
        self.assertIn("not initialized", output)
        self.assertEqual(probe.call_count, 1)

    def test_running_session_opens_ui_and_preserves_diagnostics(self):
        with patch.object(hub, "_run_probe", side_effect=[
            (True, "Session: RUNNING · Container: RUNNING"), (True, "no output"),
        ]) as probe:
            success, output = hub._run_waydroid_action("/usr/bin/waydroid")
        self.assertTrue(success)
        self.assertEqual(output, "no output")
        self.assertEqual(probe.call_args.args, ("/usr/bin/waydroid", ("show-full-ui",)))

    def test_logged_failure_with_zero_exit_still_surfaces_as_failure(self):
        with patch.object(hub, "_run_probe", side_effect=[
            (True, "Session: RUNNING · Container: FROZEN"),
            (True, "[12:30:10] Failed to access IPlatform service"),
        ]):
            success, output = hub._run_waydroid_action("/usr/bin/waydroid")
        self.assertFalse(success)
        self.assertIn("Failed to access IPlatform", output)

    def test_failed_command_retains_stderr(self):
        with patch.object(hub.subprocess, "run", return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="container service unavailable",
        )):
            success, output = hub._run_probe("/usr/bin/waydroid", ("show-full-ui",))
        self.assertFalse(success)
        self.assertIn("exit code 1", output)
        self.assertIn("container service unavailable", output)

    def test_request_timeout_is_reported(self):
        with patch.object(hub.subprocess, "run", side_effect=subprocess.TimeoutExpired("waydroid", 5)):
            success, output = hub._run_probe("/usr/bin/waydroid", ("show-full-ui",))
        self.assertFalse(success)
        self.assertIn("did not respond", output)


class CallbackGuardTests(unittest.TestCase):
    def test_destroyed_window_ignores_waydroid_result(self):
        window = types.SimpleNamespace(_closed=True)
        self.assertFalse(hub.GamingWindow._finish_waydroid_action(window, False, "failure"))

    def test_stale_generation_does_not_change_ui(self):
        window = types.SimpleNamespace(_closed=False, _generation=2)
        self.assertFalse(hub.GamingWindow._apply_statuses(window, 1, {}, {}))

    def test_duplicate_waydroid_click_starts_no_new_command(self):
        window = types.SimpleNamespace(_waydroid_pending=True)
        with patch.object(hub.shutil, "which") as which:
            hub.GamingWindow._launch_action(window, "waydroid-ui")
        which.assert_not_called()

    def test_duplicate_refresh_starts_no_thread(self):
        window = types.SimpleNamespace(_closed=False, _refreshing=True)
        with patch.object(hub.threading, "Thread") as worker:
            hub.GamingWindow._start_status_refresh(window)
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
