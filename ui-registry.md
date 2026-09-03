# UI Registry

## WaybarTopBar
- Purpose: Persistent logo, workspace, date/time, tray, display, Bluetooth, network, sound, battery, avatar, control, and power status.
- Variants: Resting, hover, active workspace, warning battery, critical battery.
- Tokens used: `color-bg-elevated`, `color-surface`, `color-border`, semantic colors, `space-xs/sm/md`, 8px control radius, 16px panel radius.
- Used in: `airootfs/etc/xdg/waybar/config` and `style.css`; launched by Hyprland.
- Notes: The avatar is informational and does not create a second settings surface.

## AICoreHUD
- Purpose: Central assistant radar, ring state, and "Dark OS / Control Everything" identity.
- Variants: Idle, listening, thinking, speaking, error.
- Tokens used: `color-primary`, `color-secondary`, `color-danger`, text colors, ring/gauge language.
- Used in: `DarkOSHUDOverlay` (internal radar canvas) in `darkos_shell/surfaces.py`.
- Notes: Activity increases ring brightness and rotation speed; AI requests remain explicit previews.

## AppIconRail
- Purpose: Always-visible access to AI, Files, Terminal, Settings, Browser, Gallery, Store, Notes, Music, and Gaming.
- Variants: Resting, hover, keyboard focus.
- Tokens used: Elevated background, border, primary/text colors, `space-xs/sm`, 8px control radius, 16px panel radius.
- Used in: `DarkOSIconRail`; TOP-layer namespace `darkos-rail`.
- Notes: Missing future apps report an honest phase stub instead of claiming launch success.

## LeftInformationPanels
- Purpose: Left-of-center AI chat preview, weather status, and live CPU/GPU/RAM/storage/network overview.
- Variants: Live local metric, unavailable metric, AI preview, unexecuted response.
- Tokens used: Glass panel, semantic warning, spacing scale, 16px panel radius, ring/gauge language.
- Used in: `DarkOSLeftPanels`; TOP-layer namespace `darkos-left`.
- Notes: Weather has no service dependency in Phase 2 and states that directly.

## RightUtilityPanels
- Purpose: Grouped notifications, shared connectivity controls, volume/brightness, live media metadata, and calendar.
- Variants: Connected/disconnected, active/inactive toggle, live/no media, status/stub message.
- Tokens used: Glass panel, primary/secondary/accent and semantic colors, spacing scale, 8px controls, 16px panels.
- Used in: `DarkOSRightPanels`; TOP-layer namespace `darkos-right`.
- Notes: State is owned by `DarkOSApplication`; Night Light, Focus, and notification history identify themselves as previews.

## FloatingDockAndAIOrb
- Purpose: Bottom app launcher with an enlarged central assistant state control.
- Variants: Sleeping, listening, thinking, speaking, brief error pulse.
- Tokens used: Background, primary/secondary/accent/danger colors, `space-xs/sm/md`, 8px controls, 24px dock radius.
- Used in: `DarkOSDockWindow` and `AIOrbCanvas`; TOP-layer namespace `darkos-dock`.
- Notes: Store and Settings intentionally remain `wofi --show drun` placeholders.

## SecureLockScreen
- Purpose: PAM-authenticated, ext-session-lock-v1 session protection.
- Variants: Idle, password entry, checking, success, authentication failure.
- Tokens used: Black background, elevated surface, primary/secondary, text/muted, success/danger, 16px input radius, 24px logo radius, 24px blur.
- Used in: `/etc/xdg/hypr/hyprlock.conf`; triggered by `hypridle`, logind lock events, suspend, and `SUPER+L`.
- Notes: Implemented with upstream `hyprlock`, not a bypassable layer-shell overlay.

## ReGreetLogin
- Purpose: Installed-system user/session authentication and DarkOS session launch.
- Variants: User/session selection, password entry, informational message, destructive power actions.
- Tokens used: Dark background, elevated glass surface, primary/text/semantic colors, 8px controls, 16px panel radius, Inter typography.
- Used in: `/etc/greetd/`; ReGreet runs under Cage and launches `darkos.desktop`.
- Notes: Enabled by Calamares only on installed systems; the live ISO retains its separate autologin flow.

## PlymouthBoot
- Purpose: Branded progress feedback from early boot until the graphical login/session starts.
- Variants: Progress-driven logo opacity.
- Tokens used: Pure black, electric cyan, canonical DarkOS logo.
- Used in: `/usr/share/plymouth/themes/darkos/`; selected for live and installed initramfs builds.
- Notes: The logo is copied from the canonical Calamares branding asset during ISO staging.

## FileExplorer
- Purpose: Native daily-use file browsing, basic file ops, and archive preview/extract/compress.
- Variants: Normal listing, filtered (search), empty folder, error dialog, archive-contents dialog.
- Tokens used: `color-bg-alt`, `color-bg-elevated`, `color-primary`, text/muted colors, 8px control radius, monospace token (archive listing).
- Used in: `FileExplorerWindow` in `darkos-files.py`; app rail "files" action; launched with `--cwd` from Terminal's counterpart action.
- Notes: Normal floating GTK3 window, not layer-shell — glass/rounding comes from Hyprland's `decoration{}` + the `darkos-files` windowrule, not custom CSS alpha. Every control is a stock GTK3 widget (TreeView/ListBox/dialogs) so AT-SPI can drive it generically. Archive support previews + extracts/compresses; browsing inside an archive like a folder is a documented follow-up, not built yet.

## NativeTerminal
- Purpose: "The Void" — tabbed terminal emulator replacing the kitty-backed Phase 1 default.
- Variants: Single tab, multiple tabs, active/inactive tab, child-exited (auto-closes tab).
- Tokens used: `color-primary` (active tab underline + bright-cyan ANSI slot), `color-bg-alt`, a dedicated 16-slot ANSI palette derived from the token set, monospace token.
- Used in: `TerminalWindow`/`TerminalPage` in `darkos-terminal.py`; launched via `the-void.sh` (app rail "terminal" action, and by anything that shelled out to the old kitty wrapper — `-e CMD` contract preserved).
- Notes: Vte.Terminal owns actual emulation (PTY/ANSI/scrollback); this component is chrome only. Normal floating window like FileExplorer, same AT-SPI reasoning. `--cwd DIR` is a DarkOS-specific addition Files uses for "Open Terminal Here."

## Notes
- Purpose: Sidebar-driven notes list + plain-text editor; doubles as a general small-file text editor via `argv[1]`.
- Variants: Notes-list mode (sidebar visible, autosave), standalone file mode (no sidebar, explicit Save button).
- Tokens used: `color-bg-alt`, `color-bg-elevated`, sidebar/toolbar/statusbar classes shared with FileExplorer.
- Used in: `NotesWindow` in `darkos-notes.py`; app rail "notes" action (previously launched nvim in a terminal).
- Notes: Notes are plain `.txt` files under `~/Documents/DarkOS Notes/`, not a proprietary format — browsable from FileExplorer too.

## Calendar
- Purpose: Month view + per-day text events.
- Variants: Day selected (no events / has events), month with marked days.
- Tokens used: `color-bg-alt`, `color-primary` (selected day), sidebar classes for the event list.
- Used in: `CalendarWindow` in `darkos-calendar.py`.
- Notes: Built on stock `Gtk.Calendar`, which needed its own CSS node overrides (`calendar`, `calendar.header`, `calendar.button`, `calendar:selected`, `calendar.view`) — it does not inherit an ancestor's background-color the way plain Box/Label do. Events persist as JSON, not a recurring/reminder system.

## Clock
- Purpose: Local time + world clocks, alarms, timer, stopwatch in one tabbed window.
- Variants: Four Notebook tabs (Clock/Alarms/Timer/Stopwatch); timer/stopwatch idle vs. running.
- Tokens used: `color-primary` (active tab, running-state accents), shared sidebar/toolbar classes.
- Used in: `ClockWindow` in `darkos-clock.py`.
- Notes: Same GtkNotebook page-background issue as below — fixed once, shared by every notebook-based app.

## Calculator
- Purpose: Standard calculator with a history panel.
- Variants: Normal entry, error state (divide-by-zero / malformed expression), history populated.
- Tokens used: `color-bg-alt`, `action-button` styling for `=`, sidebar classes for history rows.
- Used in: `CalculatorWindow` in `darkos-calculator.py`.
- Notes: Expression evaluation is AST-walked, not `eval()` — only numeric literals and +-*/%** can ever execute.

## GTK3 node theming gaps (cross-cutting, found 2026-08-27)
- Purpose: Not a component — a recurring gotcha worth flagging for whoever builds the next app.
- Notes: GtkCalendar, GtkNotebook's page/stack area, and GtkTextView's text area all render as stock light-theme by default — they don't inherit background-color from an ancestor's `.app-window` class the way plain Box/Label/Button do. Each needed its own direct CSS node targeting (`calendar`/`calendar.view`, `notebook`/`notebook stack`, `textview`/`textview text`) in `darkos_shell/css.py`. Any future app using one of these (or another complex native widget — GtkComboBox, GtkTreeView headers already handled) should check it renders dark before calling it done; a "compiles + doesn't crash" check will not catch this class of bug, only actually looking at it will.

## Reader / Clipboard / EmojiPicker / Gallery / Downloads
- Purpose: The rest of Phase 4 — PDF viewing, clipboard history, emoji search, image browsing, a Downloads-focused file view.
- Variants: Reader (no document / loaded / zoomed); Clipboard (empty / pinned+recent); EmojiPicker (full grid / search results / recent); Gallery (grid / full-size viewer); Downloads (populated / empty folder).
- Tokens used: shared toolbar/statusbar/sidebar classes throughout; Gallery and Reader deliberately run near-opaque (0.96–0.98 in hyprland.conf) rather than the ~0.90 most app windows use, since translucent chrome behind dense text or photo color accuracy actively hurts those two.
- Used in: `darkos-reader.py`, `darkos-clipboard.py`, `darkos-emoji.py`, `darkos-gallery.py`, `darkos-downloads.py`.
- Notes: All five are normal floating GTK3 windows, stock widgets only, same AT-SPI reasoning as every other Phase 4 app. Clipboard's history is deliberately session-only (not written to disk) — see build-plan.md Phase 4 for the reasoning. Downloads is a specialized folder view, not a real download-progress tracker — there's no event source for that yet.

## Settings / NetworkCenter
- Purpose: Phase 5's system-management surface — one Settings app with sixteen tabs, plus a separate Network Center for Wi-Fi/Bluetooth/Connect/Cloud.
- Variants: Settings — real-data tabs (System/Devices/Users/Storage), write-through-to-tokens tabs (Fonts/Icons/Themes/Wallpaper/Motion/Designer), graceful-failure tabs (Performance/Services), honest-stub tabs (Permissions, Accessibility's backend wiring). Network Center — real-data-or-real-error for Wi-Fi/Bluetooth, UI-shell-only for Connect, placeholder for Cloud.
- Tokens used: shared sidebar/toolbar/statusbar/terminal-tabs classes throughout; `Gtk.LevelBar` (Storage) and `Gtk.FontChooserWidget`/`Gtk.ColorButton`/`Gtk.Scale` (Fonts/Themes/Designer) are stock widgets, no custom styling needed beyond the usual dark-background node-targeting.
- Used in: `darkos-settings.py`, `darkos-network.py`; rail's "settings" action now launches Settings directly instead of the `wofi --show drun` placeholder.
- Notes: `darkos_shell/user_settings.py` is the new shared read/write layer — `tokens.py` imports it at module load, so accent color, corner radius, and reduce-motion are live values with hardcoded fallbacks, not a write-only JSON file. Confirmed by direct test (write settings.json, re-import tokens, values change) and by wiring `REDUCE_MOTION` into the HUD's own tick handler as the first real consumer. Two configparser gotchas (default key-lowercasing, and `write()`'s spacing not matching this repo's `.desktop` convention) were caught and fixed in Startup's toggle before shipping — see build-plan.md Phase 5 for detail.

## SecurityCenter
- Purpose: Vault (password/secret manager), Privacy toggles, Shield (antivirus — honest stub), Permissions, and a file Encrypt/Decrypt utility.
- Variants: Vault locked (create vs. unlock forms) / unlocked (entry list); Encrypt idle / file chosen / success / wrong-passphrase error.
- Tokens used: shared sidebar/toolbar/terminal-tabs classes; no new CSS needed.
- Used in: `darkos-security.py`.
- Notes: Vault and Encrypt are real cryptography (`cryptography` library — PBKDF2-HMAC-SHA256 key derivation, Fernet authenticated encryption), not a toy scheme, and both the success and failure paths (wrong password/passphrase correctly rejected, no corrupted output ever written) are runtime-verified, not just the happy path — see build-plan.md Phase 5 for exactly what was checked. Shield is a deliberate honest stub (disabled "Run Scan," explanation in place of fake results) — real on-access scanning needs kernel access and daemons no sandbox can respond to, so it isn't faked.

## Backup / Dashboard
- Purpose: Backup/Recovery (tar-based folder backup + restore) and Dashboard (live CPU/memory/disk/top-processes overview).
- Variants: Backup — Back Up tab / History+Restore tab, entries with a missing-archive state. Dashboard — normal ticking state only (no error states; every data source it reads is confirmed always-available on any Linux system, unlike Performance/Services elsewhere).
- Tokens used: shared toolbar/sidebar/statusbar classes; `Gtk.LevelBar` for CPU/memory/disk (same widget as Settings' Storage tab).
- Used in: `darkos-backup.py`, `darkos-dashboard.py`.
- Notes: Both fully runtime-verified, not just code-reviewed — Backup's restore was diffed byte-for-byte against the original, Dashboard's CPU reading was confirmed to actually move under a real generated load. Backup uses plain tar archives, not Btrfs snapshots (this sandbox's filesystem is ext2/ext3, and the spec didn't call for snapshots specifically).

## Mission / Spaces
- Purpose: Workspace and window overview + switcher.
- Variants: Populated (workspaces with/without windows) / unavailable (no compositor to query).
- Tokens used: shared toolbar/sidebar classes; no new CSS needed.
- Used in: `darkos-mission.py`.
- Notes: Real `hyprctl -j workspaces` / `hyprctl -j clients` calls and real `hyprctl dispatch` actions — not the same category of gap as Shield, despite an earlier note in this same session bucketing them together. Shield's correctness is fundamentally unverifiable without a real scan engine and test malware; this is a data-display problem against a documented, stable JSON schema, closer in kind to Network Center's nmcli/bluetoothctl calls. Verified two ways: the real graceful-failure path (hyprctl genuinely absent in this sandbox) and the parsing/rendering logic against a schema-accurate fake `hyprctl` on `PATH` (a standard test-double technique, not a shipped fake) — confirmed correct workspace grouping including an empty-workspace case and confirmed the dispatch buttons don't crash the app.

## Store / DevHub
- Purpose: Phase 6's software-management surface — Store (Search/Installed/Updates/Compatibility across pacman/AUR/Flatpak/Wine/Waydroid) and DevHub (Git/Containers/Virtualization/Plugins/API Client).
- Variants: Store — every backend in a real-unavailable state in this sandbox (pacman genuinely doesn't exist off Arch, AUR RPC and Flathub are both outside the network allowlist, Wine/Waydroid uninstalled). DevHub — Git and API Client have real-success states (verified against the actual DarkOS repo and a live PyPI request); Containers/Virtualization are real-unavailable like Store.
- Tokens used: shared toolbar/sidebar/terminal-tabs classes throughout; no new CSS needed.
- Used in: `darkos-store.py`, `darkos-devhub.py`; rail's "store" action now launches Store directly instead of the `wofi --show drun` placeholder.
- Notes: Store is the one place in this project where literally every backend hit the sandbox's ceiling at once — still built correctly against each tool's real, documented interface (this is what changes on a real Arch box, not a redesign), just with nothing here to show it succeeding. DevHub's git/API-client half is the counterexample in the same app: real primitives, fully verified. Both note the Shield-gating requirement from architecture.md explicitly rather than silently ignoring it, since Shield doesn't exist yet.
