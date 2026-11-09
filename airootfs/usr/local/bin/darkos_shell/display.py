"""Display settings: read the monitors from Hyprland, build a monitor rule,
apply it, verify it took, and remember it only once the user has kept it.

Why the read-back: docs/MASTER-PLAN.md H1 warns that `hyprctl keyword` can exit
0 and do nothing on a Hyprland that has moved to Lua config. So success is
never the exit code. A change counts as applied only when `hyprctl -j monitors`
reports the requested mode, scale and rotation afterwards.

Why persist last: a mode the screen cannot show must never reach
monitors.conf, or the next login is a black screen. The Settings page applies
live, asks "Keep these settings?" with a countdown, and only then calls
persist_rule(); no answer reverts.

No GTK in here: `run` and `sleep` are injectable, so every path is tested
against canned hyprctl output.
"""
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass

CONF_NAME = "monitors.conf"
CONF_HEADER = ("# Written by DarkOS Settings > Display. One `monitor = ...` line per screen;\n"
               "# Settings rewrites the line for a screen when you keep a change.\n")

NAME_RE = re.compile(r"^[A-Za-z0-9_:.+-]{1,64}$")   # connector names; nothing that could end a line
MODE_RE = re.compile(r"^(\d{3,5})x(\d{3,5})@([\d.]+)\s*Hz$")
SCALE_CANDIDATES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
TRANSFORMS = ((0, "Normal"), (1, "Rotated 90\u00b0"), (2, "Upside down"), (3, "Rotated 270\u00b0"))
MAX_DIMENSION = 16384
REFRESH_TOLERANCE_HZ = 0.5
SCALE_TOLERANCE = 0.01


class DisplayError(RuntimeError):
    """Hyprland is not running, or did not answer sensibly."""


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    refresh: float

    def token(self):
        return f"{self.width}x{self.height}@{self.refresh:.2f}"

    def size_label(self):
        return f"{self.width} \u00d7 {self.height}"

    def refresh_label(self):
        return f"{self.refresh:g} Hz" if abs(self.refresh - round(self.refresh)) > 0.005 \
            else f"{int(round(self.refresh))} Hz"


@dataclass(frozen=True)
class Monitor:
    name: str
    description: str
    width: int
    height: int
    refresh: float
    x: int
    y: int
    scale: float
    transform: int
    focused: bool
    disabled: bool
    modes: tuple

    def current_mode(self):
        return Mode(self.width, self.height, self.refresh)


def parse_mode(text):
    match = MODE_RE.match((text or "").strip())
    if not match:
        return None
    return Mode(int(match.group(1)), int(match.group(2)), float(match.group(3)))


def parse_monitors(text):
    """Monitors from `hyprctl -j monitors`; entries without a usable name are dropped."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise DisplayError("Hyprland did not return a monitor list.") from exc
    if not isinstance(data, list):
        raise DisplayError("Hyprland did not return a monitor list.")
    monitors = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        if not NAME_RE.match(name):
            continue
        modes = []
        for raw in item.get("availableModes") or []:
            mode = parse_mode(str(raw))
            if mode and mode not in modes:
                modes.append(mode)
        modes.sort(key=lambda m: (m.width * m.height, m.width, m.refresh), reverse=True)
        try:
            monitors.append(Monitor(
                name=name,
                description=str(item.get("description") or name),
                width=int(item.get("width", 0)), height=int(item.get("height", 0)),
                refresh=float(item.get("refreshRate", 0.0)),
                x=int(item.get("x", 0)), y=int(item.get("y", 0)),
                scale=float(item.get("scale", 1.0)), transform=int(item.get("transform", 0)),
                focused=bool(item.get("focused", False)), disabled=bool(item.get("disabled", False)),
                modes=tuple(modes),
            ))
        except (TypeError, ValueError):
            continue
    monitors.sort(key=lambda m: (not m.focused, m.name))
    return monitors


def resolutions(monitor):
    """[(width, height)] largest first. A monitor that lists no modes offers only its current one."""
    seen = []
    for mode in monitor.modes or (monitor.current_mode(),):
        if (mode.width, mode.height) not in seen:
            seen.append((mode.width, mode.height))
    return seen


def refresh_rates(monitor, width, height):
    """Distinct refresh rates available at this resolution, fastest first."""
    rates = sorted({round(m.refresh, 2) for m in monitor.modes if (m.width, m.height) == (width, height)},
                   reverse=True)
    if not rates and (monitor.width, monitor.height) == (width, height):
        rates = [round(monitor.refresh, 2)]
    return [Mode(width, height, r) for r in rates]


def valid_scales(width, height):
    """Scales whose logical size is a whole number of pixels, as Hyprland requires.

    Rotation swaps the axes, but whole-number divisibility is symmetric, so
    the same scales are valid at 90 and 270 degrees.
    """
    out = []
    for scale in SCALE_CANDIDATES:
        if all(abs(v / scale - round(v / scale)) < 1e-6 for v in (width, height)):
            out.append(scale)
    return out or [1.0]


def scale_label(scale):
    return f"{int(round(scale * 100))}%"


def build_rule(monitor, mode, scale, transform=0, x=None, y=None):
    """`name,WxH@R,XxY,S,transform,T`, validated. Raises ValueError on anything unsafe.

    Nothing from the outside reaches a config line unchecked: the name must be a
    plain connector name, every other field is a number we format ourselves.
    """
    if not NAME_RE.match(monitor.name):
        raise ValueError(f"unsafe monitor name: {monitor.name!r}")
    if not (0 < mode.width <= MAX_DIMENSION and 0 < mode.height <= MAX_DIMENSION):
        raise ValueError("resolution out of range")
    if not (0 < mode.refresh <= 1000):
        raise ValueError("refresh rate out of range")
    if not (0.5 <= scale <= 4.0):
        raise ValueError("scale out of range")
    if transform not in dict(TRANSFORMS):
        raise ValueError("unknown rotation")
    px = monitor.x if x is None else int(x)
    py = monitor.y if y is None else int(y)
    return f"{monitor.name},{mode.token()},{px}x{py},{scale:g},transform,{transform}"


def parse_rule(rule):
    """Inverse of build_rule: (name, Mode, x, y, scale, transform). Raises ValueError."""
    parts = [p.strip() for p in rule.split(",")]
    if len(parts) < 4 or not NAME_RE.match(parts[0]):
        raise ValueError("not a monitor rule")
    token = parts[1]
    mode = parse_mode(token if token.endswith("Hz") else token + "Hz")
    if mode is None:
        raise ValueError("unreadable mode")
    px, _, py = parts[2].partition("x")
    transform = int(parts[5]) if len(parts) >= 6 and parts[4] == "transform" else 0
    return parts[0], mode, int(px), int(py), float(parts[3]), transform


def plan_change(monitor, mode, scale, transform):
    """(rule to try, rule that restores what is on screen right now)."""
    new_rule = build_rule(monitor, mode, scale, transform)
    old_rule = build_rule(monitor, monitor.current_mode(), monitor.scale, monitor.transform)
    return new_rule, old_rule


def default_run(argv, timeout=3):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def list_monitors(run=default_run):
    code, out = run(["hyprctl", "-j", "monitors"])
    if code != 0 or not out.strip():
        raise DisplayError("Display settings need the DarkOS desktop session (Hyprland is not running).")
    return parse_monitors(out)


def matches_rule(monitor, rule):
    """Did `monitor` (as read back) end up where the rule asked?"""
    _name, mode, _x, _y, scale, transform = parse_rule(rule)
    return (monitor.width == mode.width and monitor.height == mode.height
            and abs(monitor.refresh - mode.refresh) <= REFRESH_TOLERANCE_HZ
            and abs(monitor.scale - scale) <= SCALE_TOLERANCE
            and monitor.transform == transform)


def apply_rule(rule, run=default_run, sleep=time.sleep, tries=5, delay=0.4):
    """Apply live and verify by reading back. Returns (ok, message). Never trusts the exit code."""
    try:
        name = parse_rule(rule)[0]
    except ValueError:
        return False, "That is not a valid display setting."
    _code, out = run(["hyprctl", "keyword", "monitor", rule])
    answer = (out or "").strip()
    if answer.lower() != "ok":
        return False, answer or "Hyprland did not answer."
    for attempt in range(tries):
        try:
            for monitor in list_monitors(run):
                if monitor.name == name and matches_rule(monitor, rule):
                    return True, "Applied."
        except DisplayError:
            pass
        if attempt < tries - 1:
            sleep(delay)
    return False, "Hyprland accepted the command but the screen did not change."


def conf_path(home=None):
    base = home or os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(base, ".config", "hypr", "conf.d", CONF_NAME)


def _rule_name_in_line(line):
    stripped = line.strip()
    if not stripped.startswith("monitor"):
        return None
    _, _, value = stripped.partition("=")
    return value.split(",")[0].strip() or None


def persist_rule(rule, path=None):
    """Write this screen's line into monitors.conf (replace or append), atomically.

    Other screens' lines and any comments the user added are kept as they were.
    """
    name = parse_rule(rule)[0]
    path = path or conf_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = CONF_HEADER.splitlines()
    new_line = f"monitor = {rule}"
    replaced = False
    out = []
    for line in lines:
        if _rule_name_in_line(line) == name:
            if not replaced:
                out.append(new_line)
                replaced = True
            continue          # drop duplicates of this screen
        out.append(line)
    if not replaced:
        out.append(new_line)
    fd, tmp = tempfile.mkstemp(prefix=".monitors.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
