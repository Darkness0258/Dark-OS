# DarkOS Master Plan v5: Build It, Prove It, Then Make It the Best

**Date:** 2026-10-19
**Repo read:** `Darkness0258/Dark-OS`, HEAD `a08bc81` (tag `v194`), shallow clone, 243 tracked files.
**Supersedes:** v4, v3, v2 and the Stitch pack v2. The Stitch pack is Appendix A and the test manual is Appendix B, so this one file is the single source of truth.

## Tags

- **[V]** checked online on 2026-10-18/19 (sources in section 12)
- **[C]** checked in the repo by reading code or running tests in my sandbox. **Never run on a booted DarkOS.**
- **[R]** reported by you, your documents, or a secondary source; not independently checked
- **[U]** unverified: test before relying on it
- **[J]** my judgment or proposal: your call

Rule for the whole project: nothing is "done" in a release note without a test log from the right machine.

---

## 0. What v5 changes

1. **I got something wrong in v4 and I'm correcting it.** v4 (H5) called a Calamares bootloader failure "the last known installer state". Your own README says a fresh UEFI install passed all 34 Calamares jobs on release `v96` (commit `e933f489`), and the repo has a guarded GRUB wrapper `darkos-grub-install.sh` (`--removable --no-nvram`) **[C]**. That evidence is old, so the installer is "re-verify on HEAD", not "broken" (H5).
2. **One repo finding needs your decision today** (R1): commit `a08bc81` re-added the AI assistant files you removed on Oct 17, plus a passwordless sudo rule, and two tests now fail.
3. **The biggest gap is structural** (R4): an installed DarkOS cannot update its own shell or apps. There are no packages for them, so every fix needs a new ISO. Fixing that is what turns a respin into an OS.
4. **"World's best OS, does anything, perfect GUI" is turned into testable bars** (section 1), because nobody can build to an adjective.
5. **Added the layers a real OS needs:** safe updates and rollback, hardware that just works, languages and input, release engineering (sections 4 and 8).
6. **Honest lanes:** "anything" means Linux, Windows apps, Android on supported hardware, web and phone, not macOS apps.

---

## 1. What "best", "anything" and "perfect" can honestly mean

| Your words | Honest meaning | Testable bar |
|---|---|---|
| **World's best OS** | No OS wins everywhere. DarkOS can win a niche that Windows, macOS and stock distros serve badly. Proposed wedge **[J]**: *the Arch-based desktop that never breaks on update, shows its security honestly, and has one calm, consistent GUI.* | A stranger installs it and reaches a usable desktop; an update can always be undone; idle CPU returns to baseline; no control that does nothing |
| **Can do anything inside it** | Lanes, each with an honest label (section 6). Linux apps natively; Windows apps through Wine/Proton/Bottles, or a hidden Windows VM; Android through Waydroid on supported hardware; web apps; phone link. **macOS apps cannot run on it** (Apple's licence terms, my own knowledge **[J]**). | Every lane shows a real "available / not available, because X" state |
| **Perfect GUI** | No GUI is perfect. A GUI can be consistent, complete, accessible, fast and honest. | The GUI bar (section 5): tokens only, every state designed, keyboard-complete, scales 100-200%, readable contrast, no fake metrics |

**What serious peers already do (so the bar is real):**
- **Omarchy 4.0** (an Arch + Hyprland distro): a single-process Quickshell shell, packaged updates, a snapshot on every update with boot-menu rollback, factory reset **[R]**.
- **COSMIC** reached a stable 1.0 and was at Epoch 1.0.8 by Feb 24, 2026 **[R]**.
- **Wayland accessibility is still a weak spot industry-wide.** The "Newton" project exists to fix it (2024 status article) **[R]**. Test Orca and keyboard-only use yourself; don't assume.

If DarkOS can't install cleanly, update safely and be operated without a mouse, "best" is premature. Those three come first.

---

## 2. Ground truth from the repo [C]

Everything here was read in the repo or run in my sandbox. Non-GTK tests ran; GTK tests could not (my sandbox's `gi` is broken), and nothing was booted.

| # | Finding | Why it matters | Action |
|---|---|---|---|
| **R1** | Commit `a08bc81` ("feat: add AI assistant action dispatcher, snapshot safety layer, and test suite") re-added the AI assistant files, including `airootfs/etc/sudoers.d/darkos-ai-snapshot`: `%wheel ALL=(root) NOPASSWD: /usr/local/bin/darkos-ai-snapshot ""`. The README says the AI was removed 2026-10-17. Nothing references the files. | A dormant privilege grant that contradicts the docs. The helper takes no arguments and only creates a read-only Btrfs snapshot, so direct risk is low, but unreferenced root access should not ship. Also `ci/test-polish.py` `RemovalTests` (2 tests: files removed; no references remain) **fail at HEAD**. | Decide D0. If unintended, revert the re-add. If intended, update README/tests and justify the sudo rule. Possible innocent cause: CI still called a deleted `ci/test-activity-detector.py` at the previous commit; I can't tell your intent. |
| **R2** | CI runs 13 test groups. It does **not** run `test-polish.py`, `test-phase3-linux.py`, or the headless Sway checks in `ci/headless/`. At HEAD these pass in my sandbox: window-fx, performance, store, shield, mail, gaming, network-connect, calculator-clock, native-storage, app-kit, store-gated-install, store-gated-aur-install, integrity-check, activity-detector, phase3-linux. | Tests nobody runs rot. R1's failures went unnoticed for exactly this reason. | P0: run everything in CI, or delete what you won't maintain. |
| **R3** | `hyprctl` is called from separate helpers: `darkos-window-fx.py:189` (`timeout=2`), `darkos-mission.py:51` (`timeout=3`). The magnifier calls `hyprctl keyword` (window-fx ~1087). | Hazard H1: the Lua config change can break these silently. | P2: one `hypr.py`. |
| **R4** | The installed system is a **copy of the live ISO's squashfs** (`unpackfs.conf`). There are **0 PKGBUILDs**. The local pacman repo `darkos-local` holds only the pinned Calamares. Settings > Updates runs `checkupdates`, then `pkexec pacman -Syu --noconfirm`. | That updates Arch packages, never DarkOS's own shell and apps. A user who installed last month never gets today's fix, short of reinstalling. Not an OS yet. | P5: package DarkOS and host a repo. |
| **R5** | Update has no snapshot first. `darkos-snapshot.py` takes hourly read-only snapshots (nested `/.snapshots`, last 48 kept); restore only stages a copy and prints manual steps. No boot-menu rollback. | The riskiest button in the OS (Update) has no undo. | P6. |
| **R6** | Package repos are unpinned. The runtime `pacman.conf` enables Chaotic-AUR and BlackArch by default. | Behavior changes between builds with no code change; two third-party repos trusted by default on every install. | P2 (pin), D4 (trust). |
| **R7** | The base package list preinstalls `steam`, `lutris`, `wine*`, `winetricks`, `waydroid`, `geary`, `kooha`, and `lib32-*` Vulkan, against your "everything optional is in the Store" rule. | Larger image, bigger attack surface, slower first boot. | P4. |
| **R8** | Installer: UEFI-only (live image on systemd-boot, installed system on GRUB), Btrfs by default, `luksGeneration: luks1`. Absent from the package list: `linux-lts`, `snapper`, `grub-btrfs`, `fwupd`, `cups`, `zram-generator`, `sbctl` (Secure Boot). | No fallback kernel, no firmware updates, no printing, no compressed swap. | P4, P6, P10, P12. |
| **R9** | `CLAUDE.md` and README point to `architecture.md`, `build-plan.md`, `ui-*.md` and a `darkos-build` skill that are not in the repo. `AGENTS.md` says "no unit tests" though many exist. `hyprland.conf` says "≥0.43" but uses 0.53+ `windowrule` syntax. | Any new contributor, human or AI, starts from false documents. | P0. |
| **R10** | Arch ships Hyprland **0.56.2-4** (built 2026-09-30) **[V]**; it lists `hyprland-guiutils` as a dependency, so v4's worry about safe mode is resolved **[V]**. GitHub's release list showed no 0.57 as of my fetch **[V]**. Your Oct 2 VM log said the Lua config was missing, so the legacy `hyprland.conf` was used **[R]**. | Pin 0.56.x and test Lua now, before upstream removes hyprlang (H1). | P2. |
| **R11** | Your last reported desktop state (Oct 2): black desktop and cursor; Super+Enter did not open a terminal **[R]**. Nobody has reported booting `v194`. | I can't tell you whether HEAD works. | P1: boot it first. |

---

## 3. Hazards

### H1. Hyprland Lua config, `hyprctl dispatch`, `hyprctl keyword`
- **[V]** Lua config arrived in 0.55 (May 9, 2026). A `hyprland.lua` is loaded instead of `hyprland.conf`, checked once at startup. Upstream said hyprlang stays "1 - 2 releases" after 0.55. 0.56.2 is the newest tag **[V]**, so the next major release is the risky one.
- **[V, official wiki]** `hyprctl dispatch` is shorthand for evaluating `hl.dispatch(...)`. Workspace 3 is `hyprctl dispatch 'hl.dsp.focus({ workspace = "3" })'`. Old positional forms fail. A bare word such as `exit` is rejected ("expected a dispatcher") **[R, third-party]**. `hyprctl keyword` reportedly exits 0 but does nothing in Lua mode **[R]**. So the adapter reads output text, not exit codes (you answered this correctly).
- Read the wiki for your pinned version (`wiki.hypr.land/0.56.0/...`); the unversioned pages track `main`.
- **[U]** Where Hyprland finds `hyprland.lua` when DarkOS ships config under `/etc/xdg/hypr/`; whether `perf-auto.conf` and `start-hyprland`'s VM detection have a Lua equivalent.
- **Actions:** one `hypr.py` runs all `hyprctl` calls (R3); test every dispatcher in both modes on the pinned version; convert the config by hand (converters exist, review for `TODO`); keep legacy as fallback until the manual passes; boot check `hyprctl configerrors` is empty **[U: confirm the command's behavior on 0.56]**.

### H2. 0.53 changes
- **[V]** 0.53 rewrote the `windowrule` syntax and introduced `start-hyprland`. Your config already uses the new form **[C]** (e.g. `windowrule = float on, match:class ...`). Fix the stale "≥0.43" header (R9).

### H3. NVIDIA on Maxwell/Pascal
- **[V]** Since driver 590, Arch's `nvidia-open` drops Pascal and older; legacy cards need AUR `nvidia-580xx-dkms` or `nouveau`. A GeForce 940MX is Maxwell **[J]**, so removing `nvidia-open-dkms` was right for that laptop too.
- **[J]** Ship no proprietary NVIDIA module in the base ISO. First-boot GPU step: Turing+ offers `nvidia-open`; Maxwell/Pascal/Volta use `nouveau` by default, `580xx` as advanced opt-in. **[U]** On hybrid laptops force the iGPU (`AQ_DRM_DEVICES`, my recollection; verify).
- Log GPU model, driver and renderer string in every test record.

### H4. VM rendering is not laptop rendering
- **[V]** VMware without 3D uses `llvmpipe` (software GL); Hyprland can refuse to start with no GL; one Broadcom report says Workstation 17.6.4 adds input lag with 3D on. Settings already has an auto/software/hardware renderer choice **[C]**.
- **[J]** VM gate = boots, usable, no leaking CPU loop. Laptop gate = real speed. Always log `glxinfo -B` / `eglinfo -B`.

### H5. Installer (corrected)
Phase 1 install passed on `v96` **[R, README]**; no one has re-run it on HEAD. Re-verify: ISO from HEAD -> UEFI VM -> Erase disk -> reboot -> log in -> read `/boot/grub/install.log`. If it fails, check in order, one change per run: firmware mode (UEFI only); the Calamares log (`calamares -D6` **[V]**; log in `~/.cache/calamares/session.log` **[U]**); known shapes **[V, as reports]**: `grub-install` cannot reach the EFI partition in the chroot (Calamares #1993), "failed to register the EFI boot entry" (workaround `--no-nvram`, which your wrapper already uses), `bootctl` on a too-small ESP. **Not yet covered:** BIOS machines, dual-boot, and LUKS2 (GRUB's LUKS2 support is limited **[J, check]**; you use LUKS1 **[C]**).

### H6. Unpinned build
- **[V]** Arch's WSL image pins to an Arch Linux Archive snapshot: `Server = https://archive.archlinux.org/repos/YYYY/MM/DD/$repo/os/$arch` **before** any `Include = mirrorlist`.
- **[U]** BlackArch is third-party and not covered by the Arch archive. Decide D4.
- Every build writes its package list and `hyprctl version` into the ISO and release notes.

---

## 4. Target architecture: the layers of a real OS

| Layer | Today **[C]** | Target | First step |
|---|---|---|---|
| Base | Rolling Arch, `linux` only | Archive-pinned per release; `linux` + `linux-lts` fallback | P2, P4 |
| **DarkOS packaging** | Files baked into the ISO | PKGBUILDs (`darkos-shell`, `darkos-apps`, `darkos-config`, ...) in a signed repo; ISO = a package list | P5 |
| **Update Center** | `pacman -Syu --noconfirm`, no snapshot | One UI: pacman + Flatpak + firmware + DarkOS packages; snapshot first; changelog; reboot hint | P6 |
| **Rollback** | Hourly snapshots, manual restore | Snapshot before every update; bootable snapshot entries; documented recovery | P6 |
| Session | Hyprland unpinned, legacy config | Pinned 0.56.x, Lua config, `hypr.py` | P2 |
| Shell | GTK3 + gtk-layer-shell, one process | Keep unless the lag diagnosis blames it (P3) | P3 |
| Apps | 21 native | Audit each: works / broken / stored-only | P0 |
| Store | Hosted apps preinstalled | Opt-in native lane + starter packs | P8 |
| Security | Firewall, netwatch, Shield, snapshots, sandbox (5 apps rolled back) | Same stack, with an honest status page; Secure Boot and TPM are **later [U]** | P12 |
| Hardware | Basic | GPU first-boot, `fwupd`, CUPS, `zram`, suspend, HiDPI, multi-monitor, touchpad, portals | P10 |
| Languages | English | Urdu (RTL + fonts), Japanese input, layout switcher **[J]** | P10 |
| Accessibility | Settings exist, some stored-only | Verified list; keyboard-only completion | P7 |
| Releases | CI builds ISOs | Signed ISO, checksums, manifest, release notes with test log | P12 |

**Packaging notes (the largest change):**
- Update `build-iso.sh`, `ci/verify-iso.sh` and `profiledef.sh` carefully. Today they check four-stage byte-identical scripts, executable modes and payload lists; those checks must move from "files in airootfs" to "files inside installed packages" **[C]**.
- Hosting options **[J]**: GitHub Releases or Pages (free, signed with your key) or a small server. Decide D6. Every package must be signed; `SigLevel = Optional TrustAll` for the local repo is acceptable inside a build only.
- Keep the live-vs-installed discriminator `/run/archiso`.

**Rollback notes:**
- **[V]** `snap-pac` (pacman hooks that use `snapper` to take pre/post snapshots) and `grub-btrfs` ("Include btrfs snapshots in GRUB boot options") are in Arch `extra`. Together they are the standard route for GRUB + Btrfs **[J]**.
- Your snapshot script says its nested `/.snapshots` layout differs from Snapper's and that a layout change needs a `partition.conf` change **[C]**. Two options: (A) adopt Snapper layout + `snap-pac` + `grub-btrfs`; (B) keep your script and add a pacman hook + a boot entry generator. Spike A first in a VM **[J]**; decide D7.
- A read-only snapshot stops encryption, not deletion by root (your own docstring says so **[C]**). So never describe rollback as ransomware-proof.

---

## 5. The GUI bar ("Calm Dark")

Principle: the desktop is quiet; the system is coherent. It looks distinctive because of consistency, not glow.

**Design rules** (each is a line in the design check)
1. Three tonal surfaces (base, raised, overlay) in deep blue-grey, not pure black. Widen the steps; Stitch's sheet-3 values were only ~1.09:1 apart **[J]**.
2. One accent, seed `#00E5FF`, on about 10% of a screen or less. Validate generated tonal values.
3. 1px low-contrast borders; shadows only on floating things; glow only for keyboard focus and the active item.
4. Panels solid. Frosted glass only for dock, launcher and popovers, with Solid available.
5. Type 12/14/16/20/28; spacing 4/8/16/32/48; radii 8/16/24; all from `tokens.py`.
6. One icon family. `make_icon_button` takes icon-theme names, so use **one theme with symbolic variants** and a fallback icon **[J]**; test recoloring on Dark and High Contrast **[U]**.
7. No central HUD, rings, orb, radar, particles or fake metrics. Real logo file only; if its path is unknown, leave the slot empty.
8. Contrast at least 4.5:1 body, 3:1 large text and control borders, on every surface including accent buttons.

**Extra bars that make it "perfect enough" [J]**
- **Every control is real.** Run the reality audit (Appendix B); a setting that only writes `settings.json` is labeled or removed.
- **Every screen has designed states:** empty, loading, error, disabled.
- **Keyboard-complete.** Every screen and every task works with no mouse; focus is always visible; tab order is sane.
- **Scales** at 100/125/150/200% **[U: GTK3 behavior with Hyprland fractional scale]**.
- **Text works** in Urdu (right-to-left) and Japanese.
- **Motion budget:** compositor animations only, brief, never looping, nothing animates when hidden. Starting targets to tune: window ~200 ms, workspace ~250 ms, panels ~200 ms, dock hover ~150 ms. Honor Reduce Motion where wired; list wired and unwired sites first.
- **Modes:** Dark and High Contrast (opaque, no blur). Light is later. **Effects:** Lite and Full only until a third is measured. Appearance changes say "Applies after restart" unless they really apply live (only dock position/size does).
- **Trends adopted:** tonal depth, restrained accent, compact density, one command surface, optional wallpaper-derived accent later (needs a runtime theme object). **Trends rejected:** giant glow, glass everywhere, ambient widgets, decorative gauges.
- **Golden screenshots [J]:** a headless harness exists in `ci/headless/` (Sway, not Hyprland **[C]**); extend it to capture key screens with `grim` and diff after changes. It supports layout regressions only, not Hyprland rules.

**Screens**

| Screen | Must have | Must not have |
|---|---|---|
| Desktop | Wallpaper, compact dock (bottom first), slim status area | Central widgets, two docks, always-on weather |
| Command Center | Only toggles with real backends, brightness/volume, notifications with Clear all, compact resource rows | Giant gauges, fabricated numbers, anything running while hidden |
| Windows | Same title bar everywhere, snap popover, labelled Alt+Tab, overview | Buttons that do nothing |
| Search | One launcher: Apps, Files, Settings, Actions; empty/results/none/error | NL claims; "Create calendar event" without a calendar |
| Files | Sidebar, breadcrumbs, list/grid, useful empty and error states | Decorative cards instead of files |
| Settings | Appearance, Wallpaper, Performance, Dock, Accessibility, Updates, About; others only with real code | Stored-only pages; "Auto" labels with no tested detection |
| Store | Opt-in, source badge, sizes, permissions, "starts at login", Install/Remove with data prompt | Ads, nags, first-run installs, invented metadata |
| Login/Lock | Default wallpaper, readable clock, small real logo | Large glowing ring |
| Update Center | What will change, snapshot status, Update, Roll back | Silent updates |

---

## 6. "Do anything": capability lanes

**Rule:** the useful core ships preinstalled; everything else is opt-in. Nothing installs, autostarts or nags without a user action.

| Lane | Backend | Phase | Honest label |
|---|---|---|---|
| Native Linux | `pacman`, Flatpak, then AppImage | P8 | AUR labelled Community; Flatpak labelled **Unscanned** in v1 **[J]** |
| Other Linux distros' apps | `distrobox` containers **[J, check the package and integration]** | P11 | "Runs in a container" |
| Web apps | Browser app-mode launchers **[J]** | P11 | "Web app" |
| Windows apps | Bottles (Wine/Proton); Steam for games | P11 | "Results vary. Not every Windows app runs." |
| Windows VM | A hidden Windows VM shown as app windows (the WinApps/WinBoat approach) **[R]** | later | Needs your own Windows licence and lots of RAM; not for games **[R]** |
| Phone link | KDE Connect (`kdeconnect` already in the package list) | P11 | Explicit pairing, independent toggles |
| Android | Waydroid | later | Specific reasons: *no binder*, *not a Wayland session*, or *no usable GPU: experimental and slow* **[V: Waydroid needs Wayland and binder; software mode exists]**. **[U]** Does your kernel have binder? |
| macOS apps | none | never | Borrow ideas only |
| Security tooling | BlackArch groups, opt-in at first boot | exists | Explicit; see D4 |

**Core list (proposal from app names only [U]):** Files, Terminal, Settings, Store, Calculator, Notes, Clock, Calendar, Gallery, Reader, Clipboard, Downloads, Network Center, Security Center, Backup, Emoji, plus browser, media player, text editor. **Store-only:** Gaming hub, Mail, DevHub, Mission, Dashboard and extras.

**Store cards:** source badge, sizes (or "Unknown"), permissions, "starts at login", Install/Remove with a "Keep or delete app data?" prompt. **Starter packs** (Everyday, Student, Developer, Creator, Gamer, Office): first-run picker, all unticked, skippable with equal weight. Keep one seam, `recommend(profile) -> ranked list`, static today.

---

## 7. Release ladder [J]

| Release | Meaning | Must pass |
|---|---|---|
| **Alpha 0: installs** | A stranger can put it on a disk | ISO builds and verifies from HEAD; live boot; Calamares install; installed system boots to the desktop; logs saved |
| **Alpha 1: usable** | Daily-use core | Pinned Hyprland, empty `configerrors`; lag rules (section 9); wallpaper contract; every app opens with working min/max/close; Settings honest; accessibility baseline; firewall confirmed from another machine |
| **Beta: updates safely** | A user can keep it | DarkOS packages + Update Center; snapshot before update; bootable rollback; native Store lane; hardware first-boot; passes on two real machines |
| **RC: daily-drivable** | You'd give it to a friend | 30 days of your own daily use; signed ISO; docs; licence; support matrix; known-issues list |
| **Later** | Not in any gate | AI (opt-in), Cloud tier, Light theme, widgets, Windows VM lane, Android, Secure Boot/TPM |

---

## 8. Build order (time-boxes are estimates [J])

Each phase ends with an exit test and two "explain it" questions. If you can't answer them without looking, you're not done. I coach (hint, then pseudocode, then a snippet, then a full solution only if you're stuck); you write the code you must defend.

| # | Phase | Time | Exit test | Explain it |
|---|---|---|---|---|
| **P0** | **Repo truth.** Decide R1 (D0). Run every test in CI or delete it. Restore or delete the missing docs. Fix stale headers. Add `docs/STATUS.md` using the tag system. | 1 day | CI green with `test-polish` and `test-phase3` included | Why did two tests fail for days without anyone noticing? What can a dormant `NOPASSWD` rule do? |
| **P1** | **Boot truth.** Build from HEAD. Boot VM, install to disk, reboot, log in. Appendix B steps 1-6. | 2-3 days | Alpha 0 record committed | Why does the live image use systemd-boot but the installed one GRUB? What does `/run/archiso` decide? |
| **P2** | **Pin + Lua + `hypr.py`.** Archive date in `pacman.conf`; manifest written into the ISO; one hyprctl module; Lua config; both modes tested. | 2-3 days | `configerrors` empty; every hyprctl call goes through `hypr.py` | Why must the archive `Server` line come before the mirrorlist? |
| **P3** | **Lag diagnosis** (section 9). Fix one cause at a time. A shell-rewrite spike (GTK4, Quickshell, DankMaterialShell) runs **only** if the numbers blame the shell. | 2 days (+3) | Ranked causes with numbers | How would software GL look in your CSV versus a leaked redraw loop? |
| **P4** | **Base diet and safety nets.** Move `steam`/`lutris`/`wine*`/`waydroid`/`geary`/`kooha`/`lib32-*` to Store packs. Add `linux-lts`, `zram-generator`, `fwupd`, `cups`. Decide D4. | 2 days | Idle RAM and ISO size logged before and after; nothing opt-in preinstalled; both kernels boot | What does an opt-in rule protect, besides disk space? |
| **P5** | **Packaging.** PKGBUILDs for DarkOS code; a signed repo; the ISO installs from it; `verify-iso.sh` adapted. | 1-2 weeks | On an installed VM, publish a new package version, run `pacman -Syu`, see the shell fix arrive | Why can't an ISO-only user get a fix, and what exactly changes for a package user? |
| **P6** | **Safe updates.** Snapshot before update; Update Center; bootable rollback; recovery steps. | 1 week | Break an update on purpose; roll back from the boot menu; desktop returns | What two things must exist before that test can run? What does a read-only snapshot not protect against? |
| **P7** | **Tokens, core screens, wallpaper, accessibility.** Decide D5; settings audit; section 5 bars. | 1-2 weeks | Section 5 table and design check pass; wallpaper contract passes | What does `apply_css()` read, and when? |
| **P8** | **Store v1 + starter packs + first-run setup.** | 1-2 weeks | Install, launch, remove, data prompt, on a fresh ISO | What does "Unscanned" stop the user from believing? |
| **P9** | **Search and switching.** Compare custom tools against Vicinae and hyprshell (check version, licence, accessibility, lag). | 1 week | One launcher, one switcher, no duplicate keybinds | Why test any Hyprland tool against your pinned version? |
| **P10** | **Real-hardware pass** on 2+ machines: GPU first-boot, suspend, battery, Wi-Fi, Bluetooth, audio, printing, HiDPI, multi-monitor, touchpad, portals, languages. | 1-2 weeks | Appendix B record sheet for each machine | Which of these failures would a stranger blame on DarkOS rather than the hardware? |
| **P11** | **Lanes.** Windows (Bottles), phone link, distrobox, web apps. Android only on supported hardware. | 2 weeks | One small `.exe` installs, runs, removes; pairing tested; honest unavailable states | What does the Windows disclaimer promise, and what doesn't it? |
| **P12** | **Release engineering.** Signed ISO, checksums, package manifest, release notes with test logs, licence, docs, bug template, support matrix. Decide on Secure Boot. | 1 week | A release you could hand to a stranger | What does a signature prove, and what doesn't it? |

**Rough total [J]:** Alpha 1 in about 2-3 weeks; **Beta in about 2 months** of focused part-time work; RC after real-hardware surprises (those decide the schedule, not the code). Hackathons and coursework will stretch these.

**Session-basics audit (add to P1/P10):** neither `xdg-desktop-portal-gtk` (file chooser for Flatpak apps) nor a keyring package such as `gnome-keyring` is in `packages.x86_64` **[C]**; they may still arrive as dependencies **[U]**, so check on a booted system. Also check: screen share and screenshot via the Hyprland portal; clipboard history; notification actions; Polkit prompts.

**Anti-goals:** no shell rewrite before P3; no new feature before P5; no claim of macOS apps; no AI before it has a measured CPU/RAM budget; no release note without a test log.

---

## 9. Lag: diagnose first, one variable at a time

| # | Hypothesis | Test |
|---|---|---|
| 1 | Software GL in the VM | Renderer string, VM 3D on vs. off; laptop for comparison |
| 2 | A redraw loop or timer still alive in the shell (three were found before) | Shell CPU alone, panels closed, 60 s; then open/close the Command Center |
| 3 | Another process: ClamAV continuous scan, `darkos-protect`, netwatch, waybar, mako, tray applets | `top` by CPU and memory for the first 5 minutes **[J]** ClamAV loads its whole database into RAM |
| 4 | Compositor effects on weak GL | Lite vs. Full, same session |
| 5 | Live-ISO conditions (RAM-backed root, no swap) | Repeat on the installed system (needs P1) |
| 6 | Wrong GPU on a hybrid laptop | Which device the compositor chose; compare with iGPU forced |
| 7 | `swaybg` memory or leaked processes | RSS of every `swaybg` after 20 switches |

**Logger (you write it, pseudocode only):**
```
every 1 s for 60 s:
    for name in [hyprland, darkos-shell, swaybg, waybar, clamd, darkos-protect]:
        read CPU% and RSS
    append one CSV row
at the end: median per process; print renderer string + hyprctl version
```
Three runs, take the median. Write the pass/fail rules down **after the first baseline and before the second run**, as relative rules (for example: closing the Command Center returns CPU to within about 1 percentage point of idle **[J, starting value]**). No absolute numbers until you have a baseline.

**Wallpaper contract.** 1) Fresh install shows image 1; Use default restores it. 2) Choice persists and applies each login; login and lock use the default. 3) Bad custom files give a clear error and fall back. 4) After 20 rapid switches: exactly one DarkOS-started `swaybg`, no orphans, no blank flash. `swaybg` is long-running, not one-shot **[V]**: store its PID under `$XDG_RUNTIME_DIR`, never `pkill`, start the new one, confirm it stays alive, then stop the old one after checking the PID is still `swaybg`. **[U]** Which surface wins when two overlap.

---

## 10. Decisions (in blocking order)

1. **D0. `a08bc81`:** was re-adding the AI files and the sudo rule intentional? (R1)
2. **D1. Which hardware is "the laptop"?** CPU, GPU, RAM. It decides H3 and which numbers count.
3. **D2. Logo path.** Where is the real DarkOS logo file? Don't redraw it.
4. **D3. Hyprland pin.** Proposal: 0.56.2 and one archive date chosen in P2.
5. **D4. Trust.** Chaotic-AUR and BlackArch: off by default and added on opt-in, or on by default?
6. **D5. Theme tokens.** "Applies after restart" labels now, or refactor `tokens.py` to a runtime object?
7. **D6. Where the DarkOS package repo lives.**
8. **D7. Rollback layout.** Snapper-style (recommended spike) or your own script plus a hook.
9. **D8. Licence** for DarkOS code; it decides what you may copy from GPL projects.
10. **D9. Base vs. Store split** (section 6 proposal) and the Store scan gap ("Unscanned" for v1 is my recommendation).
11. **D10. Shell layout and palette seed.** Bottom dock or vertical; keep cyan?

---

## 11. Not verified in this pass

- Whether the current HEAD boots, installs, or looks right. **Nothing was booted.** My sandbox could not run GTK tests, a compositor, Btrfs, or the installer.
- Whether Hyprland finds `hyprland.lua` under `/etc/xdg/hypr/`.
- Hyprland 0.57: none found on GitHub's release list or in search; a newer tag may exist after my fetch.
- Omarchy 4.0, COSMIC and WinBoat details are from secondary coverage, not their own sources. The Arch wiki's Secure Boot page refused my fetch, so Secure Boot and TPM claims stay **[U]**.
- All durations and thresholds are starting guesses to be replaced by your measurements.

---

## 12. Sources

- Hyprland Lua config: https://hypr.land/news/26_lua/ · 0.53: https://hypr.land/news/update53/ · versioned wiki: https://wiki.hypr.land/0.56.0/Configuring/Advanced-and-Cool/Using-hyprctl/
- Arch Hyprland package (0.56.2-4): https://archlinux.org/packages/extra/x86_64/hyprland/ · Hyprland releases: https://github.com/hyprwm/Hyprland/releases
- `grub-btrfs`: https://archlinux.org/packages/extra/any/grub-btrfs/ · `snap-pac`: https://archlinux.org/packages/extra/any/snap-pac/
- Bare-word dispatch example: https://github.com/jasonboukheir/dotfiles/issues/31 · third-party Lua-mode notes: https://github.com/dusklinux/dusky/pull/216
- Arch NVIDIA 590: https://bbs.archlinux.org/viewtopic.php?id=311143
- VM rendering: https://bbs.archlinux.org/viewtopic.php?id=285331 · https://github.com/omacom/omarchy/discussions/7758 · Broadcom 17.6.4 report: https://community.broadcom.com/vmware-cloud-foundation/discussion/vmware-workstation-1764-input-lag-with-3d-acceleration-on-linux-guest-which-vmx-keys-actually-take-effect
- Calamares reports: https://github.com/calamares/calamares/issues/1993 · https://discuss.cachyos.org/t/the-bootloader-could-not-be-installed/10134
- Waydroid: https://wiki.archlinux.org/title/Waydroid
- Archive pinning: https://bbs.archlinux.org/viewtopic.php?id=304826 · https://lists.reproducible-builds.org/pipermail/rb-general/2025-December/003975.html
- Omarchy 4.0: https://blog.desdelinux.net/omarchy-4-0-lanzamiento-novedades-quickshell-omakase/ · https://learn.omacom.io/2/the-omarchy-manual/101/system-snapshots · https://www.starryhope.com/linux/omarchy-snapshots-limine-rollback/
- COSMIC Epoch 1.0.8: https://phoronix.com/news/cosmic-epoch-1.0.8
- WinBoat / WinApps: https://www.theregister.com/2026/02/14/winapps_and_winboat/
- Newton (Wayland accessibility): https://www.osnews.com/story/139996/update-on-newton-the-wayland-native-accessibility-project/
- Stitch: https://zapier.com/blog/google-stitch/ · https://moda.app/blog/google-stitch-review
- DankMaterialShell: https://archlinux.org/packages/extra/x86_64/dms-shell-hyprland/
- Repo: https://github.com/Darkness0258/Dark-OS

---

## Appendix A. Stitch pack (carried from v4, section 10)

**Facts [V]:** Stitch can take uploaded screenshots as input; its DESIGN.md format is an open-sourced draft spec you can export and import between projects; it exports to Figma, code, zip and an MCP connection. A review reports up to 5 linked screens at once **[R]**.

**How to use it**
1. One Desktop project. Run Prompt 0 first; export `DESIGN.md`.
2. Attach **real files**: wallpaper image 1, the real logo file once located, and 2-3 reference screenshots with this line: *"Use the attached screenshots only for spacing, hierarchy and information density. Do not copy their layout, branding or colours."*
3. Paste the header at the top of every prompt. Ask for 2-4 screens per prompt; if fewer arrive, say "You only generated N screens. Please generate all of the ones I described."
4. Refine one thing at a time and name the screen. Stitch output is reference, not drop-in code, and weak at dense tables and motion.
5. Don't design what isn't built: no Windows-lane, Android or phone-link screens until those lanes exist.

**Style header**
```
Desktop operating-system UI called DarkOS, "Calm dark". Three tonal deep blue-grey surfaces (base, raised, overlay), not pure black. One accent #00E5FF on small areas only (primary button, focus ring, active item). 1px low-contrast borders. Soft shadows only on floating elements. Frosted glass only on the dock and launcher; all other panels solid. One rounded icon style. Inter for text, JetBrains Mono for code. Type 12/14/16/20/28, spacing 4/8/16/32/48, radius 8/16/24. No glow except keyboard focus. No central HUD, rings, orb, assistant or chat UI. No invented logos or fake metrics: leave the logo slot empty. Show placeholder data as placeholder.
```

**Round 1 corrections (from the three sheets you generated).** Add to the header and regenerate:
```
Do not invent a DarkOS logo or emblem: show an empty rounded-square placeholder labelled LOGO. No taglines or slogans anywhere. Nothing in the centre of the Command Center: show CPU, GPU, RAM and Storage as four compact rows (label, thin bar, number), not circular gauges. Store: no Featured or Popular hero banners, just an even grid of equal-sized cards. Use generic placeholder app icons (rounded square with a letter), not real brand logos. Dark and High Contrast only; no Light or Auto. No Windows, Apple or Android logos. No mobile screens. Use the attached wallpaper unchanged.
```
Keep from the sheets: the design-system panel from sheet 3 (tokens, button state matrix, Frosted vs. Solid), the quick-settings sliders and lock-screen layout from sheet 2, and the Appearance page with a preview panel from sheet 1.

**Prompt 0: design system sheet (1 screen).** Surface swatches with hex values; accent and muted success/warning/danger; type scale; buttons (primary, secondary, ghost, danger) in default/hover/pressed/disabled/focused; toggle, checkbox, slider, dropdown, search field, tooltip, toast, app card, confirm dialog; one overlay shown Frosted and Solid; 24 common system icons at 16/24/32 px in one style; Dark and High Contrast examples.

**Prompt 1: shell (3 screens).** (1) Empty desktop with the attached wallpaper, compact dock, slim status area, nothing in the centre. (2) Same desktop with the Command Center: quick toggles, brightness/volume, notifications with Clear all, compact resource summary; mostly solid. (3) Compact vertical icon-only dock with active-app markers.

**Prompt 2: windows (3 screens).** (1) Files window with title bar, sidebar, breadcrumbs, grid/list, and a snap popover under the maximize button. (2) Alt+Tab switcher with labelled previews and one selected. (3) Workspace overview with a workspace strip and readable thumbnails.

**Prompt 3: search (3 screens).** (1) Empty launcher: recents and a few deterministic suggestions. (2) Query "photos": Apps, Files, Settings, Actions, with icon, title, subtitle, shortcut hint. (3) No-results and error states.

**Prompt 4: settings (3 screens).** (1) Appearance: Dark/High Contrast, accent swatches, Glass Clear/Frosted/Solid, Effects Lite/Full, helper text "Applies after restart". (2) Wallpaper: 3x3 grid of nine abstract wallpapers (first = attached default), selected marker, Choose image..., Use default. (3) Performance: Lite vs. Full with honest helper text and an error state.

**Prompt 5: store (4 screens).** (1) First-run "Pick your extras": six packs, all unselected, Skip and Install selected with equal weight. (2) Store home: search, categories, compact cards with source badges, no ads. (3) App detail: sizes (or "Unknown"), permission chips, "Starts at login", Install. (4) Installed and Updates with a "Keep app data / Delete app data" dialog, plus loading, failure and "Unscanned" states.

**Prompt 6: variants (2 screens).** (1) Store home in High Contrast: opaque, thick borders, strong focus rings. (2) Lite-profile Command Center: opaque, no blur, no ornamental rings.

**Prompt 7: Update Center (2 screens, new).** (1) A list of pending updates grouped as System, Apps, Firmware and DarkOS, with sizes, a line "A restore point will be created first", and Update and Details buttons. (2) A "Roll back" screen listing restore points with date and a short reason, a confirm dialog, and an error state.

---

## Appendix B. Testing manual

Run on the VM **and** the laptop after each work pass. Log: commit hash, ISO id, `hyprctl version`, GPU model and driver, OpenGL renderer string, resolution, effects profile.

1. **Build:** CI builds the ISO; `ci/verify-iso.sh` passes; package list and Hyprland version saved.
2. **Install (VM):** Calamares to disk, reboot, log in. Record firmware (UEFI) and read `/boot/grub/install.log`.
3. **Fresh boot:** reaches the desktop with no keyboard help; note time.
4. **Config:** `hyprctl configerrors` empty; every dispatcher the tools use runs in the active config mode.
5. **Idle:** panels closed, 60 s, run the section 9 logger, Lite and Full.
6. **Command Center (`SUPER+H`):** open, log, close, confirm CPU returns to baseline. If not, a loop is leaking.
7. **Wallpaper:** the section 9 contract, login and lock included, `swaybg` count after 20 switches.
8. **Apps and window tools:** each app opens; min/max/close/move/resize/focus; Alt+Tab, snap, overview, search.
9. **Dock:** 4 positions x 3 sizes, with a maximized window.
10. **Settings:** each control works and persists, or states "Applies after restart"; disabled controls look disabled.
11. **Accessibility:** each toggle works; focus visible; tab order sane; High Contrast opaque; one real task finished using only the keyboard.
12. **Store (when built):** fresh image has no extras; install one Flatpak, launch, remove, answer the data prompt; unscanned shown as unscanned.
13. **Security:** firewall default-deny confirmed from another machine; any sandboxed app opens.
14. **Updates (new, P5-P6):** publish a new DarkOS package version, update, see the change; break an update on purpose, roll back from the boot menu, desktop returns.
15. **Hardware (new, P10):** suspend/resume, battery drain overnight, Wi-Fi, Bluetooth, audio in/out, printer, external monitor, touchpad gestures, a Flatpak app opening a file through the portal, Urdu and Japanese text.
16. **Design check on screenshots** (desktop, Command Center, Files, Settings, Store, Update Center): no central HUD, tokens only, one icon family, accent about 10% or less, contrast per rule 8, no always-on glow.

**Reality audit sheet (P0):** one row per app and per Settings control: *Works / Broken / Stored-only*, with the evidence (command or screenshot).

| Field | VM | Laptop 1 | Laptop 2 | Notes |
|---|---|---|---|---|
| Commit / ISO id | | | | |
| Hyprland version, config mode | | | | |
| GPU / driver / GL renderer | | | | `llvmpipe` = software |
| Install + first boot | | | | UEFI, time to desktop |
| Idle CPU / RSS (median of 3) | | | | per process |
| Command Center open / closed | | | | returns to baseline? |
| `swaybg` count after 20 switches | | | | |
| `configerrors` | | | | |
| Dock matrix | | | | |
| Update + rollback | | | | |
| Store cycle | | | | |
| Hardware list (step 15) | | | | |
| Design check | | | | |
