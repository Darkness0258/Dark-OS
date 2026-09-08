#!/usr/bin/env python3
"""Verify hub activation and explicit file-app multi-instance flags."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class Application:
    latest = None

    def __init__(self, **kwargs):
        self.flags = kwargs["flags"]
        self.windows = []
        Application.latest = self

    def connect(self, _event, callback):
        self.activate = callback

    def get_active_window(self):
        return None  # A hub may be unfocused when the user launches it again.

    def get_windows(self):
        return self.windows

    def run(self, _argv):
        self.activate(self)
        self.activate(self)


gi = types.ModuleType("gi")
gi.require_version = lambda *_: None
repository = types.ModuleType("gi.repository")
repository.Gtk = types.SimpleNamespace(Application=Application, IconSize=types.SimpleNamespace(LARGE_TOOLBAR=0))
repository.GLib = types.SimpleNamespace(set_prgname=Mock())
repository.Gio = types.SimpleNamespace(ApplicationFlags=types.SimpleNamespace(DEFAULT_FLAGS=0, NON_UNIQUE=1))
css = types.ModuleType("darkos_shell.css")
css.apply_css = Mock()
spec = importlib.util.spec_from_file_location("darkos_app_kit_tested", Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin/darkos_shell/app_kit.py")
kit = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository, "darkos_shell.css": css}):
    spec.loader.exec_module(kit)


class AppKitTests(unittest.TestCase):
    def builder(self, app):
        window = Mock()
        app.windows.append(window)
        return window

    def test_hub_reactivation_presents_existing_unfocused_window(self):
        build = Mock(side_effect=self.builder)
        kit.run_app("org.darkos.Test", "test", build)
        self.assertEqual(Application.latest.flags, 0)
        build.assert_called_once()
        Application.latest.windows[0].present.assert_called_once()

    def test_file_argument_apps_explicitly_opt_into_separate_processes(self):
        kit.run_app("org.darkos.Test", "test", self.builder, multiple_instances=True)
        self.assertEqual(Application.latest.flags, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
