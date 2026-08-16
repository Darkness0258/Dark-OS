# Progress Tracker

## Phase 2 Review — Core Shell Chrome

**Reviewed against:** `e933f489` (Phase 1 baseline)
**Review date:** 2026-08-13
**Reviewer:** Claude Code (ultracode pass)
**Status:** All code fixes applied. ReGreet login path VM-verified on 2026-08-16 (see "Verified in VM" below); the Plymouth boot items remain open (Blocking 1).

---

## Fixes Applied This Pass

1. **Plymouth HOOKS — assertion hardened** — `build-iso.sh` sed anchor is still `udev` (correct: archiso's releng HOOKS array uses udev, not systemd). What changed: added `|| exit 1` on the sed so a failure doesn't pass silently, and replaced the previous "trust sed's exit code" check with a grep that confirms the resolved HOOKS= line contains the literal string `plymouth` — a silent no-op now fails the build. The installed-system path was already correct: `darkos-grub-install.sh:284-306` handles `/etc/mkinitcpio.conf` with udev/systemd fallback and a grep assertion, then runs `mkinitcpio -P` and captures the exit code in the log.
2. **refresh_media timeout stacking — fixed** — changed from `GLib.timeout_add_seconds(2, ...)` to `GLib.timeout_add(5000, ...)` so the 5s interval exceeds the 1.5s `command_output` timeout, preventing overlapping calls.
3. **AI chat card placement — confirmed** — `build_chat_panel()` is in `DarkOSLeftPanels`, not the centered HUD. `AIRadarCanvas` and `DarkOSHUDOverlay` contain only the radar and tagline.
4. **Top bar 24px blur — confirmed rendering** — Hyprland layerrule at `hyprland.conf:90` applies `blur on, blur_popups on` to the Waybar namespace. GTK3 cannot use CSS `backdrop-filter`; blur is compositor-rendered. ui-tokens.md updated to document this.
5. **Quick toggles — confirmed wired** — Wi-Fi uses `nmcli radio wifi`, Bluetooth uses `bluetoothctl power`. Airplane mode disables both. Night Light and Focus are honest preview stubs. Volume uses `pamixer`, brightness uses `brightnessctl`.
6. **BlackArch picker terminal launch — fixed** — routed `darkos-firstboot-tools` through `/usr/local/bin/the-void.sh` (`the-void.sh -e sudo /usr/local/bin/darkos-tool-groups`) instead of bare `kitty`. In VMs without hardware OpenGL 3.3 support, `kitty` silently aborted on context creation; `the-void.sh` applies software rendering fallback (`LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe`) ensuring the interactive terminal selector opens properly.
7. **Now Playing card placement — fixed** — reordered `DarkOSRightPanels` scroller content so `build_media()` renders above `build_connectivity()`, guaranteeing the Now Playing card is immediately visible at top of right panels without scrolling.

## Docs Updated This Pass

- ui-tokens.md: added GTK blur mechanism note
- progress-tracker.md: this file
- build-plan.md Phase 1: already references README verification section (no change needed)
- .agents/AGENTS.md: already references README verification section (no change needed)
- darkos-grub-install.sh: already writes `built_from=<sha>` to the marker (no change needed)

## Verified in VM — 2026-08-16

The erase-disk-install → reboot cycle that previously blocked this page was
executed and confirmed:

- **Login confirmed** — the installed system reaches ReGreet (real login UI, no
  hang, no getty fallback) with the installer ISO disconnected.
- **Password hash confirmed** — the installed `/etc/shadow` holds a real hash
  created by the Calamares `users` module, and the password set during
  installation authenticates through ReGreet/PAM.
- **First-boot dialog confirmed** — `darkos-firstboot-tools` presents its wofi
  "Install BlackArch tools?" prompt on the first installed Hyprland session,
  and correctly skips on the live ISO and after its completion marker.

Pointer: this supersedes the 2026-08-13 "awaiting VM verification" status. The
same 2026-08-16 VM pass also produced the follow-up fixes in `64d4504`
(hyprlock `##` escape) and the shell scroller-height commits `9b16243` /
`75d2021`.

## Blocking

1. **Plymouth on the installed-system path — still unverified:**
   - Installed system's resolved mkinitcpio HOOKS line contains `plymouth`
   - Plymouth splash renders on installed-system boot

## Worth Fixing (future pass, not this one)

1. **darkos-shell.py is a 1400-line monolith** — `DarkOSApplication` class ~170 lines, `DarkOSRightPanels` ~220 lines. Flagged for Phase 3 refactor, not touched in this pass to avoid regressions before VM test.
2. **`progress-tracker.md` stale "Pending" line** — already resolved in this rewrite.

## Verified Clean

- All syntax checks pass: `bash -n` on 9 shell scripts + 4 build scripts, `python -m py_compile darkos-shell.py`
- Build registration complete for all changed files
- No input injection anywhere in the codebase
- Structural decisions (separate windows, shared state on DarkOSApplication) correct
