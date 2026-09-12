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

Runs as the desktop user, not root -- inotify doesn't need CAP_SYS_ADMIN,
so unlike a fanotify-based version would have needed, this doesn't require
its own privileged systemd service. A per-user `systemd --user` unit is
the natural fit; not written here since it depends on the unit-file
conventions the rest of this repo's systemd units use, which is worth
matching rather than guessing at in isolation.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/usr/local/bin")

from darkos_shell.continuous_watch import ContinuousWatcher, InotifyUnavailable
from darkos_shell.shield import scan_and_quarantine

WATCH_PATHS = [Path.home() / "Downloads", Path.home() / "Desktop"]


def _on_file_ready(path: Path) -> None:
    cancel = threading.Event()
    result, actions = scan_and_quarantine(path, cancel)
    if result.outcome == "detected":
        for action in actions:
            print(f"[darkos-protect] {action}", flush=True)
    elif result.outcome == "error":
        # Errors here are routine (permission-denied on a file that
        # vanished between the close event and the scan starting, e.g.
        # a browser's temp download artifact) -- logged, not fatal to
        # the watcher itself.
        print(f"[darkos-protect] scan error on {path}: {result.detail}", flush=True)


def main() -> int:
    watcher = ContinuousWatcher(WATCH_PATHS, _on_file_ready)
    try:
        watcher.start()
    except InotifyUnavailable as error:
        print(f"[darkos-protect] cannot start: {error}", file=sys.stderr, flush=True)
        return 1
    print(f"[darkos-protect] watching: {[str(p) for p in WATCH_PATHS]}", flush=True)
    try:
        while True:
            time.sleep(30)
            watcher.rescan()  # cheap; picks up a Downloads/Desktop that didn't exist at start
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
