# DarkOS Testing Manual

Build under test: the 2026-10-17/18 change set (AI assistant removed, nine
wallpapers restored with a Settings picker, Lite/Full effects profile, new
features, lag fixes) as cleaned up by the 2026-10-19 P0 pass, the 2026-10-22
Calm Dark pass, the 2026-11-02 Void v2 + app audit pass, and the 2026-11-07
backlog pass (icons, Welcome, Task Manager, Display, Power & sleep, mirror
ranking). This file lists
feature checks; the boot-truth record to fill in is Appendix B of
`docs/MASTER-PLAN.md`. Run on **both** the VMware VM and the laptop, and log
the commit hash (`cat /etc/darkos-build-sha`) and `hyprctl version` every time.

## 0b. Checks specific to the 2026-10-19 pass (do these first)

Nothing below needs the desktop to be usable; run it in a terminal.

| # | Command | Expected |
|---|---|---|
| 0b.1 | `cat /etc/darkos-build-sha` | first 8 characters of the commit you meant to test |
| 0b.2 | `ls /usr/local/bin/darkos_shell/ai_brain.py` | "No such file or directory" |
| 0b.3 | `ls /etc/sudoers.d/` | no `darkos-ai-snapshot` |
| 0b.4 | `which kitty` | not found (it was removed with the AI test harness) |
| 0b.5 | `ls /usr/share/backgrounds/darkos/` | nine `NN-name.jpg` files plus `thumbs`, no `darkos-wallpaper.png` |
| 0b.6 | `grep -c darkos/env /usr/local/bin/start-hyprland` | `0` |
| 0b.7 | `hyprctl configerrors` | empty. If not, send the output: it is the single most useful line |

## 0c. Checks specific to the 2026-10-22 Calm Dark pass (after 0b)

Build under test: branch `calm-dark` (merge it, push to `main`, let CI build). What
changed: one dock and one slim status bar instead of rail + dock + bar, one
Command Center instead of two panels, a generated palette, solid windows, shorter
animations, a grouped Settings sidebar, and The Void's colours and tabs.
**None of this has been seen on Hyprland or booted**; the sandbox used headless
sway (no blur, no `hyprctl`). Judge the glass, the border and the animations here.

| # | Do this | Expected |
|---|---|---|
| 0c.1 | Log in and look | Three things only: a slim bar at the top (logo, window title, clock in the middle, status icons), one dock at the bottom (Apps, divider, Files, Terminal, Browser, Notes, Store, Settings). No left icon rail, no second clock, no avatar button, no wide "DARK OS" text |
| 0c.2 | Click **Apps** in the dock | The same search overlay as `Super+E` |
| 0c.3 | Click the control icon at the right end of the bar, or `Super+H` | One panel at the top right: five toggles, volume and brightness sliders, Notifications, System rows, Calendar. No weather, no rings, no "not connected" text. `Esc` closes it |
| 0c.4 | Run `notify-send Hi test`, let the pop-up fade, open the panel | "Hi" is listed. **Clear all** empties the list and it stays empty until a new one arrives |
| 0c.5 | Drag the volume slider, then `pamixer --get-volume` | Matches where you let go. Sliders for a missing backend (no backlight in a VM) are simply absent |
| 0c.6 | Play audio in a player, open the panel; quit the player | "Now playing" appears, then disappears. Nothing shows when no player runs |
| 0c.7 | Leave the panel closed, run `top` | `darkos-shell.py` is near 0% CPU: its timers stop while the panel is hidden |
| 0c.8 | Open Files, Settings and The Void | One title bar style, blue-grey surfaces (not pure black), windows solid (nothing see-through), only the focused window has a thin cyan border |
| 0c.9 | Open Settings | Sidebar has headings Appearance / System / Access & privacy; no blank placeholder icons; opens on Themes |
| 0c.10 | `Super+E`, type `dock`, Enter | Settings opens on **Dock & panels** (the page the search entry names) |
| 0c.11 | In The Void open three tabs | Each tab title is readable, not "..." |
| 0c.12 | Press `Tab` through Settings | A visible cyan ring follows keyboard focus; nothing else glows |
| 0c.13 | Settings > Themes: pick red, restart the shell (`pkill -f darkos-shell.py; python /usr/local/bin/darkos-shell.py &`) | Accent turns red in the shell and apps and text stays readable. Waybar and notification borders stay cyan (known: static files use the default accent) |
| 0c.14 | Settings > Accessibility > High contrast, restart the shell | Opaque black and white, 2 px borders, no translucency |
| 0c.15 | Open/close a window, switch workspace | About 0.2 s, no bounce, nothing loops |
| 0c.16 | `hyprctl configerrors` | Empty. `animation = layers` and the single-colour `col.active_border` are new |

Automated, on any dev machine with GTK3 (see CLAUDE.md for the packages):
`python ci/test-design-tokens.py`, `test-command-center.py`, `test-ui-consistency.py`,
`test-void.py`, `python tools/gen-theme.py --check`, `bash ci/headless/run-all.sh`.

## 0d. Checks specific to The Void v2 + app audit pass (after 0c)

Build under test: branch `calm-dark`. What changed: The Void (`darkos-terminal.py`)
gained split panes, scrollback search, an engagement workspace, session logging,
save-scrollback, a BlackArch tool launcher, clickable scrollback links and a command
palette; one real bug was found and fixed in `darkos-integrity-check.py`. Everything
below except 0d.14 ran against real spawned shells and real VTE under headless Xvfb —
**this is the first time any of it has been seen on Hyprland or with a real pointer**.

| # | Do this | Expected |
|---|---|---|
| 0d.1 | Open The Void, `Ctrl+Shift+E` | Window splits left/right; focus moves to the new (right) pane, a fresh shell prompt |
| 0d.2 | In the new pane, `Ctrl+Shift+O` | That pane splits top/bottom; three panes total, independent prompts |
| 0d.3 | Click into the top-left pane, `Ctrl+Shift+W` | Only that pane closes; its sibling takes its place (no gap, no empty split); the other two panes are untouched |
| 0d.4 | Keep closing panes with `Ctrl+Shift+W` until one is left, then once more | The tab itself closes (or the window, if it was the only tab) |
| 0d.5 | Type something, `Ctrl+F`, type a word that's on screen | A find bar slides in at the top of the pane; the match is highlighted |
| 0d.6 | Press Enter / click the down arrow a few times, then the up arrow | Jumps to the next / previous match, wrapping around at the ends |
| 0d.7 | `Esc` in the find bar | Bar closes, focus returns to the terminal (typing resumes in the shell, not the search box) |
| 0d.8 | Click the engagement icon in the tab bar's top-right corner, create one (name + target) | Dialog shows it as "Active: <name> (target: ...)"; `ls ~/engagements/<slug>/` shows `scans/ loot/ notes/ logs/` and `engagement.json` |
| 0d.9 | Open a new tab (`Ctrl+Shift+T`), run `echo $TARGET $ENGAGEMENT_DIR` | Both are set, matching what you entered in 0d.8 |
| 0d.10 | Command palette (`Ctrl+Shift+P`), type "target", run **Set Target** with a new value | A dialog asks for the value; after confirming, `echo $TARGET` in the current pane shows the new value immediately |
| 0d.11 | Command palette, "Start Session Log" | The pane's shell restarts in place (same prompt, same cwd) with a one-line banner naming the log file; run a command, then `cat` that file from another pane — the command and its output are both in it |
| 0d.12 | Command palette, "Save Scrollback As..." | A normal GTK save dialog; the saved `.txt` file's content matches what's on screen |
| 0d.13 | Tool launcher icon, pick the **scanner** group, double-click **nmap** | Dialog closes; `nmap -sV -Pn <your target>` (or `nmap -sV -Pn $TARGET` with no engagement active) appears on the pane's current line, **not run** — you have to press Enter yourself |
| 0d.14 | Same dialog, **Install Group** on any group | Opens a new tab running `sudo darkos-tool-groups install blackarch-<group>`, same as the existing `darkos-tool-groups` launcher |
| 0d.15 | `printf 'see https://example.com and 203.0.113.9 and CVE-2024-1234\n'` in a pane, then **right-click** each one | **This one needs a human with a real pointer — not run here, see 0d note above.** Expect: a small context menu per kind (URL: Open/Copy; IP: Set as Target/Copy; CVE: Copy only); also try `Ctrl+click` on the URL, which should open it in the default browser directly |
| 0d.16 | Command palette, type "zoom", run **Zoom In** a couple of times, then **Reset Zoom** | Font grows, then returns to the starting size |
| 0d.17 | Open Files, right-click a folder, "Open Terminal Here" (or whatever the existing action is called) | Still opens The Void in that folder — the `--cwd` contract is unchanged |

Automated: `python ci/test-void.py` (pure-Python `darkos_void` checks, no display
needed) and `xvfb-run -a dbus-run-session -- python ci/test-void.py` (adds the GTK
classes: real split/close-merge, real engagement env injection, real tool-launcher
insert, real command-palette dispatch, real session-log file, real linkify matches
on live content) — 55 tests total. `bash ci/headless/run-all.sh launch` starts every
`darkos-*.py` bare and checks stderr for a traceback (this is what caught the
`darkos-integrity-check.py` bug).

## 0e. Checks specific to the 2026-11-07 backlog pass (after 0d)

Build under test: branch `calm-dark`. What changed: the app icons were fixed, and there is a new Welcome app, a
Task Manager (`Ctrl+Shift+Esc`), Settings > Display, Settings > Power & sleep, and a "Download mirrors" card in
Settings > Updates. All of it was tested under headless Xvfb against **fakes** (`hyprctl`, `reflector`, `pkexec`,
`powerprofilesctl`, `/sys/class/power_supply` and `/proc` trees), and the windows were screenshotted with the real
stylesheet but no compositor. **None of it has run on Hyprland, on real hardware, or against the real tools.**
Most likely to fail for environmental reasons: 0e.20-0e.22 (Hyprland's monitor keyword), 0e.26 (hypridle reading
the generated file) and 0e.32 (reflector + polkit).

| # | Do this | Expected |
|---|---|---|
| 0e.1 | Open the Apps overlay (`Super+E`, Apps) and look at the dock | Every app has a real glyph, no grey "missing image" squares. The installer entry (live ISO only) uses `calamares`, which comes from the Calamares package and could not be checked here: tell me if it is a placeholder |
| 0e.2 | `grep -h '^Icon=' /usr/share/applications/darkos-*.desktop /usr/share/applications/the-void.desktop \| sort -u` | Every line ends in `-symbolic`, except `calamares` |
| 0e.3 | `for n in $(grep -h '^Icon=' /usr/share/applications/darkos-*.desktop /usr/share/applications/the-void.desktop \| cut -d= -f2 \| grep -- -symbolic \| sort -u); do find /usr/share/icons/Adwaita -name "$n.svg" \| grep -q . \|\| echo "MISSING $n"; done` | Prints nothing. (The names were checked on Ubuntu's Adwaita 46; this checks Arch's.) |
| 0e.4 | Delete `~/.config/darkos/welcome.done`, log out and in | After about 10 s "Welcome to DarkOS" opens once. No wofi prompt about performance or tools appears |
| 0e.5 | Press Enter straight away | It goes to the next page. It must not skip the tour |
| 0e.6 | Look page: click a wallpaper tile | The tile gets a cyan frame and the desktop wallpaper changes within a second or two |
| 0e.7 | Look page: Effects = Lite, Dock position = Left | `grep -E 'effects\|dock_position' ~/.config/darkos/settings.json` shows both. The dock moves at once; the effects change applies after the next login |
| 0e.8 | Power page | Lists exactly the profiles in `powerprofilesctl list` (a VM may offer none, and it then says so). Choosing one is reflected by `powerprofilesctl get` |
| 0e.9 | Tools page: "Choose tool groups..." | The Void opens running the tool-group picker after a sudo prompt. "Don't ask again" creates `~/.config/darkos/firstboot-tools.declined` |
| 0e.10 | Finish page: Done, then log out and in | The tour does not come back. "Welcome" in the Apps overlay opens it again |
| 0e.11 | Live ISO | One page: "Install DarkOS" and "Keep trying it", no Back/Skip/Next bar. Install DarkOS starts the installer |
| 0e.12 | `Ctrl+Shift+Esc` | Task Manager opens: dark table sorted by CPU; DarkOS apps are named like `darkos-files.py`, not `python3`; the CPU and memory bars move |
| 0e.13 | In the Void: `yes > /dev/null &` | It appears near the top at about 100% CPU within 2-3 s. Select it, End task: it disappears within a second or two |
| 0e.14 | `sleep 1000 &`, select it, Force quit | A dialog asks first (Cancel is the default button); confirming ends it |
| 0e.15 | Tick "All users", select a root process | End task and Force quit go dim and the status line says who owns it |
| 0e.16 | Select the Task Manager's own row, End task | "That is this Task Manager. Close its window instead." |
| 0e.17 | Select `Hyprland`, End task, then press **Cancel** (do not confirm) | A warning says it closes the whole session |
| 0e.18 | Minimize the Task Manager for 30 s, then `ps -o %cpu,cmd -C python \| grep taskmgr` | About 0.0% CPU: nothing is sampled while it is hidden |
| 0e.19 | Settings > Display | One card per screen with its current resolution, refresh rate, scale and orientation; Apply is dim. "Hyprland is not running" means you are not in the Hyprland session |
| 0e.20 | Pick another resolution, Apply, then do nothing | The screen changes and a banner says "Keep these display settings? Reverting in N s". At 0 it reverts by itself. `cat ~/.config/hypr/conf.d/monitors.conf` has no new `monitor =` line |
| 0e.21 | Set scale to 125%, Apply, press **Keep changes** | `monitors.conf` has one `monitor = ...` line for that screen. After logging out and in the setting persists |
| 0e.22 | If a card says "Not applied: Hyprland accepted the command but the screen did not change" | That is plan hazard H1: `hyprctl keyword monitor` is a silent no-op on this Hyprland. Send `hyprctl version` and `hyprctl configerrors` |
| 0e.23 | Apply a change and close Settings while the banner is up | The previous mode comes back within a couple of seconds |
| 0e.24 | `hyprctl monitors` | Matches what the cards show |
| 0e.25 | Settings > Power & sleep | Laptop: AC and battery cards plus "Right now: ...". VM or desktop: only the AC card and "no battery" |
| 0e.26 | Set "Lock the screen after" to 1 minute (the active source) | `grep timeout ~/.config/hypr/hypridle.conf` shows 60. `pgrep -a hypridle` shows `hypridle -c .../hypridle.conf`. Idle for a minute and the lock screen appears |
| 0e.27 | Laptop: unplug the charger and wait up to 15 s | `hypridle.conf` switches to the battery timings (default 180 and 900). Plug in and it returns to 300 and 1800 |
| 0e.28 | Set Suspend earlier than Lock | It is moved after Lock and a note explains why |
| 0e.29 | `pgrep -fc darkos-power-watch` | `1` |
| 0e.30 | `systemctl suspend`, then wake | The screen is locked on wake and not black |
| 0e.31 | Settings > Updates | A "Download mirrors" card says "Not ranked by DarkOS yet" (or when it was ranked) |
| 0e.32 | Rank mirrors, authenticate | Progress text, then within about two minutes "Ranked N mirrors; fastest: ...". `head -1 /etc/pacman.d/mirrorlist` starts `# Ranked by DarkOS on`; `grep -c '^Server' /etc/pacman.d/mirrorlist` is at least 3; `sudo pacman -Sy` works |
| 0e.33 | Cancel the password prompt | "Not changed: Cancelled..." and the list is unchanged |
| 0e.34 | Network off, Rank mirrors | "Not changed: reflector failed..." and `/etc/pacman.d/mirrorlist` is unchanged |
| 0e.35 | Restore previous list | The earlier list returns; `/etc/pacman.d/mirrorlist.darkos-bak` stays |
| 0e.36 | `sudo choose-mirror --country DE` | Does what the card does, from a terminal |
| 0e.37 | Live ISO, Settings > Updates | The card says it does nothing on the live ISO and its controls are dim |

Not run by me, so assume nothing about them: the real `hyprctl keyword monitor`, `reflector`, `pkexec` / the polkit
prompt, `hypridle -c`, `powerprofilesctl`, swaybg applying a wallpaper, a battery, the Task Manager on a busy
machine, and how any of the new windows look with blur and rounded corners.

## 0f. Checks specific to the 2026-11-24 pass: Task Manager fix and the opt-in Store (after 0e)

Build under test: the branch with the Store commit on top of `calm-dark`. What changed: the Task Manager's table no
longer uses a GTK filter model (CI run 199 had exited 139, a segfault; the cause below is likely, not confirmed), and
the Store has two new tabs, **Browse** and **Packs**, plus a "Pick your extras" page (4 of 6) in Welcome. All of it
was tested on Ubuntu 24.04 under Xvfb against **fake** `pacman`, `flatpak` and `sudo`: the real install and remove
scripts ran, but never against the real tools. **Most likely to fail: 0f.5 (the gate with one package at a time),
0f.9-0f.10 (Flathub and Flatpak's own commands) and 0f.12 (Steam's provider prompt).**

| # | Do this | Expected |
|---|---|---|
| 0f.1 | Task Manager: select a row, then type in the search box for a minute while the list refreshes, clear it, repeat with "All users" on | No crash and no GTK warning in the terminal you started it from. The table always follows the text; if the selected row is filtered out, End task and Force quit go dim |
| 0f.2 | Open the Store | Opens on **Browse**: 38 cards in an even grid, no banners, nothing featured. Flathub cards say "Flathub · Unscanned" in amber; Arch cards say "Arch repositories". Installed ones (Steam, Geary, Kooha, Lutris, Wine, Waydroid while they are still in the base image) say "Installed". `pacman -Qq \| wc -l` is the same before and after opening it |
| 0f.3 | Click GIMP (or any Arch app) | Detail page: "Shield scans it before it installs." Download shows a size and "in N packages, dependencies included"; compare with `pacman -Sp --print-format '%s' gimp \| paste -sd+ \| bc`. Disk space is a size or "Unknown". Permissions: "Not sandboxed: runs with your own access". Starts at login: "Known after install" |
| 0f.4 | Click Install | The Void opens, asks for sudo, Shield downloads, scans and installs. Close it: within a couple of seconds the card says Installed, Remove... replaces Install, and Starts at login says "No autostart entry found" or "Yes: it adds an autostart entry". Compare with `pacman -Ql gimp \| grep xdg/autostart` |
| 0f.5 | Packs tab: tick Everyday > Geary and Creator > GIMP, then Install selected | One terminal; the gate runs once per package (`darkos-store-gated-install.py`), then it says "Everything you picked is installed". Tell me if any package makes the gate hang or print "choose a provider" |
| 0f.6 | Same, but turn Wi-Fi off first | "These did not install: ..." naming the packages; the cards still say not installed; no half-state |
| 0f.7 | Move `clamscan` away (`sudo mv /usr/bin/clamscan /usr/bin/clamscan.off`), reopen the Store | A line in amber says Shield's scanner is not available; Install is dim for Arch apps, with the reason; Flathub apps still install. Move it back afterwards |
| 0f.8 | Browse: Anki (Flathub) on an account that never added Flathub | Download and Disk space say Unknown, Permissions says Unknown, and a note says Install adds Flathub for your account only |
| 0f.9 | Install Anki | The Void runs `flatpak remote-add --user --if-not-exists flathub ...` then the install. `flatpak remotes --user` lists flathub. Reopen Anki's page: sizes appear, and the permission chips match `flatpak info --show-permissions net.ankiweb.Anki` (broad ones, like all files, are amber) |
| 0f.10 | Remove... on Anki, choose "Remove and delete data" | `~/.var/app/net.ankiweb.Anki` is gone. With "Remove, keep my data" it stays. Cancel does nothing at all |
| 0f.11 | Remove... on an Arch app that has data (Steam, Thunderbird, GIMP) | The dialog lists the real folders with sizes. "Remove, keep my data" leaves them; "Remove and delete data" deletes exactly those folders (nothing else under `~`). If pacman refuses (something depends on it), the data stays even if you chose delete |
| 0f.12 | Install Steam from Browse | Tell me exactly what the terminal shows. Steam depends on a virtual `lib32-vulkan-driver`; if the gate's `pacman -Sp` stops to ask for a provider, the install will fail or hang and that is a real finding |
| 0f.13 | Packs tab | Six packs in order: Everyday, Student, Developer, Creator, Gamer, Office. Nothing ticked; Install selected is dim and says "Nothing selected". LibreOffice is in three packs: ticking it in one ticks it in all. "Select all" flips to "Clear". Already-installed apps are dim and say Installed |
| 0f.14 | `rm ~/.config/darkos/welcome.done ~/.config/darkos/firstboot-extras.*`, log out and in, press Next three times | Page 4 of 6, "Pick your extras": nothing ticked, **Skip** and **Install selected** look the same, Install selected is dim. Walking past it with Next writes nothing |
| 0f.15 | Tick two apps, Install selected (2) | One terminal. On success `~/.config/darkos/firstboot-extras.done` exists; on any failure it does not |
| 0f.16 | Skip | `~/.config/darkos/firstboot-extras.declined` exists; run Welcome again and the page is gone |
| 0f.17 | `diff <(ls /etc/xdg/autostart ~/.config/autostart) <(...)` before and after installing a pack | The Store itself adds nothing. Any new entry belongs to an app you installed, and that app's page says so |

Not run by me, so assume nothing about them: real `pacman -Sp --print-format %s` output (CI probes it), the gate chained
over several packages, a provider prompt inside the gate, `flatpak remote-add --user`, `flatpak remote-info
--show-metadata`, `flatpak uninstall --delete-data`, whether the Store notices the terminal closing, and the Store
window with blur and rounded corners.

## 0. What was and was not verified before you got this

Verified in a Linux sandbox (Python/GTK/headless sway):

- All 18 CI test files pass (`ci/test-*.py`), including `ci/test-polish.py`
  (25 tests for the new code).
- `bash -n` on `build-iso.sh`, `ci/verify-iso.sh`, `profiledef.sh`;
  `shellcheck` clean on `start-hyprland` and `darkos-perf-apply`.
- The real shell starts under a headless Wayland compositor: dock with a clock
  in the centre, left rail, no HUD, no crash.
- Real `swaybg` under headless sway: the default wallpaper appears, switching
  to another one replaces it (one `swaybg` left running), and a bad path in
  `settings.json` falls back to the default.
- Screenshots of the Settings Wallpaper, Performance and Updates tabs were
  checked by eye (this found and fixed three layout/legibility bugs).
- **The Void v2** (split panes, search, engagement workspace, tool launcher,
  session logging, save-scrollback, command palette, and the regex-matching
  half of clickable links) against real spawned `/bin/bash` children and real
  VTE under headless Xvfb — 55 tests in `ci/test-void.py`, plus every
  pre-existing `ci/test-*.py` re-run clean afterward. Two specifics were
  checked empirically rather than assumed, since getting either wrong would
  have broken something real: VTE's `spawn_async` `envv` adds to the
  inherited environment instead of replacing it (so `TARGET`/`ENGAGEMENT_DIR`
  don't clobber PATH/HOME), and `Vte.Regex`'s PCRE2 flag values, read from
  `/usr/include/pcre2.h` rather than typed from memory.
- **App audit** (`docs/APP-AUDIT.md`): every `.desktop`'s `Exec`/`Icon`/
  `Categories`, every `darkos-*.py`'s imports/external commands against
  `packages.x86_64`, every `darkos-*.py` started on headless sway with
  stderr read (new: `ci/headless/app_launch_check.sh`, the `launch` check),
  `pacman.conf`'s `[multilib]`/`[blackarch]`.

**NOT verified (needs you, on the ISO):** the ISO build itself, boot, login,
Hyprland config parsing, every new keybind, Night Light, Focus, Orca, swappy,
PiP, the Updates tab, the wallpaper on the real greeter and lock screen, and
above all **whether the lag is actually fixed** (the working theory is that the
AI assistant caused it; that is untested). Also not verified: The Void v2's
live button-click -> context-menu hop on a real pointer (0d.15 — the regex
matching and the menu actions on either side of that one interaction are both
covered; only the click itself needs a human), and whether real Arch's
`adwaita-icon-theme` has the same symbolic-only icon gaps found on Ubuntu's
(`docs/APP-AUDIT.md` part 1).
Nothing here replaces testing on the VM.

## 1. Build

Easiest: let CI build it. Push to `main`, wait for the green run, download the
release parts (`darkos-iso-part-aa`, `-ab`, ...) and join them in `cmd`:
`copy /b darkos-iso-part-aa + darkos-iso-part-ab darkos.iso` (add the third part
if there is one). The release number must be higher than `v194`, which still
has the AI files. To build on an Arch host instead:

```bash
# Arch host / CI, repo root
sudo ./build-iso.sh            # runs the structural checks first
ci/verify-iso.sh out/*.iso     # path as used in your pipeline
```

Expected: build finishes; `verify-iso.sh` prints no `FAIL`. New packages that
must resolve (all in Arch `extra`): `hyprsunset`, `swappy`, `orca`,
`speech-dispatcher`, `pacman-contrib`. If the build stops with
"target not found", note the package name and tell me.

The squashfs is now zstd (`profiledef.sh`). The ISO is a little bigger than
before; that is expected.

## 2. VM settings (VMware Workstation)

| Setting | Value |
|---|---|
| Firmware | UEFI |
| RAM | 4 GB minimum, 6 GB better |
| CPUs | 2 minimum, 4 better |
| Display | **Accelerate 3D graphics: ON**, graphics memory 256 MB+ |
| Disk | 40 GB+ |

Run the whole manual twice if you can: once with 3D acceleration on, once off.

## 3. Boot and login smoke test

| # | Step | Expected | Result |
|---|---|---|---|
| 3.1 | Boot the ISO | Boot menu, then the Plymouth splash, then login | |
| 3.2 | Note the time from boot menu to login prompt | Write it down: ____ s | |
| 3.3 | Log in | Desktop shows the **Midnight Silk** wallpaper (dark blue silk waves); a plain dark colour (`#0d0f12`) for a moment first is normal | |
| 3.4 | Look at the dock | Centre of the dock is a **clock**, not an orb | |
| 3.5 | Look at the top centre | No HUD ring | |
| 3.6 | Press `SUPER+SPACE` and `SUPER+A` | Nothing happens (assistant is gone) | |
| 3.7 | Press `SUPER+H` | Left and right panels open; left has weather and system gauges, **no AI chat card** | |

If 3.1 or 3.3 hangs, run section 9 and send me the output. The earlier hang at
the boot splash was believed to be `nvidia-open-dkms`, which was removed but
never re-tested, so this is the first real test of that fix.

## 4. Lag measurement (the most important part)

Open the terminal (`SUPER+Return` or `SUPER+Q`) and run each block. Record the
numbers; a "feels fast/slow" note is also useful.

Run this section on **both** the VM and the laptop. The plan's effects names
(Off / Balanced / Full) map to this build's **Lite** (about Off) and **Full**;
there is no Balanced yet.

```bash
# 4.1 Which effects profile and renderer are active?
hyprctl version | head -3          # record this in every test log
cat ~/.config/hypr/conf.d/perf-auto.conf
echo "LIBGL_ALWAYS_SOFTWARE=${LIBGL_ALWAYS_SOFTWARE:-unset}"
systemd-detect-virt

# 4.2 Idle load, wait 60 s after login first
uptime
top -b -n1 -o %CPU | head -15
free -m
cat /proc/pressure/cpu /proc/pressure/memory

# 4.3 Boot cost
systemd-analyze
systemd-analyze blame | head -15
```

Expected after the changes:

- 4.1: profile `lite` in a VM (file contains `blur:enabled = false`).
- 4.2: load average well below your CPU count once the 10 s staggered start-up
  finishes; no process holding a steady 30%+ CPU while you do nothing.
  `/proc/pressure/cpu` `avg60` should be low (single digits).

Then judge responsiveness with these actions and write "ok / sluggish / bad":

| # | Action | Result |
|---|---|---|
| 4.4 | Open Files, Terminal, Settings, one after another | |
| 4.5 | Drag a window around (hold `SUPER` + left mouse) | |
| 4.6 | Type in the terminal | |
| 4.7 | Open and close the panels with `SUPER+H` five times | |
| 4.8 | Watch the dock for 30 s: does the CPU spike every few seconds? (`top`) | |

### 4.9 Try the other settings

Open **Settings > Performance** and change one thing at a time, re-testing 4.4-4.7:

1. Effects = **Full**, then Apply. Expect blur/rounded/translucent windows.
   Note whether it is clearly slower than Lite.
2. Effects = **Lite**, Renderer = **GPU (hardware)**, Apply, then log out and
   back in. With VMware 3D on this may be much faster; if the desktop fails to
   start, switch to a text console (`Ctrl+Alt+F3`), log in, and run:
   ```bash
   sed -i 's/"renderer": *"hardware"/"renderer": "software"/' ~/.config/darkos/settings.json
   ```
3. Renderer = **Software**, log out and in. This is the old behaviour in a VM.

Report which combination was fastest. That tells me whether to change the
default.

## 5. New and changed features

| # | Feature | Steps | Expected | Result |
|---|---|---|---|---|
| 5.1 | Effects profile | Settings > Performance > pick Lite/Full > Apply | Takes effect without re-login; message "Effects applied." | |
| 5.2 | Night Light | Control panel (`SUPER+S`/`SUPER+H`) > Night Light on | Screen turns warmer; status text "Night Light on (4000 K)" | |
| 5.3 | Night Light off | Toggle off | Colour returns to normal | |
| 5.4 | Focus | Toggle Focus on, then `notify-send test hi` | No popup appears | |
| 5.5 | Focus off | Toggle off, `notify-send test hi` | Popup appears (top-right, dark card) | |
| 5.6 | Annotated screenshot | `SUPER+SHIFT+A`, drag a region | swappy opens, draw an arrow, press `Ctrl+S` / save; notification says saved; file in `~/Pictures/Screenshots/` contains the arrow | |
| 5.7 | Plain screenshot | `SUPER+SHIFT+S` and `Print` | Still work as before | |
| 5.8 | Picture-in-picture | Focus any window, `SUPER+SHIFT+P` | Window becomes small (480x270), floats bottom-right, stays visible when you switch workspace (`SUPER+2`) | |
| 5.9 | PiP off | `SUPER+SHIFT+P` again | Unpinned and tiled again | |
| 5.10 | Screen reader | Settings > Accessibility > Speech on | Orca starts and speaks; off stops it. (Needs sound in the VM) | |
| 5.11 | Updates tab | Settings > Updates > Check | On the live ISO the button is disabled with an explanation. On an installed system it lists updates or says up to date | |
| 5.12 | Volume/brightness/media keys | Press the keys (or on a laptop the Fn row) | Volume changes, brightness changes (not in most VMs), play/pause | |
| 5.13 | Fullscreen / move window | `SUPER+F`; `SUPER+SHIFT+2` | Window fullscreens; window jumps to workspace 2 | |
| 5.14 | Mouse move/resize | `SUPER`+left drag, `SUPER`+right drag | Window moves / resizes | |
| 5.15 | Lock screen | `SUPER+L` | Lock screen shows the default (Midnight Silk) wallpaper with the clock; unlocks with your password | |
| 5.16 | Greeter | Reboot an installed system | Login screen shows the default wallpaper | |
| 5.17 | Wallpaper picker | Settings > Wallpaper, click "Alpine Arc" | Desktop changes within about a second with no flash of a plain colour; the tile now says "(current)" | |
| 5.18 | Wallpaper persists | Log out and back in | Still Alpine Arc (not the default) | |
| 5.19 | Own image | "Choose image...", pick any PNG/JPG/WebP | It becomes the wallpaper; after re-login it is still applied | |
| 5.20 | Use default | "Use default" | Back to Midnight Silk | |
| 5.21 | Bad path | Put `{"wallpaper_path": "/nonexistent.jpg"}` in `~/.config/darkos/settings.json`, log in again | Default wallpaper, no error dialog | |
| 5.22 | Wallpaper cost | After 5.17 run `pgrep -a swaybg` and `ps -o rss,cmd -C swaybg` | Exactly one `swaybg`; note its memory | |
| 5.23 | Dropdowns | Settings > Performance | Both dropdowns are readable (light text on a dark box) and their pop-up lists are dark | |

If 5.12 does nothing in a VM, that is normal for brightness; check volume first.

## 6. Installer

1. Start Calamares from the live session.
2. Go through the pages. There is **no longer an "API keys" page**; that is
   expected.
3. Install to the VM disk. Earlier builds failed at the bootloader module, so
   watch that step closely. If it fails, copy the log:
   `/root/.cache/calamares/session.log` (or `~/.cache/calamares/session.log`)
   and `/boot/grub/install.log` if it exists.
4. Reboot without the ISO and confirm you reach the login screen.

## 7. Regression checks (things that should still work)

| # | Check | Expected | Result |
|---|---|---|---|
| 7.1 | Files, Terminal, Notes, Settings, Store, Browser open from dock | Open normally | |
| 7.2 | Dock running-dot | Open an app: its dock icon gets the dot within ~3 s; close it: dot goes | |
| 7.3 | `SUPER+Tab` overview, `Alt+Tab` switcher, `SUPER+E` search | Work | |
| 7.4 | `SUPER+CTRL+Left/Right` snap | Window snaps to half screen | |
| 7.5 | Magnifier (Settings > Accessibility) | Zoom works | |
| 7.6 | Wi-Fi / Bluetooth toggles | Respond (in VM only the network one is meaningful) | |
| 7.7 | `SUPER+L` then unlock, idle for 5 minutes | Locks by hypridle, unlocks | |

## 8. Automated tests (run on any dev machine with GTK3)

```bash
for t in ci/test-*.py; do xvfb-run -a dbus-run-session -- python3 "$t" || echo "FAILED $t"; done
```

All should pass. The workflow runs the same files and `ci/test-ci-coverage.py`
fails if one is left out. Needed typelibs on Debian/Ubuntu: `gir1.2-gtk-3.0
gir1.2-gtklayershell-0.1 gir1.2-vte-2.91 gir1.2-gtksource-3.0
gir1.2-poppler-0.18 python3-gi-cairo xvfb dbus-x11`, plus `librsvg2-common`
(without it the icon-loading test skips) and `desktop-file-utils`. 607 tests at the 2026-11-07 pass (429 before it).
Also run `bash ci/headless/run-all.sh` (real shell on headless sway; needs `sway grim mako waybar`).

## 9. What to send me when something fails

Run this inside the VM and paste the output (or upload the file):

```bash
{
  echo "== version"; cat /etc/darkos-build-sha 2>/dev/null; uname -r; hyprctl version | head -3
  echo "== swaybg"; pgrep -a swaybg
  echo "== virt"; systemd-detect-virt
  echo "== perf-auto"; cat ~/.config/hypr/conf.d/perf-auto.conf
  echo "== settings"; cat ~/.config/darkos/settings.json
  echo "== hyprland errors"
  hyprctl configerrors 2>&1 | head -40
  echo "== failed units"; systemctl --failed --no-pager
  echo "== top"; top -b -n1 -o %CPU | head -15
  echo "== journal (errors, this boot)"; journalctl -b -p err --no-pager | tail -60
} > ~/darkos-report.txt 2>&1; echo saved ~/darkos-report.txt
```

Also say which test number failed and what you saw. `hyprctl configerrors`
is the single most useful line: this build added keybinds, a misc option set
and a `source` line that I could not check against a real Hyprland.

## 10. Known gaps (not done in this pass)

- The opt-in Store, generated colour palette/icon family/type scale, the shell
  spike (GTK3 vs GTK4 vs Quickshell vs DankMaterialShell), Windows and Android
  lanes: planned in `docs/MASTER-PLAN.md`, not built.
- Drag-to-edge window snapping, a desktop widgets board, tabs in the file
  manager, multi-monitor dock placement: not built.
- The lock screen and greeter always use the default wallpaper, not the one you
  picked.
- Cloud accounts/tiers: not built (needs real credentials and a backend).
- Captions and sticky keys: not built (captions needed the removed speech
  pipeline).
- The VMware automation scripts that verified the removed assistant were deleted
  (they are in history at `2b149a1`). A small new harness belongs in plan phase P1.
- The installed-system checks (Btrfs snapshots, ClamAV, firewall) are
  unchanged and still unverified on real hardware.
- 15 of 21 distinct app icons are legacy (non-symbolic) freedesktop names that
  the installed `adwaita-icon-theme` only ships `-symbolic` forms of (reported
  in `docs/APP-AUDIT.md` part 1, not renamed in this pass).

Not done in the 2026-11-07 pass, in `docs/STATUS.md` order: the opt-in Store (starter packs, first-run "pick
your extras"), packaging (PKGBUILDs and a signed repo), the Update Center, and the base diet. The last three can only
be verified by building and booting an ISO. Also not done: screen-off timeouts (`ci/verify-iso.sh` forbids
`dpms off` under hyprlock), multi-monitor arrangement and mirroring in Settings > Display (positions are kept as they
are), and giving Notes and Reader different icons.

## 11. Results table (copy per run; plan Appendix B)

Commit: ________   `hyprctl version`: ________

| Test | VM | Laptop | Notes |
|---|---|---|---|
| 1 Build (CI builds, `verify-iso.sh` passes) | | | |
| 2 Fresh boot (time to desktop) | | | |
| 3 Idle CPU, 60 s, Lite and Full | | | |
| 4 Command Center open/close, CPU back to idle | | | |
| 5 All apps open; titlebar buttons work | | | |
| 6 Window tools: Alt+Tab, snap, overview, search, PiP | | | |
| 7 Store | not built | not built | opt-in Store is plan phase C |
| 8 Effects level and renderer (Settings > Performance) | | | |
| 9 Wallpaper picker (5.17-5.22) | | | |
| 10 Design check (3 screenshots) | | | needs the UI references |
| 11 The Void: split panes, search, close/merge (0d.1-0d.7) | | | |
| 12 The Void: engagement workspace, set target, tool launcher (0d.8-0d.10, 0d.13-0d.14) | | | |
| 13 The Void: session logging, save scrollback, command palette (0d.11-0d.12, 0d.16) | | | |
| 14 The Void: clickable links, right-click menu, Ctrl+click (0d.15) | | | the one item not run in this pass at all |
| 15 Icons and Welcome (0e.1-0e.11) | | | |
| 16 Task Manager (0e.12-0e.18) | | | |
| 17 Display settings (0e.19-0e.24) | | | 0e.22 is the H1 check |
| 18 Power & sleep (0e.25-0e.30) | | | needs a laptop for 0e.27 |
| 19 Mirror ranking (0e.31-0e.37) | | | |

