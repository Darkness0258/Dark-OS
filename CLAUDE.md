# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Commands

- `sudo bash build-iso.sh` — full ISO build: stages a clean archiso releng profile, repairs permissions/symlinks, builds the pinned Calamares package into a local pacman repo, runs `mkarchiso`, extracts the built SquashFS and verifies executables match source byte-for-byte, then runs `ci/verify-iso.sh`. Publishes a versioned ISO (`out/darkos-YYYY.MM.DD-x86_64.iso`) and atomically updates the `out/darkos.iso` symlink. Set `DARKOS_KEEP_WORK=1` to preserve temp directories for debugging.
- `bash ci/verify-iso.sh out/darkos-*.iso` — standalone post-build artifact verification: extracts the ISO squashfs and initramfs, checks critical payload files, permissions, executable modes, script syntax, Waybar module set, greetd/ReGreet config, Hyprland/hypridle/hyprlock settings, Plymouth theme, pacman.conf signature checks, systemd symlinks, package list entries, and byte-identical payload scripts.
- `bash ci/build-calamares.sh /tmp/repo` — builds the pinned Calamares AUR package (commit `167151beb`, version 3.4.2) and publishes a local pacman repo. Accepts `DARKOS_CALAMARES_PACKAGE` + `DARKOS_CALAMARES_PACKAGE_SHA256` to reuse a verified cache.
- `bash -n <script>` — syntax-check shell scripts. CI checks all `airootfs/usr/local/bin/*.sh` plus `build-iso.sh`, `ci/build-calamares.sh`, `ci/verify-iso.sh`, and `profiledef.sh`.
- `python -m py_compile <file>` — syntax-check Python scripts.
- `git ls-files -s <file>` — verify a file's git mode is `100755` (executable tracked in git).
- `git show HEAD:<path> | od -c | head -3` — inspect committed bytes to confirm LF-only line endings.
- Boot in QEMU (UEFI only): copy `OVMF_VARS.4m.fd` to `/tmp/darkos-vars.fd` first, then `qemu-system-x86_64 -m 4096 -enable-kvm -cdrom out/darkos.iso -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd -drive if=pflash,format=raw,file=/tmp/darkos-vars.fd`.

## Developing Without a Full Rebuild

Many changes (GTK CSS, shell surface code, Waybar config, Hyprland config) can be iterated on directly inside a running VM:

- **Shell CSS or panel layout:** edit `airootfs/usr/local/bin/darkos-shell.py` in the source checkout, then restart the shell inside the VM with `pkill -f darkos-shell.py` and then `python /usr/local/bin/darkos-shell.py &` (or log out/in). The build's byte-identical check will catch any unintended edits when you eventually run `build-iso.sh`.
- **Waybar config/CSS:** edit files under `airootfs/etc/xdg/waybar/`, then `killall waybar && waybar &`.
- **Hyprland config:** edit `airootfs/etc/xdg/hypr/hyprland.conf`, then `hyprctl reload`.

Run the full build only when you need to verify packaging, permissions, symlinks, and the Calamares build all still pass.

### Live-testing helpers

No VM helper scripts are kept in the repository. `out/` is build output; any scripts found there are local to one developer machine and unverified.

## Validation

Correctness is enforced through:

- `ci/test-*.py` -- unit and integration tests. CI's "Run Linux backend and
  native app regressions" step lists the ones it runs; GTK ones need
  `xvfb-run -a dbus-run-session -- python ci/test-<name>.py`. Add a test with
  every change, and prove it can fail (run it against the old code).
- `bash -n` for shell scripts, `python -m py_compile` for Python.
- `bash ci/headless/run-all.sh` -- the real shell on a headless sway compositor
  (dock layout, main-loop stalls, screenshots). Needs sway; see its README.
  It is not Hyprland, so it does not replace the checks below.
- Full `sudo bash build-iso.sh` for packaging, permission, symlink, and Calamares changes.
- `bash ci/verify-iso.sh` for post-build artifact checks.
- QEMU boot for installer, bootloader, login, and shell-surface changes.

When in doubt, run the full build and boot the ISO in QEMU.

### Rules learned the hard way

- **Never block the GTK main thread.** No `subprocess.run`, network, or AT-SPI
  call inside a GLib timeout/idle callback: do the work in a thread and hand
  the result back with `GLib.idle_add`. `ActivityDetector` once froze the whole
  shell for seconds at a time this way. `ci/headless/stall_check.py` measures it.
- **One `Gtk.Application` registered per process in tests.** On a session bus
  only the first can become primary; later ones fail with a GLib-GIO CRITICAL.
  Share one across tests.
- **Settings are read once at import**, except `dock_position`/`dock_size`,
  which the running shell applies live by watching `settings.json`.
  `save_settings` writes atomically (temp file + rename) because of that
  watcher; keep it that way. A new value with a fixed set of choices goes in
  `user_settings.CHOICES` so bad values fall back instead of reaching GTK.
- **Only claim what was verified.** Say where it was verified (headless
  sway, xvfb, unit test, VM) and what was not.

## Windows Developer Host

This repo is developed on a Windows host with `core.autocrlf=true`. All shell scripts **must** maintain Unix LF (`\n`) line endings — CRLF causes `exit code 126` shebang failures at runtime. Executable scripts must have matching `100755` git mode and `eol=lf` in `.gitattributes`. The build rejects CRLF bytes and missing execute bits at four stages.

## CI Releng Copy Warning

At build time, mkarchiso copies releng profile defaults into `airootfs/`. Do **not** commit conflicting base files (e.g. `airootfs/etc/passwd` from releng) that would break releng seeding — keep only the project's additions and overrides in `airootfs/`.

## Changing build inputs

For any change touching `build-iso.sh`, `ci/verify-iso.sh`, `ci/build-calamares.sh`, `profiledef.sh`, `packages.x86_64`, `pacman.conf`, or any file under `airootfs/`, follow the enforcement-point rules in this file (the `darkos-build` skill that used to document them is not in the repository) and run every test the workflow runs before pushing.

## Project Structure

DarkOS is an ArchISO profile for an Arch Linux respin (the AI assistant was removed 2026-10-17). The live ISO payload lives under `airootfs/`. Build inputs are `packages.x86_64`, `pacman.conf`, `profiledef.sh`, and `build-iso.sh`. CI helpers live in `ci/`. Generated ISOs go to `out/`.

Runtime scripts are in `airootfs/usr/local/bin/`, three `.desktop` launchers in `airootfs/usr/share/applications/` (`darkos-installer`, `the-void`, `darkos-tool-groups`), Hyprland/Waybar config in `airootfs/etc/xdg/`, Calamares modules in `airootfs/etc/calamares/`, and systemd enablement in `airootfs/etc/systemd/system/`.

## Stack and Boundaries

- **Base:** Arch Linux respun with `archiso` — inherits pacman + AUR.
- **Security tools:** BlackArch repository layered onto the Arch base via `pacman.conf`.
- **Compositor/shell:** Hyprland (Wayland). Its `hyprctl` IPC socket is used by the dock, window-fx and settings helpers.
- **Installer:** Calamares (graphical).
- **Login / lock / boot:** greetd + ReGreet under Cage for installed login; `hyprlock` + `hypridle` for session locking; Plymouth for early-boot splash.
- **Shell UI:** GTK3 + gtk-layer-shell Python process creating Wayland layer-shell surfaces.
- **Windows compatibility:** Wine 11 / Bottles / Proton / QEMU/KVM — integration, not custom code.

**Non-negotiable boundaries:**

- System control goes through D-Bus / `hyprctl` / AT-SPI / standard CLI tools — never raw input injection. Wayland's security model blocks synthetic input.
- The shell never runs a blocking subprocess on the GTK main thread (the dock polls `hyprctl` on a worker thread) and does not poll while its panels are hidden.
- BlackArch tools are opt-in tool *groups* at install/setup time, not force-installed as one 2,900-package blob.
- Hosted apps are never modified or forked. Visual consistency comes from Hyprland's compositor-level decorations, not app-level changes.
- "Settings" is one app with many tabs, not 20 separate apps.

## Architecture

### Shell surface (Calm Dark)

The shell is a single GTK3 + gtk-layer-shell Python process (`darkos-shell.py`) owned by a single `Gtk.Application` instance. A fresh instance is created on the first `activate()` call; subsequent calls return immediately, which is why command-line flags like `--toggle-command-center` work on an already-running process. The application owns shared toggle state (`wifi`, `bluetooth`, `night_light`, `focus`, `airplane`; every one has a real backend) and propagates it to registered listeners via `register_state_listener` / `notify_state_listeners`.

Two layer-shell windows, plus Waybar as the status bar:

- `darkos-dock` (`DarkOSDockWindow`): floating dock on any edge. An **Apps** button (runs `darkos-window-fx.py --search`, the same overlay as `Super+E`), a divider, then Files, Terminal, Browser, Notes, Store, Settings. No clock (it is in Waybar). Exclusive zone is computed from the measured dock thickness (`tokens.dock_exclusive_zone`). The only surface that is frosted (blurred by the compositor).
- `darkos-center` (`DarkOSCommandCenter`): one solid panel at the top right, closed at start. Five toggles, volume and brightness sliders (read from `pamixer` / `brightnessctl`; a slider with no backend is hidden), notifications (parsed from `makoctl list` + `makoctl history` JSON; "Clear all" remembers the newest id because mako cannot clear history), a media section that exists only while a player does, compact `ResourceRow`s for CPU / memory / disk / GPU (GPU hidden when unavailable) and a calendar. Timers start on map and stop on unmap. `--toggle-side-panels`, `--toggle-command-center` and `--toggle-control` all toggle it.
- Waybar (`etc/xdg/waybar/`): the slim top bar. Its `style.css` is generated, see below.

Gotchas that already cost time: a layer-shell window is sized to its *minimum* request, so the panel pins its scroller's `min_content_height` to the content (`_fit_height`); `show_all()` does nothing on a `no_show_all` widget, so use `reveal()`; a `Gtk.Stack` only switches to a child that is itself visible.

`set_installer_mode(on)` hides both surfaces and records their visibility; `set_installer_mode(off)` restores them. This is the mechanism `darkos-installer` uses to suspend the shell while Calamares runs.

### Installer flow

`darkos-installer` is a session-aware wrapper. It preserves `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, and display variables through `sudo --preserve-env`, sends `--installer-mode on` to the shell process to hide all overlays, runs `calamares`, then restores the shell on exit via a trap. It requires `/run/archiso` to exist (live ISO only), enforced at the wrapper level.

### Bootloader repair

Calamares' bootloader job invokes `darkos-grub-install.sh` (not the built-in `bootloader` module directly). The script validates the ESP is a physical FAT partition with the EFI System Partition type, runs `grub-install --removable --no-nvram`, generates `grub.cfg` to a temp file and atomically moves it only after validation, writes a completion marker to `/var/lib/darkos-grub-repair.done`, and logs everything to `/boot/grub/install.log`. It uses `flock` on `/run/lock/darkos-grub-repair.lock` to prevent concurrent runs.

The `darkos-grub-repair.service` retries on first installed boot only when the completion marker is absent. `ConditionPathExists=!/run/archiso` prevents it from running on the live ISO.

### First-boot BlackArch tool flow

`darkos-firstboot-tools` runs via Hyprland `exec-once` on every session start but acts only once: it skips on the live ISO (`/run/archiso`), skips if a completion or decline marker exists in `~/.config/darkos/`, otherwise shows a wofi dialog. If the user accepts, it launches `darkos-tool-groups` in a terminal for interactive sudo-authenticated group selection.

### Boot and login

Live ISO: `autologin.conf` overrides `getty@tty1.service` to run `darkos-tty1-login`, which autologins as `darkos` only on the live ISO and falls back to a looping getty otherwise. The installed system uses `greetd` + `ReGreet` under `cage` with `GDK_DISABLE=dmabuf,vulkan` and `GSK_RENDERER=cairo` for VMware-safe software rendering.

`start-hyprland` sets `XDG_CURRENT_DESKTOP=Hyprland`, `XDG_SESSION_TYPE=wayland`, `XDG_SESSION_DESKTOP=Hyprland`, and `PYTHONWARNINGS=ignore::SyntaxWarning`, then delegates to the upstream `/usr/bin/start-hyprland` if present, falling back to `/usr/bin/Hyprland`. This wrapper is called from `.bash_profile` via `dbus-run-session -- start-hyprland`.

### Lock and idle

`hypridle` handles idle timeout (locks via `darkos-lock`) and before-sleep. `darkos-lock` is a thin wrapper that selects `LIBGL_ALWAYS_SOFTWARE=1` on VMware automatically (via `/sys/module/vmwgfx` or DMI check) to avoid `wl_surface` invalidation, then delegates to `hyprlock`. It accepts `DARKOS_HYPRLOCK_RENDERER=auto|software|hardware` to override the detection. `hyprlock` uses `screencopy_mode = 1` for CPU-based screencopy on the same VMware path. `hypridle` must not dispatch `dpms off` while `hyprlock` owns the session lock.

Hyprlock's config parser treats `#` as a comment delimiter. Any literal `#` inside a string value must be escaped as `##` (e.g. `<span foreground="##9aa4ad">`). This is required for Pango markup color values in `input-field` `placeholder_text` and `fail_text`, and is the same convention catppuccin and other production hyprlock themes use.

### Calamares modules

Custom modules in `airootfs/etc/calamares/modules/` handle the install pipeline: `welcome.conf` (connectivity check), `partition.conf` (LUKS1, small swap), `users.conf`, `removeuser.conf` (removes live `darkos` user), `services-systemd.conf` (enables greetd in installed system), `packages.conf`, `unpackfs.conf`, `shellprocess@bootloader-install.conf` (the guarded wrapper), `shellprocess@pacman-keyring.conf` (stops GnuPG agent before keyring init), and `shellprocess@live-cleanup.conf`.

The `settings.conf` `exec:` sequence runs `removeuser` before `users` so the live account is cleaned up before the real one is created; `shellprocess@live-cleanup` removes live-only sudoers and autologin; `grubcfg` writes GRUB defaults (not the actual install); the bootloader runs via `shellprocess@bootloader-install` (not the built-in `bootloader` module) to avoid exit-126 permission failures. `users` must run before `packages` and `shellprocess@pacman-keyring` — running it last in the exec sequence caused the password hash write to `/etc/shadow` to silently fail in the degraded post-packages chroot. `disable-cancel-during-exec` and `hide-back-and-next-during-exec` are both true.

## Build Pipeline

The build enforces correctness at **four stages**: source checkout, staged profile, built SquashFS, and final ISO payload. Every shipped script must be byte-identical across all four.

The `[darkos-local]` pacman repo is built by `ci/build-calamares.sh` and injected at the top of `pacman.conf` during staging, so the pinned Calamares package always resolves before network repos.

`build-iso.sh` derives a build SHA from the git checkout (or `DARKOS_BUILD_SHA` / `GITHUB_SHA`). The first 8 hex chars are written into `etc/darkos-build-sha` in the staged profile. Build environment issues almost always trace to a missing command or a checkout outside a git repository.

`profiledef.sh` declares `file_permissions` as a plain associative array (not `declare -A`), because mkarchiso sources it from inside a function — `declare -A` would make the map function-local and silently reset every permission to 0644. It also derives `iso_version` from `date +%Y.%m.%d`, so each build gets a date-stamped version.

## Build Invariants

Every script in the `runtime_scripts` list must be:

- Mode `755` in the source checkout, staged profile, built squashfs, **and** final ISO payload — asserted by `assert_runtime_scripts` at four stages.
- Have a `#!` shebang on the first line.
- Free of CRLF bytes (CRLF causes exit code 126 at runtime).
- Byte-identical between `airootfs/` source and the packaged squashfs (`cmp -s`).
- Listed in `bash_scripts` if it's a shell script (passes `bash -n`), or `python_scripts` if it's Python (passes `python -m py_compile`).

When adding a new runtime script, you must update **all four** enforcement points: the source file itself, `profiledef.sh` `file_permissions`, `build-iso.sh` `runtime_scripts` + `bash_scripts`/`python_scripts`, and `ci/verify-iso.sh` `payload` + `scripts` arrays.

## Live ISO vs Installed System

Several scripts behave differently depending on whether `/run/archiso` exists (present on the live ISO, absent on an installed system). This is the canonical discriminator used throughout the codebase:

- `darkos-tty1-login` — autologins as `darkos` only when `/run/archiso` exists.
- `darkos-firstboot-tools` — skips entirely on the live ISO.
- `darkos-installer` — refuses to run without `/run/archiso`.
- `darkos-grub-repair.service` — `ConditionPathExists=!/run/archiso` prevents first-boot repair on the live ISO.

When changing any of these scripts, verify both paths (live and installed).

## VMware Compatibility

The target test environment is VMware Workstation. Several components have explicit software-rendering paths for VMware's SVGA adapter:

- `the-void.sh` — forces `LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe` when `systemd-detect-virt --vm` succeeds.
- `darkos-lock` — same detection for `hyprlock` + `LIBGL_ALWAYS_SOFTWARE`. Override with `DARKOS_HYPRLOCK_RENDERER=software|hardware` (default `auto`).
- `start-hyprland` and greetd/ReGreet — `GDK_DISABLE=dmabuf,vulkan` and `GSK_RENDERER=cairo` for software rendering.
- `hyprland.conf` — `AQ_NO_HARDWARE_CURSORS=1` to avoid cursor issues with llvmpipe.
- `darkos-installer` — `QT_QUICK_BACKEND=software` for Calamares inside a VM.

Changes that work on bare metal may fail silently in VMware. Test inside the QEMU/VM path before assuming correctness.

## Shell CSS and Design Tokens

`darkos_shell/palette.py` (pure Python, no GTK) generates the colours: three tonal surfaces (base, raised, overlay), text, one accent and semantic colours, from the accent seed (default `#00E5FF`), and validates them (`validate()`: 4.5:1 text, 3:1 control borders, surface steps of at least 1.15:1, any accent). `tokens.py` reads settings once at import and exposes the palette, the type scale (12/14/16/20/28), spacing (4/8/16/32/48), radii (8/16/24) and motion targets; the old `COLOR_*` / `CAIRO_*` names are kept as aliases (one accent: blue and purple are gone). `css.py` renders the stylesheet from a `string.Template` (no doubled braces); it may only use scale font sizes and palette colours, no transitions, and a glow ring only on `:focus` (all enforced by `ci/test-design-tokens.py`).

Static files cannot read tokens, so `tools/gen-theme.py` renders them from the same palette: `waybar/style.css`, `mako/config` and `regreet.css` whole, and only the colour lines of `hyprlock.conf`, `hyprland.conf`, Calamares `branding.desc`/`show.qml` and `wallpapers.FALLBACK_COLOR`. Run `python3 tools/gen-theme.py` after changing the palette; CI runs `--check`. Known limit: they use the default accent, so a custom accent recolours the shell and apps (after a shell restart) but not these. Appearance settings say "Applies after restart" unless they really apply live.

## CI

GitHub Actions (`.github/workflows/build-iso.yml`) runs on every push to `main` and on manual dispatch. It builds inside an `archlinux` container with `--privileged` on `ubuntu-latest`. Steps:

1. Install build deps (`archiso`, `base-devel`, `desktop-file-utils`, `python-yaml`, etc.).
2. **Validate profile sources** — `bash -n` on all shell scripts (`build-iso.sh`, `ci/*.sh`, `profiledef.sh`, and every `airootfs/usr/local/bin/*.sh`); `compile()` on `darkos-shell.py`; `yaml.safe_load` on every Calamares `.conf` plus `airootfs/usr/share/calamares/branding/darkos/branding.desc`; `desktop-file-validate` on every `.desktop` launcher.
3. Seed Chaotic-AUR and BlackArch keyrings/mirrorlists, verifying the BlackArch sync DB is non-empty before proceeding.
4. Run `bash build-iso.sh` (no `sudo` — the privileged container runs as root).
5. Split the ISO into 1900M parts and publish as a GitHub Release tagged `v<run_number>`.

## Security

`ci/verify-iso.sh` rejects `TrustAll` in the packaged runtime `pacman.conf`. Preserve secure modes for `/etc/shadow` (0600), `/etc/gshadow` (0600), `/root/.gnupg` (0700), and sudoers files (0440/0750). BlackArch and Chaotic-AUR mirror/keyring changes are security-sensitive — the pinned BlackArch HTTPS endpoint and the verified Chaotic-AUR keyring flow are intentional.

## Design System Reference

Colours come from `darkos_shell/palette.py`, exposed through `darkos_shell/tokens.py` (the source of truth for the shell and apps); `css.py` and `tools/gen-theme.py` derive from them. Design direction and rules are in `docs/MASTER-PLAN.md` section 5.

## Multi-Agent Instructions

`AGENTS.md` (root) contains workspace-level multi-agent session rules. Comments in source files that cite `architecture.md`, `build-plan.md`, `ui-rules.md`, `ui-tokens.md` or `ui-registry.md` refer to documents deleted in commits 683bea4 and 75ebfa4; read them with `git show 683bea4~1:<name>` (they predate the 2026-10 changes). Read them when spawning subagents or interpreting agent-framework directives in this repo.

## Phased Roadmap

The AI assistant was removed on 2026-10-17 (and its leftovers on 2026-10-19). Earlier phase claims are historical records; what is currently verified is tracked in `docs/STATUS.md`, and the current phases (P0-P12) are in `docs/MASTER-PLAN.md`. Nothing has been boot-verified since the removal.

## Wallpapers and desktop effects (added 2026-10-17)

- **Wallpapers.** Nine JPEGs plus 320x180 thumbnails live in `airootfs/usr/share/backgrounds/darkos/`; `darkos_shell/wallpapers.py` is the catalogue (`CATALOG`, `DEFAULT_FILE`) and the only code that starts `swaybg`. `darkos-window-fx.py --wallpaper-apply` runs from `hyprland.conf` at login and from Settings > Wallpaper. The greeter (`regreet.toml`) and lock screen (`hyprlock.conf`) use the default image. To add a wallpaper: add the JPEG and a thumbnail, add a `CATALOG` row, and add both paths to `wallpaper_assets` in `ci/verify-iso.sh` (`ci/test-polish.py` fails if a shipped JPEG is missing from the catalogue).
- **Fallback colour.** `wallpapers.FALLBACK_COLOR` must equal `misc:background_color` in `hyprland.conf` (a test checks this).
- **Effects profile.** `darkos-perf-apply` writes `~/.config/hypr/conf.d/perf-auto.conf` (Lite or Full); `hyprland.conf` sources it as its LAST line so Lite's overrides win. Settings > Performance writes `effects` and `renderer` to `settings.json`.
- **Nothing blocks the GTK main thread.** The dock polls `hyprctl` on a worker thread, and hidden panels do not poll. Keep it that way; new periodic work needs the same.
- **Adding a file** still means registering it in `build-iso.sh`, `profiledef.sh` and `ci/verify-iso.sh`.

## Running the tests in an Ubuntu 24.04 sandbox

```
apt-get install -y --no-install-recommends python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
  gir1.2-vte-2.91 gir1.2-gtklayershell-0.1 gir1.2-poppler-0.18 xvfb dbus-x11 \
  fonts-inter fonts-jetbrains-mono adwaita-icon-theme sway grim mako-notifier \
  libnotify-bin waybar
export PYTHONDONTWRITEBYTECODE=1
python3 ci/test-app-kit.py        # plain ones
xvfb-run -a dbus-run-session -- python3 ci/test-design-tokens.py   # GTK ones
bash ci/headless/run-all.sh       # real shell on headless sway
python3 tools/gen-theme.py --check
```

Screenshots on headless sway (no blur, no Hyprland) are a layout check, not a look check. `__pycache__` must not end up in the repo or a zip handed to the user.

## Where we left off (2026-10-22)

Branch `calm-dark` holds the Calm Dark pass (see `docs/STATUS.md`). The user's order of work is: redesign the UI/UX (shell, tokens, CSS and Settings are done; the other apps pick the design up through the shared stylesheet and are unchecked), then **The Void** (the terminal, `darkos-terminal.py`) made more powerful than a normal terminal with BlackArch abilities, then make every app and package work, then the backlog. The user asked for implementation, not coaching, for this work.

**The Void v2, not started.** Today it is 273 lines of GTK3 + VTE: tabs, zoom, copy/paste. The generic app test instantiates the first `Gtk.ApplicationWindow` subclass in the module with only `app`, and `ci/test-native-apps-linux.py` drives `--cwd DIR` and `-e CMD ARGS`; keep both contracts. Plan: put the logic in a GTK-free package (`darkos_void/`: engagement workspace, tool catalogue, link classification) so it is unit-testable, with the window in `darkos-terminal.py`. Features, in value order: (1) split panes and a pane/tab model with focus and close rules; (2) search in scrollback (`Vte.Regex`, next/previous); (3) an **engagement workspace**: a name, a target and a notes folder (`~/engagements/<name>/{scans,loot,notes,logs}` plus `engagement.json`), exported as `TARGET` / `ENGAGEMENT_DIR` to new shells; (4) session logging per tab (wrap the shell in `script -qf`) and "save scrollback as text"; (5) a **tool launcher** over the BlackArch groups already defined in `airootfs/usr/local/bin/darkos-tool-groups` (installed state via `pacman -Qq`, insert a command template with `$TARGET` expanded, never auto-run), installing through the existing group installer; (6) clickable URLs, IPs, CIDRs, hashes and CVE ids via `match_add_regex`, with a context menu ("set as target", copy, open); (7) a command palette. Do not reimplement security tools; make them discoverable and context-aware. Tests: `ci/test-void.py` already pins the theme and tab fixes; add pure tests for the package and VTE tests under xvfb. Register every new `ci/test-*.py` in `.github/workflows/build-iso.yml` or `ci/test-ci-coverage.py` fails.

**App audit, not started.** For each `.desktop` in `airootfs/usr/share/applications`: `Exec` resolves, `Icon` exists (standard names only; the `darkos-*` window ids are not icons), `Categories` valid. For each `darkos-*.py`: imports and external commands against `packages.x86_64`, then start it on headless sway and read stderr. Check `pacman.conf` has `[multilib]` and `[blackarch]` for the packages that need them. Not checkable here: Arch package existence and versions.
