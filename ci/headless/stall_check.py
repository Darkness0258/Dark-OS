#!/usr/bin/env python3
"""How long is the shell's GTK main loop blocked?

A 20 ms heartbeat runs on the main loop while the real shell is up; any gap
well beyond 20 ms is time the shell could not draw, animate, or answer a click.
This is the check that found ActivityDetector freezing the whole shell for 3 s
at a time on an empty desktop (45% of the run blocked; now 0%).

Environment:
  STALL_SECONDS      how long to watch                         (default 15)
  STALL_MAX          longest single stall allowed, seconds     (default 0.5)
  STALL_BLOCKED_PCT  share of the run that may be blocked, %   (default 5)
  STALL_OPEN_PANELS  1 = also show the Command Center panels   (default 1)
"""
import os
import sys
import time

sys.path.insert(0, os.environ["DARKOS_BIN"])
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from darkos_shell import DarkOSApplication  # noqa: E402

SECONDS = float(os.environ.get("STALL_SECONDS", "15"))
MAX_STALL = float(os.environ.get("STALL_MAX", "0.5"))
MAX_BLOCKED_PCT = float(os.environ.get("STALL_BLOCKED_PCT", "5"))

app = DarkOSApplication()
app.register(None)
app.activate()
if os.environ.get("STALL_OPEN_PANELS", "1") == "1":
    app.left.show_all()
    app.right.show_all()

gaps, last, started = [], [time.time()], time.time()


def beat():
    now = time.time()
    gap = now - last[0]
    last[0] = now
    if gap > 0.15:
        gaps.append((now - started, gap))
    return True


def finish():
    total = time.time() - started
    blocked = sum(gap for _, gap in gaps)
    longest = max((gap for _, gap in gaps), default=0.0)
    pct = 100 * blocked / total
    print("watched %.1fs | stalls >150ms: %d | longest %.2fs | blocked %.2fs (%.1f%%)"
          % (total, len(gaps), longest, blocked, pct))
    for at, gap in gaps[:8]:
        print("   %.2fs stall at t=%.1fs" % (gap, at))
    ok = longest <= MAX_STALL and pct <= MAX_BLOCKED_PCT
    print(("PASS" if ok else "FAIL") + ": limits are longest <= %.2fs, blocked <= %.1f%%" % (MAX_STALL, MAX_BLOCKED_PCT))
    Gtk.main_quit()
    sys.exit(0 if ok else 1)


GLib.timeout_add(20, beat)
GLib.timeout_add(int(SECONDS * 1000), finish)
Gtk.main()
