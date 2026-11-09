"""Process table for the Task Manager, read straight from /proc.

No subprocess (`ps` forks and costs more than the sample itself), no GTK, and
a configurable proc root, so the whole thing runs against a fake tree in tests.

Static facts about a process (command line, owner) are read once and cached by
(pid, start time); each sample then re-reads only /proc/<pid>/stat. Start time
is part of the key because Linux reuses PIDs.
"""
import os
import pwd
import re
import signal
import time
from dataclasses import dataclass

PROTECTED_PIDS = (0, 1, 2)

# Interpreters whose own name says nothing: every DarkOS app is `python3 <script>`.
# Exact match, not a prefix: `shotwell photo.jpg` is not a shell script.
INTERPRETER = re.compile(r"^(python[\d.]*|node(js)?|java|ruby|perl|bash|dash|zsh|sh)$")

# (substring of the command line, what ending it does). Checked in order.
WARNINGS = (
    ("Hyprland", "Ending Hyprland closes your whole session, and every open window with it."),
    ("darkos-shell.py", "Ending the DarkOS shell removes the dock and panels until it is restarted."),
    ("pipewire", "Sound stops working until it is restarted."),
    ("wireplumber", "Sound stops working until it is restarted."),
)


@dataclass
class Proc:
    pid: int
    ppid: int
    name: str
    cmdline: str
    state: str
    uid: int
    user: str
    ticks: int          # utime + stime, in clock ticks since the process started
    rss: int            # resident memory in bytes
    threads: int
    start: int          # start time in ticks since boot (the PID-reuse key)
    cpu: float = 0.0    # percent of ONE core since the previous sample (can exceed 100)


@dataclass
class Snapshot:
    procs: list
    cpu_percent: float          # whole machine, 0..100; 0.0 on the first sample
    mem_total: int
    mem_used: int
    swap_total: int
    swap_used: int
    taken_at: float


def human_bytes(n):
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GB"


def display_name(comm, argv):
    """`python3 /usr/local/bin/darkos-clock.py` shows as `darkos-clock.py`."""
    base = comm.rstrip()
    if argv and INTERPRETER.match(base):
        for arg in argv[1:]:
            if arg and not arg.startswith("-"):
                return os.path.basename(arg) or base
    return base


def parse_stat(text):
    """Fields of /proc/<pid>/stat as (comm, state, ppid, ticks, threads, start, rss_pages).

    comm is in parentheses and may itself contain spaces and parentheses, so
    split on the LAST closing one.
    """
    left = text.index("(")
    right = text.rindex(")")
    comm = text[left + 1:right]
    rest = text[right + 2:].split()
    return (comm, rest[0], int(rest[1]), int(rest[11]) + int(rest[12]),
            int(rest[17]), int(rest[19]), int(rest[21]))


def _read(path):
    with open(path, "rb") as f:
        return f.read()


class Sampler:
    """Take successive Snapshots; CPU percentages come from the difference."""

    def __init__(self, proc_root="/proc", clock=time.monotonic, clk_tck=None, page_size=None,
                 lookup_user=None):
        self.root = proc_root
        self.clock = clock
        self.clk_tck = clk_tck or os.sysconf("SC_CLK_TCK")
        self.page = page_size or os.sysconf("SC_PAGE_SIZE")
        self.lookup_user = lookup_user or self._lookup_user
        self._static = {}      # pid -> (start, name, cmdline, uid, user)
        self._last_ticks = {}  # pid -> (start, ticks)
        self._last_time = None
        self._last_cpu = None
        self._users = {}

    def _lookup_user(self, uid):
        if uid not in self._users:
            try:
                self._users[uid] = pwd.getpwuid(uid).pw_name
            except KeyError:
                self._users[uid] = str(uid)
        return self._users[uid]

    def _static_info(self, pid, start, comm):
        cached = self._static.get(pid)
        if cached and cached[0] == start:
            return cached[1:]
        try:
            raw = _read(f"{self.root}/{pid}/cmdline")
        except OSError:
            raw = b""
        argv = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        uid = 0
        try:
            for line in _read(f"{self.root}/{pid}/status").decode("utf-8", "replace").splitlines():
                if line.startswith("Uid:"):
                    uid = int(line.split()[1])  # real uid
                    break
        except (OSError, ValueError, IndexError):
            pass
        name = display_name(comm, argv) if argv else comm
        cmdline = " ".join(argv) if argv else f"[{comm}]"
        info = (start, name, cmdline, uid, self.lookup_user(uid))
        self._static[pid] = info
        return info[1:]

    def _cpu_times(self):
        try:
            fields = _read(f"{self.root}/stat").decode().splitlines()[0].split()[1:]
            values = [int(v) for v in fields[:8]]
            idle = values[3] + values[4]
            return sum(values), idle
        except (OSError, ValueError, IndexError):
            return None

    def _memory(self):
        total = avail = swap_total = swap_free = 0
        try:
            for line in _read(f"{self.root}/meminfo").decode().splitlines():
                key, _, rest = line.partition(":")
                kb = int(rest.split()[0]) * 1024 if rest.split() else 0
                if key == "MemTotal":
                    total = kb
                elif key == "MemAvailable":
                    avail = kb
                elif key == "SwapTotal":
                    swap_total = kb
                elif key == "SwapFree":
                    swap_free = kb
        except (OSError, ValueError):
            pass
        return total, max(0, total - avail), swap_total, max(0, swap_total - swap_free)

    def sample(self):
        now = self.clock()
        elapsed = (now - self._last_time) if self._last_time is not None else None
        procs, seen_ticks = [], {}
        try:
            entries = os.listdir(self.root)
        except OSError:
            entries = []
        for entry in entries:
            if not entry.isdigit():
                continue
            pid = int(entry)
            try:
                comm, state, ppid, ticks, threads, start, rss_pages = parse_stat(
                    _read(f"{self.root}/{pid}/stat").decode("utf-8", "replace"))
                name, cmdline, uid, user = self._static_info(pid, start, comm)
            except (OSError, ValueError, IndexError):
                continue  # exited while we looked, or unreadable
            cpu = 0.0
            previous = self._last_ticks.get(pid)
            if previous and previous[0] == start and elapsed and elapsed > 0:
                cpu = max(0.0, (ticks - previous[1]) / self.clk_tck / elapsed * 100.0)
            seen_ticks[pid] = (start, ticks)
            procs.append(Proc(pid, ppid, name, cmdline, state, uid, user, ticks,
                              rss_pages * self.page, threads, start, cpu))
        # Forget processes that are gone, so the caches cannot grow without bound.
        self._last_ticks = seen_ticks
        for pid in [p for p in self._static if p not in seen_ticks]:
            del self._static[pid]

        cpu_total = self._cpu_times()
        cpu_percent = 0.0
        if cpu_total and self._last_cpu:
            d_total = cpu_total[0] - self._last_cpu[0]
            d_idle = cpu_total[1] - self._last_cpu[1]
            if d_total > 0:
                cpu_percent = max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))
        self._last_cpu = cpu_total
        self._last_time = now
        mem_total, mem_used, swap_total, swap_used = self._memory()
        return Snapshot(procs, cpu_percent, mem_total, mem_used, swap_total, swap_used, now)


def matches(proc, query):
    """Case-insensitive search over name, command line, PID and owner."""
    needle = (query or "").strip().lower()
    if not needle:
        return True
    return (needle in proc.name.lower() or needle in proc.cmdline.lower()
            or needle == str(proc.pid) or needle in proc.user.lower())


def can_signal(proc, my_uid):
    """(allowed, why not). Only the owner or root may signal a process."""
    if proc.pid in PROTECTED_PIDS:
        return False, "This is part of the system and cannot be ended."
    if my_uid == 0 or proc.uid == my_uid:
        return True, ""
    return False, f"Owned by {proc.user}: only {proc.user} or root can end it."


def warning_for(proc):
    """Extra confirmation text when ending this process is a big deal, else ''."""
    haystack = f"{proc.name} {proc.cmdline}"
    for needle, text in WARNINGS:
        if needle in haystack:
            return text
    return ""


def end_task(pid, force=False, own_pid=None, kill=os.kill):
    """Send SIGTERM (or SIGKILL when `force`). Returns (ok, message)."""
    own_pid = os.getpid() if own_pid is None else own_pid
    if pid in PROTECTED_PIDS:
        return False, "This is part of the system and cannot be ended."
    if pid == own_pid:
        return False, "That is this Task Manager. Close its window instead."
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        kill(pid, sig)
    except ProcessLookupError:
        return True, "It had already exited."
    except PermissionError:
        return False, "Not allowed: that process belongs to another user."
    except OSError as exc:
        return False, f"Could not end it: {exc.strerror or exc}."
    return True, "Force quit sent." if force else "Asked it to quit."
