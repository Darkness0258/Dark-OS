#!/usr/bin/env python3
"""Shield-gated pacman install: download, scan every resolved file, install
only if every file scans clean.

This script performs no privilege escalation itself — it must already be
running as root. `darkos-store.py`'s Install button launches it via
`sudo python3 <this path> -- <package>` inside a visible terminal, the same
terminal-handoff pattern `darkos-security.py` already uses for
`sudo freshclam` (see its Update Definitions button). The user sees the
sudo prompt, the download, the scan, and the install in one place.

Exit code 0 only after `pacman -U` actually ran against files that were
each individually confirmed clean by `darkos_shell.shield.scan_path` (the
same on-demand scanner Security's Shield tab uses). Any resolution,
download, verification, or scan failure exits nonzero and never calls
`pacman -U` — a missing engine, a detection, a scan error, and a pacman
failure are all treated as "do not install", matching scan_path's own
fail-closed contract.

This is the source-level orchestration for build-plan.md's Phase 6 Store
installation gate. The pacman -Sp/-Sw output-format assumptions below are
not verified against a real pacman transaction — no Arch root shell was
available in the session that wrote this (see progress-tracker.md for the
exact blocker). Only the orchestration logic itself is tested, via mocked
subprocess calls in ci/test-store-gated-install.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.shield import scan_path  # noqa: E402

DEFAULT_CACHE_DIR = "/var/cache/pacman/pkg"


class GatedInstallError(Exception):
    """A resolution, download, verification, or scan step refused to proceed.

    Raising this anywhere in the pipeline means pacman -U is never reached.
    """


def cache_dir(run=subprocess.run) -> str:
    """Return pacman's configured cache directory, falling back to the
    documented default if pacman-conf is unavailable or reports nothing."""
    try:
        result = run(
            ["pacman-conf", "CacheDir"],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DEFAULT_CACHE_DIR
    if result.returncode != 0:
        return DEFAULT_CACHE_DIR
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            return line
    return DEFAULT_CACHE_DIR


def resolve_targets(pkg: str, run=subprocess.run) -> list[str]:
    """Ask pacman which file(s) installing pkg would download (target plus
    any not-yet-installed dependencies) and return their expected local
    cache paths. Does not touch the network or the filesystem itself."""
    try:
        result = run(
            ["pacman", "-Sp", "--", pkg],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GatedInstallError(f"Could not resolve download targets for {pkg}: {error}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GatedInstallError(f"pacman -Sp failed for {pkg}" + (f": {detail}" if detail else ""))
    urls = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not urls:
        raise GatedInstallError(f"pacman -Sp returned no download targets for {pkg}.")
    directory = cache_dir(run=run)
    targets = []
    for url in urls:
        name = os.path.basename(urlsplit(url).path)
        if not name:
            raise GatedInstallError(f"Could not determine a filename from resolved URL: {url}")
        targets.append(os.path.join(directory, name))
    return targets


def download(pkg: str, run=subprocess.run) -> None:
    """Download pkg and any dependencies to the cache without installing
    them (pacman -Sw). Requires root."""
    try:
        result = run(
            ["pacman", "-Sw", "--noconfirm", "--", pkg],
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GatedInstallError(f"Download failed for {pkg}: {error}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GatedInstallError(f"pacman -Sw failed for {pkg}" + (f": {detail}" if detail else ""))


def verify_downloaded(paths: list[str]) -> None:
    """Fail closed if the resolved paths and what actually landed in the
    cache disagree — never scan or install a file we didn't expect."""
    for path in paths:
        if not os.path.isfile(path):
            raise GatedInstallError(
                f"Expected download not found at {path}. Refusing to install "
                "an unverified package set."
            )


def scan_all(paths: list[str]) -> None:
    """Scan every resolved file with Shield's on-demand engine. Any result
    other than a clean verdict aborts the whole batch before install."""
    for path in paths:
        result = scan_path(Path(path), threading.Event())
        if result.outcome != "clean":
            raise GatedInstallError(f"Shield did not clear {path}: {result.detail}")


def install(paths: list[str], run=subprocess.run) -> None:
    """Install already-downloaded, already-scanned local package files."""
    try:
        result = run(
            ["pacman", "-U", "--noconfirm", "--", *paths],
            capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GatedInstallError(f"Install failed: {error}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GatedInstallError("pacman -U failed" + (f": {detail}" if detail else ""))


def run_gated_install(pkg: str, run=subprocess.run) -> None:
    print(f"Resolving download targets for {pkg}...")
    targets = resolve_targets(pkg, run=run)
    print("Will scan before install:\n  " + "\n  ".join(targets))

    print("Downloading (not installing)...")
    download(pkg, run=run)
    verify_downloaded(targets)

    print("Scanning with Shield before install...")
    scan_all(targets)
    print("All files clean.")

    print("Installing...")
    install(targets, run=run)
    print(f"{pkg} installed.")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--"]
    if len(args) != 1:
        print("Usage: darkos-store-gated-install.py -- <package>", file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        print("This must run as root (launched via sudo).", file=sys.stderr)
        return 2
    try:
        run_gated_install(args[0])
    except GatedInstallError as error:
        print(f"Install blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
