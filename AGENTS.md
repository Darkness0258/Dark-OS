# Repository Guidelines

## Project Structure & Module Organization

DarkOS is an ArchISO profile for an AI-first Arch Linux respin. Root-level project docs describe product direction and design: `README.md`, `architecture.md`, `build-plan.md`, `project-overview.md`, `ui-rules.md`, and `ui-tokens.md`.

The live ISO payload lives under `airootfs/`. Runtime scripts belong in `airootfs/usr/local/bin/`, desktop launchers in `airootfs/usr/share/applications/`, Hyprland and Waybar config in `airootfs/etc/xdg/`, Calamares installer modules in `airootfs/etc/calamares/`, and systemd enablement under `airootfs/etc/systemd/system/`. Build inputs are `packages.x86_64`, `pacman.conf`, `profiledef.sh`, and `build-iso.sh`. CI helpers live in `ci/`; generated ISOs and split release artifacts go to `out/`.

## Build, Test, and Development Commands

- `sudo bash build-iso.sh`: builds a clean ISO with ArchISO, builds the pinned Calamares package, repairs executable modes, and verifies the final artifact.
- `bash ci/verify-iso.sh out/darkos-*.iso`: checks critical payload files, permissions, package list entries, service symlinks, and script syntax inside a built ISO.
- `qemu-system-x86_64 -cdrom out/darkos-*.iso -m 4096 -enable-kvm`: boots the ISO locally for VM validation.
- `bash -n <script>`: syntax-checks shell scripts before committing.
- `python -m py_compile airootfs/usr/local/bin/darkos-shell.py`: syntax-checks Python runtime scripts.

## Coding Style & Naming Conventions

Shell scripts use Bash with `set -Eeuo pipefail` for build and verification paths. Keep runtime scripts executable, shebang-led, and LF-only; the build rejects missing execute bits and CRLF bytes. Use lowercase `darkos-*` names for project scripts and launchers. Keep installer, systemd, and package changes scoped to their existing directories.

## Testing Guidelines

There are no unit tests. Correctness is enforced through syntax checks, full ISO builds, and `ci/verify-iso.sh`. For changes under `airootfs/usr/local/bin/`, run the relevant `bash -n` or `python -m py_compile` check. For installer, package, permission, or boot payload changes, run a full `sudo bash build-iso.sh` and boot the resulting ISO in QEMU.

## Commit & Pull Request Guidelines

Recent commit history is informal, so prefer clear imperative commit subjects such as `Fix ISO runtime script permissions` or `Add Calamares package verification`. Pull requests should explain the user-visible change, list validation performed, link related issues, and include screenshots or VM notes for desktop, installer, or boot-flow changes. Mention any unverified real-hardware or installed-system boot behavior explicitly.

## Security & Configuration Tips

Do not weaken runtime package-signature checks; `ci/verify-iso.sh` rejects `TrustAll` in packaged `pacman.conf`. Preserve secure modes for `/etc/shadow`, `/etc/gshadow`, `/root/.gnupg`, and sudoers files. Treat BlackArch and Chaotic-AUR mirror/keyring changes as security-sensitive.
