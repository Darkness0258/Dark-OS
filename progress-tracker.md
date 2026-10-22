# DarkOS Progress Tracker

Recreated 2026-09-29 — this file (along with architecture.md, build-plan.md,
project-overview.md, ui-rules.md, ui-tokens.md, ui-registry.md) was deleted
in commits 683bea4 and 75ebfa4. Their old content is still in git history
(`git show 683bea4~1:architecture.md`, etc.) if anyone wants to dig it back
out; it wasn't restored here since it would already be stale against this
session's changes below, and speculatively rewriting it would have cost more
time than it saved. This file only carries forward from here.

## Current status

- **AI assistant (Iras):** removed 2026-10-17; the leftovers (including a
  re-add in `a08bc81`) were removed 2026-10-19. `ci/test-polish.py`
  `RemovalTests` fails if any of it returns.
- **Sandboxing (bubblewrap):** `darkos-sandbox-launch.py` exists and is
  hardened (binds `/etc`, gives a private tmpfs scratch `$HOME`) but is
  **not currently wired to any `.desktop` file** — Calculator/Reader/
  Gallery/Clock/Emoji all launch their real binaries directly. Re-enable
  per app by pointing that app's `Exec=`/`TryExec=` back through the
  launcher once it's actually been watched open on a real Wayland session.
- **Window chrome:** every app window now gets a real titlebar (minimize/
  maximize/close) via `app_kit.py`'s `build_titlebar()`, wired into
  `run_app()` for the 19 apps that use it and by hand into
  `darkos-files.py`/`darkos-terminal.py` (the two that predate `run_app`).
- **Performance:** `start-hyprland` now detects VM/no-3D-accel at every
  session start and regenerates `~/.config/hypr/conf.d/perf-auto.conf`
  (sourced from the end of `hyprland.conf`) — disables blur/shadow/
  animations on a detected VM, no-ops on bare metal. Regenerated fresh
  every login, never hand-edited.
- **Window effects:** `darkos-window-fx.py` now owns Alt+Tab (GTK cards +
  grim thumbnails, wofi fallback), Super+E universal search (apps/files/
  settings + system actions such as lock/log out/screenshot/zoom/power
  profile/connect phone), Super+Tab workspace overview, snap layouts (halves, quadrants,
  maximize, Super+Ctrl+Down picker), and Hyprland cursor-zoom magnifier.
  Titlebar maximize hover opens a snap-layout popover. High-contrast lives
  in Settings → Accessibility and `css.py`. Not VM-verified this session.
- **Dock:** center slot is a live clock (the AI orb went away with the
  assistant). Running-app indicator dots added under dock icons
  (`hyprctl clients -j`, matched against each app's real `WM_CLASS`).
  Position (bottom/top/left/right) and size (compact/default/large) are
  settings (Settings → Designer) applied live: the shell watches
  `settings.json`. The default is pixel-identical to before: a full-screen
  diff against the previous commit on the headless compositor, clock text
  masked, found no differing pixel.
- **Verifying without a VM:** `bash ci/headless/run-all.sh` runs the real shell
  on a headless wlroots compositor (sway) and checks the dock matrix, main-
  loop stalls and screenshots. See `ci/headless/README.md` for what that
  does and does not prove (it is not Hyprland).

## 2026-10-12 — Verifying for real without a VM: a shell-wide freeze, the dock, search actions

Environment: a Linux container with GTK3, gtk-layer-shell, a headless wlroots
compositor (sway) and grim. **Not** Hyprland, no real GPU, no `mkarchiso`/
`pacman`. So "verified" below means verified there, and each item says which.

**Tests that had never run, now run.** `test-native-apps-linux.py` starts all
21 native apps under real GTK3 (21/21); `test-continuous-protection.py` and
`test-security-ui.py` pass. The last one had a real test bug (one
`Gtk.Application` per test collides on a session bus: only the first can
register); fixed with a single shared app. Whole suite: 19 files run; all pass.

**Found and fixed: the shell froze itself.** `ActivityDetector._poll` ran on
the GTK main thread every 3 s and shelled out synchronously: `hyprctl`, then
`hyprctl clients`, then (on an empty desktop, i.e. right after boot) a fresh
Python interpreter walking AT-SPI. Measured with a 20 ms main-loop heartbeat
on an emulated empty Hyprland desktop: **45% of the run blocked, 3 s stalls,
before; 0% after.** Fix: detection on a worker thread (result applied on the
main loop) and no AT-SPI helper when `hyprctl` actually answered.
Caveat: the 3 s is this container's number (no accessibility bus, so the
helper hits its timeout); on the VM expect shorter but still periodic freezes.
It is a real defect and a plausible cause of the reported lag, but **not yet
confirmed against the lag on the VM.** `ci/test-activity-detector.py` fails on
the old code (7 of 15 tests) and passes on the new.

**Dock position + size (new).** `dock_position` / `dock_size` in
`settings.json` (validated; bad values fall back), Settings → Designer radio
buttons, applied live by a debounced file watcher; `save_settings` is now
atomic so the watcher never reads a torn file. Compact really shrinks (the
GTK theme's 24 px button min-height needed a CSS override); a vertical dock
stacks the clock hours-over-minutes to stay slim. Verified on headless sway:
all 4 positions x 3 sizes, exact exclusive-zone reservation as seen by a tiled
window, invalid-value fallback, Settings-click -> shell moves
(`ci/headless/dock_matrix.py`, 32/32). **Not verified on Hyprland**, which
should treat layer-shell exclusive zones the same way but is untested.

**Search that does things + screenshots.** Finished the uncommitted draft,
with changes: dropped `pip` (never implemented) and the Open Terminal/Files/
Settings entries (duplicates of the apps), actions only appear once something
is typed (else they sort ahead of every app), and the catalog test now fails
if an action points at a flag `main()` doesn't accept. New `--snip` (region,
`slurp`) / `--snip-screen` (`grim`): saved to `~/Pictures/Screenshots`,
copied with `wl-copy`, notification. Super+Shift+S and Print. `slurp` and
`wl-clipboard` added to `packages.x86_64` (both confirmed in Arch `extra`).
Verified against real `grim`/`wl-copy` with the interactive picker shimmed:
files, clipboard bytes, pixel-exact region crop, Esc cancel, hostile selector
output rejected, delay timing. The image ships Hyprland animations
(`windowsOut 6`, `fade 7`, up to ~0.7 s), which would put a closing overlay
in the shot, so key binds capture at once, the search box passes `--delay 1`,
and a region capture waits 0.5 s after the pick for slurp's overlay to fade.
Those times come from the config, **not measured on Hyprland.** Also **not
verified:** real `slurp`, the `mako` notification, the two key binds.

**CI.** Now runs `test-window-fx.py` (it was never wired in),
`test-activity-detector.py` and `test-dock-layout.py`. `test-performance.py`
needed its `user_settings` stub taught about `CHOICES`. Deliberately not
wired: `test-security-ui.py` / `test-continuous-protection.py` (the CI
container installs `clamav`, so the latter's scan test would not skip there
and I cannot verify it). New CI lines are untested on Arch.

Not done / still open:
- Phase A for real: boot the ISO and Hyprland in the VM (the `nvidia-open-dkms`
  removal is still un-retested), Calamares bootloader step, the 5 sandboxed
  apps, Iras flag, security layers on hardware. Nothing here substitutes.
- Drag-to-edge snap, picture-in-picture, screenshot annotation
  (`swappy`/`satty` aren't packaged), speech/captions/sticky-keys backends.
- `DarkOSDockWindow._refresh_running_indicators` still runs `hyprctl clients
  -j` synchronously every 2 s. Short with a healthy Hyprland, same bug class.
- `continuous_watch.py`, `darkos_cloud.py`, `quarantine.py` are not in the
  `build-iso.sh` / `verify-iso.sh` module lists, so no syntax/byte-identity gate.
- `ci/test-build-bootstrap.sh` needs Arch's `vercmp`; not run here.

## 2026-10-09 — Phase B window chrome + accessibility, Phase C snap/overview

Roadmap file was 2026-09-30; the tree was already past that snapshot (Alt+Tab
wofi list, half-screen snap, Settings a11y flags with no backend). Phase A
(VM boot/lag) cannot run on this Windows host. Implemented what could be
proven with pure-function tests:

- Visual Alt+Tab (`--switcher`): GTK card strip, Windows-style focusHistory
  rotate, grim thumbnails when the window is on the active workspace, wofi
  fallback. Bound to Alt+Tab.
- Universal search (`--search`): `.desktop` apps, recently-used + shallow
  home files, Settings tabs. Super+E. `DARKOS_SETTINGS_TAB` deep-links
  Settings.
- Magnifier: real `hyprctl keyword cursor:zoom_factor` (misc fallback).
  Super+= / Super+- / Super+0. Settings toggle + `--a11y-apply` on login.
- High contrast: `high_contrast` in settings.json, extra CSS in `apply_css()`.
  Speech/captions/sticky keys/eye control still preference-only.
- Snap layouts: quadrants + maximize + Super+Ctrl+Down picker. Maximize
  button hover popover in `app_kit.py`. Super+Tab workspace overview.
- `grim` added to `packages.x86_64`. Tests: `python ci/test-window-fx.py`.

Not done: drag-to-edge snap daemon, speech/captions/sticky-keys compositor
backends, VM boot of this ISO.

## 2026-09-29 — Lag, no close button, 5 apps not opening: found root causes for all three, fixed what's fixable without a real session

**Context:** Hamza booted the ISO from the previous session (blur passes
3→2 patch) and reported it back plainly: heavy lag, "PC unusable," several
apps not opening, no way to close a window with the mouse, UI "boring,"
missing features vs. Windows 10/11. Asked for a fix pass with no more
back-and-forth testing rounds. No GUI/Wayland compositor is available in
this environment (confirmed again: PyGObject is installed here but the
actual GTK3/GtkLayerShell typelibs are not — `gi.require_version("Gtk",
"3.0")` raises `ValueError: Namespace Gtk not available`), so everything
below is static analysis + the existing automated test suite, not a real
boot.

**Lag — three permanent ~30fps Cairo redraw loops, plus no VM-aware
compositor fallback.** Traced every `GLib.timeout_add` in the shell:
`AIOrbCanvas` (dock, 33ms, *always visible*, not gated by Command Center),
`_HUDCanvas` (AI HUD, 33ms), `WaveformCanvas` (AI chat card, 40ms) — all
three purely AI-assistant chrome, all three running from boot forever
regardless of whether anything is happening. Separately: `start-hyprland`
already detects VMware/VirtualBox/QEMU-without-3D-accel and sets
`LIBGL_ALWAYS_SOFTWARE=1` etc., but that only fixes *whether* Hyprland can
render — it does nothing about *how much* it tries to render. Full blur +
shadow + animations on `llvmpipe` (software rasterizer) is a plausible,
maybe the single most likely, explanation for "unusable": a VM without
"Accelerate 3D graphics" enabled would crawl on blur alone, independent of
anything the shell's own Python does. Didn't get an answer on VM-vs-bare-
metal from Hamza this round (he'd moved on to just describing symptoms),
so fixed both paths rather than asking again: pulled the three Cairo loops
out via the AI flag, and made `start-hyprland` regenerate a real
performance override every session based on its own existing VM detection,
rather than a static blur-passes value that's wrong for one of the two
cases no matter what it's set to.

**No close button — root cause confirmed, not guessed.** Grepped every
app window (`grep -rn "class.*Gtk.ApplicationWindow" `): none of the ~20
call `set_decorated(False)`, but none call `set_titlebar()` either.
Hyprland draws no server-side decorations (wlroots compositors generally
don't), and GTK3 draws no automatic fallback titlebar without an explicit
`Gtk.HeaderBar`/custom titlebar widget set. So every app window was
genuinely chrome-less — `SUPER+C` was the only way to close anything,
confirmed by reading `hyprland.conf`'s own keybind list. Fixed with one
shared `build_titlebar()` in `app_kit.py` (custom `Gtk.Box`, not
`Gtk.HeaderBar`, since header-bar button layout depends on a
`gtk-decoration-layout` desktop setting nothing in this session provides)
wired into `run_app()`, covering 19 of the ~20 app files in one change;
`darkos-files.py`/`darkos-terminal.py` needed one line each since they
predate `run_app` and bootstrap by hand.

**5 apps not opening — root cause confirmed by reading bwrap's own
argument list, not by trial and error (couldn't trial-and-error here
anyway — no Wayland session).** Calculator/Reader/Gallery/Clock/Emoji all
route through `darkos-sandbox-launch.py`, whose own docstring already
admitted it was unverified on a real compositor. Its `build_bwrap_args()`
bound `/etc/fonts` but not `/etc` itself — meaning `/etc/passwd` doesn't
exist inside the sandbox, and GLib's user-config-dir lookup (hit at
*import time* by every app, via `tokens.py` → `user_settings.load_settings()`
→ `GLib.get_user_config_dir()`) needs it. This is consistent with these
five specifically failing to open at all, rather than opening broken.
Hardened the bwrap args (bind `/etc`, private tmpfs scratch `$HOME` for
`home_access: none` apps so fontconfig/GLib always have *some* writable
cache) — but since this fix is itself unverified on a real session, chose
not to trust it blind: pointed all five `.desktop` files back at their
real binaries directly (matching how the other ~15 apps already work,
known-good) rather than shipping one unverified fix on top of another and
risking a second round of "still doesn't open."

**Also added**, scoped deliberately narrow rather than attempting a long
shallow list against "more Windows 10/11 features": a live clock in the
dock (replaces the orb when the AI flag is off), running-app indicator
dots under dock icons (`hyprctl clients -j`, matched against each app's
real `WM_CLASS` — confirmed exact class strings from each app's own
`WM_CLASS` constant, not guessed), an Alt+Tab switcher, and Snap-to-half
(`$mainMod CTRL, left/right`). Did **not** attempt: a hyprctl-based
maximize/restore snap direction (Hyprland's exact `fullscreen`/`maximize`
dispatcher argument semantics have changed across versions and
couldn't be confirmed here — GTK's own `win.maximize()`, already wired to
every window's new titlebar button, covers that need through the
protocol-guaranteed path instead); drag-to-edge auto-snap (needs a
persistent window-move-event hook, meaningfully more complex to get right
blind); a Widgets board or Action Center rebuild (the existing right panel
already covers notifications/connectivity, out of scope to redo this
pass).

**Verification, stated at the same honest ceiling as every past entry in
this file:** every touched Python file passes `python3 -m py_compile`;
`start-hyprland` passes `bash -n`. Ran the *entire* existing `ci/test-*.py`
suite before and after (via `git stash`) to isolate real regressions from
pre-existing environment gaps: `test-continuous-protection.py` and
`test-security-ui.py` fail identically on a clean, untouched checkout
(same `Namespace Gtk not available`) — confirmed pre-existing, not caused
here. `test-app-kit.py` *did* catch a real bug this session introduced —
`build_titlebar`'s module-level `Gdk` import broke that test's minimal
`gi.repository` mock, which doesn't define `Gdk` — fixed by moving the
`Gdk` import to be lazy (inside `build_titlebar` itself); reran and
confirmed passing. That's the only piece of this session that got real
automated verification; none of the actual UI/lag/close-button/sandbox
fixes have been run against a real Wayland session, because none is
available in any environment this has run in yet. Treat all of it the way
`darkos-sandbox-launch.py`'s own docstring already treats bwrap: correct
by reading and reasoning carefully, not confirmed by watching it happen.

## 2026-09-29 (later same day) — VM boot hang, before any of the above ever got exercised

Booted the ISO from the previous entry's commits for real (driven directly
against the VM: screenshots, injected input, TTY-switch attempts, ping/SSH,
VMware Tools check). Result: hangs completely at the "CONTROL EVERYTHING"
splash. Not just Hyprland stuck -- TTY switching unresponsive too, no
network ever comes up. First boot: minutes. After a hard reset: same hang
in ~20s.

This is upstream of literally everything in the previous entry -- it never
reaches getty/.bash_profile/start-hyprland, so none of the AI-flag,
titlebar, sandbox, or perf-profile work has been exercised by a real boot
yet, positive or negative.

Found `nvidia-open-dkms` unconditionally in `packages.x86_64`, no real
NVIDIA GPU in the test VM, no mkinitcpio/cmdline config forcing early load
-- DKMS-builds-against-running-kernel-at-first-boot is the leading
hypothesis (fits the minutes-then-seconds pattern), not a confirmed cause.
Removed it (commit `0d8b5f9`). If the next boot still hangs, next real step
is a boot log that doesn't need the hung VM to cooperate (host-side mount
or serial console), not more input injection into an already-stuck guest.

## 2026-10-17 -- Wallpaper + AI removal, lag work, new features

**Removed:** wallpaper (image, generator, swaybg, regreet background, hyprlock
screenshot blur, Settings tab); the whole AI system (Iras brain, voice trigger,
action layer, activity detector, HUD overlay, dock orb, chat card, waveform,
cloud-tier stub, `darkos-ai-snapshot` + sudoers, Calamares API-keys module and
its build step, `espeak-ng` kept for the screen reader). Desktop is a solid
`rgb(0d0f12)` via `misc:background_color`.

**Lag work (unmeasured on the VM -- see TESTING-MANUAL.md section 4):**
dock `hyprctl` poll moved off the GTK main thread and to 3 s; hidden panels no
longer poll; dock clock 1 s -> 20 s; staggered autostart; `darkos-perf-apply`
writes a Lite/Full profile (Lite also removes opacity + rounding; default
"auto" = Lite in a VM); renderer override in Settings; squashfs -> zstd;
netwatch/integrity units run at idle priority; snapshot/integrity timers skip
the live ISO.

**Added:** Settings Performance (effects + renderer), Updates tab
(`checkupdates`/`pkexec pacman -Syu`), Night Light (hyprsunset), Focus (mako DND
mode + `/etc/xdg/mako/config`), PiP (`SUPER+SHIFT+P`), annotated screenshots via
swappy (`SUPER+SHIFT+A`), Orca screen reader toggle, media/brightness keys,
fullscreen, move-to-workspace, mouse move/resize binds. New packages: hyprsunset,
swappy, orca, speech-dispatcher, pacman-contrib (all confirmed in Arch repos
except orca/speech-dispatcher/pacman-contrib, which are standard `extra` but
were not looked up).

**Tests:** 18/18 CI files pass in a GTK/headless sandbox (new: `ci/test-polish.py`).
Deleted tests for removed code. **Not done:** ISO build/boot, Hyprland config
parse of the new lines, any real-device check. Stale VMware harness files listed
in TESTING-MANUAL.md section 10.

## 2026-10-18 -- Wallpapers restored (nine images), plan v2 added

**Restored:** wallpapers, now the nine images supplied by the user (default
`01-midnight-silk.jpg`; thumbnails in `thumbs/`). `darkos_shell/wallpapers.py` owns the
catalogue and starts `swaybg` (new one first, then stops the old, so switching never
flashes); `darkos-window-fx.py --wallpaper-apply` runs at login; Settings > Wallpaper is a
3x3 picker plus "Choose image..." and "Use default"; greeter and lock screen use the
default. The old Settings chooser called `hyprctl hyprpaper` although the ISO used
`swaybg`, so it never changed anything and was never applied at login; that is fixed.
`swaybg` is back in `packages.x86_64`. The AI assistant stays removed.

**Fixed while testing in a headless compositor:** the first wallpaper-grid layout clipped
rows 2-5 (nested fixed-height scroller); dropdowns (`Gtk.ComboBoxText`) had no CSS and
showed light text on a light background, including the existing power-profile dropdown;
disabled buttons looked enabled. Added CSS for combobox, menu, disabled `.action-button`
and `textview`.

**Verified here:** 18/18 CI test files (32 in `ci/test-polish.py`); real `swaybg` under
headless sway applies the default, switches wallpapers and falls back for bad paths;
screenshots of the Wallpaper, Performance and Updates tabs. **Not verified:** ISO build,
boot, Hyprland parsing of the new config lines, lag on the VM or laptop.

**Plan:** `darkos-update-plan.md` (v2, supplied by the user) is now the working plan; a status
section was appended to it. Companion files `darkos-reference-projects.md` and
`darkos-stitch-prompts.md` were not supplied.

## 2026-10-19 — P0 "repo truth" pass (plan: `docs/MASTER-PLAN.md`)

**Done:** reverted `a08bc81` (it re-added 13 removed AI files; 12 byte-identical, the
snapshot script had lost its exec bit); removed the leftovers it exposed (env loader in
`start-hyprland`, AI-era VMware scripts, `.ai-entry`/`.orb-button` CSS, `kitty`); the
workflow now runs every test and `ci/test-ci-coverage.py` fails if one is left out;
fixed dangling doc references in README, CLAUDE.md, AGENTS.md; added `docs/STATUS.md`;
replaced `darkos-update-plan.md` (v2) with `docs/MASTER-PLAN.md` (v5).

**Verified here:** all `ci/test-*` files pass under xvfb in an Ubuntu 24.04 sandbox;
actionlint clean; `start-hyprland` run against a stub Hyprland (old script exported
`LD_PRELOAD` from the user env file, new one does not). **Not verified:** ISO build of
this tree, boot, Hyprland config parsing, lag, install.
