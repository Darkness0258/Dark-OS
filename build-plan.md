# Build Plan

> A phased roadmap, not a wishlist. One phase should be nearly done before the next one gets fleshed out in detail.

## Phase 1: Bootable foundation
Goal — a real, installable Arch + Hyprland + BlackArch OS, even with zero AI or custom shell yet
- [x] Archiso profile: base packages, Hyprland, PipeWire, NetworkManager, Calamares installer
- [x] BlackArch repo wired into `pacman.conf`, tool groups selectable at setup
- [x] Base Hyprland config: tiling, animations, blur, rounded corners
- [x] Calamares install wizard completes in a VM (partition, unpackfs, user/root password, bootloader, reboot prompt) — `darkos-tool-groups` is now wired into the first-boot flow via `darkos-firstboot-tools` (wofi dialog on first Hyprland start, skips on live ISO and after first run). `start-hyprland` wrapper script was missing (both `.bash_profile` files called a non-existent command) — now created at `/usr/local/bin/start-hyprland`. Phase 1 verification evidence: see [README.md#phase-1-verification](README.md#phase-1-verification).

## Phase 2: Core shell (chrome only)
Goal — the reference mockup's look exists and runs, AI still stubbed
**Status: this was already reviewed and VM-verified on 2026-08-16 — not something to start from zero.** See progress-tracker.md and ui-registry.md.
- [x] Top bar: logo, date/time, system tray, avatar — `WaybarTopBar`
- [x] Central AI Core HUD (radar/dial, stub responses) — `AICoreHUD`
- [x] Left icon rail + left-of-center panels (AI chat card, weather, system overview) — `AppIconRail`, `LeftInformationPanels`
- [x] Right-of-center panels (notifications, connectivity, media widget, calendar) — `RightUtilityPanels`
- [x] Floating dock (Files, Browser, Terminal, AI, Notes, Store, Settings) — `FloatingDockAndAIOrb`
- [x] Lock screen, login screen — `SecureLockScreen`, `ReGreetLogin`, VM-confirmed 2026-08-16
- [ ] Boot animation — **flagged, not confirmed either way:** README.md and CLAUDE.md say Plymouth is fully verified on installed hardware; progress-tracker.md's own Blocking section says the installed-system path is still unverified. These two accounts disagree — needs an actual check on real/VM hardware before this line is honestly closed.

## Phase 3: The assistant, for real
Goal — AI / Voice / Vision / Memory / Command / Search / Automate actually work
Status: refactor done and verified 2026-08-18. Everything else below has code written but no confirmed runtime behavior yet, and 2 items don't appear in the refactor at all.
- [x] Refactor `darkos-shell.py` — done: split into `darkos_shell/` package (9 modules + 24-line entry point). py_compile clean, LF/permissions verified, existing hyprland.conf keybindings still route correctly.
- [ ] STT + TTS + brain wired in — `ai_brain.py` built (Groq Whisper → OpenRouter → edge-tts, local fallback whisper.cpp/Ollama/Piper), compiles clean. Not yet confirmed: an actual voice round-trip (wake word → transcription → response → audible speech).
- [ ] OS-level control via D-Bus / hyprctl (open apps, volume, brightness, search) — not clearly addressed in the 2026-08-18 summary; `__init__.py`'s "rail actions, toggles" may be carried-over Phase 2 manual controls, not AI-driven ones. Confirm.
- [ ] Generic in-app control via AT-SPI, proven on at least 2 apps — not in the summary. `activity_detector.py` uses AT-SPI for activity *detection*, a different capability from generically *controlling* an app's UI. Confirm this wasn't dropped.
- [ ] Wake-word or push-to-talk trigger — `assistant_trigger.py` built (parec/arecord/ffmpeg + openwakeword/porcupine). Not yet confirmed: it actually fires in a running session.
- [ ] Snapshot-before-act (Btrfs/ZFS system-wide undo) — not present anywhere in the 2026-08-18 module list. This one was flagged non-negotiable — confirm whether it was skipped or just left out of the summary.
- [ ] "Explain this" (AT-SPI error/crash text → AI explains + fixes) — same, not present in the module list.
- [ ] Context-aware shell — `activity_detector.py` built (AT-SPI/hyprctl → coding/gaming/writing/media → layout suggestions), compiles clean. Not yet confirmed: it correctly detects activity and swaps layout live.

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
- [ ] Shield: ClamAV scan engine + fanotify on-access scanning + rkhunter/AIDE integrity checks + quarantine UI (see architecture.md § Security & antivirus)
- [ ] Network transparency dashboard (per-app, plain-language) — reuses PHANTOM's monitoring core
- [ ] Backup / Recovery
- [ ] Dashboard (Performance, Overlay), Mission / Spaces

## Phase 6: Store & DevHub
Goal — installing software and developer tooling both work
- [ ] Store / Packages / Updates / Games — one search bar wrapping pacman/AUR/Flatpak (native), Wine/Bottles/Proton (Windows + Steam), Waydroid (Android); every install routed through Shield first
- [ ] DevHub wrapping Docker/Podman, QEMU/KVM, git, plugins/extensions, an API client panel

## Phase 7: Hosted apps, Mail, Gaming
Goal — the rest of the daily-driver experience is filled in
- [ ] Browser and media player defaults (Linux-native, unmodified)
- [ ] Wine/Bottles for genuine Windows-only software; Proton for Steam
- [ ] Waydroid for Android/mobile app compatibility
- [ ] Gaming hub UI (wraps Steam/Lutris/Proton)
- [ ] Basic native Mail client
- [ ] Camera/Webcam, Recorder/Capture

## Phase 8: Make it distributable
Goal — someone other than Hamza could install this and have it work
- [ ] Repeatable respin build script
- [ ] Branding/onboarding flow on first boot
- [ ] Tested on at least one machine that isn't the dev laptop

## Phase 9: DarkOS Cloud
Goal — accounts, tiers, and the services that need a server exist (see architecture.md § DarkOS Cloud)
- [ ] Supabase project: accounts, license/tier table, storage buckets for opt-in sync
- [ ] License check on install/boot (which tier this copy is entitled to)
- [ ] Cloud AI tier: route brain calls to hosted model when tier allows, local/free tier otherwise
- [ ] Opt-in encrypted sync/backup (settings, Notes, files) — off by default
- [ ] Signed update manifests, client-pulled
- [ ] Opt-in per-session remote support (user-generated code, visible active-session indicator, auto-expires)
- [ ] Privacy policy section disclosing cloud-AI training data use, with a defined retention window

## Backlog (not sequenced yet)
- BIOS (syslinux) and GRUB boot support — dropped from Phase 1 to get one boot path (UEFI/systemd-boot) fully verified first
- Phone Companion app (separate mobile project)
- Eye tracking / face unlock — hardware-dependent
- Offline/local LLM fallback for no-internet use
- Public release / distribution
- Licensing review pass (see project-overview.md)

---
Each feature line should be small enough to build and review in one sitting. If a line item needs its own sub-checklist, it's really a phase.
