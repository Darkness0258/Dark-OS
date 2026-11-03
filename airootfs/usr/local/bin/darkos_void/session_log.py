#!/usr/bin/env python3
"""Session logging: wrap a pane's shell in `script -qfe`.

Two ways to start a logged pane, both using `util-linux`'s `script` (already
pulled in by the `base` package group, so no new dependency):

- `wrap_with_script(argv, log_path)` — the argv for a *freshly spawned*
  terminal: `script` becomes the child VTE spawns, and it runs the real
  shell/command underneath. Use this for "new tab, logged from the start".
- `exec_command(log_path)` — a shell line to feed into a pane that is
  *already running* (`Vte.Terminal.feed_child`, as if typed): `exec script
  ...` replaces the running shell with `script` wrapping a fresh sub-shell
  on the same pty, so an existing pane can start logging mid-session
  without losing its cwd or killing anything the user already has open.

Flags: `-q` (quiet: no "Script started/done" banner), `-f` (flush output
after every write, so a `tail -f` on the log is live), `-e` (the wrapped
command's exit status becomes `script`'s own, so `child-exited` still
reports something meaningful).
"""
from __future__ import annotations

import shlex
import time
from pathlib import Path

LOG_SUBDIR = "logs"
_SCRIPT_FLAGS = "-qfe"


def default_log_dir(engagement_dir: Path | str | None = None) -> Path:
    """`<engagement_dir>/logs` when an engagement is active, else
    `~/.local/share/darkos/void-logs`."""
    if engagement_dir:
        return Path(engagement_dir) / LOG_SUBDIR
    import os
    xdg_data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg_data) / "darkos" / "void-logs"


def log_path_for(title: str = "session", when: float | None = None,
                  engagement_dir: Path | str | None = None) -> Path:
    """A timestamped, filesystem-safe log path under `default_log_dir`."""
    import re
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", title.strip()).strip("-") or "session"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(when))
    return default_log_dir(engagement_dir) / f"{safe_title}-{stamp}.log"


def wrap_with_script(argv: list[str] | None, log_path: Path | str, shell: str | None = None) -> list[str]:
    """argv for spawning a brand-new pane that logs from the start.

    `argv=None` means "the interactive shell"; `shell` overrides the
    default (`$SHELL` or `/bin/bash`) for that case.
    """
    import os
    cmd = list(argv) if argv else [shell or os.environ.get("SHELL") or "/bin/bash"]
    return ["script", _SCRIPT_FLAGS, "-c", shlex.join(cmd), str(log_path)]


def exec_command(log_path: Path | str) -> str:
    """The line to `feed_child` into an already-running pane to start
    logging now. Ends in `\\n` so it executes immediately (this is a
    direct action, not a tool-launcher insert the user reviews first)."""
    return f"exec script {_SCRIPT_FLAGS} {shlex.quote(str(log_path))}\n"
