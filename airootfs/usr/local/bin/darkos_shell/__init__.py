#!/usr/bin/env python3
"""DarkOS core shell chrome — application entry point.

This package contains all shell logic split into focused modules:
- tokens: design tokens (color, spacing, radius, glow)
- canvases: GTK DrawingArea widgets (AI Orb, waveform, ring gauges)
- system_sampler: live system metrics from /proc and /sys
- css: GTK CSS stylesheet built from tokens
- surfaces: GTK layer-shell window surfaces (Dock, HUD, Rail, Left, Right)
- platform: OS control surface (D-Bus, hyprctl, AT-SPI)
- ai_brain: STT + LLM + TTS with cloud-first, local fallback
- activity_detector: AT-SPI context-aware shell layout
- assistant_trigger: push-to-talk / wake-word activation

The thin wrapper at /usr/local/bin/darkos-shell.py imports this package
and hands off to DarkOSApplication.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, Gtk

from darkos_shell.surfaces import (
    DarkOSDockWindow,
    DarkOSHUDOverlay,
    DarkOSIconRail,
    DarkOSLeftPanels,
    DarkOSRightPanels,
    add_class,
    command_output,
    configure_layer_window,
    launch,
    make_icon_button,
    make_icon_label,
    make_label,
)
from darkos_shell.canvases import AIOrbCanvas, RingGauge, WaveformCanvas
from darkos_shell.system_sampler import SystemSampler
from darkos_shell.css import apply_css
from darkos_shell.actions import ActionDispatcher
from darkos_shell.tokens import (
    CAIRO_ACCENT,
    CAIRO_DANGER,
    CAIRO_MUTED,
    CAIRO_PRIMARY,
    CAIRO_SECONDARY,
    CAIRO_TEXT,
    COLOR_ACCENT,
    COLOR_BG_ALT,
    COLOR_BG_ELEVATED,
    COLOR_DANGER,
    COLOR_PRIMARY,
    COLOR_SECONDARY,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
    GLOW_STROKES_OUTSIDE_IN,
    RADIUS_CONTROL,
    RADIUS_DIALOG,
    RADIUS_PANEL,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
)


class DarkOSApplication(Gtk.Application):
    """Single-instance controller and shared shell state owner."""

    def __init__(self):
        super().__init__(
            application_id="org.darkos.Shell",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.dock = None
        self.rail = None
        self.hud = None
        self.left = None
        self.right = None
        self.installer_visibility = None
        self.state_listeners = []
        self.current_theme = "dark"
        self.airplane_radio_state = None
        self.toggle_state = {
            "wifi": self.query_wifi(),
            "bluetooth": self.query_bluetooth(),
            "dark_mode": True,
            "night_light": False,
            "focus": False,
            "airplane": False,
        }
        self._brain = None
        self._trigger = None
        self._activity_detector = None
        self._orb_state = "sleeping"
        self._actions = None
        self._ai_response_label = None

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

    def set_orb_state(self, state):
        self._orb_state = state

    @property
    def orb_state(self):
        return self._orb_state

    @property
    def actions(self):
        if self._actions is None:
            self._actions = ActionDispatcher()
        return self._actions

    @property
    def brain(self):
        if self._brain is None:
            from darkos_shell.ai_brain import AIBrain
            self._brain = AIBrain(actions=self.actions)
        return self._brain

    @property
    def activity_detector(self):
        if self._activity_detector is None:
            from darkos_shell.activity_detector import ActivityDetector
            self._activity_detector = ActivityDetector()
        return self._activity_detector

    @property
    def trigger(self):
        if self._trigger is None:
            from darkos_shell.assistant_trigger import AssistantTrigger
            self._trigger = AssistantTrigger(self.brain)
        return self._trigger

    # ── Activation ─────────────────────────────────────────────────────

    def do_activate(self):
        if self.dock is not None:
            return
        apply_css()
        self.dock = DarkOSDockWindow(self)
        self.rail = DarkOSIconRail(self)
        self.hud = DarkOSHUDOverlay()
        self.left = DarkOSLeftPanels(self)
        self.right = DarkOSRightPanels(self)
        for window in (self.dock, self.rail, self.hud, self.left, self.right):
            self.add_window(window)
        # Command Center (HUD + info panels) starts closed — SUPER+H or
        # --toggle-command-center opens it. Dock + rail are the always-on
        # base layer. See ui-rules.md § Layout (2026-08-23 decision).
        for window in (self.hud, self.left, self.right):
            window.hide()

        # Start activity detection → layout adaptation
        detector = self.activity_detector
        detector.add_listener(self._on_activity_changed)
        detector.start()

        # Start voice trigger (push-to-talk by default)
        trigger = self.trigger
        trigger.add_listener(self._on_voice_activated)
        trigger.start()

    # ── Activity detection → layout ─────────────────────────────────────

    def _on_activity_changed(self, profile_name, profile_data):
        """Swap dock highlight and panel visibility per activity profile."""
        if self.dock is None:
            return
        self.dock.set_activity_profile(profile_data.get("dock_highlight"))
        if self.left is not None:
            visible = profile_data.get("show_chat", True)
            if visible and not self.left.is_visible():
                self.left.show_all()
            elif not visible and self.left.is_visible():
                self.left.hide()
        if self.right is not None:
            visible = profile_data.get("show_system", True)
            if visible and not self.right.is_visible():
                self.right.show_all()
            elif not visible and self.right.is_visible():
                self.right.hide()

    # ── Voice activation → brain pipeline ───────────────────────────────

    def _on_voice_activated(self, audio_path):
        """Dispatch the full voice pipeline on a background thread."""
        import threading
        threading.Thread(
            target=self._voice_pipeline, args=(audio_path,), daemon=True
        ).start()

    def _voice_pipeline(self, audio_path):
        """Background thread: STT → LLM → TTS, results posted back to UI."""
        from pathlib import Path

        try:
            GLib.idle_add(self._set_orb_state, "listening")
            text = self.brain.process_voice(audio_path)
            if not text:
                GLib.idle_add(self._set_orb_state, "error")
                GLib.idle_add(self._ai_error, "No speech detected.")
                return
            GLib.idle_add(self._set_orb_state, "thinking")
            reply, action_summary = self.brain.process_chat(text)
            if not reply:
                GLib.idle_add(self._set_orb_state, "error")
                GLib.idle_add(self._ai_error, "No response from AI.")
                return
            GLib.idle_add(self._set_orb_state, "speaking")
            spoken = self.brain.speak(reply)
            result = reply
            if action_summary:
                result += "\n\n" + action_summary
            if not spoken:
                result += "\n\nSpeech playback is unavailable."
            GLib.idle_add(self._ai_response, text, result)
            GLib.idle_add(self._set_orb_state, "sleeping" if spoken else "error")
        finally:
            # Recordings can contain sensitive speech and must not accumulate.
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass

    def _set_orb_state(self, state):
        self._orb_state = state
        if self.dock is not None and hasattr(self.dock, "ai_orb"):
            self.dock.ai_orb.set_state(state)

    def _ai_response(self, user_text, reply):
        if self.left is not None:
            self.left.show_ai_response(user_text, reply)

    def _ai_error(self, message):
        if self.left is not None:
            self.left.show_stub(message)

    # ── Command-line dispatch ──────────────────────────────────────────

    def do_command_line(self, command_line):
        import argparse

        parser = argparse.ArgumentParser(description="DarkOS Shell Controller")
        parser.add_argument("--toggle-ai", action="store_true")
        parser.add_argument("--toggle-side-panels", action="store_true")
        parser.add_argument("--toggle-command-center", action="store_true")
        parser.add_argument("--toggle-control", action="store_true")
        parser.add_argument("--toggle-left", action="store_true")
        parser.add_argument("--toggle-rail", action="store_true")
        parser.add_argument("--ptt-start", action="store_true")
        parser.add_argument("--ptt-stop", action="store_true")
        parser.add_argument("--lock", action="store_true")
        parser.add_argument("--installer-mode", choices=("on", "off"))
        try:
            args = parser.parse_args(command_line.get_arguments()[1:])
        except SystemExit as error:
            return int(error.code or 0)

        self.activate()
        if args.installer_mode:
            self.set_installer_mode(args.installer_mode == "on")
        if args.toggle_side_panels:
            self._toggle_window(self.left)
            self._toggle_window(self.right)
        if args.toggle_command_center:
            # HUD visibility is the source of truth for "open" — unlike
            # left/right, activity_detector never touches it, so it can't
            # drift out of sync the way independently-toggled windows could.
            opening = not self.hud.is_visible()
            for window in (self.hud, self.left, self.right):
                if opening:
                    window.show_all()
                else:
                    window.hide()
        if args.toggle_control:
            self._toggle_window(self.right)
        if args.toggle_left:
            self._toggle_window(self.left)
        if args.toggle_rail:
            self._toggle_window(self.rail)
        if args.toggle_ai:
            if not self.left.is_visible():
                self.left.show_all()
            self.left.entry.grab_focus()
        if args.ptt_start:
            if self.trigger.on_push_to_talk_start():
                self._set_orb_state("listening")
            else:
                self._set_orb_state("error")
                self._ai_error("No working microphone recorder was found.")
        if args.ptt_stop:
            if not self.trigger.on_push_to_talk_stop():
                self._set_orb_state("error")
                self._ai_error("No speech was captured.")
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
        overlays = (self.dock, self.rail, self.left, self.right)
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

    # ── Rail actions ───────────────────────────────────────────────────

    def handle_rail_action(self, action):
        commands = {
            "files": ["/usr/local/bin/darkos-files.py"],
            "terminal": ["/usr/local/bin/the-void.sh"],
            "settings": ["wofi", "--show", "drun"],
            "browser": ["firefox"],
            "store": ["wofi", "--show", "drun"],
            "notes": ["/usr/local/bin/darkos-notes.py"],
        }
        if action == "ai":
            if not self.left.is_visible():
                self.left.show_all()
            self.left.entry.grab_focus()
            return
        if action in commands:
            launch(commands[action])
            return
        phase = {"gallery": "4", "music": "7", "gaming": "7"}.get(action, "later")
        if not self.left.is_visible():
            self.left.show_all()
        self.left.show_stub(
            f"Not opened: {action.title()} is a Phase {phase} surface and is not built yet."
        )

    # ── Toggle state ───────────────────────────────────────────────────

    def set_toggle(self, name, enabled):
        self.toggle_state[name] = enabled
        if name in ("wifi", "bluetooth") and self.toggle_state["airplane"]:
            if self.airplane_radio_state is not None:
                self.airplane_radio_state[name] = enabled
            self.toggle_state[name] = False
            display_name = "Wi-Fi" if name == "wifi" else "Bluetooth"
            self.right.set_control_status(
                f"{display_name} will be {'enabled' if enabled else 'disabled'} "
                "when airplane mode is disabled."
            )
        elif name == "wifi":
            launch(["nmcli", "radio", "wifi", "on" if enabled else "off"])
            self.right.set_control_status(
                f"Wi-Fi {'enabled' if enabled else 'disabled'} via NetworkManager."
            )
        elif name == "bluetooth":
            launch(["bluetoothctl", "power", "on" if enabled else "off"])
            self.right.set_control_status(
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
            self.right.set_control_status(
                f"Airplane mode {'enabled' if enabled else 'disabled'}."
            )
        elif name in ("night_light", "focus"):
            display_name = "Night Light" if name == "night_light" else "Focus"
            self.right.set_control_status(
                f"Preview only: {display_name} has no system backend yet.", True
            )
        self.notify_state_listeners()


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
