"""Wallpaper catalogue and the swaybg launcher (standard library only).

Nine wallpapers ship in BACKGROUND_DIR with a 320x180 thumbnail each, so the
Settings picker never has to decode a full-size image. settings.json key
"wallpaper_path" is "" (use the default) or an absolute image path (a shipped
wallpaper or the user's own file). `apply()` is the only place that starts
swaybg; darkos-window-fx.py --wallpaper-apply calls it at every login and the
Settings picker calls it when the choice changes.
"""
import os
import shutil
import signal
import subprocess
import time

BACKGROUND_DIR = "/usr/share/backgrounds/darkos"
DEFAULT_FILE = "01-midnight-silk.jpg"
# Shown until swaybg has drawn the image, and if the image is ever missing.
# Must match misc:background_color in hyprland.conf.
FALLBACK_COLOR = "#0d0f12"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

CATALOG = (
    ("midnight-silk", "Midnight Silk", "01-midnight-silk.jpg"),
    ("alpine-arc", "Alpine Arc", "02-alpine-arc.jpg"),
    ("green-glass", "Green Glass", "03-green-glass.jpg"),
    ("earth-horizon", "Earth Horizon", "04-earth-horizon.jpg"),
    ("amber-flow", "Amber Flow", "05-amber-flow.jpg"),
    ("dusk-lake", "Dusk Lake", "06-dusk-lake.jpg"),
    ("glass-orbits", "Glass Orbits", "07-glass-orbits.jpg"),
    ("misty-valley", "Misty Valley", "08-misty-valley.jpg"),
    ("crimson-flow", "Crimson Flow", "09-crimson-flow.jpg"),
)


def catalog(directory=BACKGROUND_DIR):
    """The shipped wallpapers as dicts: id, name, path, thumb."""
    return [
        {
            "id": wid,
            "name": name,
            "path": os.path.join(directory, filename),
            "thumb": os.path.join(directory, "thumbs", filename),
        }
        for wid, name, filename in CATALOG
    ]


def default_path(directory=BACKGROUND_DIR):
    return os.path.join(directory, DEFAULT_FILE)


def _usable(path):
    return (
        isinstance(path, str)
        and os.path.isabs(path)
        and path.lower().endswith(IMAGE_EXTENSIONS)
        and os.path.isfile(path)
        and os.access(path, os.R_OK)
    )


def resolve(path, directory=BACKGROUND_DIR):
    """Return the image to show: `path` if usable, else the default, else None.

    settings.json is hand-editable, so a stale, relative or non-image path
    falls back instead of ever reaching swaybg.
    """
    for candidate in (path, default_path(directory)):
        if _usable(candidate):
            return candidate
    return None


def swaybg_argv(path):
    if path:
        return ["swaybg", "-i", path, "-m", "fill", "-c", FALLBACK_COLOR]
    return ["swaybg", "-c", FALLBACK_COLOR]


def apply(path, directory=BACKGROUND_DIR, run=None, popen=None, sleep=time.sleep,
          which=None, kill=os.kill, settle=0.4):
    """(Re)start swaybg with the wallpaper for `path`.

    Returns (started, resolved_path). The new swaybg is started BEFORE the
    old one is stopped, so changing wallpaper never flashes the fallback
    colour. `started` is False only when swaybg is not installed.
    """
    run = run or subprocess.run
    popen = popen or subprocess.Popen
    which = which or shutil.which
    if not which("swaybg"):
        return False, None
    resolved = resolve(path, directory)
    try:
        listing = run(["pgrep", "-x", "swaybg"], capture_output=True, text=True)
        old_pids = [int(p) for p in (listing.stdout or "").split() if p.isdigit()]
    except (OSError, subprocess.SubprocessError):
        old_pids = []
    popen(swaybg_argv(resolved), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
          start_new_session=True)
    if old_pids:
        sleep(settle)
        for pid in old_pids:
            try:
                kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    return True, resolved
