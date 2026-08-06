# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**DarkOS** — an original, AI-first Linux OS (Arch respin + BlackArch security tools + Hyprland compositor) with a cinematic glassmorphism/HUD shell and a voice assistant that can see, hear, and control the whole system. This is a real startup product, not a demo.

## Build System

The ISO is built with `archiso`. Local builds and CI run the same pipeline: stage a fresh releng profile, inject a locally-built pinned Calamares as a `[darkos-local]` repo, `mkarchiso`, then verify the artifacts. **There are no unit tests — correctness is enforced at build time** by `build-iso.sh` and `ci/verify-iso.sh` (shebang, exec-bit, CRLF, mode, and content checks on every shipped script).

**Commands:**
- Build ISO locally: `sudo bash build-iso.sh` (must be root; needs archiso + base-devel on an Arch host). Set `DARKOS_KEEP_WORK=1` to preserve its temp dirs on failure.
- Syntax-check a script: `bash -n <file>` (shell) or `python -m py_compile <file>` (`.py`) — `verify-iso.sh` runs both against the built ISO.
- Trigger a CI build: push to `main` or run `workflow_dispatch`. CI builds in a `--privileged` archlinux container, splits the ISO into 1900 MB `darkos-iso-part-*` files, and publishes them as a GitHub Release (`v<run_number>`).
- Output: `out/darkos-*.iso`.

**Pipeline details (enforced by `build-iso.sh`, don't bypass them):**
- Calamares is not in the official repos. `ci/build-calamares.sh` builds a pinned AUR revision (commit `167151b`, v3.4.2-2, source SHA256 verified) into a local pacman repo. Reuse a cached package via `DARKOS_CALAMARES_PACKAGE` + `DARKOS_CALAMARES_PACKAGE_SHA256` (identity and checksum re-verified). `build-iso.sh` injects `[darkos-local]` ahead of all network repos in the staged `pacman.conf`.
- `build-iso.sh` asserts every runtime script is mode 755, has a shebang, and is CRLF-free in the source profile, the staged profile, AND the built squashfs; byte-compares packaged scripts to source; then `ci/verify-iso.sh` re-checks the final ISO payload (required files, shadow/gshadow 0600, account-db consistency, no `TrustAll` in the runtime pacman.conf, blackarch/chaotic repos present, required packages present).
- CI seeds Chaotic-AUR and BlackArch keyrings/mirrorlists manually (not in the profile). Releng base files (`airootfs/`, `efiboot/`) are copied fresh at build time — do not commit files that conflict with them.

## Calamares Installer

`airootfs/etc/calamares/settings.conf` uses **only `show:` and `exec:` phases** — any other phase name causes `FATAL: no sequence set`.

- **The bootloader is NOT a Calamares module anymore.** The sequence runs `shellprocess@bootloader-install`, which invokes `/usr/bin/bash /usr/local/bin/darkos-grub-install.sh` in the target chroot (`dontChroot: false`). Bash invocation survives a lost exec bit (QProcess exits 126) — invoke scripts via `bash` in any shellprocess job. `bootloader.conf` still exists (grubInstall → the wrapper, grubMkconfig no-op, `installEFIFallback: false`) but is deliberately NOT in the sequence — a schema-valid fallback.
- `darkos-grub-install.sh` is the single source of truth for making the installed system bootable (runs during install and as the `darkos-grub-repair.service` first-boot safety net): writes a standard `linux.preset`, removes the live-ISO mkinitcpio drop-in, `mkinitcpio -P`, forces text-mode GRUB (VMware can't draw `gfxterm`), validates/selects a physical ESP (fstab first, lsblk fallback, rejects loop/squashfs devices), `grub-install --removable --no-nvram` (writes `\EFI\BOOT\BOOTX64.EFI`; plain grub-install tries an NVRAM write that fails in a VM/chroot), generates grub.cfg to a temp file and validates it (real `menuentry` + vmlinuz + initramfs) before atomic move, then writes the completion marker. Logs to `/boot/grub/install.log`.
- The live ISO's passwordless `darkos` account is wiped before the real user is created: `removeuser` + `shellprocess@live-cleanup` delete the account, `/etc/sudoers.d/darkos`, the getty autologin override, `darkos-tty1-login`, and `darkos-installer.desktop`, and re-assert exec bits. This lets the buyer choose "darkos" as their username.
- `shellprocess@pacman-keyring`: the live keyring lives on tmpfs (archiso), so the copied target has no durable GnuPG db — it re-initializes with `pacman-key --init --populate archlinux chaotic blackarch`.
- `packages.conf` removes calamares (and installer-only deps) from the installed system.
- The `password` module doesn't exist — the `users` module handles username + password. The installed system has **no autologin** (`users.conf`: `doAutologin: false`, `setRootPassword: true`).
- Module config keys must match what the Python module expects exactly (`source:`/`destination:`, not `src:`/`dest:`) or it throws `KeyError`.

## Runtime Scripts (`airootfs/usr/local/bin/`)

Nine scripts ship in the ISO. All are `100755` in git and `0:0:755` in `profiledef.sh`; several are invoked via `bash`/`sh` to survive exec-bit loss.

- `the-void.sh` — "The Void" terminal launcher (kitty). Sets `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` only when `systemd-detect-virt --vm` reports a VM (kitty needs OpenGL 3.3+); real hardware keeps GPU.
- `darkos-tty1-login` — TTY1 autologin as `darkos` ONLY on the live ISO (`/run/archiso` exists AND the user exists); otherwise loops a normal login getty so TTY1 never blanks.
- `darkos-grub-install.sh` — see the Calamares section.
- `start-hyprland` — session launcher. Sets `XDG_CURRENT_DESKTOP`/`XDG_SESSION_TYPE`/`XDG_SESSION_DESKTOP` and execs `Hyprland` (the package provides `Hyprland`, not `start-hyprland`). Both `.bash_profile` files call `dbus-run-session -- start-hyprland`.
- `darkos-firstboot-tools` + `darkos-tool-groups` — first-boot BlackArch tool-group picker (wofi dialog via Hyprland `exec-once`; skips on live ISO and after `~/.config/darkos/firstboot-tools.done`).
- `darkos-installer` — Calamares launcher that preserves the Wayland/session bus through sudo via an explicit `--preserve-env` whitelist, and uses software Qt rendering in VMs.
- `darkos-shell.py` — Phase 2 shell chrome: GTK3 + LayerShell dock, AI Orb, radar HUD, and control-center side panels, exec-once'd from Hyprland. The AI backend is NOT connected — it's a UI preview; don't claim requests are executed.
- `darkos-diagnose.sh` — bootloader diagnostic: mounts installed root+ESP, reports repair marker, `/boot/grub/install.log`, ESP contents, and grub.cfg entries.

## Key Architecture Decisions

See `architecture.md` for full detail. Essentials:
- **Stack:** Arch base (pacman + AUR), BlackArch as opt-in install-time tool groups, Hyprland (Wayland), Calamares installer.
- **AI control:** OS-level via D-Bus + `hyprctl`; in-app via AT-SPI; screen understanding via periodic screenshot + vision model. **Non-negotiable: no raw input injection (xdotool/spoofing) — control goes through standard IPC/APIs.** The visual shell never blocks on the AI backend. Hosted apps (Firefox, mpv, Steam, Docker) are never modified or forked; visual consistency comes from Hyprland compositor decorations.
- **App strategy:** ~27 native apps with most ~90 features as tabs inside hubs; "Settings" is one app with many tabs.

## Current Status

- **Phase 1 (bootable foundation) builds**; CI publishes ISOs.
- **Installed-system boot is STILL unverified** — nobody has rebooted after a real install. The decisive checks: `/boot/grub/install.log` on the installed system ending clean, plus a real login appearing.
- **Phase 2 (core shell chrome) is active** — `darkos-shell.py` is the working dock/HUD overlay; the AI assistant (Phase 3) is not yet wired.

## Design System Reference

Files: `ui-tokens.md` (primitives) and `ui-rules.md` (layout/conventions).
- **Palette:** pure black `#000000` bg, electric cyan `#00e5ff` primary, neon blue `#2d7bff` secondary, purple `#a855f7` accent. Glass: `rgba(255,255,255,0.06)` fill, `backdrop-filter: blur(24px)`, 16px radius.
- **Layout DNA:** top bar (logo + date/time + tray), left icon rail, central AI Core radar/dial HUD, floating glass side panels, bottom dock with enlarged AI Orb. AI Orb has 5 states (sleeping/listening/thinking/speaking/error) with distinct motion signatures; spring easing, target 120 FPS.
- **Type:** Inter / SF Pro Display for UI, Space Grotesk for headings.

## Phased Roadmap (build-plan.md)

| Phase | Goal |
|-------|------|
| 1 | Bootable Arch + Hyprland + BlackArch ISO ✓ (boot test pending) |
| 2 | Core shell chrome (top bar, HUD, panels, dock, lock screen) — active |
| 3 | AI assistant (STT/TTS/brain, OS control, AT-SPI in-app control) |
| 4 | Daily-use native apps (Files, Terminal, Notes, Calendar, etc.) |
| 5 | System management (Settings hub, Network Center, Security Center) |
| 6 | Store & DevHub |
| 7 | Hosted apps, Mail, Gaming hub |
| 8 | Distributable (real hardware, onboarding flow) |

## Common Tasks

- **Add a package to the ISO:** one name per line in `packages.x86_64`.
- **Add a config file to the ISO:** place under `airootfs/` matching the target path, add permissions to `profiledef.sh`'s `file_permissions` array, and remember `.gitattributes` already forces `eol=lf` on all text.
- **Add/modify a runtime script:** update the script (must be `100755` in git — verify with `git ls-files -s`, fix with `git update-index --chmod=+x`), add its `file_permissions` entry, and add it to `runtime_scripts`/`bash_scripts` arrays in `build-iso.sh` (and the `verify-iso.sh` payload) or the build won't pass.
- **Modify the desktop look:** `airootfs/etc/xdg/hypr/hyprland.conf` (compositor), `waybar/config` + `waybar/style.css` (top bar), `darkos-shell.py` (dock/HUD/side panels).

## Cautions

- **Windows dev box — line endings / exec bit.** Developed on Windows with `core.autocrlf=true`. `.gitattributes` normalizes all text files to LF (`* text=auto eol=lf`; png/webp marked binary). Executable scripts must still be stored `100755` in git. Both `build-iso.sh` and `verify-iso.sh` fail the build on a missing shebang, CRLF bytes, or a lost exec bit — so a broken script surfaces as a loud build failure, not a silent broken ISO. To inspect a committed blob's real bytes: `git show HEAD:<path> | od -c | head -3`.
- **Hyprland 0.55+ Lua migration threat:** Hyprland 0.55 (May 2026) added a Lua `hyprland.lua` format; the old key-value `hyprland.conf` still loads but upstream said support lasts "1-2 releases". CI installs Hyprland unpinned from the rolling repo — a future run could drop old-format support. **Pin the version or migrate before the old format breaks.** The config already uses current `windowrule` syntax and removed the `blur` layer rules because both syntax forms error on the shipped version.
- **Boot mode is UEFI/systemd-boot only** — BIOS/GRUB as a bootmode is backlog (GRUB on the installed system is the fallback-loader flow above).
- **`pacman.conf` uses `SigLevel = Optional TrustAll` for chaotic-aur/blackarch only** (incomplete CI keyring seeding workaround); core/extra/multilib use `Required DatabaseOptional`. Tighten before production use. `verify-iso.sh` additionally fails the build if `TrustAll` leaks into the runtime pacman.conf.
- **kitty VM crash:** kitty requires OpenGL 3.3+, which VMware's virtual GPU often lacks. Worked around VM-only via `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` in `the-void.sh` (VM-gated). Remove on real hardware.
- **Live session auth:** the `darkos` user comes from committed `passwd`/`group`/`shadow` files (sysusers.d can't write a read-only squashfs). `sudoers.d/darkos` uses `%wheel` so a Calamares-created user also gets passwordless sudo during install; `users.conf` sets `setRootPassword: true` so the installed system does not inherit the blank root password.
- **Installed system has NO autologin** — `users.conf` sets `doAutologin: false`, and `darkos-tty1-login` only autologins when `/run/archiso` exists. Re-enable deliberately if boot-to-desktop is ever wanted.
- **`airootfs/` files from the releng profile are NOT committed** — copied fresh each build. If you need a releng-provided config, verify it in the CI copy rather than assuming it's in the repo.
