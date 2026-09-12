"""Continuous protection: watch a small set of directories and hand off
any file that finishes being written to a scan callback.

architecture.md's requirement is "flags new/modified files for a
background scan instead of polling the whole disk" -- event-driven, not
which specific kernel API. This was first written against fanotify, which
is what a literal reading of "fanotify-based watcher" elsewhere in this
project suggested. It's swapped for inotify instead, for reasons worth
recording rather than silently deciding:

  - fanotify_init()/fanotify_mark() both reported success in testing, but
    never actually delivered a single event for a real file write -- not
    a hypothetical, an actual blocking read() that timed out empty. The
    same test directory, same write, immediately produced a correct
    inotify event. That's not proof fanotify is broken on a real target
    machine, but it IS proof this couldn't be verified the way everything
    else in this session was, and "written but never seen to work" isn't
    a bar this project accepts elsewhere.
  - inotify doesn't need CAP_SYS_ADMIN. fanotify's classic API does. That
    would have forced continuous protection into its own root-owned
    systemd service, with quarantine.py needing to chown files back to
    the watched user (already built in, doesn't hurt to keep) -- inotify
    can just run watching the current user's own directories, no separate
    privileged daemon required. Simpler architecture for the same result.
  - Real downside, stated plainly: inotify watches don't recurse either
    (same limitation noted below for the fanotify version), and it has a
    per-process watch-count limit (fs.inotify.max_user_watches) -- a
    non-issue at "a handful of top-level directories" scope, worth
    knowing if that scope ever grows.

x86_64-only (libc directly, no raw syscall numbers). Standard library
only, no new dependency for the ISO to carry.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import select
import struct
import threading
from pathlib import Path
from typing import Callable

_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
_libc.inotify_init1.argtypes = [ctypes.c_int]
_libc.inotify_init1.restype = ctypes.c_int
_libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
_libc.inotify_add_watch.restype = ctypes.c_int
_libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
_libc.inotify_rm_watch.restype = ctypes.c_int

IN_CLOSE_WRITE = 0x00000008
IN_NONBLOCK = 0x00000800
IN_CLOEXEC = 0x00080000

# struct inotify_event: s32 wd, u32 mask, u32 cookie, u32 len, then `len`
# bytes of (null-padded) name. Fixed part is 16 bytes on every arch this
# targets -- no alignment surprises, all fields are already 4 bytes wide.
_HEADER = struct.Struct("=iIII")
_HEADER_LEN = _HEADER.size
assert _HEADER_LEN == 16, f"unexpected inotify_event header size: {_HEADER_LEN}"


class InotifyUnavailable(RuntimeError):
    """Raised when inotify_init1 fails."""


class ContinuousWatcher:
    """Watches `watch_paths` (each marked individually, non-recursively --
    a subdirectory created after start() needs rescan() to pick up) and
    calls `on_file_ready(path)` once for each file fully written to one of
    them. Paths that don't exist at start() are skipped, not fatal."""

    def __init__(self, watch_paths: list[Path], on_file_ready: Callable[[Path], None]):
        self._watch_paths = [Path(p) for p in watch_paths]
        self._on_file_ready = on_file_ready
        self._fd: int | None = None
        self._wd_to_dir: dict[int, Path] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        fd = _libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if fd < 0:
            raise InotifyUnavailable(f"inotify_init1 failed (errno {ctypes.get_errno()})")
        self._fd = fd
        self.rescan()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def rescan(self) -> None:
        """Mark any watch path that exists but isn't marked yet."""
        if self._fd is None:
            return
        marked_dirs = set(self._wd_to_dir.values())
        for path in self._watch_paths:
            if path in marked_dirs or not path.is_dir():
                continue
            wd = _libc.inotify_add_watch(self._fd, str(path).encode(), IN_CLOSE_WRITE)
            if wd >= 0:
                self._wd_to_dir[wd] = path

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _run(self) -> None:
        assert self._fd is not None
        while not self._stop_event.is_set():
            ready, _, _ = select.select([self._fd], [], [], 1.0)
            if not ready:
                continue
            try:
                raw = os.read(self._fd, 4096)
            except OSError:
                continue
            offset = 0
            while offset + _HEADER_LEN <= len(raw):
                wd, mask, _cookie, name_len = _HEADER.unpack_from(raw, offset)
                offset += _HEADER_LEN
                name = raw[offset : offset + name_len].split(b"\x00", 1)[0].decode()
                offset += name_len
                directory = self._wd_to_dir.get(wd)
                if directory is not None and name and (mask & IN_CLOSE_WRITE):
                    self._on_file_ready(directory / name)
