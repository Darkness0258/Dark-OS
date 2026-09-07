#!/usr/bin/env python3
"""Mock power-profile calls; never changes the development host's profile."""
import importlib.util
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
repository.Gdk = repository.GdkPixbuf = repository.GLib = Mock()
kit = types.ModuleType("darkos_shell.app_kit")
kit.add_class = kit.run_app = Mock()
preferences = types.ModuleType("darkos_shell.user_settings")
preferences.load_settings = preferences.save_settings = Mock()
spec = importlib.util.spec_from_file_location("darkos_settings_tested", Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin/darkos-settings.py")
settings = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository, "darkos_shell.app_kit": kit, "darkos_shell.user_settings": preferences, spec.name: settings}):
    spec.loader.exec_module(settings)

BEFORE = settings.PowerProfileState(("balanced", "power-saver"), "balanced", "details")
AFTER = settings.PowerProfileState(BEFORE.supported, "power-saver", "details")


class PerformanceTests(unittest.TestCase):
    def test_only_available_profiles_are_offered(self):
        with patch.object(settings, "_powerprofiles_command", side_effect=["* balanced:\n  Driver: placeholder\n  power-saver:\n", "balanced"]):
            result = settings.query_power_profiles()
        self.assertEqual(result.supported, ("balanced", "power-saver"))

    def test_invalid_response_fails_closed(self):
        for outputs in (["unexpected output"], ["balanced:\n", "performance"]):
            with patch.object(settings, "_powerprofiles_command", side_effect=outputs):
                with self.assertRaises(settings.PowerProfileError):
                    settings.query_power_profiles()

    def test_unsupported_profile_never_reaches_set(self):
        with patch.object(settings, "query_power_profiles", return_value=BEFORE):
            with patch.object(settings, "_powerprofiles_command") as command:
                for name in ("performance", "--help", None, 1):
                    self.assertFalse(settings.set_power_profile(name).success)
            command.assert_not_called()

    def test_success_requires_readback(self):
        with patch.object(settings, "query_power_profiles", side_effect=[BEFORE, AFTER]):
            with patch.object(settings, "_powerprofiles_command", return_value="") as command:
                self.assertTrue(settings.set_power_profile("power-saver").success)
        command.assert_called_once_with(("set", "power-saver"), timeout=settings.POWER_PROFILE_SET_TIMEOUT)

    def test_refusal_and_mismatching_readback_are_not_success(self):
        for error in (None, settings.PowerProfileError("authorization denied")):
            with patch.object(settings, "query_power_profiles", side_effect=[BEFORE, BEFORE]):
                with patch.object(settings, "_powerprofiles_command", side_effect=error, return_value=""):
                    self.assertFalse(settings.set_power_profile("power-saver").success)

    def test_command_keeps_user_authorization_and_errors(self):
        with patch.object(settings.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "permission denied")) as run:
            with self.assertRaisesRegex(settings.PowerProfileError, "permission denied"):
                settings._powerprofiles_command(("set", "balanced"))
        self.assertEqual(run.call_args.args[0], ["powerprofilesctl", "set", "balanced"])
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_closed_callback_does_not_touch_widgets(self):
        window = types.SimpleNamespace(_closed=True, _power_profile_generation=1)
        self.assertFalse(settings.SettingsWindow._apply_power_profile_result(window, 1, Mock()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
