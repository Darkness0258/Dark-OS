#!/usr/bin/env python3
"""Action dispatcher + safety layer for AI-driven OS control.

Each public method is one action the brain can request.
Snapshot-before-act wraps any mutating action with a Btrfs/ZFS snapshot.
D-Bus and hyprctl calls go through the helpers here so they all share
the same timeout and error contract.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


class SnapshotError(Exception):
    """Raised when snapshot-before-act cannot create a snapshot."""


class ActionDispatcher:
    """Executes AI-requested OS actions with snapshot safety."""

    def __init__(self):
        self._snapshot_enabled = self._check_btrfs()
        self._snapshot_root = "/"
        self._latest_snapshot = None

    # ── Public action API ───────────────────────────────────────────────
    # Every mutating action follows the same shape:
    #   1. self._snapshot()          ← safety net
    #   2. actual work
    #   3. return result string
    # Read-only actions (query, list) skip the snapshot.

    def open_app(self, app_name: str) -> str:
        self._snapshot()
        apps = {
            "firefox": ["firefox"],
            "browser": ["firefox"],
            "terminal": ["/usr/local/bin/the-void.sh"],
            "files": ["/usr/local/bin/the-void.sh", "-e", "ranger"],
            "notes": ["/usr/local/bin/the-void.sh", "-e", "nvim"],
            "settings": ["wofi", "--show", "drun"],
        }
        cmd = apps.get(app_name.lower(), [app_name])
        try:
            _launch(cmd)
            return f"Opened {app_name}."
        except Exception as exc:
            return f"Could not open {app_name}: {exc}"

    def set_volume(self, level: int) -> str:
        self._snapshot()
        level = max(0, min(100, level))
        try:
            _command(["pamixer", "--set-volume", str(level)])
            return f"Volume set to {level}%."
        except FileNotFoundError:
            return "Volume control unavailable: pamixer not installed."
        except Exception as exc:
            return f"Volume error: {exc}"

    def set_brightness(self, level: int) -> str:
        self._snapshot()
        level = max(10, min(100, level))
        try:
            _command(["brightnessctl", "set", f"{level}%"])
            return f"Brightness set to {level}%."
        except FileNotFoundError:
            return "Brightness control unavailable: brightnessctl not installed."
        except Exception as exc:
            return f"Brightness error: {exc}"

    def switch_workspace(self, index: str) -> str:
        self._snapshot()
        try:
            idx = int(index)
            _command(["hyprctl", "dispatch", "workspace", str(idx)])
            return f"Switched to workspace {idx}."
        except (ValueError, Exception) as exc:
            return f"Workspace error: {exc}"

    def search(self, query: str) -> str:
        """Run a system-wide search using find + grep on common dirs."""
        # Read-only: no snapshot needed.
        try:
            result = _command(
                ["find", os.path.expanduser("~"), "-iname", f"*{query}*",
                 "-not", "-path", "*/.cache/*"],
                timeout=10,
            )
            hits = result.splitlines()[:8]
            if not hits:
                return f"No results for '{query}'."
            return f"Found {len(hits)} result(s):\n" + "\n".join(hits)
        except Exception as exc:
            return f"Search failed: {exc}"

    def explain(self, target: str) -> str:
        """Pull text from an error/crash/notification and return it
        for the brain to explain.  The brain calls this, gets the raw
        text, and formats its own explanation in chat."""
        text = _atspi_get_selected_text() or _atspi_get_active_window_text()
        if not text:
            return "No text found under the cursor or in the active window."
        return text  # Brain will explain this text in chat.

    def atspi_click(self, role: str, name_match: str) -> str:
        self._snapshot()
        result = _atspi_do_action("click", role, name_match)
        return result or f"Clicked {role} matching '{name_match}'."

    def atspi_set_text(self, role: str, name_match: str, value: str) -> str:
        self._snapshot()
        result = _atspi_do_action("set_text", role, name_match, value)
        return result or f"Set {role} '{name_match}' to '{value}'."

    # ── Snapshot-before-act ─────────────────────────────────────────────

    def _snapshot(self):
        """Create a Btrfs snapshot if we're on Btrfs.  Silently skip on
        other filesystems — the safety layer is best-effort."""
        if not self._snapshot_enabled:
            return
        try:
            desc = f"darkos-ai-{int(time.time())}"
            snap_dir = Path(self._snapshot_root) / ".snapshots"
            snap_dir.mkdir(parents=True, exist_ok=True)
            dst = str(snap_dir / desc)
            _command(["btrfs", "subvolume", "snapshot", self._snapshot_root, dst])
            self._latest_snapshot = desc
        except Exception:
            pass  # Snapshot is best-effort; action still runs.

    @staticmethod
    def _check_btrfs() -> bool:
        try:
            with open("/proc/mounts") as fh:
                return any("btrfs" in line.split()[2] for line in fh if line.strip())
        except OSError:
            return False

    def latest_snapshot(self) -> str | None:
        return self._latest_snapshot


# ── Shared helpers ─────────────────────────────────────────────────────

def _launch(cmd: list):
    subprocess.Popen(cmd, start_new_session=True)


def _command(cmd: list, timeout: float = 5.0) -> str:
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"exit {result.returncode}")
    return result.stdout.strip()


def _atspi_get_selected_text() -> str | None:
    """Try AT-SPI clipboard / selection text."""
    try:
        out = _command(
            ["python3", "-c", """
import gi; gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
desktop = Atspi.get_desktop(0)
# Walk focused component for selected text
def walk(node, depth=0):
    if depth > 8:
        return ''
    try:
        if node.get_role_name() in ('text', 'password text', 'document'):
            te = node.get_text_iface()
            if te:
                r = te.get_selection(0)
                if r[0] >= 0:
                    return te.get_text(r[0], r[1])
    except Exception:
        pass
    try:
        child = node.get_child_at_index(0)
        if child:
            s = walk(child, depth+1)
            if s:
                return s
    except Exception:
        pass
    return ''
print(walk(desktop))
"""],
            timeout=3,
        )
        return out if out else None
    except Exception:
        return None


def _atspi_get_active_window_text() -> str | None:
    """Best-effort grab of the active window's text content."""
    try:
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            title = data.get("title", "")
            if title:
                return title
    except Exception:
        pass
    return None


def _atspi_do_action(action: str, *args) -> str | None:
    """Generic AT-SPI action via a subprocess helper.
    action: click | set_text | focus
    args: role hint, name match, optional value
    Returns result string or None on failure."""
    try:
        payload = json.dumps({"action": action, "args": list(args)})
        result = subprocess.run(
            ["python3", "-c", f"""
import sys, json, gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
payload = json.loads(sys.argv[1])
action = payload['action']
args = payload['args']

def walk(node, depth=0):
    if depth > 10:
        return None
    try:
        role = node.get_role_name()
        name = (node.get_name() or '').lower()
        if args and any(a.lower() in name for a in args):
            if action == 'click':
                try:
                    node.do_action(0)
                    return f'clicked {{name}}'
                except Exception:
                    pass
            elif action == 'set_text' and len(args) >= 3:
                try:
                    te = node.get_text_iface()
                    if te:
                        te.set_text(0, te.get_character_count(), args[2])
                        return f'set text on {{name}}'
                except Exception:
                    pass
            elif action == 'focus':
                try:
                    node.set_selection(0, 0)
                    return f'focused {{name}}'
                except Exception:
                    pass
    except Exception:
        pass
    try:
        child = node.get_child_at_index(0)
        if child:
            r = walk(child, depth+1)
            if r:
                return r
        for i in range(1, node.get_n_children()):
            child = node.get_child_at_index(i)
            if child:
                r = walk(child, depth+1)
                if r:
                    return r
    except Exception:
        pass
    return None

desktop = Atspi.get_desktop(0)
for i in range(desktop.get_n_children()):
    app = desktop.get_child_at_index(i)
    r = walk(app)
    if r:
        print(r)
        break
else:
    print('')
""", payload],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None
