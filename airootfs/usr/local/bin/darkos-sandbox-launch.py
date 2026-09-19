#!/usr/bin/env python3
"""DarkOS sandbox launcher -- wraps a GUI app in bubblewrap before exec.

Usage (from a .desktop file's Exec= line):
    darkos-sandbox-launch.py <profile-name> -- <real-binary> [args...]

Reused mechanism, not a new one: bubblewrap is the same sandboxing tool
Flatpak already uses for every Flatpak-installed app in this project's
Store. This just applies it to DarkOS's own native apps too, via a
small per-app profile instead of hand-writing a bwrap invocation into
every .desktop file.

PILOT SCOPE, on purpose: this session built the wrapper for real and
applied it to exactly one app (Calculator -- see PROFILES below) rather
than all 21 at once. Same reasoning that split the network broker into
backend-then-UI and kept the security layers to one at a time: a
generic mechanism proven against the simplest real case first, not 21
simultaneous untested profiles. Extending PROFILES to more apps is
mechanical once each app's real file/network needs are worked out --
Reader and Gallery (open arbitrary user files, the actual "compromised
app can't reach everything" case this whole layer exists for) are the
obvious next ones, deliberately not done here.

VERIFICATION, both what's real and what isn't: bubblewrap's actual
isolation was verified for real in this sandbox -- a sandboxed process
genuinely cannot see paths that weren't explicitly bound in (checked
directly, not assumed from bwrap's docs). What ISN'T verified: whether
a real GTK3 app still renders correctly under actual Hyprland/Wayland
once sandboxed this way. This sandbox has no Wayland compositor at
all -- weaker than even the Xvfb tier the UI work earlier got, because
bwrap's Wayland-socket-sharing behavior is exactly the kind of thing
that only shows real problems on a real compositor. Treat every app
run through this as unverified-for-rendering until it's been watched
open on real hardware, the same way the BTRFS layer needed watching.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DARKOS_SHELL_PKG = Path("/usr/local/bin/darkos_shell")

# Each profile describes what one app genuinely needs, not a blanket
# policy. allow_network/allow_home default to False -- an app has to
# earn those, not start with them.
PROFILES = {
    "calculator": {
        "app_path": Path("/usr/local/bin/darkos-calculator.py"),
        "allow_network": False,  # pure arithmetic, no reason to ever reach out
        "allow_home": False,     # no file open/save, no history persisted
    },
}


def build_bwrap_args(profile: dict) -> list[str]:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    args = [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind", "/etc/fonts", "/etc/fonts",
        # Own binary + the shared app_kit/css/tokens helpers every DarkOS
        # app imports (see darkos-network.py, darkos-calculator.py, etc.
        # all doing `from darkos_shell.app_kit import ...`) -- without
        # this the app fails at import time, before anything sandboxing-
        # related even matters.
        "--ro-bind", str(profile["app_path"]), str(profile["app_path"]),
        "--ro-bind", str(DARKOS_SHELL_PKG), str(DARKOS_SHELL_PKG),
        "--proc", "/proc",
        "--dev", "/dev",
        # GPU access for accelerated Cairo/GL rendering -- binding this
        # is standard for a sandboxed GUI app, but whether DarkOS's 940MX
        # actually needs/uses it under Hyprland is a real-hardware
        # question, not one this sandbox can answer.
        "--dev-bind-try", "/dev/dri", "/dev/dri",
        # Wayland socket + D-Bus session bus + other runtime IPC live
        # here -- a GUI app can't function at all without it. Read-write
        # because some GTK apps write small state/lock files into their
        # own subdirectory of this at runtime.
        "--bind", runtime_dir, runtime_dir,
        "--setenv", "XDG_RUNTIME_DIR", runtime_dir,
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
    ]
    if not profile.get("allow_network", False):
        args.append("--unshare-net")
    if profile.get("allow_home", False):
        home = os.environ.get("HOME", str(Path.home()))
        args += ["--bind", home, home]
    # else: no HOME bind at all -- the sandboxed app simply can't see it.
    return args


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[2] != "--":
        print(f"usage: {sys.argv[0]} <profile-name> -- <real-binary> [args...]", file=sys.stderr)
        return 2

    profile_name = sys.argv[1]
    real_cmd = sys.argv[3:]
    profile = PROFILES.get(profile_name)
    if profile is None:
        print(f"darkos-sandbox-launch: no profile named {profile_name!r}", file=sys.stderr)
        return 2
    if not real_cmd:
        print("darkos-sandbox-launch: no command given after --", file=sys.stderr)
        return 2

    bwrap_args = build_bwrap_args(profile)
    full_cmd = bwrap_args + real_cmd
    os.execvp("bwrap", full_cmd)  # replaces this process; never returns on success


if __name__ == "__main__":
    sys.exit(main())
