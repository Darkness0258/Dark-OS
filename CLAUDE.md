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
│   │   ├── systemd/system/getty@tty1.service.d/autologin.conf  # Auto-login on TTY1
│   │   ├── sudoers.d/darkos
│   │   ├── passwd, group, shadow         # Live session user (darkos auto-login, passwordless)
│   │   ├── calamares/                   # Installer module sequence & branding
│   │   └── pacman.d/                    # Mirrorlists (seeded by CI)
│   ├── usr/share/calamares/branding/darkos/  # Calamares slideshow + product strings
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

**Known issues:**
- Calamares has a module config skeleton and branding, but the install flow hasn't been tested end-to-end yet — may fail on partition layout, unpackfs source paths, or user setup

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
- Calamares configs in `/etc/calamares/` are a minimal skeleton — the module sequence, partitioning, and branding need refinement before Calamares can actually complete an install. The `unpackfs.conf` source path assumes the standard archiso squashfs layout
