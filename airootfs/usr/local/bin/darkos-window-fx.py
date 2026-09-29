#!/usr/bin/env python3
"""DarkOS window effects: Alt+Tab switcher and Windows-style half-screen Snap.

Two small, independent features in one script so both only need one entry
in the build's four-stage script registration instead of two.

    darkos-window-fx.py --switcher
        Alt+Tab window switcher. Hyprland has no built-in one. Reads the
        open window list from `hyprctl clients -j` (the same command the
        dock's running-indicator in darkos_shell/surfaces.py already
        uses), shows it in wofi --dmenu (already shipped and used for
        SUPER+E's app launcher, so it's a proven-available binary here),
        and focuses whichever one is picked via
        `hyprctl dispatch focuswindow address:<addr>`.

    darkos-window-fx.py --snap {left,right}
        Snap the focused window to the left or right half of its
        monitor, the way Windows' Win+Left/Win+Right does. Reads the
        real monitor resolution from `hyprctl monitors -j` and the
        focused window from `hyprctl activewindow -j`, then computes
        exact pixel geometry itself and applies it with
        `moveactive exact` / `resizeactive exact` -- deliberately not
        using any dispatcher's own percentage support, since that's
        exactly the kind of version-dependent detail this could not be
        confirmed against a real Hyprland session before shipping.
        `togglefloating` (no argument) is the one float/tile dispatcher
        already proven correct in this repo's own hyprland.conf
        (SUPER+V), so it's reused here rather than a guessed-at
        `setfloating`/`settiled` pair. Maximize/restore aren't handled
        here: every DarkOS app window already has a real maximize
        button via its titlebar (see darkos_shell/app_kit.py's
        build_titlebar), which goes through GTK's win.maximize() --
        the standard, compositor-agnostic xdg-shell request every
        Wayland compositor must honor, rather than another hyprctl
        dispatcher this session can't verify.
"""

from __future__ import annotations

import json
import subprocess
import sys


def _hyprctl_json(subcommand):
    try:
        output = subprocess.run(
            ["hyprctl", subcommand, "-j"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        return json.loads(output)
    except Exception:
        return None


def _dispatch(*args):
    try:
        subprocess.run(["hyprctl", "dispatch", *args], timeout=2, capture_output=True)
    except Exception:
        pass


def run_switcher():
    clients = _hyprctl_json("clients") or []
    entries = [c for c in clients if c.get("title") and c.get("address")]
    if not entries:
        return 0
    menu_lines = [f"{c['title']}  —  {c.get('class', '')}" for c in entries]
    try:
        result = subprocess.run(
            ["wofi", "--dmenu", "--prompt", "Switch window"],
            input="\n".join(menu_lines),
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return 1
    picked = result.stdout.strip()
    for client, line in zip(entries, menu_lines):
        if line == picked:
            _dispatch("focuswindow", f"address:{client['address']}")
            break
    return 0


def run_snap(side):
    if side not in ("left", "right"):
        print(f"darkos-window-fx: unknown --snap value {side!r}", file=sys.stderr)
        return 2
    monitors = _hyprctl_json("monitors") or []
    active = _hyprctl_json("activewindow")
    if not monitors or not active:
        return 1  # nothing focused, or hyprctl unavailable -- silently no-op

    monitor = next(
        (m for m in monitors if m.get("id") == active.get("monitor")),
        monitors[0],
    )
    scale = monitor.get("scale") or 1.0
    # hyprctl reports monitor width/height already multiplied by scale;
    # moveactive/resizeactive take logical (pre-scale) pixels.
    mon_x = round(monitor.get("x", 0) / scale)
    mon_y = round(monitor.get("y", 0) / scale)
    mon_w = round(monitor.get("width", 1920) / scale)
    mon_h = round(monitor.get("height", 1080) / scale)

    if not active.get("floating"):
        _dispatch("togglefloating")

    half_w = mon_w // 2
    target_x = mon_x + (half_w if side == "right" else 0)
    _dispatch("moveactive", "exact", str(target_x), str(mon_y))
    _dispatch("resizeactive", "exact", str(half_w), str(mon_h))
    return 0


def main():
    argv = sys.argv[1:]
    if "--switcher" in argv:
        return run_switcher()
    if "--snap" in argv:
        idx = argv.index("--snap")
        side = argv[idx + 1] if idx + 1 < len(argv) else ""
        return run_snap(side)
    print(f"usage: {sys.argv[0]} --switcher | --snap {{left,right}}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
