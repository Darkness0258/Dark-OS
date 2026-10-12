"""Shared user-settings store.

darkos-settings.py writes here; darkos_shell/tokens.py reads it at import
time so a chosen accent color / corner radius / reduce-motion preference
becomes the actual value the rest of the shell uses — not just a JSON file
nobody consults. Most settings take effect on the next shell restart; the
dock position/size are the exception: the running shell watches this file
and re-lays the dock out live (darkos_shell/__init__.py).
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
    "high_contrast": False,
    "a11y_sticky_keys": False,
    "a11y_eye_control": False,
    "shield_protection_enabled": True,
    "dock_position": "bottom",
    "dock_size": "default",
}

# Settings whose value must come from a fixed set. settings.json is
# hand-editable and written by another process, so a bad value falls back to
# the default here instead of ever reaching layer-shell/GTK code.
CHOICES = {
    "dock_position": ("bottom", "top", "left", "right"),
    "dock_size": ("compact", "default", "large"),
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
    for key, allowed in CHOICES.items():
        if data[key] not in allowed:
            data[key] = DEFAULTS[key]
    return data


def save_settings(data):
    """Write atomically (temp file + rename). The running shell watches this
    file, and a plain truncate-then-write lets it read an empty/half-written
    file and briefly fall back to defaults."""
    path = settings_path()
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: data.get(k, v) for k, v in DEFAULTS.items()}, f, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
