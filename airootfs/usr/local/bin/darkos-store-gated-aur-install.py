#!/usr/bin/env python3
"""AUR install: clone, show the PKGBUILD for human review, build as the
invoking (non-root) user, scan the built package with Shield, install only
if it comes back clean.

This is a materially weaker guarantee than darkos-store-gated-install.py's
pacman gate, and says so to the user before building. AUR packages are build
scripts (PKGBUILDs), not pre-built binaries: the PKGBUILD's prepare()/build()/
package() functions run arbitrary shell as whichever user invokes makepkg.
Scanning the *finished* package with Shield is still real defense in depth,
but it cannot undo anything a malicious build step already did — network
access, environment/dotfile reads, whatever the script chose to run. The
actual mitigation here is PKGBUILD transparency: this script prints the full
PKGBUILD and requires an explicit y/N before building anything.

Must NOT run as root — makepkg itself refuses to, and building untrusted
shell as root would defeat the point. Only the final `pacman -U` needs a
password, requested by this script at that point (not upfront), inside the
same terminal darkos-store.py opened via the-void.sh.

Deliberately duplicates GatedInstallError/scan_all from
darkos-store-gated-install.py rather than sharing a module — both are small,
and the two scripts have different privilege models (this one is mostly
unprivileged; that one runs entirely as root). Worth factoring into a shared
darkos_shell module later if a third install path shows up.

Exit code 0 only after pacman -U actually ran against a build that was
confirmed by the user and scanned clean. Every other path — clone failure,
missing PKGBUILD, declined confirmation, build failure, resolution mismatch,
non-clean scan, install failure — exits nonzero and never calls pacman -U.
Like the pacman gate, the git/makepkg/pacman command shapes here are a
source-review judgment call: no AUR-reachable network and no real Arch root
shell were available in the session that wrote this (see progress-tracker.md).
Only the orchestration is tested, via mocked subprocess calls in
ci/test-store-gated-aur-install.py.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.shield import scan_path  # noqa: E402

PKG_NAME_RE = re.compile(r"^[a-zA-Z0-9@._+][a-zA-Z0-9@._+-]*$")


class GatedInstallError(Exception):
    """A validation, clone, review, build, verification, or scan step refused
    to proceed. Raising this anywhere means pacman -U is never reached."""


def validate_pkg_name(pkg: str) -> None:
    if not PKG_NAME_RE.match(pkg):
        raise GatedInstallError(f"Refusing to treat {pkg!r} as an AUR package name.")


def clone(pkg: str, workdir: str, run=subprocess.run) -> Path:
    """Shallow-clone the AUR package's own git repo (the standard, only way
    to fetch its PKGBUILD) as the invoking user. No root, no network trust
    beyond aur.archlinux.org itself."""
    dest = Path(workdir) / pkg
    try:
        result = run(
            ["git", "clone", "--depth", "1", "--",
             f"https://aur.archlinux.org/{pkg}.git", str(dest)],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GatedInstallError(f"Could not clone {pkg} from AUR: {error}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GatedInstallError(f"git clone failed for {pkg}" + (f": {detail}" if detail else ""))
    return dest


def read_pkgbuild(pkg_dir: Path) -> str:
    pkgbuild = pkg_dir / "PKGBUILD"
    try:
        return pkgbuild.read_text(errors="replace")
    except OSError as error:
        raise GatedInstallError(f"Could not read PKGBUILD at {pkgbuild}: {error}") from None


def build(pkg_dir: Path, run=subprocess.run) -> None:
    """Run makepkg as the current (non-root) user. makepkg itself refuses
    root; this checks first so the failure message is ours, not a wall of
    makepkg's own output."""
    if os.geteuid() == 0:
        raise GatedInstallError("Refusing to build a PKGBUILD as root.")
    try:
        result = run(
            ["makepkg", "--syncdeps", "--needed", "--clean", "--noconfirm"],
            cwd=str(pkg_dir), capture_output=True, text=True, timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GatedInstallError(f"Build failed: {error}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GatedInstallError("makepkg failed" + (f": {detail}" if detail else ""))


def resolve_built_packages(pkg_dir: Path, run=subprocess.run) -> list[str]:
    """Ask makepkg what package file(s) this PKGBUILD produces (deterministic
    from pkgname/pkgver/pkgrel/arch — doesn't require having built yet)."""
    try:
        result = run(
            ["makepkg", "--packagelist"],
            cwd=str(pkg_dir), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GatedInstallError(f"Could not resolve built package files: {error}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GatedInstallError("makepkg --packagelist failed" + (f": {detail}" if detail else ""))
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not paths:
        raise GatedInstallError("makepkg --packagelist returned no package files.")
    return paths


def verify_built(paths: list[str]) -> None:
    for path in paths:
        if not os.path.isfile(path):
            raise GatedInstallError(
                f"Expected build output not found at {path}. Refusing to scan or "
                "install an unverified package set."
            )


def scan_all(paths: list[str]) -> None:
    for path in paths:
        result = scan_path(Path(path), threading.Event())
        if result.outcome != "clean":
            raise GatedInstallError(f"Shield did not clear {path}: {result.detail}")


def install(paths: list[str], run=subprocess.run) -> None:
    """Install the built, scanned package(s). This is the one step that
    needs root — asks for it itself, right here, not upfront."""
    try:
        result = run(
            ["sudo", "pacman", "-U", "--noconfirm", "--", *paths],
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GatedInstallError(f"Install failed: {error}") from None
    if result.returncode != 0:
        raise GatedInstallError(f"pacman -U exited {result.returncode}")


def confirm_build(pkgbuild_text: str, pkg: str, prompt=input) -> bool:
    print("=" * 70)
    print(f"PKGBUILD for {pkg}:")
    print("=" * 70)
    print(pkgbuild_text)
    print("=" * 70)
    print(
        "This will run as your user, not root. DarkOS does not scan this "
        "source for malicious behavior before building — review it yourself. "
        "Shield only scans the finished package afterward, which does not "
        "undo anything a bad build step already did."
    )
    answer = prompt(f"Build {pkg} from the PKGBUILD above? [y/N] ").strip().lower()
    return answer == "y"


def run_gated_aur_install(pkg: str, workdir: str, run=subprocess.run, prompt=input) -> None:
    validate_pkg_name(pkg)

    print(f"Cloning {pkg} from AUR...")
    pkg_dir = clone(pkg, workdir, run=run)
    pkgbuild_text = read_pkgbuild(pkg_dir)

    if not confirm_build(pkgbuild_text, pkg, prompt=prompt):
        raise GatedInstallError("Declined after reviewing the PKGBUILD.")

    print("Building (this may ask for a password to install build dependencies)...")
    build(pkg_dir, run=run)

    built = resolve_built_packages(pkg_dir, run=run)
    verify_built(built)

    print("Scanning the built package with Shield...")
    scan_all(built)
    print("Build clean.")

    print("Installing (will ask for your password)...")
    install(built, run=run)
    print(f"{pkg} installed.")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--"]
    if len(args) != 1:
        print("Usage: darkos-store-gated-aur-install.py -- <package>", file=sys.stderr)
        return 2
    if os.geteuid() == 0:
        print(
            "Do not run this as root — it clones and builds as your normal "
            "user, and only asks for a password for the final install step.",
            file=sys.stderr,
        )
        return 2
    workdir = tempfile.mkdtemp(prefix="darkos-aur-")
    try:
        run_gated_aur_install(args[0], workdir)
    except GatedInstallError as error:
        print(f"Install blocked: {error}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
