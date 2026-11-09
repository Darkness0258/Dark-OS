# DarkOS status

<<<<<<< HEAD
Updated 2026-11-07 (backlog pass: icons, Welcome, Task Manager, Display, Power & sleep, mirror
ranking, on top of The Void v2 + app audit). Tags are the ones defined in
=======
Updated 2026-11-02 (The Void v2 + app audit pass on top of Calm Dark). Tags are the ones defined in
>>>>>>> origin/main
[MASTER-PLAN.md](MASTER-PLAN.md): **[C]** checked in the repo or a sandbox, never on a
booted DarkOS; **[R]** reported, not checked; **[U]** unverified; **[J]** judgment.

## What is true now

- **Backlog pass, 2026-11-07 [C] (branch `calm-dark`, tests 429 -> 607, all green).** In the order asked:
  - **App icons fixed.** Every launcher now uses a symbolic Adwaita name that exists
    (`ci/test-ui-consistency.py` `LauncherIconTests`). Two of the audit's guesses were
    wrong and are corrected in `docs/APP-AUDIT.md` part 1: `utilities-system-monitor` and
    `image-viewer` have no `-symbolic` form either.
  - **Welcome app** (`darkos-welcome.py`): first-run tour on the installed system, install
    entry on the live ISO. It replaces the old wofi first-boot prompts and reuses their
    marker files, so nobody is asked twice.
  - **Task Manager** (`darkos-taskmgr.py`, `Ctrl+Shift+Esc`): reads `/proc` on a worker
    thread, stops sampling while hidden, End task / Force quit with the safety rules.
  - **Settings > Display**: resolution, refresh rate, scale, rotation with a 15 s
    Keep/Revert banner; read back from `hyprctl`, saved only once kept.
  - **Settings > Power & sleep**: separate lock/suspend timings for AC and battery,
    applied to hypridle; `darkos-power-watch.py` switches them when the source changes.
  - **Mirror ranking**: `darkos-mirrors.py` + a Settings > Updates card. Validated,
    backed up, atomic; every failure leaves the current list alone. `choose-mirror` is now
    a wrapper onto it.
  - **`ci/test-registration.py`**: a new app or module must be in `build-iso.sh`,
    `profiledef.sh` and `ci/verify-iso.sh`. It found seven older files in none of them
    (grandfathered by name; the list can only shrink).
  - Every new window was screenshotted under xvfb with the real stylesheet, which found
    six defects the behaviour tests could not see (see `progress-tracker.md`).
- **The AI assistant is gone [C].** Commit `a08bc81` had put 13 removed files back; the
  P0 pass reverted it and removed the leftovers (the `~/.config/darkos/env` loader in
  `start-hyprland`, the AI-era VMware scripts, the dead `.ai-entry` and `.orb-button`
  CSS, `kitty`). `ci/test-polish.py` `RemovalTests` fails if any of it returns.
- **Every test in `ci/` now runs in CI [C].** The workflow had skipped six tests and
  called a deleted one. `ci/test-ci-coverage.py` fails when a `ci/test-*` file is not run
  by `.github/workflows/build-iso.yml`, or the workflow calls a missing file.
- **Tests pass in an Ubuntu 24.04 sandbox with GTK3 under xvfb [C]**, not on Arch and
  not on Arch's Python. The workflow's test step was replayed there; actionlint is clean.
- **CI has built exactly one ISO since the 2026-10-17 removal: release `v194`, which is
  `a08bc81` and contains the AI files [C].** Release tags use the workflow run number and
  `v193` to `v194` are consecutive, so no run happened between them. The AI-free tree has
  not been built by CI yet.

## What changed in the Calm Dark pass (branch `calm-dark`) [C]

- **One palette, generated and checked.** `darkos_shell/palette.py` builds three tonal
  surfaces, text, one accent and semantic colours in OKLCH and validates them against
  the contrast rules for any accent. `tokens.py` and `css.py` are built on it; the old
  token names are aliases. `tools/gen-theme.py` renders Waybar, mako, the login screen
  and the colour lines of hyprlock, Hyprland and Calamares from the same palette, and
  `--check` fails CI on drift.
- **Chrome reduced to a bar, a dock and a panel.** The icon rail, the weather panel,
  the ring gauges, the dock clock, the fake Dark Mode toggle, the Waybar logo text and
  avatar stub are gone. The dock has an Apps button (the `Super+E` overlay). The
  Command Center is one solid panel; sliders read the real volume and brightness,
  notifications come from real `makoctl` output, media only shows while a player runs,
  and its timers stop while it is hidden.
- **Hyprland:** solid app windows, 200-250 ms animations, one accent focus border.
- **Settings:** grouped sidebar, five icons the theme lacked replaced, and a bug fixed
  where the sidebar could highlight one page while another was displayed.
- **The Void:** colours, cursor and font from tokens; tab labels no longer collapse.
- **New tests, all in CI:** `test-design-tokens.py` (46), `test-command-center.py` (20),
  `test-ui-consistency.py` (8), `test-void.py` (7). The headless-sway suite passes
  (dock matrix 32/32, zero main-loop stalls). Writing the tests found three real bugs
  in the new code (sliders and media could never appear; the panel collapsed to a
  sliver; the Settings stack ignored page switches).

## What changed in the Void v2 + app audit pass [C]

- **The Void v2:** split panes, scrollback search, the engagement workspace, session
  logging + save-scrollback, a BlackArch tool launcher, clickable links, a command
  palette. Logic moved into a new GTK-free `darkos_void/` package; `darkos-terminal.py`
  grew from 273 to ~1,020 lines of GTK/VTE chrome. Full detail, including the one real
  bug a test caught (a `child-exited` race during window teardown) and the one thing
  that's a manual spot-check item (the live button-click → context-menu hop), is in
  CLAUDE.md "Where we left off".
- **`ci/test-void.py`: 7 tests -> 55.** Pure-Python coverage for the whole `darkos_void`
  package needs no display; the GTK classes drive real spawned shells under xvfb.
- **App audit, see `docs/APP-AUDIT.md`:** `.desktop` files, imports/external commands
  vs. `packages.x86_64`, every `darkos-*.py` on headless sway with stderr read,
  `pacman.conf`'s `[multilib]`/`[blackarch]`. One real bug found and fixed:
  `darkos-integrity-check.py` crashed outright (not a graceful message) when
  `aide`/`rkhunter` aren't on PATH. New, kept: `ci/headless/app_launch_check.sh`
  (the `launch` check in `run-all.sh`) is what found it, and now guards against it
  coming back.
<<<<<<< HEAD
- **Fixed since:** the app icons (see the backlog pass above). The one thing still unchecked is
  whether Arch's `adwaita-icon-theme` has every name used; `TESTING-MANUAL.md` 0e.3 is a
  one-line check for it.

## Not done yet (next session, in this order)

1. **Opt-in Store** (starter packs, first-run "pick your extras"; plan P8).
2. **Packaging** (PKGBUILDs + signed repo; plan P5). Needs `makepkg` on Arch.
3. **Update Center** (snapshot before update, bootable rollback; plan P6).
4. **Base diet** (move Steam, Wine, Mail, etc. out of the base ISO; plan P4). Its exit test
   is idle RAM and ISO size before/after plus both kernels booting, so it needs an ISO build.
   Do it after the Store has the packs those apps move into.

Items 2-4 can only be verified by building and booting an ISO, which this sandbox cannot do.
They were left alone rather than done blind.
=======
- **Reported, not fixed this pass:** most of the app icons are legacy
  (non-symbolic) names that the real `adwaita-icon-theme` only ships `-symbolic`
  forms of (15 of 21 distinct `Icon=` values) — see `docs/APP-AUDIT.md` part 1 for
  the per-app table and the one Arch-only confirmation it's still missing.

## Not done yet (next session, in this order)

1. **App icons:** rename 15 `.desktop` `Icon=` values per `docs/APP-AUDIT.md` part 1
   (append `-symbolic`, except `clock` and `devhub`/`applications-development`, which
   need a different name entirely).
2. Welcome app, task manager, display settings, AC/battery timings, mirror ranking,
   opt-in Store, packaging, Update Center, base diet (the backlog; plan P5+).
>>>>>>> origin/main

## What is not verified

- **Boot, login, lag, install, every keybind, every new setting [U].** Nothing has been
  booted since the removal. This is P1 in the plan, and it needs you.
- **How the redesign looks on Hyprland [U].** Screenshots were taken on headless sway: no
  blur, no `hyprctl`, no Nerd Font (status-bar glyphs showed as boxes there). Also
  unchecked: Waybar's `image` module (the logo) and `makoctl` JSON on Arch's versions
  (tested on Waybar 0.9.24 and mako 1.8 from Ubuntu 24.04).
- **That Hyprland accepts `hyprland.conf` on the shipped version [U].** Run
  `hyprctl configerrors` first (plan Appendix B).
- **The new CI test lines on Arch's package versions [U].** They only import packages the
  build container already installs, but they have not run there.
- **Installer, Btrfs snapshots, ClamAV, firewall on real hardware [U].**
- **The Void v2's live button-click -> context-menu hop on a real pointer [U].** Every
  other part of split panes/engagement/tool launcher/logging/palette/link-matching ran
  against real spawned shells and real VTE under xvfb; only this one interaction (not
  the regex matching behind it, confirmed separately) needs a human with a mouse —
  see `TESTING-MANUAL.md`.
<<<<<<< HEAD
- **Whether real Arch's `adwaita-icon-theme` has every icon name now used [U].** Names were
  checked against Ubuntu 24.04's Adwaita 46 with the SVG loader present. Same upstream, but
  not the same package or version; `TESTING-MANUAL.md` 0e.3 checks it on the real image.
- **Everything the backlog pass added, on a real Hyprland session [U].** The tests use fake
  `hyprctl`, `reflector`, `pkexec`, `powerprofilesctl`, sysfs and `/proc` trees. None of
  the real tools ran: not `hyprctl keyword monitor` (see MASTER-PLAN H1), not `reflector`,
  not `hypridle -c`, not the polkit prompt, not the swaybg wallpaper apply. The windows
  were screenshotted without a compositor, so blur, rounding and the real title bar were
  not seen. `TESTING-MANUAL.md` 0e lists the checks.
- **Battery behaviour [U].** No battery exists here; AC/battery switching was tested only
  against fake `/sys/class/power_supply` trees.
=======
- **Whether real Arch's `adwaita-icon-theme` has the same symbolic-only gaps found on
  Ubuntu 24.04's [U].** Same upstream GNOME project, so likely, but not the same distro
  packaging; see `docs/APP-AUDIT.md` part 1.
>>>>>>> origin/main

## Hardware on record [R]

Primary PC "Darkness": Intel Core i5-6440HQ, 16 GB RAM, Intel HD 530 plus NVIDIA GeForce
940MX. This answers the plan's D1 for the laptop; the VM host is the same machine.

## Stale on purpose, listed so nobody chases it

- Source comments citing `architecture.md`, `build-plan.md`, `ui-rules.md`, `ui-tokens.md`,
  `ui-registry.md`: those files were deleted in `683bea4`/`75ebfa4`
  (`git show 683bea4~1:<name>`). `ci/hardware-audit.sh` still prints `ui-rules.md`.
- README "Phase 1/2 Verification" sections are old reports **[R]**, not a result on HEAD.
- The VMware automation (`run-vmware-test.ps1` and its guest scripts) was deleted because
  it asserted the removed assistant. A small new harness belongs in P1; the old one is in
  history (`git show 2b149a1:ci/run-vmware-test.ps1`).

## Check which build you are running

`cat /etc/darkos-build-sha` prints the first 8 hex characters of the commit the ISO was
built from. `ls /usr/local/bin/darkos_shell/ai_brain.py` must say "No such file".
