"""On-demand ClamAV scans; no automatic deletion or implied background protection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import re
import selectors
import shutil
import subprocess
import threading
import time
from typing import Literal

REPORT_LIMIT = 131072


def stop_scanner(process: subprocess.Popen[bytes]) -> None:
    """Terminate a scanner when needed and reap it without unbounded waits."""
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def collect_report(
    process: subprocess.Popen[bytes], cancel: threading.Event, timeout: float,
) -> tuple[bytes, Literal["cancelled", "error"] | None, str]:
    """Drain Linux's nonblocking pipe with bounded storage and a deadline.

    Returns an incomplete result as soon as the output limit is crossed, even
    if a clean-looking scan summary appeared earlier in the stream.
    """
    if process.stdout is None:
        raise ValueError("Scanner output pipe was not created")
    report = bytearray()
    deadline = time.monotonic() + timeout
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    with selectors.DefaultSelector() as watcher:
        watcher.register(descriptor, selectors.EVENT_READ)
        eof = False
        while not eof or process.poll() is None:
            if cancel.is_set():
                return bytes(report), "cancelled", "Cancelled"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return bytes(report), "error", "Time limit reached"
            for _key, _events in watcher.select(timeout=min(0.1, remaining)):
                try:
                    chunk = os.read(descriptor, min(16384, REPORT_LIMIT + 1 - len(report)))
                except BlockingIOError:
                    continue
                if not chunk:
                    watcher.unregister(descriptor)
                    eof = True
                    break
                available = REPORT_LIMIT - len(report)
                report.extend(chunk[:available])
                if len(chunk) > available:
                    return bytes(report), "error", "Scan report size limit reached"
    return bytes(report), None, ""


@dataclass(frozen=True)
class ScanResult:
    """Scanner outcome and bounded diagnostic output for the UI."""

    outcome: Literal["clean", "detected", "error", "cancelled"]
    detail: str


def parse_infected_files(detail: str) -> list[tuple[Path, str]]:
    """Pull (path, signature) pairs out of a "detected" ScanResult's detail
    text. clamscan --infected prints exactly one line per hit in the form
    "<path>: <signature> FOUND" -- documented, stable output shape, not
    guessed. Signature names never contain a colon, so anchoring the split
    on ": <no-colon-text> FOUND$" correctly handles paths that do (rare on
    Linux, but not impossible). Silently skips anything that doesn't match
    rather than raising -- a report line this doesn't recognize shouldn't
    block quarantining the ones it does."""
    hits: list[tuple[Path, str]] = []
    for line in detail.splitlines():
        match = re.match(r"^(.+): ([^:]+) FOUND$", line.strip())
        if not match:
            continue
        path_text, signature = match.group(1), match.group(2)
        try:
            hits.append((Path(path_text).resolve(strict=True), signature))
        except OSError:
            continue  # file already gone (moved/deleted between scan and parse)
    return hits


def scan_path(
    target: Path,
    cancel: threading.Event,
    timeout: float = 600,
    database: Path | None = None,
) -> ScanResult:
    """Scan a selected regular file or directory without modifying its contents.

    Args:
        target: File or folder selected by the user.
        cancel: Set by the UI when the user cancels or closes the window.
        timeout: Overall scan limit in seconds.
        database: Optional explicit database, used for isolated engine tests.

    Returns:
        An explicit result; missing definitions, scan errors, and limits never
        become a clean verdict. A clean result covers only scanned content.
    """
    if cancel.is_set():
        return ScanResult("cancelled", "Scan cancelled; files were left in place.")
    if not math.isfinite(timeout) or timeout <= 0:
        return ScanResult("error", "Scan time limit must be a positive finite number.")
    executable = shutil.which("clamscan")
    if executable is None:
        return ScanResult("error", "ClamAV is unavailable. Install the clamav package.")
    try:
        if target.is_symlink() or not (target.is_file() or target.is_dir()):
            return ScanResult("error", "Select an existing regular file or folder, not a link.")
        target = target.resolve(strict=True)
        argv = [
            executable,
            "--recursive",
            "--infected",
            "--stdout",
            "--follow-dir-symlinks=0",
            "--follow-file-symlinks=0",
            "--alert-exceeds-max=yes",
            "--alert-encrypted=yes",
        ]
        if database is not None:
            argv.append(f"--database={database.resolve(strict=True)}")
        argv.extend(["--", str(target)])
        # A nonblocking pipe bounds both stored output and total scan time.
        # No disk spool or preexec_fn is needed in this GTK worker thread.
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env={**os.environ, "LC_ALL": "C"},
        )
        try:
            report, interrupted, reason = collect_report(process, cancel, timeout)
        finally:
            try:
                stop_scanner(process)
            finally:
                if process.stdout is not None:
                    process.stdout.close()
        detail = report.decode("utf-8", errors="replace").strip()
        if interrupted:
            return ScanResult(interrupted, f"{reason}; scan incomplete.\n{detail}")
        code = process.returncode
        if code == 1:
            return ScanResult("detected", "Threats or inspection-limit alerts reported.\n" + detail)
        if code != 0:
            return ScanResult("error", f"ClamAV exited with status {code}.\n{detail}")
        scanned = re.search(r"^Scanned files:\s*(\d+)\s*$", detail, re.MULTILINE)
        if scanned is None or int(scanned[1]) == 0 or "ERROR" in detail:
            return ScanResult("error", "No completed file scan could be confirmed.\n" + detail)
        return ScanResult("clean", "No threats reported in scanned content.\n" + detail)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return ScanResult("error", f"Scan could not complete: {error}")


def scan_and_quarantine(
    target: Path,
    cancel: threading.Event,
    timeout: float = 600,
    database: Path | None = None,
) -> tuple[ScanResult, list[str]]:
    """scan_path, then quarantine anything it found -- the one path shared
    by the on-demand Security Center scan and the continuous-protection
    watcher, so both quarantine the same way instead of two copies of the
    same loop drifting apart. `database` forwards straight to scan_path,
    same purpose: real engine tests without needing the real (and here,
    unreachable without network access) definitions database. Import is
    local to avoid a hard import-time dependency from shield.py (the
    module with no other project imports) onto quarantine.py; keeps
    `python -m py_compile shield.py` meaningful on its own."""
    from darkos_shell.quarantine import quarantine_file

    result = scan_path(target, cancel, timeout=timeout, database=database)
    actions: list[str] = []
    if result.outcome == "detected":
        for path, signature in parse_infected_files(result.detail):
            try:
                quarantine_file(path, reason=signature)
                actions.append(f"quarantined: {path} ({signature})")
            except OSError as error:
                actions.append(f"COULD NOT quarantine {path}: {error}")
    return result, actions
