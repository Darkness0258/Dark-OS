"""Shared user-settings store.

darkos-settings.py writes here; darkos_shell/tokens.py reads it at import
time so a chosen accent color / corner radius / reduce-motion preference
becomes the actual value the rest of the shell uses — not just a JSON file
nobody consults. Takes effect on the next shell restart; live-reload while
the shell keeps running is a real follow-up, not attempted here.
"""
import json
import os

from gi.repository import GLib

DEFAULTS = {
    "accent_color": "#00e5ff",
    "corner_radius": 16,
    "reduce_motion": False,
    "icon_theme": "",
    "gtk_font": "",
    "wallpaper_path": "",
    "a11y_speech": False,
    "a11y_captions": False,
    "a11y_magnifier": False,
    "a11y_sticky_keys": False,
    "a11y_eye_control": False,
}


def settings_path():
    d = os.path.join(GLib.get_user_config_dir(), "darkos")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "settings.json")


def load_settings():
    data = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            data.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError):
        pass
    return data


def save_settings(data):
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump({k: data.get(k, v) for k, v in DEFAULTS.items()}, f, indent=2)
        return True
    except OSError:
        return False
