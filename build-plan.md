# Build Plan

> A phased roadmap, not a wishlist. One phase should be nearly done before the next one gets fleshed out in detail.

## Phase 1: Bootable foundation
Goal — a real, installable Arch + Hyprland + BlackArch OS, even with zero AI or custom shell yet
- [x] Archiso profile: base packages, Hyprland, PipeWire, NetworkManager, Calamares installer
- [x] BlackArch repo wired into `pacman.conf`, tool groups selectable at setup
- [x] Base Hyprland config: tiling, animations, blur, rounded corners
- [x] Boots and installs clean in a VM — Calamares completes the full install flow (partitioning, unpackfs, user/root password, bootloader). `darkos-tool-groups` picker script not yet written; real-hardware boot test still pending.

## Phase 2: Core shell (chrome only)
Goal — the reference mockup's look exists and runs, AI still stubbed
- [ ] Top bar: logo, date/time, system tray, avatar
- [ ] Central AI Core HUD (radar/dial, stub responses)
- [ ] Left icon rail + left-of-center panels (AI chat card, weather, system overview)
- [ ] Right-of-center panels (notifications, connectivity, media widget, calendar)
- [ ] Floating dock (Files, Browser, Terminal, AI, Notes, Store, Settings)
- [ ] Lock screen, login screen, boot animation

## Phase 3: The assistant, for real
Goal — AI / Voice / Vision / Memory / Command / Search / Automate actually work
- [ ] STT + TTS + brain wired in (service choices confirmed — see architecture.md TBDs)
- [ ] OS-level control via D-Bus / hyprctl (open apps, volume, brightness, search)
- [ ] Generic in-app control via AT-SPI, proven on at least 2 apps
- [ ] Wake-word or push-to-talk trigger decided and working

## Phase 4: Daily-use native apps
Goal — the apps someone touches every day exist
- [ ] File Explorer (+ Archive)
- [ ] Terminal (full, not just the Phase 1 shell default)
- [ ] Notes (+ Editor), Calendar, Clock, Calculator
- [ ] Reader, Clipboard manager, Emoji picker, Gallery, Downloads manager

## Phase 5: System management
Goal — Settings actually manages the system. This is where most of the original ~90-item list lands, as tabs, not apps
- [ ] Settings hub: System, Config, Devices, Users, Services, Startup, Storage, Fonts, Icons, Themes, Wallpaper, Motion, Designer, Permissions, Accessibility (Speech, Captions, Magnifier, Keyboard, Eye Control)
- [ ] Network Center (Wi-Fi, Bluetooth, Connect, Cloud)
- [ ] Security Center (Vault, Privacy, Shield, Permissions, Encrypt)
- [ ] Backup / Recovery
- [ ] Dashboard (Performance, Overlay), Mission / Spaces

## Phase 6: Store & DevHub
Goal — installing software and developer tooling both work
- [ ] Store / Packages / Updates, wrapping pacman / AUR / flatpak
- [ ] DevHub wrapping Docker/Podman, QEMU/KVM, git, plugins/extensions, an API client panel

## Phase 7: Hosted apps, Mail, Gaming
Goal — the rest of the daily-driver experience is filled in
- [ ] Browser and media player defaults (Linux-native, unmodified)
- [ ] Wine/Bottles for genuine Windows-only software; Proton for Steam
- [ ] Gaming hub UI (wraps Steam/Lutris/Proton)
- [ ] Basic native Mail client
- [ ] Camera/Webcam, Recorder/Capture

## Phase 8: Make it distributable
Goal — someone other than Hamza could install this and have it work
- [ ] Repeatable respin build script
- [ ] Branding/onboarding flow on first boot
- [ ] Tested on at least one machine that isn't the dev laptop

## Backlog (not sequenced yet)
- BIOS (syslinux) and GRUB boot support — dropped from Phase 1 to get one boot path (UEFI/systemd-boot) fully verified first
- Phone Companion app (separate mobile project)
- Eye tracking / face unlock — hardware-dependent
- Offline/local LLM fallback for no-internet use
- Public release / distribution
- Licensing review pass (see project-overview.md)

---
Each feature line should be small enough to build and review in one sitting. If a line item needs its own sub-checklist, it's really a phase.
