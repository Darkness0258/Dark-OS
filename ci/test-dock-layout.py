#!/usr/bin/env python3
"""Dock position (bottom/top/left/right) and size (compact/default/large).

Layers, cheapest first:
  * DockLayoutTests / SettingsValidationTests  pure Python (GLib only)
  * DockWindowTests / SettingsUiTests / ShellWatcherTests  real GTK widgets;
    need a display and skip without one:
        xvfb-run -a dbus-run-session -- python ci/test-dock-layout.py

What cannot be checked here -- the layer-shell anchors and exclusive zone on a
real compositor -- was verified separately against a headless wlroots
compositor (see progress-tracker.md).
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

BIN = Path(__file__).resolve().parents[1] / "airootfs/usr/local/bin"
sys.path.insert(0, str(BIN))

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gio, Gtk

    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False

if not GTK_AVAILABLE:
    # tokens/user_settings only need GLib, but importing the real package runs
    # __init__.py (which needs Gtk). Register an empty stand-in package that
    # still resolves the submodules.
    package = types.ModuleType("darkos_shell")
    package.__path__ = [str(BIN / "darkos_shell")]
    sys.modules["darkos_shell"] = package

from darkos_shell import tokens, user_settings  # noqa: E402

DEFAULTS = user_settings.DEFAULTS


class DockLayoutTests(unittest.TestCase):
    def test_every_position_and_size_resolves_to_consistent_geometry(self):
        for position in tokens.DOCK_POSITIONS:
            for size in tokens.DOCK_SIZES:
                layout = tokens.dock_layout(position, size)
                self.assertEqual((layout.position, layout.size), (position, size))
                self.assertEqual(layout.vertical, position in ("left", "right"))
                self.assertEqual(layout.button_px, tokens.DOCK_BUTTON_PX[size])
                self.assertEqual(layout.edge_margin, tokens.DOCK_EDGE_MARGIN)

    def test_there_are_exactly_four_positions_and_three_sizes(self):
        self.assertEqual(set(tokens.DOCK_POSITIONS), {"bottom", "top", "left", "right"})
        self.assertEqual(set(tokens.DOCK_SIZES), {"compact", "default", "large"})

    def test_the_default_keeps_reserving_the_legacy_108px(self):
        # The dock used to hard-code exclusive_zone=108: 14px edge margin, a
        # 75px-thick dock, 19px clearance. The default look must not move.
        layout = tokens.dock_layout("bottom", "default")
        self.assertEqual(tokens.dock_exclusive_zone(layout, 75), 108)

    def test_unknown_values_fall_back_independently(self):
        self.assertEqual(tokens.dock_layout("diagonal", 99), tokens.dock_layout("bottom", "default"))
        self.assertEqual(tokens.dock_layout(None, None), tokens.dock_layout("bottom", "default"))
        self.assertEqual(tokens.dock_layout("left", "huge").size, "default")
        self.assertEqual(tokens.dock_layout("left", "huge").position, "left")
        self.assertEqual(tokens.dock_layout("sideways", "large").position, "bottom")
        self.assertEqual(tokens.dock_layout("sideways", "large").size, "large")

    def test_labels_are_dropped_when_compact_or_vertical(self):
        self.assertTrue(tokens.dock_layout("bottom", "default").show_labels)
        self.assertTrue(tokens.dock_layout("top", "large").show_labels)
        self.assertFalse(tokens.dock_layout("bottom", "compact").show_labels)
        self.assertFalse(tokens.dock_layout("left", "default").show_labels)
        self.assertFalse(tokens.dock_layout("right", "large").show_labels)

    def test_button_size_grows_with_the_size_setting(self):
        sizes = [tokens.dock_layout("bottom", s).button_px for s in ("compact", "default", "large")]
        self.assertEqual(sizes, sorted(sizes))
        self.assertEqual(len(set(sizes)), 3)

    def test_exclusive_zone_follows_the_measured_thickness(self):
        layout = tokens.dock_layout("left", "default")
        self.assertEqual(tokens.dock_exclusive_zone(layout, 50), 50 + 14 + 19)
        self.assertEqual(tokens.dock_exclusive_zone(layout, 50.9), 50 + 14 + 19)  # int(), no float drift
        self.assertGreater(tokens.dock_exclusive_zone(layout, 80), tokens.dock_exclusive_zone(layout, 50))

    def test_settings_and_tokens_share_one_source_of_truth(self):
        self.assertIs(tokens.DOCK_POSITIONS, user_settings.CHOICES["dock_position"])
        self.assertIs(tokens.DOCK_SIZES, user_settings.CHOICES["dock_size"])
        self.assertIn(DEFAULTS["dock_position"], user_settings.CHOICES["dock_position"])
        self.assertIn(DEFAULTS["dock_size"], user_settings.CHOICES["dock_size"])
        default = tokens.dock_layout(DEFAULTS["dock_position"], DEFAULTS["dock_size"])
        self.assertEqual((default.position, default.size), ("bottom", "default"))


class SettingsValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "settings.json")
        patcher = patch.object(user_settings, "settings_path", lambda: self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_raw(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_missing_file_gives_the_defaults(self):
        loaded = user_settings.load_settings()
        self.assertEqual((loaded["dock_position"], loaded["dock_size"]), ("bottom", "default"))

    def test_valid_choices_round_trip(self):
        data = dict(DEFAULTS, dock_position="right", dock_size="large")
        self.assertTrue(user_settings.save_settings(data))
        loaded = user_settings.load_settings()
        self.assertEqual((loaded["dock_position"], loaded["dock_size"]), ("right", "large"))

    def test_invalid_choices_fall_back_without_touching_other_settings(self):
        other = next(k for k, v in DEFAULTS.items() if isinstance(v, bool))
        self.write_raw(json.dumps({"dock_position": "diagonal", "dock_size": 99, other: not DEFAULTS[other]}))
        loaded = user_settings.load_settings()
        self.assertEqual((loaded["dock_position"], loaded["dock_size"]), ("bottom", "default"))
        self.assertEqual(loaded[other], not DEFAULTS[other])

    def test_one_bad_choice_does_not_discard_the_other(self):
        self.write_raw(json.dumps({"dock_position": "left", "dock_size": "enormous"}))
        loaded = user_settings.load_settings()
        self.assertEqual((loaded["dock_position"], loaded["dock_size"]), ("left", "default"))

    def test_corrupt_json_gives_the_defaults(self):
        self.write_raw("{ this is not json")
        self.assertEqual(user_settings.load_settings()["dock_position"], "bottom")

    def test_unhashable_garbage_does_not_crash_validation(self):
        self.write_raw(json.dumps({"dock_position": ["left"], "dock_size": {"a": 1}}))
        loaded = user_settings.load_settings()
        self.assertEqual((loaded["dock_position"], loaded["dock_size"]), ("bottom", "default"))

    def test_save_is_atomic_and_leaves_no_temp_files(self):
        self.assertTrue(user_settings.save_settings(dict(DEFAULTS, dock_position="top")))
        self.assertEqual(os.listdir(self.tmp.name), ["settings.json"])

    def test_failed_save_keeps_the_old_file_and_cleans_up(self):
        user_settings.save_settings(dict(DEFAULTS, dock_position="left"))
        with patch.object(user_settings.os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(user_settings.save_settings(dict(DEFAULTS, dock_position="right")))
        self.assertEqual(user_settings.load_settings()["dock_position"], "left")
        self.assertEqual(os.listdir(self.tmp.name), ["settings.json"])

    def test_save_still_ignores_unknown_keys(self):
        user_settings.save_settings({"dock_position": "top", "not_a_setting": 1})
        with open(self.path, encoding="utf-8") as handle:
            self.assertNotIn("not_a_setting", json.load(handle))


def settle():
    while Gtk.events_pending():
        Gtk.main_iteration()


def descendants(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from descendants(child)


@unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
class DockWindowTests(unittest.TestCase):
    def make_dock(self, **saved):
        from darkos_shell import surfaces

        settings = dict(DEFAULTS, **saved)
        # gtk-layer-shell only works on Wayland; on the X11 display CI uses it
        # logs a CRITICAL for every call. A recording stand-in keeps the log
        # clean and lets the tests assert exactly what the dock asks for.
        self.layer_shell = Mock(name="GtkLayerShell")
        for target, value in (("load_settings", Mock(return_value=settings)),
                              ("GtkLayerShell", self.layer_shell)):
            patcher = patch.object(surfaces, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        dock = surfaces.DarkOSDockWindow(Mock())
        self.addCleanup(dock.destroy)
        settle()
        return dock

    def last_values(self, setter):
        """edge -> the last value the dock set through layer-shell."""
        state = {}
        for call in getattr(self.layer_shell, setter).call_args_list:
            _window, edge, value = call.args
            state[edge] = value
        return state

    @staticmethod
    def classes(dock):
        return set(dock._dock_box.get_style_context().list_classes())

    def assert_geometry(self, dock, position, size):
        layout = tokens.dock_layout(position, size)
        self.assertEqual((dock._layout.position, dock._layout.size), (position, size))
        want = Gtk.Orientation.VERTICAL if layout.vertical else Gtk.Orientation.HORIZONTAL
        self.assertEqual(dock._dock_box.get_orientation(), want)
        classes = self.classes(dock)
        self.assertEqual("vertical" in classes, layout.vertical)
        self.assertEqual("compact" in classes, size == "compact")
        self.assertTrue(dock._dock_icons)
        for key, button in dock._dock_icons.items():
            self.assertEqual(button.get_size_request(), (layout.button_px, layout.button_px), key)
            self.assertEqual(dock._dock_images[key].get_pixel_size(), layout.button_px // 2, key)
            self.assertEqual(dock._dock_labels[key].get_visible(), layout.show_labels, key)

    def test_starts_bottom_default(self):
        self.assert_geometry(self.make_dock(), "bottom", "default")

    def test_construction_honours_saved_settings(self):
        self.assert_geometry(self.make_dock(dock_position="left", dock_size="large"), "left", "large")

    def test_construction_survives_invalid_saved_settings(self):
        self.assert_geometry(self.make_dock(dock_position="diagonal", dock_size=99), "bottom", "default")

    def test_every_position_and_size_lays_out_correctly_live(self):
        dock = self.make_dock()
        for position in tokens.DOCK_POSITIONS:
            for size in tokens.DOCK_SIZES:
                dock.apply_layout(position, size)
                settle()
                self.assert_geometry(dock, position, size)

    def test_apply_layout_reports_whether_anything_changed(self):
        dock = self.make_dock()
        self.assertFalse(dock.apply_layout("bottom", "default"))
        self.assertTrue(dock.apply_layout("top", "default"))
        self.assertFalse(dock.apply_layout("top", "default"))
        self.assertFalse(dock.apply_layout("top", "default"))
        self.assertTrue(dock.apply_layout("top", "large"))

    def test_invalid_values_fall_back_to_the_default_layout(self):
        dock = self.make_dock(dock_position="left", dock_size="large")
        self.assertTrue(dock.apply_layout("nonsense", "nonsense"))
        self.assert_geometry(dock, "bottom", "default")

    def test_going_back_to_default_restores_everything(self):
        dock = self.make_dock()
        dock.apply_layout("left", "compact")
        dock.apply_layout("bottom", "default")
        settle()
        self.assert_geometry(dock, "bottom", "default")
        self.assertNotIn("vertical", self.classes(dock))
        self.assertNotIn("compact", self.classes(dock))

    def test_dock_has_a_launcher_first_and_no_clock(self):
        """One launcher, then the pinned apps; the clock lives in the status
        bar (a second clock in the dock was the old design's duplicate)."""
        dock = self.make_dock()
        self.assertFalse(hasattr(dock, "clock_label"))
        self.assertEqual(
            list(dock._dock_icons),
            ["launcher", "files", "terminal", "browser", "notes", "store", "settings"],
        )
        launcher = dock._dock_icons["launcher"]
        self.assertEqual(launcher.get_tooltip_text(), "Apps")
        # The separator follows the launcher on every edge.
        for position in ("bottom", "left"):
            dock.apply_layout(position, "default")
            self.assertTrue(dock._dock_separator.get_visible())

    def test_every_icon_keeps_a_tooltip_and_accessible_name_when_labels_are_hidden(self):
        for saved in ({"dock_position": "left"}, {"dock_size": "compact"}):
            dock = self.make_dock(**saved)
            self.assertFalse(dock._layout.show_labels)
            for key, button in dock._dock_icons.items():
                self.assertTrue(button.get_tooltip_text(), f"{key} has no tooltip with its label hidden")
                self.assertTrue(button.get_accessible().get_name(), f"{key} has no accessible name")

    def test_layer_shell_anchor_and_margin_follow_the_position(self):
        dock = self.make_dock()
        edges = dock._EDGES
        self.assertEqual(set(edges), {"bottom", "top", "left", "right"})
        for position, edge in edges.items():
            dock.apply_layout(position, "default")
            anchored = {e for e, flag in self.last_values("set_anchor").items() if flag}
            self.assertEqual(anchored, {edge}, f"{position}: anchored to the wrong edge(s)")
            margins = self.last_values("set_margin")
            self.assertEqual(margins[edge], 14, position)
            for other in edges.values():
                if other != edge:
                    self.assertEqual(margins[other], 0, f"{position}: stale margin left on another edge")

    def test_the_dock_is_a_top_layer_surface_with_its_hyprland_namespace(self):
        dock = self.make_dock()
        # Hyprland layer rules (blur, ignorealpha) match on this namespace.
        self.layer_shell.set_namespace.assert_called_with(dock, "darkos-dock")
        self.layer_shell.set_layer.assert_called_with(dock, self.layer_shell.Layer.TOP)

    def test_exclusive_zone_is_pushed_to_layer_shell_only_when_it_changes(self):
        dock = self.make_dock()
        self.layer_shell.set_exclusive_zone.reset_mock()
        dock._exclusive_zone = None
        dock._update_exclusive_zone(Mock(width=72, height=75))
        dock._update_exclusive_zone(Mock(width=72, height=75))
        self.layer_shell.set_exclusive_zone.assert_called_once_with(dock, 108)

    def test_exclusive_zone_follows_the_allocated_thickness(self):
        dock = self.make_dock()
        allocation = Mock(width=72, height=75)
        dock._exclusive_zone = None
        dock._update_exclusive_zone(allocation)
        self.assertEqual(dock._exclusive_zone, 14 + 75 + 19)  # horizontal -> height
        dock.apply_layout("left", "default")
        dock._update_exclusive_zone(Mock(width=50, height=420))
        self.assertEqual(dock._exclusive_zone, 14 + 50 + 19)  # vertical -> width
        dock._update_exclusive_zone(Mock(width=1, height=1))  # not allocated yet: keep the last value
        self.assertEqual(dock._exclusive_zone, 14 + 50 + 19)


@unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
class SettingsUiTests(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        # Only the first Gtk.Application registered in a process can become
        # primary on a session bus, so every test shares one.
        cls.app = Gtk.Application(application_id="test.darkos.dock.ci", flags=Gio.ApplicationFlags.NON_UNIQUE)
        assert cls.app.register(None)
        spec = importlib.util.spec_from_file_location("darkos_settings_under_test", BIN / "darkos-settings.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "settings.json")
        patcher = patch.object(user_settings, "settings_path", lambda: self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def designer_radios(self, **saved):
        if saved:
            user_settings.save_settings(dict(DEFAULTS, **saved))
        window = self.module.SettingsWindow(self.app)
        self.addCleanup(window.destroy)
        page = window.stack.get_child_by_name("designer")
        self.assertIsNotNone(page, "Settings has no Designer page")
        return {w.get_label(): w for w in descendants(page) if isinstance(w, Gtk.RadioButton)}

    def saved(self):
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_designer_tab_offers_every_dock_choice(self):
        radios = self.designer_radios()
        for label in ("Bottom", "Top", "Left", "Right", "Compact", "Default", "Large"):
            self.assertIn(label, radios)
        self.assertEqual(len(radios), 7)

    def test_radios_reflect_the_saved_settings_without_writing_anything(self):
        radios = self.designer_radios(dock_position="right", dock_size="large")
        self.assertTrue(radios["Right"].get_active())
        self.assertTrue(radios["Large"].get_active())
        self.assertFalse(radios["Bottom"].get_active())
        self.assertFalse(radios["Default"].get_active())

    def test_building_the_window_does_not_save_by_itself(self):
        self.designer_radios()
        self.assertFalse(os.path.exists(self.path))

    def test_choosing_a_position_writes_only_that_setting(self):
        radios = self.designer_radios()
        radios["Left"].set_active(True)
        self.assertEqual(self.saved()["dock_position"], "left")
        self.assertEqual(self.saved()["dock_size"], "default")

    def test_choosing_a_size_keeps_the_position(self):
        radios = self.designer_radios(dock_position="top")
        radios["Compact"].set_active(True)
        saved = self.saved()
        self.assertEqual((saved["dock_position"], saved["dock_size"]), ("top", "compact"))

    def test_every_choice_the_ui_offers_is_one_the_shell_accepts(self):
        for position in user_settings.CHOICES["dock_position"]:
            self.assertEqual(tokens.dock_layout(position, "default").position, position)
        for size in user_settings.CHOICES["dock_size"]:
            self.assertEqual(tokens.dock_layout("bottom", size).size, size)


@unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
class ShellWatcherTests(unittest.TestCase):
    """The shell re-lays the dock out when Settings rewrites settings.json."""

    @staticmethod
    def fake_shell(dock):
        shell = types.SimpleNamespace(dock=dock, _settings_reload_id=0)
        shell._reload_dock_settings = Mock()
        return shell

    def test_reload_applies_the_saved_dock_settings(self):
        import darkos_shell

        dock = Mock()
        shell = self.fake_shell(dock)
        shell._settings_reload_id = 42
        saved = dict(DEFAULTS, dock_position="right", dock_size="large")
        with patch.object(darkos_shell, "load_settings", return_value=saved):
            keep_going = darkos_shell.DarkOSApplication._reload_dock_settings(shell)
        dock.apply_layout.assert_called_once_with("right", "large")
        self.assertFalse(keep_going)  # one-shot GLib timeout
        self.assertEqual(shell._settings_reload_id, 0)

    def test_reload_before_the_dock_exists_is_harmless(self):
        import darkos_shell

        shell = self.fake_shell(None)
        with patch.object(darkos_shell, "load_settings", return_value=dict(DEFAULTS)):
            self.assertFalse(darkos_shell.DarkOSApplication._reload_dock_settings(shell))

    def test_a_burst_of_file_events_is_coalesced_into_one_reload(self):
        import darkos_shell

        shell = self.fake_shell(Mock())
        with patch.object(darkos_shell.GLib, "timeout_add", return_value=77) as timeout_add:
            for _event in ("deleted", "created", "changes-done-hint"):
                darkos_shell.DarkOSApplication._on_settings_changed(shell, None, None, None, _event)
        timeout_add.assert_called_once()
        self.assertEqual(timeout_add.call_args.args[0], 150)
        self.assertEqual(shell._settings_reload_id, 77)

    def test_the_shell_actually_installs_the_watcher_on_activation(self):
        import inspect

        import darkos_shell

        source = inspect.getsource(darkos_shell.DarkOSApplication.do_activate)
        self.assertIn("self._watch_settings()", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
