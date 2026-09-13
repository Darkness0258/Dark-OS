#!/usr/bin/env python3
"""DarkOS continuous protection daemon.

Watches a small set of user directories and scans+quarantines anything
dropped into them, closing the loop architecture.md describes: watch,
scan, quarantine -- automatically, without a manual on-demand scan.

Scope, stated plainly rather than left implicit:
  - Covers ~/Downloads and ~/Desktop. Solid, verified (see
    ci/test-continuous-protection.py), safe to rely on.
  - Does NOT yet cover removable media. Watching new mounts needs
    detecting them as they appear (a udev/polling loop) and marking each
    mount's own directory -- inotify doesn't watch a parent and
    automatically pick up new subdirectories on its own. Real gap, not
    wired here; rescan() exists for exactly this once it is.
  - Does NOT replace the Store gate (build-plan.md Shield item, still
    open) -- that's an explicit scan-before-install hook, not something
    this passive watcher can stand in for, since pacman's own cache isn't
    a user-writable directory this can watch the same way.

Runs as the desktop user, not root -- inotify doesn't need CAP_SYS_ADMIN.
Launched via hyprland.conf's exec-once, the same mechanism every other
session daemon here uses (waybar, mako, hypridle, darkos-shell.py itself)
-- checked start-hyprland first rather than assuming systemd --user was
available: this project's session is tty1-autologin straight into
Hyprland, no display manager, no systemd --user session ever gets
started. A --user unit would have silently never run.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/usr/local/bin")

from darkos_shell.continuous_watch import ContinuousWatcher, InotifyUnavailable
from darkos_shell.shield import scan_and_quarantine

WATCH_PATHS = [Path.home() / "Downloads", Path.home() / "Desktop"]
LOG_PATH = Path.home() / ".local" / "share" / "darkos" / "protect.log"

log = logging.getLogger("darkos-protect")


def _setup_logging() -> None:
    """A real log file, not just stdout -- exec-once doesn't redirect
    stdout anywhere durable (same gap ci/hardware-audit.sh already
    documented for darkos-shell.py itself), and this is a security-relevant
    daemon: losing its output on every session restart isn't acceptable
    the way it might be for a cosmetic one."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_PATH)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)
    log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)


def _notify(summary: str, body: str, urgency: str = "normal") -> None:
    """Best-effort desktop notification via notify-send -> mako, already
    part of this session's exec-once stack. A quarantine the user never
    sees isn't much better than one that never happened -- this is what
    actually closes that gap, not just the log file. Deliberately can't
    fail the caller: no notification daemon reachable yet (e.g. very
    early in session startup) is routine, not an error worth surfacing
    as one."""
    try:
        subprocess.run(
            ["notify-send", "--urgency", urgency, summary, body],
            timeout=5,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log.info("notify-send unavailable (%s) -- continuing without it", error)


def _on_file_ready(path: Path) -> None:
    cancel = threading.Event()
    result, actions = scan_and_quarantine(path, cancel)
    if result.outcome == "detected":
        for action in actions:
            log.warning(action)
        _notify(
            "DarkOS Shield",
            f"Quarantined {path.name} -- open Security Center to review or restore.",
            urgency="critical",
        )
    elif result.outcome == "error":
        # Errors here are routine (permission-denied on a file that
        # vanished between the close event and the scan starting, e.g.
        # a browser's temp download artifact) -- logged, not fatal to
        # the watcher itself, and not worth a notification.
        log.info("scan error on %s: %s", path, result.detail)


def _reconcile(watcher: ContinuousWatcher, running: bool) -> bool:
    """One settings-check-and-react step: start the watcher if protection
    is enabled and it isn't running, stop it if disabled and it is,
    otherwise just rescan(). Returns the new running state. Pulled out of
    main()'s loop so this can actually be tested without waiting through
    real 30-second sleeps for every transition."""
    from darkos_shell.user_settings import load_settings

    enabled = load_settings().get("shield_protection_enabled", True)
    if enabled and not running:
        try:
            watcher.start()
            log.info("protection turned on -- watching: %s", [str(p) for p in watcher._watch_paths])
            return True
        except InotifyUnavailable as error:
            log.error("cannot start: %s", error)
            return False
    if not enabled and running:
        watcher.stop()
        log.info("protection turned off")
        return False
    if running:
        watcher.rescan()  # picks up a Downloads/Desktop that didn't exist at start
    return running


def main() -> int:
    _setup_logging()
    watcher = ContinuousWatcher(WATCH_PATHS, _on_file_ready)
    running = _reconcile(watcher, running=False)
    try:
        while True:
            time.sleep(30)
            running = _reconcile(watcher, running)
    except KeyboardInterrupt:
        pass
    finally:
        if running:
            watcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
