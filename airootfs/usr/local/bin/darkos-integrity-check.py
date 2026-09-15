#!/usr/bin/env python3
"""DarkOS system integrity check — rkhunter + AIDE, build-plan.md's last
open Shield item. Meant to run as root via a systemd timer (see
darkos-integrity-check.service/.timer), not from a user session.

Two tools, two different automation contracts -- verified for real
against the actual binaries in a sandbox before writing this, not
assumed:
  - AIDE signals findings through its EXIT CODE (0 = clean, non-zero =
    added/changed/removed entries -- confirmed by tampering a real file
    and watching the exit code actually change). Reliable to branch on.
  - rkhunter's exit code is 0 regardless of what it finds -- confirmed by
    running it for real and getting warnings with exit 0 anyway. Findings
    only show up in the text output, so this parses for "Warning:" lines
    instead of trusting the exit code.

AIDE also needs a first-run: --check fails outright against a database
that doesn't exist yet, so this treats a missing database as "initialize
it now, nothing to compare against yet, not a finding" rather than an
error -- the very first run after install establishes the baseline, every
run after that is a real check.

Root can't just call notify-send and have it reach the logged-in user's
session -- that needs the user's own D-Bus session address, found via
their /run/user/<uid>/bus socket. Verified the socket-discovery logic for
real against a simulated /run/user layout; the actual cross-user notify
delivery itself needs a real logged-in Hyprland session to confirm, same
category as everything else in this project that needed real hardware.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

AIDE_DB = Path("/var/lib/aide/aide.db")
AIDE_DB_NEW = Path("/var/lib/aide/aide.db.new")
AIDE_CONFIG = Path("/etc/aide.conf")
LOG_PATH = Path("/var/log/darkos/integrity-check.log")

log = logging.getLogger("darkos-integrity-check")


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_PATH)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)
    log.addHandler(logging.StreamHandler(sys.stdout))
    log.setLevel(logging.INFO)


def _logged_in_user() -> tuple[str, int] | None:
    """(username, uid) of a real desktop session, found via an active
    /run/user/<uid>/bus socket -- the standard per-user D-Bus session
    location. None if nobody's logged in (e.g. a check running before
    anyone's booted to the desktop)."""
    run_user = Path("/run/user")
    if not run_user.is_dir():
        return None
    for entry in sorted(run_user.iterdir()):
        if not (entry.name.isdigit() and (entry / "bus").exists()):
            continue
        try:
            import pwd

            return pwd.getpwuid(int(entry.name)).pw_name, int(entry.name)
        except (KeyError, ValueError):
            continue
    return None


def _notify(summary: str, body: str, urgency: str = "normal") -> None:
    """Best-effort desktop notification for whichever user is actually
    logged in. Root has no session of its own to notify -- this has to
    reach into the user's, or the alert just silently never displays."""
    user = _logged_in_user()
    if user is None:
        log.info("no logged-in user found -- notification skipped, log only")
        return
    username, uid = user
    try:
        subprocess.run(
            [
                "sudo", "-u", username,
                f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                "notify-send", "--urgency", urgency, summary, body,
            ],
            timeout=5,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log.info("notify-send unavailable (%s) -- continuing without it", error)


def run_aide() -> None:
    if not AIDE_DB.exists():
        log.info("no AIDE baseline yet -- initializing (this run establishes it, doesn't check against it)")
        result = subprocess.run(
            ["aide", "--config", str(AIDE_CONFIG), "--init"],
            capture_output=True, text=True, timeout=1800,
        )
        if result.returncode == 0 and AIDE_DB_NEW.exists():
            AIDE_DB_NEW.rename(AIDE_DB)
            log.info("AIDE baseline established")
        else:
            log.error("AIDE --init failed (exit %s): %s", result.returncode, result.stderr[:2000])
        return

    result = subprocess.run(
        ["aide", "--config", str(AIDE_CONFIG), "--check"],
        capture_output=True, text=True, timeout=1800,
    )
    if result.returncode == 0:
        log.info("AIDE: clean, no changes since baseline")
        return
    log.warning("AIDE: differences found (exit %s):\n%s", result.returncode, result.stdout[:4000])
    _notify(
        "DarkOS Integrity Check",
        "AIDE found file changes against the baseline — check "
        f"{LOG_PATH} or run `aide --config {AIDE_CONFIG} --check` for details.",
        urgency="critical",
    )


def run_rkhunter() -> None:
    result = subprocess.run(
        ["rkhunter", "--cronjob", "--rwo"],
        capture_output=True, text=True, timeout=1800,
    )
    warnings = [line for line in result.stdout.splitlines() if re.match(r"^Warning:", line)]
    if not warnings:
        log.info("rkhunter: clean, no warnings")
        return
    log.warning("rkhunter: %d warning(s):\n%s", len(warnings), "\n".join(warnings))
    _notify(
        "DarkOS Integrity Check",
        f"rkhunter found {len(warnings)} warning(s) — check {LOG_PATH} for details.",
        urgency="critical",
    )


def main() -> int:
    _setup_logging()
    log.info("=== integrity check starting ===")
    run_aide()
    run_rkhunter()
    log.info("=== integrity check finished ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
