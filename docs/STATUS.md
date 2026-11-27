# DarkOS status

Updated 2026-11-26 (a CI icon fix, on top of the 2026-11-24 CI crash fix and opt-in Store and the
2026-11-07 backlog pass: icons, Welcome, Task Manager, Display, Power & sleep, mirror ranking). Tags are
the ones defined in [MASTER-PLAN.md](MASTER-PLAN.md): **[C]** checked in the repo or a sandbox, never on a
booted DarkOS; **[R]** reported, not checked; **[U]** unverified; **[J]** judgment.

## What is true now

- **CI icon fix, 2026-11-26 [C] (691 -> 692 tests).**
  - **The 2026-11-24 patch was red in `ci/test-ui-consistency.py` [R].** From the log: `emblem-ok-symbolic`, named
    by `darkos-gaming.py` and `darkos-devhub.py`, was the only symbolic icon the UI uses that the runner's theme
    did not have.
  - **Cause [C].** Adwaita 48 deleted the symbolic emblems (upstream NEWS 48.alpha, issue #287). The legacy set 50
    restored (issue #316) has `emblem-important` and `emblem-system`, not `emblem-ok`. The ISO and the runner take
    current Adwaita from Arch, so the DevHub tool status and the Gaming probe status drew the generic placeholder on
    the ISO too. The sandbox's Ubuntu 24.04 has Adwaita 46, which still has the icon, so the test passed here.
  - **Reproduced and fixed [C].** With upstream Adwaita 51.0 plus AdwaitaLegacy 46.2 as the only `Adwaita`, the test
    failed with the CI's exact message; both apps now use `object-select-symbolic`, which is in Adwaita 46 and 51 and
    loads at 16 and 24 px in both. `RemovedIconTests` pins the nine emblem names that are gone and fails on the old
    code in the stock sandbox.
  - **The rest of the step [U on Arch].** The step stops at the first failure, so the tests after this one had not run
    to the end on Arch. Replayed here with Adwaita 51 as the icon theme, all 32 commands pass; that is Ubuntu's GTK
    and Python 3.12, so it is not a CI result. This failure is older than the 2026-11-24 patch (the two lines date from
    September, the test from 2026-10-27); that runs 196-197 failed on it is likely but unverified.
- **CI crash fix and the opt-in Store, 2026-11-24 [C] (607 -> 691 tests, all green on Ubuntu 24.04).**
  - **CI was red at `7bb3a98` [C].** Run 199, step "Run Linux backend and native app regressions", exit
    139 (a segfault). The step's log needs a GitHub login, so which test crashed could not be read [U].
    Runs 196-197 failed in the same step with exit 1 and 198 in the earlier build-iso.sh step (the conflict
    markers); run 199 was the first time the Nov 7 tests ran on Arch at all.
  - **A real crash found in the Task Manager, and fixed [C].** Its table was `ListStore` -> `TreeModelFilter`
    -> `TreeModelSort`; the filter's visible function read the live search text while the search box fires its
    signal ~150 ms late. A sample landing in that gap left GTK 3.24's cached filter state stale and corrupted
    the view's row tree: `_gtk_rbtree_*` assertions abort with asserts on (Ubuntu: exit 134) and would
    segfault with them off (Arch's build: exit 139). Real window, random typing/selecting/sampling: 5 of 6
    seeds aborted before, 0 of 8 after. Filtering is now done by hand into one self-sorting `ListStore`
    (`_sync_rows`). That this is what run 199 hit is [U] until CI is green.
  - **CI now names the culprit.** That step runs with `PYTHONFAULTHANDLER=1` and `set -x`: the last
    `+ python ci/test-...` line and the Python stack identify any crash.
  - **Opt-in Store (plan P8) [C, xvfb + fake pacman/flatpak/sudo].**
    `darkos_shell/store_catalog.py`: 38 apps (31 Arch, 7 Flathub) and six starter packs (Everyday, Student,
    Developer, Creator, Gamer, Office); `recommend(profile)` is the one seam and is static. Sizes, permissions
    and "starts at login" are read live or shown as Unknown, never typed in.
    `store_actions.py`: the install and remove terminal scripts (arguments positional, never interpolated),
    safe deletion of an app's own data (only catalogue folders, inside `$HOME`, never through a symlink),
    parsers for `pacman -Sp/-Si` and Flatpak output.
    `store_browse.py` + `pack_picker.py`: the Store's **Browse** tab (search, categories, an even grid of equal
    cards, source badge, a detail page with sizes, permission chips, "Starts at login", Install / Remove...),
    the **Packs** tab (all unticked; Install selected is the only thing that installs) and the "Keep or
    delete app data?" dialog. Arch apps say Shield scans them; Flathub apps say **Unscanned**.
    Welcome has a new page 4 of 6, "Pick your extras": nothing ticked, Skip and Install selected alike.
    `ci/test-store-catalogue-live.py` checks the 27 catalogue package names that are not already in
    `packages.x86_64` against real pacman databases; it skips here and runs on the Arch runner only.
    The Search tab's notice claimed AUR and Flatpak installs "stay disabled" while the code enables them;
    corrected.

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
- **Fixed since:** the app icons (see the backlog pass above). The one thing still unchecked is
  whether Arch's `adwaita-icon-theme` has every name used; `TESTING-MANUAL.md` 0e.3 is a
  one-line check for it.

## Not done yet (next session, in this order)

1. **Packaging** (PKGBUILDs + signed repo; plan P5). Needs `makepkg` on Arch.
2. **Update Center** (snapshot before update, bootable rollback; plan P6).
3. **Base diet** (move Steam, Wine, Mail, etc. out of the base ISO; plan P4). Its exit test
   is idle RAM and ISO size before/after plus both kernels booting, so it needs an ISO build.
   The packs it moves apps into now exist: Geary and Kooha are in Everyday; Steam, Lutris, Wine (with
   gecko, mono, winetricks) and Waydroid are in Gamer. Not in any pack yet: `lib32-vulkan-intel/radeon/nouveau`
   and `lib32-nvidia-utils` (a GPU-specific choice, and a provider prompt in the gate is unverified).
   `ci/test-gaming.py` and `ci/test-store.py` still expect the apps in the base list.
4. **Store follow-ups:** the Installed and Updates tabs have no Remove / data prompt yet (Browse has);
   README.md is stale (still says "voice assistant", app count 21, now 23); orphans
   `ci/phase-7-audit.md` and `ci/vmware-calamares-plan.template.json` need a decision.

Items 1-3 can only be verified by building and booting an ISO, which this sandbox cannot do.
They were left alone rather than done blind.

## What is not verified

- **Boot, login, lag, install, every keybind, every new setting [U].** Nothing has been
  booted since the removal. This is P1 in the plan, and it needs you.
- **How the redesign looks on Hyprland [U].** Screenshots were taken on headless sway: no
  blur, no `hyprctl`, no Nerd Font (status-bar glyphs showed as boxes there). Also
  unchecked: Waybar's `image` module (the logo) and `makoctl` JSON on Arch's versions
  (tested on Waybar 0.9.24 and mako 1.8 from Ubuntu 24.04).
- **That Hyprland accepts `hyprland.conf` on the shipped version [U].** Run
  `hyprctl configerrors` first (plan Appendix B).
- **Run 199 is red on Arch [C], and its cause is [U].** The Nov 7 tests ran there for the first
  time and a test exited 139. The Task Manager fix above is the likely cause, found by fuzzing
  on Ubuntu; it is not confirmed until CI is green. Check the next run's last `+ python ci/test-...`
  line if it is not.
- **The Store against the real tools [U].** No real `pacman`, `flatpak`, `sudo` or terminal ran: the
  tests put fake binaries on a temp PATH and run the real shell scripts against them. Unchecked:
  `pacman -Sp --print-format %s` on a real system (the live check probes it on CI), the gate chained
  over several packages (it takes one at a time), a provider prompt inside the gate (Steam's
  `lib32-vulkan-driver`), `flatpak remote-add --user`, `flatpak remote-info --show-metadata`,
  `flatpak uninstall --delete-data`, and the Store noticing the terminal closing. The 27 Arch package
  names are typed from knowledge; CI checks them. The 7 Flathub ids were checked to exist in the Flathub
  GitHub organisation. TESTING-MANUAL.md 0f lists what to try.
- **Installer, Btrfs snapshots, ClamAV, firewall on real hardware [U].**
- **The Void v2's live button-click -> context-menu hop on a real pointer [U].** Every
  other part of split panes/engagement/tool launcher/logging/palette/link-matching ran
  against real spawned shells and real VTE under xvfb; only this one interaction (not
  the regex matching behind it, confirmed separately) needs a human with a mouse —
  see `TESTING-MANUAL.md`.
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
