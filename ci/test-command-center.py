#!/usr/bin/env python3
"""Command Center: the single panel that replaced the rail, the weather
panel and the ring gauges.

    xvfb-run -a dbus-run-session -- python ci/test-command-center.py

Backends (makoctl, pamixer, brightnessctl, playerctl) are faked; the
notification parser is also run on real `makoctl list` / `makoctl history`
output saved in ci/fixtures/. gtk-layer-shell is replaced by a recording
stand-in because it only works on Wayland.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "airootfs/usr/local/bin"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(BIN))

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, Gtk

    GTK_AVAILABLE = Gtk.init_check()[0]
except (ImportError, ValueError):
    GTK_AVAILABLE = False


def settle():
    while Gtk.events_pending():
        Gtk.main_iteration()


class FakeApplication:
    toggle_state = {
        "wifi": True, "bluetooth": False, "night_light": False,
        "focus": False, "airplane": False,
    }

    def __init__(self):
        self.calls = []

    def register_state_listener(self, listener):
        self.listener = listener

    def set_toggle(self, name, value):
        self.calls.append((name, value))
        self.toggle_state[name] = value


MAKO_LIST = (FIXTURES / "makoctl-list.json").read_text(encoding="utf-8")
MAKO_HISTORY = (FIXTURES / "makoctl-history.json").read_text(encoding="utf-8")


@unittest.skipUnless(GTK_AVAILABLE, "GTK not available")
class CommandCenterTests(unittest.TestCase):
    def make(self, command_output=None, auto_refresh=False):
        """Build a Command Center on faked backends. Opening the panel starts
        background refreshes; they are switched off by default so a worker
        thread can't race the assertions (auto_refresh=True lets them run)."""
        from darkos_shell import surfaces

        self.surfaces = surfaces
        if not auto_refresh:
            for name in ("refresh_levels", "refresh_notifications", "refresh_media"):
                patcher = patch.object(surfaces.DarkOSCommandCenter, name, Mock(return_value=True))
                patcher.start()
                self.addCleanup(patcher.stop)
        self.launch = Mock(return_value=True)
        for target, value in (
            ("GtkLayerShell", Mock(name="GtkLayerShell")),
            ("launch", self.launch),
            ("command_output", command_output or Mock(return_value=None)),
        ):
            patcher = patch.object(surfaces, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Deliver worker-thread results immediately, on this thread.
        idle = patch.object(surfaces.GLib, "idle_add", lambda func, *args: func(*args) and None)
        idle.start()
        self.addCleanup(idle.stop)
        self.app = FakeApplication()
        self.center = surfaces.DarkOSCommandCenter(self.app)
        self.addCleanup(self.center.destroy)
        return self.center

    # -- Controls ------------------------------------------------------

    def test_only_toggles_with_a_real_backend_exist(self):
        center = self.make()
        self.assertEqual(
            list(center.toggle_buttons),
            ["wifi", "bluetooth", "night_light", "focus", "airplane"],
        )
        for button in center.toggle_buttons.values():
            self.assertTrue(button.get_accessible().get_name())

    def test_toggling_calls_the_application_but_syncing_does_not(self):
        center = self.make()
        self.assertTrue(center.toggle_buttons["wifi"].get_active())
        self.assertEqual(self.app.calls, [], "building the panel must not flip anything")
        center.toggle_buttons["focus"].set_active(True)
        self.assertEqual(self.app.calls, [("focus", True)])

    def test_airplane_mode_disables_wifi_and_bluetooth_buttons(self):
        center = self.make()
        self.app.toggle_state["airplane"] = True
        center.sync_from_application()
        self.assertFalse(center.toggle_buttons["wifi"].get_sensitive())
        self.assertFalse(center.toggle_buttons["bluetooth"].get_sensitive())
        self.assertTrue(center.toggle_buttons["night_light"].get_sensitive())

    def test_sliders_are_hidden_when_no_backend_answers(self):
        center = self.make()
        center._apply_levels(None, None)
        self.assertFalse(center.volume_row.get_visible())
        self.assertFalse(center.brightness_row.get_visible())

    def test_sliders_show_the_real_values_without_applying_them(self):
        center = self.make()
        center._apply_levels("62", "intel_backlight,backlight,3000,45%,4800")
        self.assertTrue(center.volume_row.get_visible())
        self.assertEqual(center.volume_scale.get_value(), 62)
        self.assertEqual(center.brightness_scale.get_value(), 45)
        self.assertEqual(center._pending_levels, {}, "reading must not write back")
        self.launch.assert_not_called()

    def test_dragging_a_slider_sends_one_command_with_the_final_value(self):
        center = self.make()
        for value in (30, 40, 55):
            center.volume_scale.set_value(value)
        center._flush_levels()
        self.launch.assert_called_once_with(["pamixer", "--set-volume", "55"])

    def test_a_failed_backlight_write_is_reported_not_swallowed(self):
        center = self.make()
        self.launch.return_value = False
        center.brightness_scale.set_value(60)
        center._flush_levels()
        self.assertIn("Brightness", center.control_status.get_text())

    # -- Notifications -------------------------------------------------

    def test_real_mako_output_parses(self):
        parse = __import__("darkos_shell.surfaces", fromlist=["x"]).parse_mako_notifications
        listed = parse(MAKO_LIST)
        history = parse(MAKO_HISTORY)
        self.assertEqual({n["summary"] for n in listed}, {"New message", "Updates ready"})
        self.assertEqual({n["app"] for n in history}, {"Mail", "Updater"})
        self.assertTrue(all(n["id"] > 0 for n in history))
        self.assertEqual(len({n["id"] for n in history}), 2, "ids are distinct")

    def test_garbage_from_makoctl_gives_an_empty_list_not_a_crash(self):
        parse = __import__("darkos_shell.surfaces", fromlist=["x"]).parse_mako_notifications
        for text in ("", "nope", "{}", '{"data": 5}', '{"data": [[1, "x", null]]}', None):
            self.assertEqual(parse(text), [], repr(text))

    def test_the_panel_lists_active_then_history_newest_first_without_duplicates(self):
        def fake(command, timeout=1.5):
            return {"list": MAKO_LIST, "history": MAKO_HISTORY}.get(command[1])

        center = self.make(Mock(side_effect=fake))
        center._notification_lock.acquire()  # refresh_notifications() takes it
        center._fetch_notifications()
        settle()
        cards = center.notification_list.get_children()
        self.assertEqual(len(cards), 2, "two notifications, each listed once")
        self.assertFalse(center.notification_empty.get_visible())

    def test_at_most_five_cards(self):
        center = self.make()
        entries = [{"id": i, "app": "A", "summary": f"n{i}", "body": ""} for i in range(1, 12)]
        center._apply_notifications(entries, True)
        self.assertEqual(len(center.notification_list.get_children()), center.MAX_NOTIFICATIONS)

    def test_clear_all_dismisses_and_hides_old_ones_but_shows_new_ones(self):
        center = self.make()
        old = [{"id": 1, "app": "Mail", "summary": "a", "body": ""},
               {"id": 2, "app": "Mail", "summary": "b", "body": ""}]
        center._apply_notifications(old, True)
        center.clear_notifications(None)
        self.launch.assert_called_with(["makoctl", "dismiss", "--all"])
        self.assertEqual(center.notification_list.get_children(), [])
        self.assertTrue(center.notification_empty.get_visible())
        center._apply_notifications(old + [{"id": 3, "app": "Mail", "summary": "c", "body": ""}], True)
        self.assertEqual(len(center.notification_list.get_children()), 1)

    def test_a_missing_mako_says_so_instead_of_claiming_all_is_well(self):
        center = self.make()
        center._apply_notifications([], False)
        self.assertIn("aren't available", center.notification_empty.get_text())

    # -- Media ---------------------------------------------------------

    def test_the_media_section_only_exists_while_a_player_does(self):
        center = self.make()
        center._apply_media(None, None)
        self.assertFalse(center.media_section.get_visible())
        center._apply_media("Blue in Green\tMiles Davis", "Playing")
        self.assertTrue(center.media_section.get_visible())
        self.assertEqual(center.media_title.get_text(), "Blue in Green")
        self.assertEqual(center.media_artist.get_text(), "Miles Davis")
        center._apply_media(None, None)
        self.assertFalse(center.media_section.get_visible())

    # -- Resources -----------------------------------------------------

    def test_the_gpu_row_only_exists_when_there_is_a_gpu(self):
        center = self.make()
        center.sampler = Mock(
            cpu_percent=Mock(return_value=10), memory_percent=Mock(return_value=20),
            storage_percent=Mock(return_value=30), gpu_percent=Mock(return_value=None),
            network_rates=Mock(return_value=(2048, 512)),
        )
        center.show()
        settle()
        center.refresh_system()
        self.assertFalse(center.resource_rows["gpu"].get_visible())
        self.assertEqual(center.resource_rows["cpu"].value.get_text(), "10%")
        self.assertIn("2 KiB/s", center.network_label.get_text())
        center.sampler.gpu_percent.return_value = 40
        center.refresh_system()
        self.assertTrue(center.resource_rows["gpu"].get_visible())

    def test_bars_turn_amber_then_red_only_when_it_matters(self):
        from darkos_shell.canvases import ResourceRow

        row = ResourceRow("CPU")
        classes = lambda: {c for c in ("warn", "crit") if row.bar.get_style_context().has_class(c)}
        row.set_percent(50)
        self.assertEqual(classes(), set())
        row.set_percent(90)
        self.assertEqual(classes(), {"warn"})
        row.set_percent(97)
        self.assertEqual(classes(), {"crit"})
        row.set_percent(10)
        self.assertEqual(classes(), set())
        row.set_percent(250)
        self.assertEqual(row.value.get_text(), "100%")

    # -- Lifecycle and sizing ------------------------------------------

    def test_timers_run_only_while_the_panel_is_open(self):
        center = self.make(auto_refresh=True)
        center.hide()
        settle()
        self.assertEqual(center._timers, [])
        center.show()
        settle()
        self.assertEqual(len(center._timers), 3)
        center.hide()
        settle()
        self.assertEqual(center._timers, [], "nothing may keep running while hidden")

    def test_escape_closes_the_panel(self):
        center = self.make()
        center.show()
        settle()
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Escape
        center._on_key(center, event)
        self.assertFalse(center.get_visible())

    def test_the_panel_is_as_tall_as_its_content_not_a_sliver(self):
        """Regression: a layer-shell window is sized to its minimum request,
        and the scroller's minimum is ~12px, so the panel was drawn as a thin
        bar. It must follow its content's natural height."""
        center = self.make()
        center.show()
        settle()
        center._fit_height()
        settle()
        _minimum, natural = center._content.get_preferred_height_for_width(center.WIDTH)
        shown = center.scroller.get_min_content_height()
        self.assertGreater(shown, 300)
        self.assertEqual(shown, min(natural, center._max_panel_height()))

    def test_a_tiny_screen_scrolls_instead_of_growing_off_screen(self):
        center = self.make()
        with patch.object(center, "_max_panel_height", return_value=400):
            center._fit_height()
        self.assertLessEqual(center.scroller.get_min_content_height(), 400)


if __name__ == "__main__":
    unittest.main(verbosity=1)
