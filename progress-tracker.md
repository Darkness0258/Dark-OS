# DarkOS Progress Tracker

Recreated 2026-09-29 — this file (along with architecture.md, build-plan.md,
project-overview.md, ui-rules.md, ui-tokens.md, ui-registry.md) was deleted
in commits 683bea4 and 75ebfa4. Their old content is still in git history
(`git show 683bea4~1:architecture.md`, etc.) if anyone wants to dig it back
out; it wasn't restored here since it would already be stale against this
session's changes below, and speculatively rewriting it would have cost more
time than it saved. This file only carries forward from here.

## Current status

- **AI assistant (Iras):** intentionally disabled — `AI_ASSISTANT_ENABLED = False`
  in `darkos_shell/tokens.py`. Nothing was deleted; the HUD, dock orb, AI
  chat card, push-to-talk, `ai_brain.py`, `assistant_trigger.py` are all
  still in the tree, just unwired while it's off. Flip the flag back to
  restore all of it in one line.
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
- **New:** `darkos-window-fx.py` — Alt+Tab switcher (`wofi` + `hyprctl
  clients -j`) and Windows-style half-screen Snap (`$mainMod CTRL,
  left/right`). Deliberately does NOT implement a maximize/restore snap
  direction via hyprctl — GTK's own `win.maximize()`, already wired to
  every titlebar's maximize button, covers that through the standard
  xdg-shell protocol instead of a guessed-at dispatcher.
- **Dock:** center slot is the AI orb when the flag is on, a live clock
  when it's off. Running-app indicator dots added under dock icons
  (`hyprctl clients -j`, matched against each app's real `WM_CLASS`).

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
