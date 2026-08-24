# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Commands

- `sudo bash build-iso.sh` — full ISO build: stages a clean archiso releng profile, repairs permissions/symlinks, builds the pinned Calamares package into a local pacman repo, runs `mkarchiso`, extracts the built SquashFS and verifies executables match source byte-for-byte, then runs `ci/verify-iso.sh`. Publishes a versioned ISO (`out/darkos-YYYY.MM.DD-x86_64.iso`) and atomically updates the `out/darkos.iso` symlink. Set `DARKOS_KEEP_WORK=1` to preserve temp directories for debugging.
- `bash ci/verify-iso.sh out/darkos-*.iso` — standalone post-build artifact verification: extracts the ISO squashfs and initramfs, checks critical payload files, permissions, executable modes, script syntax, Waybar module set, greetd/ReGreet config, Hyprland/hypridle/hyprlock settings, Plymouth theme, pacman.conf signature checks, systemd symlinks, package list entries, and byte-identical payload scripts.
- `bash ci/build-calamares.sh /tmp/repo` — builds the pinned Calamares AUR package (commit `167151beb`, version 3.4.2) and publishes a local pacman repo. Accepts `DARKOS_CALAMARES_PACKAGE` + `DARKOS_CALAMARES_PACKAGE_SHA256` to reuse a verified cache.
- `bash -n <script>` — syntax-check shell scripts. CI checks all `airootfs/usr/local/bin/*.sh` plus `build-iso.sh`, `ci/build-calamares.sh`, `ci/verify-iso.sh`, and `profiledef.sh`.
- `python -m py_compile <file>` — syntax-check Python scripts.
- `git ls-files -s <file>` — verify a file's git mode is `100755` (executable tracked in git).
- `git show HEAD:<path> | od -c | head -3` — inspect committed bytes to confirm LF-only line endings.
- Boot in QEMU (UEFI only): copy `OVMF_VARS.4m.fd` to `/tmp/darkos-vars.fd` first, then `qemu-system-x86_64 -m 4096 -enable-kvm -cdrom out/darkos.iso -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd -drive if=pflash,format=raw,file=/tmp/darkos-vars.fd`.

## Developing Without a Full Rebuild

Many changes (GTK CSS, shell surface code, Waybar config, Hyprland config) can be iterated on directly inside a running VM:

- **Shell CSS or panel layout:** edit `airootfs/usr/local/bin/darkos-shell.py` in the source checkout, then restart the shell inside the VM with `python /usr/local/bin/darkos-shell.py --toggle-hud` followed by `killall darkos-shell.py` and `python /usr/local/bin/darkos-shell.py &` (or log out/in). The build's byte-identical check will catch any unintended edits when you eventually run `build-iso.sh`.
- **Waybar config/CSS:** edit files under `airootfs/etc/xdg/waybar/`, then `killall waybar && waybar &`.
- **Hyprland config:** edit `airootfs/etc/xdg/hypr/hyprland.conf`, then `hyprctl reload`.

Run the full build only when you need to verify packaging, permissions, symlinks, and the Calamares build all still pass.

### Live-testing helpers in `out/`

The `out/` directory holds ~14 VM helper scripts for Phase 2 iteration: hot-reload (shell/Waybar/Hyprland), audit (surface inventory), lock probe (hyprlock state), waybar reload, smoke test (post-login surface check), and others. Use these inside a running VM to iterate without rebuilding.

## Validation

There are no unit tests. Correctness is enforced through:

- `bash -n` for shell scripts, `python -m py_compile` for Python.
- Full `sudo bash build-iso.sh` for packaging, permission, symlink, and Calamares changes.
- `bash ci/verify-iso.sh` for post-build artifact checks.
- QEMU boot for installer, bootloader, login, and shell-surface changes.

When in doubt, run the full build and boot the ISO in QEMU.

## Windows Developer Host

This repo is developed on a Windows host with `core.autocrlf=true`. All shell scripts **must** maintain Unix LF (`\n`) line endings — CRLF causes `exit code 126` shebang failures at runtime. Executable scripts must have matching `100755` git mode and `eol=lf` in `.gitattributes`. The build rejects CRLF bytes and missing execute bits at four stages.

## CI Releng Copy Warning

At build time, mkarchiso copies releng profile defaults into `airootfs/`. Do **not** commit conflicting base files (e.g. `airootfs/etc/passwd` from releng) that would break releng seeding — keep only the project's additions and overrides in `airootfs/`.

## Use the `darkos-build` Skill

For any change touching `build-iso.sh`, `ci/verify-iso.sh`, `ci/build-calamares.sh`, `profiledef.sh`, `packages.x86_64`, `pacman.conf`, or any file under `airootfs/`, invoke the `darkos-build` skill. It documents the exact enforcement points for new runtime scripts and prevents tripping build-time checks.

## Project Structure

DarkOS is an ArchISO profile for an AI-first Arch Linux respin. The live ISO payload lives under `airootfs/`. Build inputs are `packages.x86_64`, `pacman.conf`, `profiledef.sh`, and `build-iso.sh`. CI helpers live in `ci/`. Generated ISOs go to `out/`, which also holds ~14 live-testing helper scripts (hot-reload, audit, lock probes, waybar reload, smoke tests) used during Phase 2 development inside a running VM.

Runtime scripts are in `airootfs/usr/local/bin/`, three `.desktop` launchers in `airootfs/usr/share/applications/` (`darkos-installer`, `the-void`, `darkos-tool-groups`), Hyprland/Waybar config in `airootfs/etc/xdg/`, Calamares modules in `airootfs/etc/calamares/`, and systemd enablement in `airootfs/etc/systemd/system/`.

## Stack and Boundaries

- **Base:** Arch Linux respun with `archiso` — inherits pacman + AUR.
- **Security tools:** BlackArch repository layered onto the Arch base via `pacman.conf`.
- **Compositor/shell:** Hyprland (Wayland). Its `hyprctl` IPC socket is the assistant's control surface.
- **Installer:** Calamares (graphical).
- **Login / lock / boot:** greetd + ReGreet under Cage for installed login; `hyprlock` + `hypridle` for session locking; Plymouth for early-boot splash.
- **Shell UI:** GTK3 + gtk-layer-shell Python process creating Wayland layer-shell surfaces.
- **Windows compatibility:** Wine 11 / Bottles / Proton / QEMU/KVM — integration, not custom code.

**Non-negotiable boundaries:**

- System control goes through D-Bus / `hyprctl` / AT-SPI / standard CLI tools — never raw input injection. Wayland's security model blocks synthetic input.
- The visual shell never blocks on the AI backend — if the assistant is offline, the HUD degrades gracefully.
- BlackArch tools are opt-in tool *groups* at install/setup time, not force-installed as one 2,900-package blob.
- Hosted apps are never modified or forked. Visual consistency comes from Hyprland's compositor-level decorations, not app-level changes.
- "Settings" is one app with many tabs, not 20 separate apps.

## Architecture

### Shell surface (Phase 2)

The shell is a single GTK3 + gtk-layer-shell Python process (`darkos-shell.py`) owned by a single `Gtk.Application` instance. A fresh instance is created on the first `activate()` call; subsequent calls return immediately — this is why command-line flags like `--toggle-hud` work on an already-running process. The application owns shared toggle state (`wifi`, `bluetooth`, `dark_mode`, `night_light`, `focus`, `airplane`) and propagates it to registered listeners via `register_state_listener` / `notify_state_listeners`.

Five independent layer-shell windows are anchored separately to compositor edges:

- `darkos-dock` — floating bottom dock (Files, Terminal, Browser, AI Orb, Notes, Store, Settings, Logout via wlogout). Exclusive zone 82px.
- `darkos-hud` — top-center AI Core radar/dial overlay with activity-linked motion.
- `darkos-rail` — left-side vertical icon rail (10 actions: AI, Files, Terminal, Settings, Browser, Gallery, Store, Notes, Music, Gaming).
- `darkos-left` — left-of-center panels (AI chat with waveform, weather stub, system overview with live CPU/GPU/RAM/Disk gauges). Refreshes every 2s via `SystemSampler` reading `/proc/stat`, `/proc/meminfo`, `/sys/class/drm`, and `/proc/net/dev`.
- `darkos-right` — right-of-center panels (notifications, connectivity toggles, media widget reading `playerctl`, calendar).

The AI Orb cycles through five states (`sleeping`, `listening`, `thinking`, `speaking`, `error`) that also drive the HUD radar animation. All AI requests are stubbed with "Not executed: connect an AI backend" — no backend exists yet. The visual shell never blocks on the AI backend.

`set_installer_mode(on)` hides all five surfaces and records their visibility; `set_installer_mode(off)` restores them. This is the mechanism `darkos-installer` uses to suspend the shell while Calamares runs.

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

Hyprlock's config parser treats `#` as a comment delimiter. Any literal `#` inside a string value must be escaped as `##` (e.g. `<span foreground="##9aa4ad">`). This is required for Pango markup color values in `input-field` `placeholder_text` and `fail_text`, and is the same convention catppuccin and other production hyprlock themes use.

### Calamares modules

Custom modules in `airootfs/etc/calamares/modules/` handle the install pipeline: `welcome.conf` (connectivity check), `partition.conf` (LUKS1, small swap), `users.conf`, `removeuser.conf` (removes live `darkos` user), `services-systemd.conf` (enables greetd in installed system), `packages.conf`, `unpackfs.conf`, `shellprocess@bootloader-install.conf` (the guarded wrapper), `shellprocess@pacman-keyring.conf` (stops GnuPG agent before keyring init), and `shellprocess@live-cleanup.conf`.

The `settings.conf` `exec:` sequence runs `removeuser` before `users` so the live account is cleaned up before the real one is created; `shellprocess@live-cleanup` removes live-only sudoers and autologin; `grubcfg` writes GRUB defaults (not the actual install); the bootloader runs via `shellprocess@bootloader-install` (not the built-in `bootloader` module) to avoid exit-126 permission failures. `users` must run before `packages` and `shellprocess@pacman-keyring` — running it last in the exec sequence caused the password hash write to `/etc/shadow` to silently fail in the degraded post-packages chroot. `disable-cancel-during-exec` and `hide-back-and-next-during-exec` are both true.

## Build Pipeline

The build enforces correctness at **four stages**: source checkout, staged profile, built SquashFS, and final ISO payload. Every shipped script must be byte-identical across all four.

The `[darkos-local]` pacman repo is built by `ci/build-calamares.sh` and injected at the top of `pacman.conf` during staging, so the pinned Calamares package always resolves before network repos.

`build-iso.sh` derives a build SHA from the git checkout (or `DARKOS_BUILD_SHA` / `GITHUB_SHA`). The first 8 hex chars are written into `etc/darkos-build-sha` in the staged profile. Build environment issues almost always trace to a missing command or a checkout outside a git repository.

`profiledef.sh` declares `file_permissions` as a plain associative array (not `declare -A`), because mkarchiso sources it from inside a function — `declare -A` would make the map function-local and silently reset every permission to 0644. It also derives `iso_version` from `date +%Y.%m.%d`, so each build gets a date-stamped version.

## Build Invariants

Every script in the `runtime_scripts` list must be:

- Mode `755` in the source checkout, staged profile, built squashfs, **and** final ISO payload — asserted by `assert_runtime_scripts` at four stages.
- Have a `#!` shebang on the first line.
- Free of CRLF bytes (CRLF causes exit code 126 at runtime).
- Byte-identical between `airootfs/` source and the packaged squashfs (`cmp -s`).
- Listed in `bash_scripts` if it's a shell script (passes `bash -n`), or `python_scripts` if it's Python (passes `python -m py_compile`).

When adding a new runtime script, you must update **all four** enforcement points: the source file itself, `profiledef.sh` `file_permissions`, `build-iso.sh` `runtime_scripts` + `bash_scripts`/`python_scripts`, and `ci/verify-iso.sh` `payload` + `scripts` arrays. The `.claude/skills/darkos-build/SKILL.md` skill documents the exact steps.

## Live ISO vs Installed System

Several scripts behave differently depending on whether `/run/archiso` exists (present on the live ISO, absent on an installed system). This is the canonical discriminator used throughout the codebase:

- `darkos-tty1-login` — autologins as `darkos` only when `/run/archiso` exists.
- `darkos-firstboot-tools` — skips entirely on the live ISO.
- `darkos-installer` — refuses to run without `/run/archiso`.
- `darkos-grub-repair.service` — `ConditionPathExists=!/run/archiso` prevents first-boot repair on the live ISO.

When changing any of these scripts, verify both paths (live and installed).

## VMware Compatibility

The target test environment is VMware Workstation. Several components have explicit software-rendering paths for VMware's SVGA adapter:

- `the-void.sh` — forces `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` when `systemd-detect-virt --vm` succeeds.
- `darkos-lock` — same detection for `hyprlock` + `LIBGL_ALWAYS_SOFTWARE`. Override with `DARKOS_HYPRLOCK_RENDERER=software|hardware` (default `auto`).
- `start-hyprland` and greetd/ReGreet — `GDK_DISABLE=dmabuf,vulkan` and `GSK_RENDERER=cairo` for software rendering.
- `hyprland.conf` — `AQ_NO_HARDWARE_CURSORS=1` to avoid cursor issues with llvmpipe.
- `darkos-installer` — `QT_QUICK_BACKEND=software` for Calamares inside a VM.

Changes that work on bare metal may fail silently in VMware. Test inside the QEMU/VM path before assuming correctness.

## Shell CSS and Design Tokens

`darkos-shell.py` defines color constants in two forms: hex strings for CSS injection and `(r, g, b)` tuples for Cairo rendering. Both derive from `ui-tokens.md`. When changing a token, update both the hex constant and the Cairo tuple, and the corresponding CSS `alpha()` call if the alpha changes. The glow system uses three layered strokes (sharp core, mid glow, outer haze) — this applies to all Cairo-drawn elements (orb, radar, gauges). GTK widget glow uses CSS `box-shadow` with `alpha(color, 0.20)`.

## CI

GitHub Actions (`.github/workflows/build-iso.yml`) runs on every push to `main` and on manual dispatch. It builds inside an `archlinux` container with `--privileged` on `ubuntu-latest`. Steps:

1. Install build deps (`archiso`, `base-devel`, `desktop-file-utils`, `python-yaml`, etc.).
2. **Validate profile sources** — `bash -n` on all shell scripts (`build-iso.sh`, `ci/*.sh`, `profiledef.sh`, and every `airootfs/usr/local/bin/*.sh`); `compile()` on `darkos-shell.py`; `yaml.safe_load` on every Calamares `.conf` plus `airootfs/usr/share/calamares/branding/darkos/branding.desc`; `desktop-file-validate` on every `.desktop` launcher.
3. Seed Chaotic-AUR and BlackArch keyrings/mirrorlists, verifying the BlackArch sync DB is non-empty before proceeding.
4. Run `bash build-iso.sh` (no `sudo` — the privileged container runs as root).
5. Split the ISO into 1900M parts and publish as a GitHub Release tagged `v<run_number>`.

## Security

`ci/verify-iso.sh` rejects `TrustAll` in the packaged runtime `pacman.conf`. Preserve secure modes for `/etc/shadow` (0600), `/etc/gshadow` (0600), `/root/.gnupg` (0700), and sudoers files (0440/0750). BlackArch and Chaotic-AUR mirror/keyring changes are security-sensitive — the pinned BlackArch HTTPS endpoint and the verified Chaotic-AUR keyring flow are intentional.

## Design System Reference

Visual design tokens live in `ui-tokens.md`, layout/motion rules in `ui-rules.md`, and a per-surface component inventory in `ui-registry.md`. All three describe the same Phase 2 shell; `ui-tokens.md` is the source of truth for color values, and `darkos-shell.py` must stay in sync with it.

## Multi-Agent Instructions

`AGENTS.md` (root) and `.agents/AGENTS.md` contain workspace-level multi-agent session rules. Read them when spawning subagents or interpreting agent-framework directives in this repo.

## Phased Roadmap

Phase 1 (bootable Arch + Hyprland + BlackArch ISO) is complete and VM-verified. Phase 2 (core shell chrome: top bar, AI Core HUD, dock, rail, side panels, lock screen, login, boot animation) is complete and VM-verified. Phase 3 (AI assistant: STT/TTS/brain, OS control, AT-SPI, push-to-talk, snapshots, Command Center) is complete and VM-verified. Phases 4-8 cover daily-use apps, system management, store/DevHub, hosted apps/gaming/mail, and distributability. Full details in `build-plan.md`.
