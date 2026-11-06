#!/usr/bin/env python3
"""Switch hypridle between the AC and battery timings when the power source changes.

Started once per session from hyprland.conf. It reads two or three tiny sysfs
files every few seconds (no GTK, no subprocess unless something changed) and,
when the source differs from last time, writes that source's timings and
restarts hypridle (darkos_shell/power.py). Settings applies its own changes
immediately, so this only has to notice plugging in and unplugging.
"""
import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from darkos_shell import power, user_settings  # noqa: E402

POLL_SECONDS = 10


def run(detect=power.detect, apply=power.apply_idle_config, load=user_settings.load_settings,
        sleep=time.sleep, iterations=None):
    """Poll forever (or `iterations` times in tests); act only when the source changes."""
    last = None
    count = 0
    while iterations is None or count < iterations:
        state = detect()
        if state.source != last:
            try:
                apply(load(), state.source)
            except OSError as exc:
                print(f"darkos-power-watch: could not write the idle config: {exc}", file=sys.stderr)
            last = state.source
        count += 1
        if iterations is None or count < iterations:
            sleep(POLL_SECONDS)


def single_instance(runtime_dir=None):
    """Hold a lock for the life of the process; a second copy exits quietly."""
    directory = runtime_dir or os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    fd = os.open(os.path.join(directory, "darkos-power-watch.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def main():
    lock = single_instance()
    if lock is None:
        return 0
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
