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
- [ ] Boot animation — **confirmed not verified (2026-08-18):** README.md/CLAUDE.md's "fully verified" claim was premature. Config side checked and is fine — `darkos-grub-install.sh` fail-closes on the HOOKS line and theme selection, and the Aug 16 install completing all 34 jobs proves both held. What's actually unknown: whether the splash visually renders during boot. Needs Hamza to report what he actually sees on a real boot before this is fixable.

## Phase 3: The assistant, for real
Goal — AI / Voice / Vision / Memory / Command / Search / Automate actually work
Status: refactor done 2026-08-18. Wiring + new modules completed 2026-08-20. All py_compile clean. Runtime VM verification pending — see checklist below.
- [x] Refactor `darkos-shell.py` — done: split into `darkos_shell/` package (9 modules + 24-line entry point). py_compile clean, LF/permissions verified, existing hyprland.conf keybindings still route correctly.
- [x] STT + TTS + brain **code wired** — `ai_brain.py` wired to chat entry and voice trigger. Chat `on_submit` calls `brain.process_chat()` on a background thread; voice dispatch routes through `process_voice → process_chat → speak`. Orb state transitions (listening/thinking/speaking/error/sleeping) driven by the dispatch chain. `[ ]` Runtime verified: say wake word → audible response, type in chat → response.
- [x] OS-level control via D-Bus / hyprland **code wired** — `actions.py:ActionDispatcher` built with `open_app`, `set_volume`, `set_brightness`, `switch_workspace`, `search`. Brain dispatches via `[ACTION]` markers in LLM replies. Snapshot-before-act wraps all mutating actions. `[ ]` Runtime verified: ask to open an app / change volume and confirm it executes.
- [x] Generic in-app control via AT-SPI **code wired** — `actions.py:_atspi_do_action` walks the AT-SPI tree supporting click, set_text, focus actions. `_atspi_get_selected_text` and `_atspi_get_active_window_text` feed the explain-this path. `[ ]` Runtime verified: proven on at least 2 apps per architecture.md.
- [x] Push-to-talk trigger **code wired** — `assistant_trigger.py` recording path bug fixed (`_recording_path` now stored/returned). Push-to-talk via SUPER+SPACE on dock window. `AssistantTrigger(self.brain)` instantiated and started in `do_activate()`. `[ ]` Runtime verified: hold SUPER+SPACE, speak, hear response.
- [x] Snapshot-before-act **code wired** — `actions.py:_snapshot()` creates Btrfs snapshots at `/.snapshots/darkos-ai-<timestamp>` before any mutating action. Silently skips on non-Btrfs. `[ ]` Runtime verified: trigger an action, confirm `btrfs subvolume list` shows the snapshot.
- [x] "Explain this" **code wired** — `ActionDispatcher.explain()` pulls AT-SPI selected text or active window title, returns it for the brain to explain inline. `[ ]` Runtime verified: select error text, ask "explain this", confirm AI explains it.
- [x] Context-aware shell **code wired** — `ActivityDetector` started in `do_activate()` with `_on_activity_changed` listener. Swaps dock icon highlight and panel visibility per profile (coding/gaming/writing/media/default). `[ ]` Runtime verified: switch between coding app and game, watch layout change.

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
