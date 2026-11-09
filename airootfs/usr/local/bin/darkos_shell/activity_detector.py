#!/usr/bin/env python3
"""Context-aware shell: AT-SPI activity detection and layout adaptation.

Reads the foreground app + activity pattern (coding/gaming/writing) via AT-SPI
and emits suggested layout modes. This is an assistive layout change, not an
autonomous system action — no snapshot is needed.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Activity profiles map to Dock/panel layout adjustments.
# None = no change (keep current layout).
ACTIVITY_PROFILES = {
    "coding": {
        "description": "Code editor or IDE in focus",
        "dock_highlight": "terminal",
        "show_chat": True,
        "show_system": True,
        "panel_opacity": 0.90,
        "app_signals": {"code", "editor", "vim", "neovim", "vscode", "intellij", "jetbrains", "emacs"},
    },
    "gaming": {
        "description": "Game or launcher in focus",
        # The Phase 3 dock has no dedicated Gaming app yet (Phase 7). Highlight
        # Store, the existing entry point for acquiring/launching software.
        "dock_highlight": "store",
        "show_chat": False,
        "show_system": False,
        "panel_opacity": 0.30,
        "app_signals": {"steam", "lutris", "heroic", "game", "wine"},
    },
    "writing": {
        "description": "Document or notes app in focus",
        "dock_highlight": "notes",
        "show_chat": True,
        "show_system": True,
        "panel_opacity": 0.85,
        "app_signals": {"libreoffice", "writer", "word", "notion", "obsidian", "logseq", "zettlr"},
    },
    "media": {
        "description": "Media player or browser in focus",
        # Browser is the shipped media entry point until the Phase 7 player.
        "dock_highlight": "browser",
        "show_chat": False,
        "show_system": False,
        "panel_opacity": 0.70,
        "app_signals": {"firefox", "chromium", "mpv", "vlc", "spotify", "youtube"},
    },
    "default": {
        "description": "General use",
        "dock_highlight": None,
        "show_chat": True,
        "show_system": True,
        "panel_opacity": 0.78,
        "app_signals": set(),
    },
}


class ActivityDetector:
    """Detects foreground app activity and suggests shell layout changes."""

    def __init__(self):
        self._current_profile = "default"
        self._last_window = ""
        self._listeners = []
        self._poll_interval = 3.0  # seconds between AT-SPI checks
        self._running = False
        self._detecting = False  # a background detection is in flight

    def start(self):
        """Begin polling for foreground window changes."""
        if self._running:
            return
        self._running = True
        self._poll()

    def stop(self):
        """Stop polling."""
        self._running = False

    def add_listener(self, callback):
        """Register a callback(profile_name, profile_data) for layout changes."""
        self._listeners.append(callback)

    @property
    def current_profile(self) -> str:
        return self._current_profile

    # ── Detection ──────────────────────────────────────────────────────

    def _poll(self):
        """Start one detection and schedule the next poll.

        Detection shells out (hyprctl, then a helper Python process as a last
        resort). It used to run right here on the GTK main thread, which
        froze the whole shell -- dock, clock, hover, clicks -- for up to ~3 s
        on every poll while the desktop was empty. It now runs on a worker
        thread and only the result is applied on the main loop.
        """
        if not self._running:
            return
        if not self._detecting:
            self._detecting = True
            threading.Thread(
                target=self._detect_in_background,
                name="darkos-activity-detector",
                daemon=True,
            ).start()
        from gi.repository import GLib
        GLib.timeout_add_seconds(int(self._poll_interval), self._poll)

    def _detect_in_background(self):
        """Worker-thread half of a poll: may block, must not touch GTK."""
        from gi.repository import GLib
        try:
            profile = self._detect_activity()
        except Exception:
            profile = None  # AT-SPI may not be available on first boot
        GLib.idle_add(self._apply_detected, profile)

    def _apply_detected(self, profile):
        """Main-thread half of a poll: publish the result to listeners."""
        self._detecting = False
        if self._running and profile is not None and profile != self._current_profile:
            self._current_profile = profile
            self._notify_listeners(profile)
        return False

    def _detect_activity(self) -> str:
        """Return the best-matching activity profile name."""
        window_title = self._get_active_window_title()
        if not window_title:
            return "default"
        if window_title == self._last_window:
            return self._current_profile
        self._last_window = window_title
        title_lower = window_title.lower()
        for name, profile in ACTIVITY_PROFILES.items():
            if name == "default":
                continue
            for signal in profile.get("app_signals", set()):
                if signal in title_lower:
                    return name
        return "default"

    @staticmethod
    def _hypr_env() -> dict:
        """Return os.environ with HYPRLAND_INSTANCE_SIGNATURE auto-discovered."""
        env = os.environ.copy()
        if "HYPRLAND_INSTANCE_SIGNATURE" not in env:
            hypr_base = f"/run/user/{os.getuid()}/hypr"
            if os.path.isdir(hypr_base):
                entries = [os.path.join(hypr_base, d) for d in os.listdir(hypr_base)]
                entries.sort(key=os.path.getmtime, reverse=True)
                if entries:
                    env["HYPRLAND_INSTANCE_SIGNATURE"] = os.path.basename(entries[0])
        return env

    @staticmethod
    def _get_active_window_title() -> str:
        """Best-effort active window title from Hyprland or AT-SPI."""
        env = ActivityDetector._hypr_env()
        hypr_answered = False

        # Primary: hyprctl activewindow (fast, direct)
        try:
            result = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True,
                text=True,
                timeout=2.0,
                env=env,
            )
            if result.returncode == 0:
                hypr_answered = True
                data = json.loads(result.stdout)
                title = data.get("title", "") or data.get("class", "") or ""
                if title:
                    return title
        except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
            pass

        # Fallback 1: hyprctl clients — pick the most-recently-focused window
        try:
            result = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True,
                text=True,
                timeout=2.0,
                env=env,
            )
            if result.returncode == 0:
                hypr_answered = True
                clients = json.loads(result.stdout)
                # Filter to visible, mapped, non-pinned windows
                visible = [
                    c for c in clients
                    if c.get("mapped") and not c.get("hidden") and c.get("visible")
                ]
                if visible:
                    # focusHistoryID 0 = most recently focused
                    visible.sort(key=lambda c: c.get("focusHistoryID", 999))
                    best = visible[0]
                    return best.get("title", "") or best.get("class", "") or ""
        except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
            pass

        if hypr_answered:
            # Hyprland is running and simply has nothing focused (an empty
            # desktop). The AT-SPI helper below is for non-Hyprland sessions;
            # reaching it here spawned a fresh Python interpreter every poll
            # just to learn there is no window.
            return ""

        # Fallback 2: AT-SPI — walk into frame children for the window title
        try:
            result = subprocess.run(
                ["python3", "-c", """
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
desktop = Atspi.get_desktop(0)
for i in range(desktop.get_child_count()):
    app = desktop.get_child_at_index(i)
    if not app:
        continue
    for j in range(app.get_child_count()):
        frame = app.get_child_at_index(j)
        if frame and frame.get_role_name() == 'frame':
            name = frame.get_name()
            if name:
                print(name)
                raise SystemExit(0)
    name = app.get_name()
    if name:
        print(name)
        raise SystemExit(0)
print('')
"""],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""

    def _notify_listeners(self, profile_name: str):
        profile = ACTIVITY_PROFILES.get(profile_name, ACTIVITY_PROFILES["default"])
        for callback in self._listeners:
            try:
                callback(profile_name, profile)
            except Exception:
                pass
