# DarkOS status

Updated 2026-10-22 (Calm Dark pass on top of the P0 "repo truth" pass). Tags are the ones defined in
[MASTER-PLAN.md](MASTER-PLAN.md): **[C]** checked in the repo or a sandbox, never on a
booted DarkOS; **[R]** reported, not checked; **[U]** unverified; **[J]** judgment.

## What is true now

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

## Not done yet (next session, in this order)

1. **The Void v2** (see CLAUDE.md "Where we left off"). Only its theme and tab bug are fixed.
2. **App audit:** every launcher's `Exec`/`Icon`, every dependency against
   `packages.x86_64`, every app started on headless sway with its stderr read.
3. Welcome app, task manager, display settings, AC/battery timings, mirror ranking,
   opt-in Store, packaging, Update Center, base diet (the backlog; plan P5+).

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
