# DarkOS Testing Manual

Build under test: the 2026-10-17/18 change set (AI assistant removed, nine
wallpapers restored with a Settings picker, Lite/Full effects profile, new
features, lag fixes) as cleaned up by the 2026-10-19 P0 pass. This file lists
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

**NOT verified (needs you, on the ISO):** the ISO build itself, boot, login,
Hyprland config parsing, every new keybind, Night Light, Focus, Orca, swappy,
PiP, the Updates tab, the wallpaper on the real greeter and lock screen, and
above all **whether the lag is actually fixed** (the working theory is that the
AI assistant caused it; that is untested).
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
gir1.2-poppler-0.18 python3-gi-cairo xvfb dbus-x11`.

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

