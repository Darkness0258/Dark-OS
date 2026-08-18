# DarkOS Workspace Agent Rules & Guidelines

Welcome to **DarkOS** — an original, AI-first Linux OS (Arch respin + BlackArch security tools + Hyprland compositor) featuring a cinematic glassmorphism/HUD shell and an integrated AI assistant.

---

## 1. Build System & Commands

- **Local ISO Build**: bash build-iso.sh (runs mkarchiso -v -w /tmp/archiso-tmp -o out .)
- **Build Output**: out/
- **CI Workflow**: .github/workflows/build-iso.yml (runs in Arch container on GitHub Actions, produces split ISO releases)
- **Adding Packages**: Append package names (one per line) to packages.x86_64.
- **Adding Config Files**: Place in airootfs/ matching target filesystem path (e.g. airootfs/etc/foo.conf -> /etc/foo.conf). Add any specific permission overrides to profiledef.sh (file_permissions array).

---

## 2. Development & File System Rules (Windows Developer Host)

- **Line Endings & Exec Bits**:
  - Windows host uses core.autocrlf=true. All shell scripts **MUST** maintain Unix LF (\n) line endings to avoid #!/bin/bash\r shebang crashes.
  - Executable scripts MUST have eol=lf in .gitattributes or .sh extension, be stored with 100755 mode in git (git update-index --chmod=+x <file>), and have matching entries in profiledef.sh.
- **CI Releng Copy Overrides**:
  - At CI build time, releng profile defaults are copied into airootfs/. Do NOT commit conflicting base files that break releng seeding.

---

## 3. Architecture & Non-Negotiable Boundaries

- **Shell & Compositor**: Hyprland (Wayland). Control surface via hyprctl and D-Bus IPC.
- **AI Control Surface**:
  - OS-level actions -> D-Bus / hyprctl
  - In-app control -> AT-SPI (Linux Accessibility API)
  - Vision -> periodic screenshot + vision model call
  - *Rule*: Never use raw hardware input injection (e.g. xdotool or direct input synthetic event spoofing).
- **Visual Shell**: Shell graphics / UI must NEVER block on AI model backend calls.
- **App Strategy**:
  - Apps (~27 native apps) use compositor-level decorations (Hyprland blur/glass) for unified aesthetic.
  - Hosted apps (Firefox, mpv, Steam, Docker) are NEVER modified or forked.
  - BlackArch tools are opt-in installer selections, not forced dependencies.

---

## 4. UI & Design System Tokens

- **Palette**:
  - Background: Pure Black #000000
  - Primary Accent: Electric Cyan #00e5ff
  - Secondary Accent: Neon Blue #2d7bff
  - Deep Accent: Purple #a855f7
- **Glassmorphism**:
  - Surface: rgba(255, 255, 255, 0.06)
  - Blur: backdrop-filter: blur(24px)
  - Border Radius: 16px (or standard panel radius)
- **Layout Signature**: Top status bar + Left icon rail + Center HUD radar/dial + Floating side panels + Floating dock with enlarged AI Orb.

---

## 5. Roadmap Status (Phase 2 -> Phase 3 Transition)

- **Phase 1 (Bootable Foundation)**: Completed base archiso, Hyprland desktop config, Waybar, TTY autologin, and Calamares installer config (darkos-grub-install.sh). Fixed critical bug: start-hyprland wrapper script was missing (both .bash_profile files called a non-existent command). Wired darkos-tool-groups into first-boot flow via darkos-firstboot-tools (wofi dialog on first Hyprland start, skips on live ISO and after first run). Verification evidence: see [README.md#phase-1-verification](../README.md#phase-1-verification).
- **Phase 2 (Core Shell Chrome)**: Reviewed 2026-08-13 (Claude Code ultracode pass), VM-verified 2026-08-16 — top bar, AI Core HUD, icon rail, left/right panels, dock, lock screen, and login are done (see ui-registry.md for the full component list). **Open discrepancy:** README.md/CLAUDE.md say the Plymouth boot animation is fully verified on installed hardware; progress-tracker.md's own Blocking section says that specific path is still unverified. Confirm which is accurate before treating Phase 2 as 100% closed. Next real focus is Phase 3 (the assistant) — see build-plan.md.
