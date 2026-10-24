#!/usr/bin/env python3
"""DarkOS core shell chrome — application entry point.

This package contains all shell logic split into focused modules:
- palette: Calm Dark colour generation and contrast checks (no GTK)
- tokens: design tokens (color, type scale, spacing, radius, motion)
- canvases: small custom widgets (ResourceRow)
- system_sampler: live system metrics from /proc and /sys
- css: GTK CSS stylesheet built from tokens
- surfaces: GTK layer-shell window surfaces (Dock, Command Center)
- platform: OS control surface (D-Bus, hyprctl, AT-SPI)

The thin wrapper at /usr/local/bin/darkos-shell.py imports this package
and hands off to DarkOSApplication.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, Gtk

from darkos_shell.surfaces import (
    DarkOSCommandCenter,
    DarkOSDockWindow,
    command_output,
    launch,
)
from darkos_shell.css import apply_css
from darkos_shell.user_settings import load_settings, settings_path


class DarkOSApplication(Gtk.Application):
    """Single-instance controller and shared shell state owner."""

    def __init__(self):
        super().__init__(
            application_id="org.darkos.Shell",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.dock = None
        self.center = None
        self.installer_visibility = None
        self.state_listeners = []
        self.current_theme = "dark"
        self.airplane_radio_state = None
        self.toggle_state = {
            "wifi": self.query_wifi(),
            "bluetooth": self.query_bluetooth(),
            "night_light": False,
            "focus": False,
            "airplane": False,
        }
        self._settings_monitor = None
        self._settings_reload_id = 0

    # ── Live settings reload ───────────────────────────────────────────

    def _watch_settings(self):
        """Re-lay out the dock when Settings changes dock_position/dock_size.

        Everything else in settings.json (accent, radius, ...) still applies
        on the next shell restart; only the dock is applied live.
        """
        try:
            gfile = Gio.File.new_for_path(settings_path())
            self._settings_monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        except GLib.Error as error:
            print(f"DarkOS: not watching settings.json: {error.message}", flush=True)
            return
        self._settings_monitor.connect("changed", self._on_settings_changed)

    def _on_settings_changed(self, _monitor, _file, _other_file, _event):
        # One save raises several events (create / rename / changes-done);
        # coalesce them into a single reload.
        if self._settings_reload_id == 0:
            self._settings_reload_id = GLib.timeout_add(150, self._reload_dock_settings)

    def _reload_dock_settings(self):
        self._settings_reload_id = 0
        if self.dock is not None:
            settings = load_settings()
            self.dock.apply_layout(settings["dock_position"], settings["dock_size"])
        return False

    # ── Static queries ─────────────────────────────────────────────────

    @staticmethod
    def query_wifi():
        value = command_output(["nmcli", "radio", "wifi"])
        return value == "enabled" if value is not None else False

    @staticmethod
    def query_bluetooth():
        value = command_output(["bluetoothctl", "show"])
        return bool(value and "Powered: yes" in value)

    @staticmethod
    def query_wwan():
        value = command_output(["nmcli", "radio", "wwan"])
        return value == "enabled" if value is not None else False

    # ── State management ───────────────────────────────────────────────

    def register_state_listener(self, listener):
        self.state_listeners.append(listener)

    def notify_state_listeners(self):
        for listener in self.state_listeners:
            try:
                listener.sync_from_application()
            except Exception:
                pass

    def do_activate(self):
        if self.dock is not None:
            return
        apply_css()
        self.dock = DarkOSDockWindow(self)
        self.center = DarkOSCommandCenter(self)
        for window in (self.dock, self.center):
            self.add_window(window)
        # The Command Center starts closed: SUPER+H, SUPER+S, the status bar's
        # control button or --toggle-command-center opens it. The dock is the
        # only always-on surface of ours (the status bar is Waybar).
        self.center.hide()

        self._watch_settings()

    # -- Command-line dispatch --------------------------------------------

    def do_command_line(self, command_line):
        import argparse

        parser = argparse.ArgumentParser(description="DarkOS Shell Controller")
        # All three open the one Command Center; the older names stay so a
        # saved keybinding or Waybar config keeps working.
        parser.add_argument("--toggle-side-panels", action="store_true")
        parser.add_argument("--toggle-command-center", action="store_true")
        parser.add_argument("--toggle-control", action="store_true")
        parser.add_argument("--lock", action="store_true")
        parser.add_argument("--installer-mode", choices=("on", "off"))
        try:
            args = parser.parse_args(command_line.get_arguments()[1:])
        except SystemExit as error:
            return int(error.code or 0)

        self.activate()
        if args.installer_mode:
            self.set_installer_mode(args.installer_mode == "on")
        if args.toggle_side_panels or args.toggle_command_center or args.toggle_control:
            self._toggle_window(self.center)
        if args.lock:
            launch(["loginctl", "lock-session"])
        return 0

    @staticmethod
    def _toggle_window(window):
        if window.is_visible():
            window.hide()
        else:
            window.show_all()

    # ── Installer mode ─────────────────────────────────────────────────

    def set_installer_mode(self, enabled):
        overlays = (self.dock, self.center)
        if enabled:
            if self.installer_visibility is None:
                self.installer_visibility = tuple(
                    window.is_visible() for window in overlays
                )
            for window in overlays:
                window.hide()
            return
        if self.installer_visibility is None:
            return
        for window, was_visible in zip(overlays, self.installer_visibility):
            if was_visible:
                window.show_all()
            else:
                window.hide()
        self.installer_visibility = None

    # ── Toggle state ───────────────────────────────────────────────────

    @staticmethod
    def _apply_night_light(enabled):
        return _night_light_apply(enabled)

    @staticmethod
    def _apply_focus(enabled):
        return _focus_apply(enabled)

    def set_toggle(self, name, enabled):
        self.toggle_state[name] = enabled
        if name in ("wifi", "bluetooth") and self.toggle_state["airplane"]:
            if self.airplane_radio_state is not None:
                self.airplane_radio_state[name] = enabled
            self.toggle_state[name] = False
            display_name = "Wi-Fi" if name == "wifi" else "Bluetooth"
            self.center.set_control_status(
                f"{display_name} will be {'enabled' if enabled else 'disabled'} "
                "when airplane mode is disabled."
            )
        elif name == "wifi":
            launch(["nmcli", "radio", "wifi", "on" if enabled else "off"])
            self.center.set_control_status(
                f"Wi-Fi {'enabled' if enabled else 'disabled'} via NetworkManager."
            )
        elif name == "bluetooth":
            launch(["bluetoothctl", "power", "on" if enabled else "off"])
            self.center.set_control_status(
                f"Bluetooth {'enabled' if enabled else 'disabled'}."
            )
        elif name == "airplane":
            if enabled:
                if self.airplane_radio_state is None:
                    self.airplane_radio_state = {
                        "wifi": self.toggle_state["wifi"],
                        "bluetooth": self.toggle_state["bluetooth"],
                        "wwan": self.query_wwan(),
                    }
                launch(["nmcli", "radio", "all", "off"])
                launch(["bluetoothctl", "power", "off"])
                self.toggle_state["wifi"] = False
                self.toggle_state["bluetooth"] = False
            else:
                radio_state = self.airplane_radio_state or {
                    "wifi": False,
                    "bluetooth": False,
                    "wwan": False,
                }
                launch(
                    ["nmcli", "radio", "wifi", "on" if radio_state["wifi"] else "off"]
                )
                launch(
                    ["nmcli", "radio", "wwan", "on" if radio_state["wwan"] else "off"]
                )
                launch(
                    [
                        "bluetoothctl",
                        "power",
                        "on" if radio_state["bluetooth"] else "off",
                    ]
                )
                self.toggle_state["wifi"] = radio_state["wifi"]
                self.toggle_state["bluetooth"] = radio_state["bluetooth"]
                self.airplane_radio_state = None
            self.center.set_control_status(
                f"Airplane mode {'enabled' if enabled else 'disabled'}."
            )
        elif name in ("night_light", "focus"):
            apply = self._apply_night_light if name == "night_light" else self._apply_focus
            message, failed = apply(enabled)
            if failed and enabled:
                self.toggle_state[name] = False  # backend missing: don't show it as on
            self.center.set_control_status(message, failed)
        self.notify_state_listeners()


NIGHT_LIGHT_KELVIN = "4000"


def _night_light_apply(enabled, which=None, run=None, popen=None):
    """Start/stop hyprsunset. Returns (message, is_error).

    hyprsunset runs as a long-lived process that holds the colour
    temperature, so on = spawn it, off = end it (the screen returns to
    neutral when it exits).
    """
    import shutil
    import subprocess
    which = which or shutil.which
    run = run or subprocess.run
    popen = popen or subprocess.Popen
    if not which("hyprsunset"):
        return ("Night Light needs hyprsunset, which is not installed.", True)
    run(["pkill", "-x", "hyprsunset"], capture_output=True)
    if enabled:
        popen(["hyprsunset", "-t", NIGHT_LIGHT_KELVIN],
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              start_new_session=True)
        return (f"Night Light on ({NIGHT_LIGHT_KELVIN} K).", False)
    return ("Night Light off.", False)


def _focus_apply(enabled, which=None, run=None):
    """Switch mako between do-not-disturb and normal. Returns (message, is_error)."""
    import shutil
    import subprocess
    which = which or shutil.which
    run = run or subprocess.run
    if not which("makoctl"):
        return ("Focus needs mako (makoctl), which is not installed.", True)
    result = run(["makoctl", "mode", "-s", "do-not-disturb" if enabled else "default"],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return ("Focus could not reach mako; is it running?", True)
    return ("Focus on: notification pop-ups are hidden." if enabled
            else "Focus off: notifications show again.", False)


def main():
    import sys

    try:
        application = DarkOSApplication()
        return application.run(sys.argv)
    except Exception as error:
        print(f"DarkOS shell fatal error: {error}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
