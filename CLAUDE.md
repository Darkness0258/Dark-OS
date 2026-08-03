# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**DarkOS** — an original, AI-first Linux OS (Arch respin + BlackArch security tools + Hyprland compositor) with a cinematic glassmorphism/HUD shell and a voice assistant that can see, hear, and control the whole system. This is a real startup product, not a demo.

## Build System

The ISO is built using `archiso` (Arch Linux's official ISO creation toolchain). The project follows the standard archiso profile layout.

**Build commands:**
- Build ISO locally: `bash build-iso.sh` (runs `mkarchiso -v -w /tmp/archiso-tmp -o out .`)
- CI builds: triggered on every push via `.github/workflows/build-iso.yml` — runs in an Arch Linux container on GitHub Actions, produces split ISO artifacts (1900MB parts) published as a GitHub Release
- Build output directory: `out/`

**CI quirks to be aware of:**
- CI runs in `--privileged` container mode
- Seeds Chaotic-AUR and BlackArch mirrorlists/keyrings manually (not in the profile itself)
- Copies `/usr/share/archiso/configs/releng/` base files (`airootfs/`, `efiboot/`) at build time — these are NOT committed to the repo
- Uses `softprops/action-gh-release@v2` to publish split ISO parts as releases
- If adding new files to `airootfs/`, ensure they don't conflict with files seeded from the releng profile at CI time

## Project Structure

```
├── airootfs/                    # Files copied into the live ISO root
│   ├── etc/
│   │   ├── xdg/
│   │   │   ├── hypr/hyprland.conf   # Hyprland compositor config
│   │   │   └── waybar/              # Waybar config + CSS (top bar)
│   │   ├── fastfetch/config.jsonc   # Neofetch replacement config
│   │   ├── systemd/system/
│   │   │   ├── getty@tty1.service.d/autologin.conf  # Auto-login on TTY1
│   │   │   └── darkos-grub-repair.service   # First-boot GRUB installer
│   │   ├── sudoers.d/darkos
│   │   ├── passwd, group, shadow         # Live session user (darkos auto-login, passwordless)
│   │   ├── calamares/                   # Installer module configs
│   │   └── pacman.d/                    # Mirrorlists (seeded by CI)
│   ├── usr/
│   │   ├── local/bin/                     # Runtime scripts (see below)
│   │   └── share/
│   │       ├── applications/the-void.desktop  # Branded terminal launcher
│   │       └── calamares/branding/darkos/     # Installer slideshow + icon
│   └── home/darkos/.bash_profile    # Auto-starts Hyprland on TTY1
├── packages.x86_64              # Arch packages to install in the ISO (one per line)
├── pacman.conf                  # Repo config: core, extra, multilib, chaotic-aur, blackarch
├── profiledef.sh                # archiso profile metadata (ISO name, boot modes, file permissions)
├── build-iso.sh                 # Local build script wrapper
├── architecture.md              # Stack, app catalog, AI control mechanism, boundaries
├── build-plan.md                # 8-phase roadmap (Phase 1 = bootable foundation)
├── project-overview.md          # Product vision, success criteria, out-of-scope items
├── ui-tokens.md                 # Design tokens: colors, spacing, typography, glass/glow specs
├── ui-rules.md                  # Layout, motion, interactive states, accessibility rules
└── .github/workflows/build-iso.yml  # CI: builds ISO in Arch container, publishes release
```

## Key Architecture Decisions

See `architecture.md` for full detail. Essential points:

**Stack:**
- Base: Arch Linux respun with `archiso` (pacman + AUR)
- Security tools: BlackArch repo layered via `pacman.conf` (opt-in tool groups, not force-installed)
- Compositor/shell: Hyprland (Wayland) — IPC socket (`hyprctl`) is the AI assistant's control surface
- Installer: Calamares (graphical)
- Windows compatibility: Wine 11 / Bottles / Proton / QEMU/KVM (integration work, not rebuilt)
- macOS compatibility: Does not exist as binary compat — macOS influence is original UI inspired by its UX patterns only

**App catalog:** ~27 native apps (most ~90 features are tabs/sections inside hubs) + hosted tier (real, unmodified software like Firefox, mpv, Docker). Visual consistency from Hyprland's compositor-level decorations, not app-level reskinning.

**AI control mechanism:**
- OS-level actions (volume, brightness, workspaces, launching apps): D-Bus + `hyprctl`
- Generic in-app control: AT-SPI (Linux accessibility API)
- Screen understanding: periodic screenshot + vision-model call

**Non-negotiable boundaries (from architecture.md):**
- System control goes through D-Bus / hyprctl / AT-SPI / standard CLI — never raw input-injection
- The visual shell never blocks on the AI backend
- BlackArch tools are opt-in tool groups at install time, not a 2,900-package blob
- Hosted apps are never modified or forked
- "Settings" is one app with many tabs, not 20 separate apps

## Current Status (Phase 1: Bootable Foundation)

**Done:**
- Archiso profile with base packages, Hyprland, PipeWire, NetworkManager, Calamares
- BlackArch repo wired into `pacman.conf`, CI seeds mirrorlists
- Base Hyprland config (tiling, animations, blur, rounded corners)
- Waybar top bar config + styling
- TTY1 autologin + auto-start Hyprland
- CI builds ISO and publishes to GitHub Releases
- `start-hyprland` wrapper script (was missing — both `.bash_profile` files called a non-existent command; now created at `/usr/local/bin/start-hyprland`)
- `darkos-tool-groups` wired into first-boot flow via `darkos-firstboot-tools` (wofi dialog on first Hyprland start, skips on live ISO and after first run)

**Known issues:**
- Calamares completes the install wizard in a VM (partitioning → unpackfs → user/root password) without fatal errors. The bootloader step runs `darkos-grub-install.sh` **during install** (via `bootloader.conf`'s `grubInstall` key), which builds a standard initramfs (the live ISO's `archiso` preset was wrong for a real disk — without it the kernel can't load the NVMe driver and panics with `VFS: unknown-block(0,0)`), forces text-mode GRUB (VMware can't draw `gfxterm`, showing a blank cursor), installs GRUB `--removable`, and regenerates `grub.cfg`. `darkos-grub-repair.service` remains as a first-boot safety net. However, nobody has rebooted into the installed system yet — it's not yet confirmed that the resulting OS boots, that the passwordless live-session setup is actually replaced, or that the real bootloader entry works. The decisive check is `/boot/grub/install.log` on the installed system ending clean, plus a real login appearing.
- Real-hardware boot test still pending

## Calamares Installer Notes

The Calamares config went through heavy iteration this session. Key lessons:

- **settings.conf sequence must use `show:` and `exec:` phases only** — any other phase name (e.g. `branding:`, `install:`, `postcfg:`) causes `FATAL: no sequence set`
- **The Calamares bootloader modules are back in the exec sequence and work.** The earlier "read-only squashfs chmod" finding applied to scripts executed **from the live squashfs mount itself** (e.g. `darkos-tty1-login` during live boot). Calamares' `bootloader` module runs via `check_target_env_call` → `chroot <installed-root>` — a **writable ext4 partition**, not the squashfs mount — so the wrapper's exec bit (set by `profiledef.sh`, preserved by `unpackfs`) works there.
  - The real VM risk is the **NVRAM boot-entry write**: plain `grub-install` tries to write one, which has no EFI runtime in a VM/chroot and exits without writing the fallback path. Handled by pointing `grubInstall` at `darkos-grub-install.sh`, which passes `--removable` (writes `\EFI\BOOT\BOOTX64.EFI`, which VMware checks) and skips NVRAM.
  - systemd-boot was dropped: its module constructs kernel paths as `<kernelSearchPath>/<version>/<kernelName>`, matching Fedora layouts but not Arch's flat `/boot/vmlinuz-linux`.
  - `darkos-grub-repair.service` remains as a **safety net** on the installed system's first boot (guarded by `!/run/archiso` so it never runs on the live ISO, and by the completion marker so it retries until GRUB is genuinely bootable).
- The `shellprocess` Calamares module may not be available — it isn't in the version packaged for Arch. Don't rely on it.
- For Calamares module config files, key names must match exactly what the Python module expects: `source:` not `src:`, `destination:` not `dest:` — the module throws `KeyError` on abbreviated names.
- The `password` module doesn't exist as a standalone Calamares module; the `users` module handles both username and password on one page.

## Runtime Scripts (`airootfs/usr/local/bin/`)

Five scripts are shipped in the ISO and run at runtime. All are `100755` in git and `0:0:755` in `profiledef.sh`; several are invoked via `sh` to survive exec-bit loss from the CI releng-airootfs merge.

- **`the-void.sh`** — terminal launcher ("The Void", backed by kitty). Sets `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` only when `systemd-detect-virt --vm` reports a VM (kitty needs OpenGL 3.3+, VMware's virtual GPU often lacks it). Real hardware keeps GPU rendering. Referenced by the Hyprland `$mod+Q` keybind and `the-void.desktop`, both via `sh script`.
- **`darkos-tty1-login`** — TTY1 autologin helper. Autologins as `darkos` only when `/run/archiso` exists (live ISO) AND the user exists; otherwise loops a normal login getty forever (so TTY1 never blanks). The `getty@tty1` override calls it directly and re-asserts its exec bit via `ExecStartPre=/bin/sh -c 'chmod +x … || true'` — the `sh -c` wrap is required because systemd's `ExecStartPre` does not run through a shell (a bare `|| true` would be passed to `chmod` as literal filenames).
- **`darkos-grub-install.sh`** — the single source of truth for making the installed system bootable. Runs **both** during install (via `bootloader.conf`'s `grubInstall` key, in the writable Calamares chroot) **and** as a first-boot safety net (`darkos-grub-repair.service`). In one fixed order: ensures a standard `linux.preset` (the inherited live `archiso` one is wrong for a real disk), drops `/etc/mkinitcpio.conf.d/archiso.conf`, builds the initramfs (`mkinitcpio -P` — without it the kernel can't load the NVMe driver), forces text-mode GRUB (`GRUB_TERMINAL_OUTPUT=console`, `GRUB_GFXPAYLOAD_LINUX=text` — VMware can't draw `gfxterm`), mounts the ESP (fstab-first, lsblk fallback), installs GRUB `--removable`, regenerates `grub.cfg`, and writes the completion marker only when a real `menuentry` exists. Logs everything to `/boot/grub/install.log`.
- **`start-hyprland`** — Hyprland session launcher. Both the live ISO and the installed system call `dbus-run-session -- start-hyprland` from their `.bash_profile`. The `hyprland` package provides `Hyprland` (capital H), not `start-hyprland`, so this wrapper bridges the gap: it sets the session environment variables (`XDG_CURRENT_DESKTOP`, `XDG_SESSION_TYPE`, `XDG_SESSION_DESKTOP`) and execs `Hyprland`. Without this script, neither the live session nor the installed system could start the desktop.
- **`darkos-firstboot-tools`** — first-boot BlackArch tool-group picker. Runs via Hyprland `exec-once` on every session start, but only acts once: skips on the live ISO (`/run/archiso` check), skips if the completion marker exists (`~/.config/darkos/firstboot-tools.done`), otherwise shows a wofi dialog asking whether to install BlackArch tool groups. If the user opts in, launches `darkos-tool-groups` in a terminal (kitty + sudo) so the user can enter their password. Writes the marker regardless of the choice so it only fires once.

## Design System Reference

**Files:** `ui-tokens.md` (primitives) and `ui-rules.md` (layout/conventions).

**Palette:** Pure black `#000000` bg, electric cyan `#00e5ff` primary, neon blue `#2d7bff` secondary, purple `#a855f7` accent. Glass surfaces use `rgba(255,255,255,0.06)` fill with `backdrop-filter: blur(24px)` and 16px corner radius.

**Layout DNA:** Top bar (logo + date/time + tray), left icon rail, central AI Core radar/dial HUD, floating glass panels left/right of center, floating bottom dock with AI Orb enlarged at center.

**Motion:** Physics-based spring easing, target 120 FPS, AI Orb has 5 states (sleeping/listening/thinking/speaking/error) each with distinct motion signature.

## Phased Roadmap (build-plan.md)

| Phase | Goal |
|-------|------|
| 1 | Bootable Arch + Hyprland + BlackArch ISO |
| 2 | Core shell chrome (top bar, HUD, panels, dock, lock screen) |
| 3 | AI assistant (STT/TTS/brain, OS control, AT-SPI in-app control) |
| 4 | Daily-use native apps (Files, Terminal, Notes, Calendar, etc.) |
| 5 | System management (Settings hub, Network Center, Security Center) |
| 6 | Store & DevHub |
| 7 | Hosted apps, Mail, Gaming hub |
| 8 | Distributable (tested on real hardware, onboarding flow) |

## Common Tasks

- **Add a package to the ISO:** Add its name (one per line) to `packages.x86_64`
- **Add a config file to the ISO:** Place it under `airootfs/` matching the target path (e.g., `airootfs/etc/foo.conf` → `/etc/foo.conf` on the ISO) and add any required permissions to `profiledef.sh`'s `file_permissions` array
- **Change boot behavior:** Edit `profiledef.sh` bootmodes (currently `uefi.systemd-boot` only; BIOS/GRUB are backlog)
- **Modify the desktop look:** `hyprland.conf` for compositor settings, `waybar/config` and `waybar/style.css` for the top bar
- **Test locally:** Run `bash build-iso.sh` (requires archiso installed on an Arch Linux system or container)
- **Trigger a CI build:** Push to any branch on GitHub — the workflow dispatches on `push` and `workflow_dispatch`

## Cautions

- **Hyprland 0.55+ Lua migration threat:** Hyprland 0.55 (May 2026) introduced a Lua-based `hyprland.lua` config format. The old `hyprland.conf` key-value format still loads but upstream said support lasts "1-2 releases" then gets dropped. The CI pulls `hyprland` from Arch's rolling `extra` repo with no version pin — a future CI run could install a version that no longer supports the old config. **Pin the Hyprland version or migrate to `hyprland.lua` before the old format breaks.** If CI starts failing with "config option does not exist" errors, check whether Hyprland was updated past the deprecation window.
- Boot mode support is currently **UEFI/systemd-boot only** — BIOS and GRUB are explicitly deferred to the backlog
- The CI container is `archlinux:latest` (rolling release) — upstream archiso API changes can break the build. If `mkarchiso` fails after a fresh CI run, check upstream for renamed bootmode identifiers or changed profile conventions
- `airootfs/` files inherited from the releng profile (copied fresh each CI run) are NOT in the repo — if you need a config that the releng profile provides, verify it exists in the CI copy rather than assuming it's committed
- `pacman.conf` uses `SigLevel = Optional TrustAll` for Chaotic-AUR and BlackArch repos only — core/extra/multilib use `Required DatabaseOptional`. This was done to work around incomplete keyring seeding in CI and is acceptable for a live ISO, but should be tightened before any production or persistent install use
- **kitty VM crash:** kitty requires OpenGL 3.3+. VMware's virtual GPU often only exposes an older version through Mesa, causing kitty to abort immediately. The config works around this with `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` set in the keybind and the `.desktop` entry for "The Void". This is a VM-only workaround — remove these env vars when testing on real hardware.
- **Live session auth:** The `darkos` user is created via committed `passwd`/`group`/`shadow` files (not `sysusers.d` — that can't write to a read-only squashfs). The `sudoers.d/darkos` uses `%wheel` (not the `darkos` user directly) so that a Calamares-created installed-system user also gets passwordless sudo during install. The Calamares `users.conf` has `setRootPassword: true` so the installed system does NOT inherit the live session's blank root password.
- **Installed system has NO autologin** — `users.conf` sets `doAutologin: false`, and the `getty@tty1` override delegates to `darkos-tty1-login`, which only autologins as `darkos` when `/run/archiso` exists AND the user exists. So the live ISO auto-logs-in, but a real install prompts for the password — the hardcoded `--autologin darkos` never lands on an installed system (where the `darkos` user doesn't exist). Re-enable `doAutologin` deliberately if boot-to-desktop is ever wanted.
- **Software rendering is VM-gated** — `the-void.sh` only sets `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` when `systemd-detect-virt` reports a VM. The Hyprland `$mod+Q` keybind and `the-void.desktop` both call this launcher, so real hardware (e.g. HD 530) keeps GPU rendering automatically — no manual toggling before hardware tests.
- **Line endings / exec bit — Windows dev box:** This repo is developed on Windows with `core.autocrlf=true` globally set. Any shell script not covered by `.gitattributes` risks two silent bugs: CRLF in the shebang (`#!/bin/bash\r` → exit 126 "bad interpreter") and losing the exec bit in the git blob (mode 100644 → chroot says "not executable", also exit 126). Both manifest as Calamares bootloader failures. **Rules:** every executable script must (a) have a `.gitattributes` `eol=lf` entry or a `.sh` extension, (b) be stored `100755` in git — verify with `git ls-files -s <file>`, set with `git update-index --chmod=+x`, and (c) have a `file_permissions` entry in `profiledef.sh`. To inspect a committed blob's real bytes: `git show HEAD:<path> | od -c | head -3`.