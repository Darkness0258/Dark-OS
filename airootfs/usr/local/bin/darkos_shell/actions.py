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
import time
from pathlib import Path


class SnapshotError(Exception):
    """Raised when snapshot-before-act cannot create a snapshot."""


class ActionDispatcher:
    """Executes AI-requested OS actions with snapshot safety."""

    def __init__(self) -> None:
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
        apps = {
            "firefox": ["firefox"],
            "browser": ["firefox"],
            "terminal": ["/usr/local/bin/the-void.sh"],
            "files": ["/usr/local/bin/the-void.sh", "-e", "ranger"],
            "notes": ["/usr/local/bin/the-void.sh", "-e", "nvim"],
            "settings": ["wofi", "--show", "drun"],
        }
        cmd = apps.get(app_name.strip().lower())
        if cmd is None:
            return f"Could not open {app_name}: unsupported application."
        self._snapshot()
        try:
            _launch(cmd)
            return f"Opened {app_name}."
        except Exception as exc:
            return f"Could not open {app_name}: {exc}"

    def set_volume(self, level: int) -> str:
        try:
            level = _bounded_integer(level, "volume level", 0, 100)
        except ValueError as exc:
            return f"Volume error: {exc}"
        self._snapshot()
        try:
            _command(["pamixer", "--set-volume", str(level)])
            return f"Volume set to {level}%."
        except FileNotFoundError:
            return "Volume control unavailable: pamixer not installed."
        except Exception as exc:
            return f"Volume error: {exc}"

    def set_brightness(self, level: int) -> str:
        try:
            level = _bounded_integer(level, "brightness level", 10, 100)
        except ValueError as exc:
            return f"Brightness error: {exc}"
        self._snapshot()
        try:
            _command(["brightnessctl", "set", f"{level}%"])
            return f"Brightness set to {level}%."
        except FileNotFoundError:
            return "Brightness control unavailable: brightnessctl not installed."
        except Exception as exc:
            return f"Brightness error: {exc}"

    def switch_workspace(self, index: str) -> str:
        try:
            idx = _bounded_integer(index, "workspace index", 1, 10)
        except ValueError as exc:
            return f"Workspace error: {exc}"

        self._snapshot()
        try:
            try:
                _command(["hyprctl", "dispatch", "workspace", str(idx)])
            except Exception:
                _command(["hyprctl", "repl", f"hl.dispatch(hl.dsp.focus{{ workspace = {idx} }})"])
            return f"Switched to workspace {idx}."
        except Exception as exc:
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
        try:
            return _atspi_do_action("click", role, name_match)
        except Exception as exc:
            return f"Could not click {role} matching '{name_match}': {exc}"

    def atspi_set_text(self, role: str, name_match: str, value: str) -> str:
        self._snapshot()
        try:
            return _atspi_do_action("set_text", role, name_match, value)
        except Exception as exc:
            return f"Could not set {role} '{name_match}': {exc}"

    # ── Snapshot-before-act ─────────────────────────────────────────────

    def _snapshot(self) -> str | None:
        """Create a Btrfs safety snapshot before a mutating action.

        Returns the snapshot name when Btrfs is active and ``None`` on a
        non-Btrfs root.  If Btrfs is active but the snapshot cannot be
        created, raise ``SnapshotError`` so the requested action does not run
        without its safety net.
        """
        if not self._snapshot_enabled:
            return None

        # The installed system exposes a narrowly scoped, no-argument helper
        # through sudoers. This keeps arbitrary paths out of the privileged
        # boundary while allowing the unprivileged shell to protect Btrfs root.
        helper = Path("/usr/local/bin/darkos-ai-snapshot")
        if self._snapshot_root == "/" and helper.is_file():
            command = [str(helper)]
            if os.geteuid() != 0:
                command = ["sudo", "-n", str(helper)]
            try:
                output = _command(command)
            except Exception as error:
                raise SnapshotError(f"could not create root safety snapshot: {error}") from error
            desc = output.splitlines()[-1].strip() if output else ""
            if not desc.startswith("darkos-ai-") or not desc[10:].isdigit():
                raise SnapshotError("snapshot helper returned an invalid snapshot name")
            self._latest_snapshot = desc
            return desc

        desc = f"darkos-ai-{time.time_ns()}"
        snap_dir = Path(self._snapshot_root) / ".snapshots"
        dst = str(snap_dir / desc)

        try:
            snap_dir.mkdir(parents=True, exist_ok=True)
        except OSError as direct_error:
            try:
                _command(["sudo", "-n", "mkdir", "-p", str(snap_dir)])
            except Exception as privileged_error:
                raise SnapshotError(
                    f"could not create snapshot directory {snap_dir}: "
                    f"{privileged_error}"
                ) from direct_error

        try:
            _command(["btrfs", "subvolume", "snapshot", self._snapshot_root, dst])
        except Exception as direct_error:
            try:
                _command(
                    [
                        "sudo",
                        "-n",
                        "btrfs",
                        "subvolume",
                        "snapshot",
                        self._snapshot_root,
                        dst,
                    ]
                )
            except Exception as privileged_error:
                raise SnapshotError(
                    f"could not create safety snapshot {dst}: {privileged_error}"
                ) from direct_error

        self._latest_snapshot = desc
        return desc

    @staticmethod
    def _check_btrfs() -> bool:
        """Return whether the root filesystem itself is Btrfs."""
        try:
            result = subprocess.run(
                ["findmnt", "--noheadings", "--output", "FSTYPE", "--target", "/"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and result.stdout.strip() == "btrfs"

    def latest_snapshot(self) -> str | None:
        return self._latest_snapshot


# ── Shared helpers ─────────────────────────────────────────────────────

def _bounded_integer(value: object, label: str, minimum: int, maximum: int) -> int:
    """Parse a bounded integer without accepting bools or lossy floats."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip()
        try:
            parsed = int(candidate)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{label} must be an integer between {minimum} and {maximum}"
            ) from exc
    else:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _launch(cmd: list[str]) -> None:
    subprocess.Popen(cmd, start_new_session=True)


def _command(cmd: list[str], timeout: float = 5.0) -> str:
    env = os.environ.copy()
    if cmd and cmd[0] == "hyprctl" and not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        hypr_base = f"/run/user/{os.getuid()}/hypr"
        if os.path.isdir(hypr_base):
            entries = [os.path.join(hypr_base, d) for d in os.listdir(hypr_base)]
            entries.sort(key=os.path.getmtime, reverse=True)
            if entries:
                env["HYPRLAND_INSTANCE_SIGNATURE"] = os.path.basename(entries[0])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"exit {result.returncode}")
    return result.stdout.strip()


def _atspi_get_selected_text() -> str | None:
    """Return selected text, or scoped text, from the active accessible window.

    A desktop-wide full-text walk can leak text from an unrelated background
    application and makes ``explain()`` nondeterministic. Resolve the active
    Hyprland window first, then let AT-SPI inspect only the matching (or
    accessibility-active) frame. Within that frame, a real selection wins over
    the focused control and other readable text.
    """
    active_title = ""
    active_class = ""
    try:
        active = json.loads(_command(["hyprctl", "activewindow", "-j"], timeout=2.0))
        active_title = str(active.get("title") or "").strip()
        active_class = str(active.get("class") or "").strip()
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass

    payload = json.dumps({"title": active_title, "class": active_class})
    try:
        out = _command(
            ["python3", "-c", r"""
import json
import sys

import gi

gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

identity = json.loads(sys.argv[1])
hypr_title = " ".join(str(identity.get("title") or "").split()).casefold()
hypr_class = " ".join(str(identity.get("class") or "").split()).casefold()
desktop = Atspi.get_desktop(0)


def normalized(value):
    return " ".join(str(value or "").split()).casefold()


def state_contains(node, state):
    try:
        states = node.get_state_set()
        return bool(states and states.contains(state))
    except Exception:
        return False


def children(node):
    try:
        count = node.get_child_count()
    except Exception:
        return
    for index in range(max(0, count)):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is not None:
            yield child


def walk(node, depth=0):
    if node is None or depth > 24:
        return
    yield node
    for child in children(node):
        yield from walk(child, depth + 1)


def frame_score(frame):
    try:
        frame_name = normalized(frame.get_name())
        app = frame.get_parent()
        app_name = normalized(app.get_name()) if app else ""
    except Exception:
        frame_name = ""
        app_name = ""

    score = 0
    if hypr_title and frame_name == hypr_title:
        score += 100
    elif hypr_title and frame_name and (
        hypr_title in frame_name or frame_name in hypr_title
    ):
        score += 70
    if hypr_class and app_name == hypr_class:
        score += 60
    elif hypr_class and app_name and (
        hypr_class in app_name or app_name in hypr_class
    ):
        score += 35
    if state_contains(frame, Atspi.StateType.ACTIVE):
        score += 50
    if state_contains(frame, Atspi.StateType.FOCUSED):
        score += 25
    return score


frames = []
for node in walk(desktop):
    try:
        role = normalized(node.get_role_name())
    except Exception:
        continue
    if role in {"frame", "dialog", "window"}:
        frames.append(node)

scored = sorted(
    ((frame_score(frame), frame) for frame in frames),
    key=lambda item: item[0],
    reverse=True,
)

# A positive *unique* best score means Hyprland identity or AT-SPI
# active/focused state scoped the frame. Looking through every positive match
# would reintroduce the same leak for applications with several open windows.
# If the best candidates are ambiguous, return no AT-SPI text and let the
# caller use the active Hyprland title as its conservative fallback.
scoped_frames = []
if scored and scored[0][0] > 0:
    best_score = scored[0][0]
    best_frames = [frame for score, frame in scored if score == best_score]
    if len(best_frames) == 1:
        scoped_frames = best_frames


def selected_text(node):
    try:
        text_iface = node.get_text_iface()
    except Exception:
        return ""
    if not text_iface:
        return ""
    try:
        count = Atspi.Text.get_n_selections(text_iface)
    except Exception:
        return ""
    for index in range(max(0, count)):
        try:
            selection = Atspi.Text.get_selection(text_iface, index)
            start = getattr(selection, "start_offset", -1)
            end = getattr(selection, "end_offset", -1)
            if start < 0 or end <= start:
                continue
            value = Atspi.Text.get_text(text_iface, start, end)
        except Exception:
            continue
        if value and value.strip():
            return value.strip()[:6000]
    return ""


def readable_text(node):
    try:
        role = normalized(node.get_role_name())
    except Exception:
        return ""
    # Password controls are intentionally excluded. ``explain()`` should
    # never feed credentials to a cloud model.
    if role not in {
        "text", "document", "entry", "paragraph", "label", "terminal",
        "notification",
    }:
        return ""
    try:
        text_iface = node.get_text_iface()
        value = Atspi.Text.get_text(text_iface, 0, -1) if text_iface else ""
    except Exception:
        return ""
    return value.strip()[:6000] if value and value.strip() else ""


# First pass: an explicit selection anywhere inside the active frame.
for frame in scoped_frames:
    for node in walk(frame):
        value = selected_text(node)
        if value:
            print(value)
            raise SystemExit(0)

# Second pass: focused readable controls, then other readable content, still
# strictly within the active frame.
for frame in scoped_frames:
    nodes = list(walk(frame))
    ordered = [
        node for node in nodes
        if state_contains(node, Atspi.StateType.FOCUSED)
    ]
    ordered.extend(node for node in nodes if node not in ordered)
    for node in ordered:
        value = readable_text(node)
        if value:
            print(value)
            raise SystemExit(0)

print("")
""", payload],
            timeout=5,
        )
        return out if out else None
    except Exception:
        return None


def _atspi_get_active_window_text() -> str | None:
    """Best-effort grab of the active window's text content."""
    try:
        data = json.loads(_command(["hyprctl", "activewindow", "-j"], timeout=2.0))
        title = data.get("title", "")
        if title:
            return title
    except (OSError, RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass
    return None


_ATSPI_ACTION_SCRIPT = r"""
import json
import sys

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

payload = json.loads(sys.argv[1])
action = payload["action"]
args = payload["args"]

if action not in {"click", "set_text", "focus"}:
    print(f"unsupported AT-SPI action: {action}", file=sys.stderr)
    raise SystemExit(2)
if len(args) < 2:
    print("AT-SPI action requires a role and accessible name", file=sys.stderr)
    raise SystemExit(2)
if action == "set_text" and len(args) < 3:
    print("AT-SPI set_text requires a value", file=sys.stderr)
    raise SystemExit(2)

role_query = str(args[0]).strip().casefold()
name_query = str(args[1]).strip().casefold()
failures = []


def matches(node):
    try:
        role_name = (node.get_role_name() or "").strip().casefold()
        accessible_name = (node.get_name() or "").strip().casefold()
    except Exception:
        return False
    role_matches = not role_query or role_query in role_name
    name_matches = not name_query or name_query in accessible_name
    return role_matches and name_matches


def invoke(node):
    display_name = (node.get_name() or "").strip() or "unnamed control"
    if action == "click":
        action_iface = node.get_action_iface()
        if not action_iface:
            failures.append(f"{display_name!r} has no Action interface")
            return None
        count = Atspi.Action.get_n_actions(action_iface)
        if count <= 0:
            failures.append(f"{display_name!r} exposes no actions")
            return None

        named = []
        for index in range(count):
            try:
                action_name = (
                    Atspi.Action.get_action_name(action_iface, index) or ""
                ).casefold()
            except Exception:
                action_name = ""
            named.append((index, action_name))
        preferred_words = ("click", "press", "activate", "open", "toggle")
        ordered = [
            index
            for index, action_name in named
            if any(word in action_name for word in preferred_words)
        ]
        ordered.extend(index for index, _ in named if index not in ordered)
        for index in ordered:
            try:
                if Atspi.Action.do_action(action_iface, index):
                    return f"Clicked {node.get_role_name()} matching {display_name!r}."
            except Exception as exc:
                failures.append(f"action {index} on {display_name!r} failed: {exc}")
        failures.append(f"all actions on {display_name!r} returned failure")
        return None

    if action == "set_text":
        editable_iface = node.get_editable_text_iface()
        if not editable_iface:
            failures.append(f"{display_name!r} has no EditableText interface")
            return None
        try:
            if Atspi.EditableText.set_text_contents(editable_iface, str(args[2])):
                return f"Set {node.get_role_name()} {display_name!r}."
        except Exception as exc:
            failures.append(f"setting text on {display_name!r} failed: {exc}")
            return None
        failures.append(f"setting text on {display_name!r} returned failure")
        return None

    component_iface = node.get_component_iface()
    if not component_iface:
        failures.append(f"{display_name!r} has no Component interface")
        return None
    try:
        if Atspi.Component.grab_focus(component_iface):
            return f"Focused {node.get_role_name()} matching {display_name!r}."
    except Exception as exc:
        failures.append(f"focusing {display_name!r} failed: {exc}")
        return None
    failures.append(f"focusing {display_name!r} returned failure")
    return None


def walk(node, depth=0):
    if node is None or depth > 16:
        return None
    if matches(node):
        try:
            result = invoke(node)
        except Exception as exc:
            failures.append(f"matched control could not be used: {exc}")
            result = None
        if result:
            return result
    try:
        child_count = node.get_child_count()
    except Exception:
        return None
    for index in range(max(0, child_count)):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        result = walk(child, depth + 1)
        if result:
            return result
    return None


result = walk(Atspi.get_desktop(0))
if result:
    print(result)
    raise SystemExit(0)

detail = failures[-1] if failures else (
    f"no accessible {role_query or 'control'} matched {name_query!r}"
)
print(detail, file=sys.stderr)
raise SystemExit(3)
"""


def _atspi_do_action(action: str, *args: str) -> str:
    """Generic AT-SPI action via a subprocess helper.

    action: click | set_text | focus
    args: role hint, name match, optional value
    Returns a result string and raises ``RuntimeError`` on failure.
    """
    payload = json.dumps({"action": action, "args": list(args)})
    try:
        result = subprocess.run(
            ["python3", "-c", _ATSPI_ACTION_SCRIPT, payload],
            capture_output=True, text=True, timeout=5,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("python3 is unavailable for AT-SPI control") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("AT-SPI action timed out") from exc

    output = result.stdout.strip()
    if result.returncode != 0:
        detail = result.stderr.strip() or output or f"exit {result.returncode}"
        raise RuntimeError(detail)
    if not output:
        raise RuntimeError("AT-SPI helper returned no action result")
    return output
