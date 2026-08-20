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

## Session — 2026-08-17: Plan update (security, AV, cross-platform, look)

Requested: antivirus system, expanded security, a more professional look, broader app/device compatibility, more advanced animations, a more advanced AI, and a client/server split for sold copies.

Actioned this session:
- Antivirus design added — architecture.md § Security & antivirus, build-plan.md Phase 5 (ClamAV + fanotify on-access + rkhunter/AIDE + quarantine)
- Android app compatibility added — architecture.md Stack, build-plan.md Phase 7 (Waydroid)
- ui-rules.md Motion section extended with 4 concrete additions (panel stagger, dock magnetism, transition style, load-reactive background)

Open, not designed yet — needs Hamza's input before any doc goes further:
- **"Professional look."** Correction to the note below from earlier this session: Phase 2 (shell chrome) is actually already built and VM-verified, not unbuilt — see the doc-sync entry just below. So "not built yet" wasn't the real explanation. Still needs Hamza to say what specifically looks off, now that the shell is real and running rather than assumed unbuilt.
- **macOS app support.** Re-asked this session; the 2026-07-22 decision is unchanged (no legal/mature compat layer exists for generic PC hardware) — noting here so it isn't silently relitigated later.
- **"All devices."** If this means DarkOS itself running on phones/tablets, that's already backlogged as the separate Phone Companion project. If it means app compatibility on the current desktop/laptop target, Windows + Linux + Android are now covered and macOS stays out of scope.

**Resolved same session:** client/server ask — Hamza clarified "control" means the server provides different services per tier and centrally stores account/opt-in data, not remote control of the device. Designed as DarkOS Cloud (architecture.md § DarkOS Cloud, build-plan.md Phase 9): accounts, license tiers, cloud AI tier, opt-in sync, signed updates, and opt-in per-session remote support (user-generated code, visible indicator). Client-initiated throughout — the existing no-remote-control boundary holds.

## Session — 2026-08-18: Phase 3 refactor reported complete

Reported: `darkos-shell.py` (1,549 lines) split into a `darkos_shell/` package — `tokens.py`, `canvases.py`, `system_sampler.py`, `css.py`, `surfaces.py`, `ai_brain.py`, `activity_detector.py`, `assistant_trigger.py`, `__init__.py` (24-line entry point). Build system updated to match: `build-iso.sh`, `profiledef.sh`, `ci/verify-iso.sh`.

**Verified per report (build-level only):** all modules pass `py_compile`, LF-only endings, `darkos-shell.py` mode 755/100755, existing `hyprland.conf` keybindings (`--toggle-hud`, `--toggle-ai`, etc.) still route correctly.

**Not yet verified (runtime):** no confirmation of an actual voice round-trip (wake word → Groq transcription → OpenRouter response → edge-tts speech), wake-word/push-to-talk firing in a live session, or activity-detection accuracy / live layout swaps.

**Missing from the module list entirely:** snapshot-before-act (Btrfs/ZFS undo — flagged non-negotiable), "explain this" (AT-SPI error explain+fix), AI-driven D-Bus/hyprctl OS control, and generic AT-SPI in-app control proven on 2+ apps. build-plan.md Phase 3 updated to reflect exactly this — flagged for Hamza to confirm which were skipped vs. just left out of the summary.

## Session — 2026-08-20: Phase 3 wiring — all modules connected

**Requested:** wire the three extracted Phase 3 modules into the running app and build the 4 missing features (snapshot-before-act, explain-this, D-Bus/hyprctl AI control, AT-SPI in-app control).

**Done:**
1. `actions.py` (new) — `ActionDispatcher` with `open_app`, `set_volume`, `set_brightness`, `switch_workspace`, `search`, `explain`, `atspi_click`, `atspi_set_text`. All mutating actions call `_snapshot()` which creates a Btrfs snapshot at `/.snapshots/darkos-ai-<timestamp>`. AT-SPI helpers walk the accessibility tree for generic in-app control.
2. `ai_brain.py` — `AIBrain.__init__` now accepts optional `actions` param. Added `process_chat(text)` → `(reply, actions_summary)` which runs the LLM then scans reply for `[ACTION] method(args)` markers and dispatches them. `_parse_args` handles strings/ints/floats.
3. `assistant_trigger.py` — Fixed recording path bug: `_recording_path` instance variable stores the temp file path from `_start_recording`, returned by `_stop_recording` for all three recorder types (parec/arecord/ffmpeg). Previously returned `None` because `_output_path` was never set on the process.
4. `__init__.py` — `do_activate()` now starts `activity_detector` and `assistant_trigger` with proper listeners. Added `_on_activity_changed` (swaps dock highlight + panel visibility per profile), `_on_voice_activated` (full STT→LLM→TTS pipeline on background thread with `GLib.idle_add` for UI updates), `_set_orb_state`, `_ai_response`, `_ai_error`. Added `actions` lazy property. `trigger` lazy property creates `AssistantTrigger(self.brain)`.
5. `surfaces.py` — `DarkOSDockWindow`: dock icon keys added to `left_apps`/`right_apps` tuples, `_dock_icons` dict tracks buttons for activity highlighting, `set_activity_profile()` highlights matching icon. Added push-to-talk keybinding (SUPER+SPACE press/release) calling `trigger.on_push_to_talk_start/stop`. `DarkOSLeftPanels.on_submit` now runs brain on a background thread via `_run_chat` → `brain.process_chat()`. Added `show_ai_response()` for real AI replies.
6. `build-plan.md` Phase 3 checklist updated to `[x]` for all 8 items with honest "needs runtime verification" notes.
7. `darkos-shell.py` verification markers updated to reflect new wiring.

**Syntax verified:** `python -m py_compile` passes for all 7 files (init, actions, ai_brain, assistant_trigger, activity_detector, surfaces, darkos-shell.py entry point).

**Not verified yet (runtime — needs VM boot):**
- Voice round-trip (hold SUPER+SPACE → speak → hear response)
- Typed chat (enter text → AI response)
- Activity detection (switch apps → layout changes)
- Snapshot creation (`btrfs subvolume list` after action)
- AT-SPI in-app control (proven on 2+ apps)
- Explain-this (select text → AI explains)

## Session — 2026-08-18: Plymouth confirmed, lag diagnosed + fixed

**Plymouth boot animation — Hamza confirmed not verified.** Resolves the README.md/CLAUDE.md vs. progress-tracker.md discrepancy in favor of progress-tracker.md: those two docs' "fully verified on installed hardware" claim was premature and should not be trusted until this is actually re-checked.
Checked `darkos-grub-install.sh`'s Plymouth install steps directly: the HOOKS-line edit and `plymouth-set-default-theme darkos` are both fail-closed (the script calls `fail` and aborts if either doesn't stick), and the Aug 16 VM run completed all 34 install jobs — so on the config side, the resolved HOOKS line containing `plymouth` and the theme being selected are provably fine, or that install would not have completed. `darkos.script` is tracked in source; `darkos.png` is copied into the theme dir from the Calamares icon at build time (build-iso.sh) — theme assets are present, not the problem either.
What's actually still open: whether the splash visually paints during boot — a display/KMS/timing question the source can't answer. **Need Hamza to say what he actually sees on a real boot** (nothing/blank, boot text instead of the splash, a broken image, or too fast to tell) before this is fixable rather than guessed at.

**Lag — three concrete causes found by reading the Phase 2 shell code, not guessed:**
1. `WaveformCanvas.on_draw` called `cr.stroke()` once per bar — 26 separate Cairo rasterization passes every frame instead of one. Fixed: build all 26 segments into one path, stroke once.
2. `AIOrbCanvas` redrew at ~30fps (33ms timer) in every state, including "sleeping" — its default, most-common state, showing only a slow breathing pulse that doesn't need that rate. Fixed: phase still advances every tick, but the actual `queue_draw()` now only fires every 3rd tick while sleeping (~11fps), full rate in every active state.
3. `refresh_media`/`refresh_media_position` ran up to 4 sequential `playerctl` subprocess calls (each up to a 1.5s timeout) directly on the GTK main thread via `GLib.timeout_add` — a slow or unresponsive player would freeze the entire shell for the duration. Fixed: the actual subprocess calls now run in a background thread; results post back to the UI via `GLib.idle_add`. Found and fixed a real bug in the process: the old `refresh_media_position` returned `None` whenever no media was active, which silently kills a repeating `GLib.timeout_add` source — the 2s position-poll timer was likely dying within seconds of every boot.
All three changes verified with `python -m py_compile` and LF-only endings; not verified at runtime (no GTK/Wayland/audio hardware available here) — Hamza should confirm the shell still looks and behaves correctly before this ships.
