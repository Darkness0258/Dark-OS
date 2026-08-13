# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build, Test, and Verify

The build pipeline checks every artifact at multiple stages before accepting the ISO.

- `sudo bash build-iso.sh` -- full build: stages a clean archiso releng profile, pins executable modes and symlinks, builds the pinned Calamares package into a local pacman repo, runs `mkarchiso`, extracts the built SquashFS and verifies executables match source byte-for-byte, then runs `ci/verify-iso.sh`. Publishes `out/darkos.iso` only after every check passes. Set `DARKOS_KEEP_WORK=1` to preserve temp directories for debugging.
- `bash ci/verify-iso.sh out/darkos-*.iso` -- standalone post-build artifact verification: extracts the ISO squashfs and initramfs, checks critical payload files, permissions, executable modes, script syntax, Waybar module set, greetd/ReGreet config, Hyprland/hypridle/hyprlock settings, Plymouth theme, pacman.conf signature checks, systemd symlinks, package list entries, and byte-identical payload scripts.
- `bash ci/build-calamares.sh /tmp/repo` -- builds the pinned Calamares AUR package (commit `167151beb`, version 3.4.2) and publishes a local pacman repo. Accepts `DARKOS_CALAMARES_PACKAGE` + `DARKOS_CALAMARES_PACKAGE_SHA256` to reuse a verified cache.
- `bash -n <script>` -- syntax-check shell scripts. The CI workflow checks all `airootfs/usr/local/bin/*.sh` plus `build-iso.sh`, `ci/build-calamares.sh`, `ci/verify-iso.sh`, and `profiledef.sh`.
- `python -m py_compile <file>` -- syntax-check Python scripts.
- Boot in QEMU (UEFI only): `qemu-system-x86_64 -m 4096 -enable-kvm -cdrom out/darkos.iso -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd -drive if=pflash,format=raw,file=/tmp/darkos-vars.fd`.

## Developing Without a Full Rebuild

Many changes (GTK CSS, shell surface code, Waybar config, Hyprland config) can be iterated on directly inside a running VM without rebuilding the ISO:

- **Shell CSS or panel layout changes:** edit `airootfs/usr/local/bin/darkos-shell.py` in the source checkout, then restart the shell inside the VM with `python /usr/local/bin/darkos-shell.py --toggle-hud` followed by `killall darkos-shell.py` and `python /usr/local/bin/darkos-shell.py &` (or log out/in). The build's byte-identical check will catch any unintended edits when you do eventually run `build-iso.sh`.
- **Waybar config/CSS:** edit the files under `airootfs/etc/xdg/waybar/`, then `killall waybar && waybar &` inside the VM.
- **Hyprland config:** edit `airootfs/etc/xdg/hypr/hyprland.conf`, then `hyprctl reload` inside the VM.

Run the full build only when you need to verify that packaging, permissions, symlinks, and the Calamares build all still pass.

## Project Structure

DarkOS is an ArchISO profile for an AI-first Arch Linux respin. The live ISO payload lives under `airootfs/`. Build inputs are `packages.x86_64`, `pacman.conf`, `profiledef.sh`, and `build-iso.sh`. CI helpers live in `ci/`. Generated ISOs go to `out/`, which also holds ~14 live-testing helper scripts (hot-reload, audit, lock probes, waybar reload, smoke tests) used during Phase 2 development inside a running VM.

Runtime scripts are in `airootfs/usr/local/bin/`, three `.desktop` launchers in `airootfs/usr/share/applications/` (`darkos-installer`, `the-void`, `darkos-tool-groups`), Hyprland/Waybar config in `airootfs/etc/xdg/`, Calamares modules in `airootfs/etc/calamares/`, and systemd enablement in `airootfs/etc/systemd/system/`.

## Architecture

### Shell surface (Phase 2)

The shell is a single GTK3 + gtk-layer-shell Python process (`darkos-shell.py`) that creates five independent layer-shell windows, each anchored separately to a compositor edge. All are owned by `DarkOSApplication` (the single-instance `Gtk.Application`), which owns shared toggle state (`wifi`, `bluetooth`, `dark_mode`, `night_light`, `focus`, `airplane`) and propagates it to registered listeners via `register_state_listener` / `notify_state_listeners`.

- `darkos-dock` -- floating bottom dock (Files, Terminal, Browser, AI Orb, Notes, Store, Settings). Exclusive zone 82px.
- `darkos-hud` -- top-center AI Core radar/dial overlay with activity-linked motion.
- `darkos-rail` -- left-side vertical icon rail (10 actions: AI, Files, Terminal, Settings, Browser, Gallery, Store, Notes, Music, Gaming).
- `darkos-left` -- left-of-center panels (AI chat with waveform, weather stub, system overview with live CPU/GPU/RAM/Disk gauges). Refreshes every 2s via `SystemSampler` reading `/proc/stat`, `/proc/meminfo`, `/sys/class/drm`, and `/proc/net/dev`.
- `darkos-right` -- right-of-center panels (notifications, connectivity toggles, media widget reading `playerctl`, calendar).

The AI Orb cycles through five states (`sleeping`, `listening`, `thinking`, `speaking`, `error`) that also drive the HUD radar animation. All AI requests are stubbed with "Not executed: connect an AI backend" -- no backend exists yet. The visual shell never blocks on the AI backend.

`set_installer_mode(on)` hides all five surfaces and records their visibility; `set_installer_mode(off)` restores them. This is the mechanism `darkos-installer` uses to suspend the shell while Calamares runs.

The shell accepts command-line flags on an existing instance: `--toggle-hud`, `--toggle-ai`, `--toggle-side-panels`, `--toggle-control`, `--toggle-left`, `--toggle-rail`, `--lock`, `--installer-mode on|off`. Hyprland keybinds in `hyprland.conf` call these to show/hide surfaces at runtime. A fresh instance is created on the first `activate()` call; subsequent calls return immediately.

### Installer flow

`darkos-installer` is a session-aware wrapper. It preserves `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, and display variables through `sudo --preserve-env`, sends `--installer-mode on` to the shell process to hide all overlays, runs `calamares`, then restores the shell on exit via a trap. It requires `/run/archiso` to exist (live ISO only), enforced at the wrapper level.

### Bootloader repair

Calamares' bootloader job invokes `darkos-grub-install.sh` (not the built-in `bootloader` module directly). The script validates the ESP is a physical FAT partition with the EFI System Partition type, runs `grub-install --removable --no-nvram`, generates `grub.cfg` to a temp file and atomically moves it only after validation, writes a completion marker to `/var/lib/darkos-grub-repair.done`, and logs everything to `/boot/grub/install.log`. It uses `flock` on `/run/lock/darkos-grub-repair.lock` to prevent concurrent runs.

The `darkos-grub-repair.service` retries on first installed boot only when the completion marker is absent. `ConditionPathExists=!/run/archiso` prevents it from running on the live ISO.

### First-boot BlackArch tool flow

`darkos-firstboot-tools` runs via Hyprland `exec-once` on every session start but acts only once: it skips on the live ISO (`/run/archiso`), skips if a completion or decline marker exists in `~/.config/darkos/`, otherwise shows a wofi dialog. If the user accepts, it launches `darkos-tool-groups` in a terminal for interactive sudo-authenticated group selection.

### Boot and login

Live ISO: `autologin.conf` overrides `getty@tty1.service` to run `darkos-tty1-login`, which autologins as `darkos` only on the live ISO and falls back to a looping getty otherwise. The installed system uses `greetd` + `ReGreet` under `cage` with `GDK_DISABLE=dmabuf,vulkan` and `GSK_RENDERER=cairo` for VMware-safe software rendering.

`start-hyprland` sets `XDG_CURRENT_DESKTOP=Hyprland`, `XDG_SESSION_TYPE=wayland`, `XDG_SESSION_DESKTOP=Hyprland`, and `PYTHONWARNINGS=ignore::SyntaxWarning`, then delegates to the upstream `/usr/bin/start-hyprland` if present, falling back to `/usr/bin/Hyprland`. This wrapper is called from `.bash_profile` via `dbus-run-session -- start-hyprland`.

### Lock and idle

`hypridle` handles idle timeout (locks via `darkos-lock`) and before-sleep. `darkos-lock` is a thin wrapper that selects `LIBGL_ALWAYS_SOFTWARE=1` on VMware automatically (via `/sys/module/vmwgfx` or DMI check) to avoid `wl_surface` invalidation, then delegates to `hyprlock`. It accepts `DARKOS_HYPRLOCK_RENDERER=auto|software|hardware` to override the detection. `hyprlock` uses `screencopy_mode = 1` for CPU-based screencopy on the same VMware path. `hypridle` must not dispatch `dpms off` while `hyprlock` owns the session lock.

### Calamares modules

Custom modules in `airootfs/etc/calamares/modules/` handle the install pipeline: `welcome.conf` (connectivity check), `partition.conf` (LUKS1, small swap), `users.conf`, `removeuser.conf` (removes live `darkos` user), `services-systemd.conf` (enables greetd in installed system), `packages.conf`, `unpackfs.conf`, `shellprocess@bootloader-install.conf` (the guarded wrapper), `shellprocess@pacman-keyring.conf` (stops GnuPG agent before keyring init), and `shellprocess@live-cleanup.conf`. The `settings.conf` `exec:` sequence runs `removeuser` before `users` so the live account is cleaned up before the real one is created; `shellprocess@live-cleanup` removes live-only sudoers and autologin; `grubcfg` writes GRUB defaults (not the actual install); the bootloader runs via `shellprocess@bootloader-install` (not the built-in `bootloader` module) to avoid exit-126 permission failures. `disable-cancel-during-exec` and `hide-back-and-next-during-exec` are both true.

`out/` holds ~14 live-testing helper scripts used during Phase 2 development inside a running VM: `hot-reload-shell.sh`, `collect-final-smoke.sh`, `audit-final-runtime.sh`, `repair-audio-live.sh`, `reload-waybar-live.sh`, `test-lock-dpms-live.sh`, `trigger-lock-live.sh`, `install-lock-config-live.sh`, `collect-lock-crash.sh`, `test-hyprlock-live.sh`, `probe-hyprlock.sh`, `test-darkos-lock-wrapper.sh`, `verify-final-desktop.sh`, and `verify-packaged-lock.sh`.

Three `.desktop` launchers live in `airootfs/usr/share/applications/`: `darkos-installer` (launches the session-aware wrapper), `the-void` (kitty terminal, validated by `desktop-file-validate` in CI), and `darkos-tool-groups` (BlackArch tool picker in a terminal).

### AI control boundaries (non-negotiable)

OS-level actions (volume, brightness, workspaces, launching apps) go through D-Bus + `hyprctl`. Generic in-app control uses AT-SPI (Linux accessibility API), avoiding per-app integrations. Screen understanding uses periodic screenshots + vision model for custom-drawn UI. Never use raw input injection -- Wayland security model blocks it.

## Coding Conventions

Shell scripts use `set -Eeuo pipefail` for build and verification paths. Runtime scripts use `set -euo pipefail` or `set -u` + `set -o pipefail`. All scripts must be executable, shebang-led, and LF-only -- the build rejects missing execute bits and CRLF bytes. Use lowercase `darkos-*` names for project scripts and launchers. Keep installer, systemd, and package changes scoped to their existing directories.

The build enforces a strict list of 11 runtime executables, their permissions (mode 755), shebangs, and CRLF-free content at four stages: source checkout, staged profile, built SquashFS, and final ISO payload. Any mismatch fails the build.

## Build Invariants

`build-iso.sh` and `ci/verify-iso.sh` enforce these on every shipped script:

- Mode `755` in the source checkout, staged profile, and built squashfs.
- A `#!` shebang on the first line.
- LF-only line endings -- CRLF causes exit code 126 at runtime.
- Byte-identical between `airootfs/` source and the packaged squashfs (`cmp -s`).
- Shell scripts pass `bash -n`; the Python shell passes `python -m py_compile`.

`profiledef.sh` declares `file_permissions` as a plain associative array (not `declare -A`), because mkarchiso sources it from inside a function -- `declare -A` would make the map function-local and silently reset every permission to 0644.

## Live ISO vs Installed System

Several scripts behave differently depending on whether `/run/archiso` exists (present on the live ISO, absent on an installed system). This is the canonical discriminator used throughout the codebase:

- `darkos-tty1-login` -- autologins as `darkos` only when `/run/archiso` exists.
- `darkos-firstboot-tools` -- skips entirely on the live ISO.
- `darkos-installer` -- refuses to run without `/run/archiso`.
- `darkos-grub-repair.service` -- `ConditionPathExists=!/run/archiso` prevents first-boot repair on the live ISO.

When changing any of these scripts, verify both paths (live and installed).

## VMware Compatibility

The target test environment is VMware Workstation. Several components have explicit software-rendering paths for VMware's SVGA adapter:

- `the-void.sh` -- forces `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` when `systemd-detect-virt --vm` succeeds.
- `darkos-lock` -- same detection for `hyprlock` + `LIBGL_ALWAYS_SOFTWARE`. Override with `DARKOS_HYPRLOCK_RENDERER=software|hardware` (default `auto`).
- `start-hyprland` and greetd/ReGreet -- `GDK_DISABLE=dmabuf,vulkan` and `GSK_RENDERER=cairo` for software rendering.
- `hyprland.conf` -- `AQ_NO_HARDWARE_CURSORS=1` to avoid cursor issues with llvmpipe.
- `darkos-installer` -- `QT_QUICK_BACKEND=software` for Calamares inside a VM.

Changes that work on bare metal may fail silently in VMware. Test inside the QEMU/VM path before assuming correctness.

## Shell CSS and Design Tokens

`darkos-shell.py` defines color constants in two forms: hex strings for CSS injection and `(r, g, b)` tuples for Cairo rendering. Both derive from `ui-tokens.md`. When changing a token, update both the hex constant and the Cairo tuple, and the corresponding CSS `alpha()` call if the alpha changes. The glow system uses three layered strokes (sharp core, mid glow, outer haze) -- this applies to all Cairo-drawn elements (orb, radar, gauges). GTK widget glow uses CSS `box-shadow` with `alpha(color, 0.20)`.

## CI

GitHub Actions (`.github/workflows/build-iso.yml`) runs on every push to `main` and on manual dispatch. It builds inside an `archlinux` container with `--privileged`, seeds Chaotic-AUR and BlackArch keyrings/mirrorlists, validates all scripts and configs (including `desktop-file-validate` for `.desktop` files and `yaml.safe_load` for Calamares configs), builds the ISO, splits it into 1900M parts, and publishes as a GitHub Release tagged `v<run_number>`.

## Security

`ci/verify-iso.sh` rejects `TrustAll` in the packaged runtime `pacman.conf`. Preserve secure modes for `/etc/shadow` (0600), `/etc/gshadow` (0600), `/root/.gnupg` (0700), and sudoers files (0440/0750). BlackArch and Chaotic-AUR mirror/keyring changes are security-sensitive -- the pinned BlackArch HTTPS endpoint and the verified Chaotic-AUR keyring flow are intentional.

## Project Skill

The `.claude/skills/darkos-build/SKILL.md` skill provides build-specific guidance: how to add a runtime script, a package, or a config file without tripping the enforcement gates, and the Calamares sequence gotchas. Use it when the task touches `build-iso.sh`, `ci/verify-iso.sh`, `profiledef.sh`, `packages.x86_64`, or any file under `airootfs/`.

## Design System Reference

Visual design tokens live in `ui-tokens.md`, layout/motion rules in `ui-rules.md`, and a per-surface component inventory in `ui-registry.md`. All three describe the same Phase 2 shell; `ui-tokens.md` is the source of truth for color values, and `darkos-shell.py` must stay in sync with it.

## Multi-Agent Instructions

`AGENTS.md` (root) and `.agents/AGENTS.md` contain workspace-level multi-agent session rules. Read them when spawning subagents or interpreting agent-framework directives in this repo.

## Phased Roadmap

Phase 1 (bootable Arch + Hyprland + BlackArch ISO) is complete and VM-verified. Phase 2 builds the core shell chrome (top bar, AI Core HUD, dock, rail, side panels). Phases 3-8 cover the assistant, daily-use apps, system management, store/DevHub, hosted apps/gaming/mail, and distributability. Full details in `build-plan.md`.
