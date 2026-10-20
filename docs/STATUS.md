# DarkOS status

Updated 2026-10-19 (P0 "repo truth" pass). Tags are the ones defined in
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

## What is not verified

- **Boot, login, lag, install, every keybind, every new setting [U].** Nothing has been
  booted since the removal. This is P1 in the plan, and it needs you.
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
