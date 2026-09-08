# UI Registry

The current payload contains 21 native GTK applications, including Gaming Hub
and Mail. This registry describes their implemented surfaces; target-system
acceptance and remaining phase requirements are tracked in [ci/phase-7-audit.md](ci/phase-7-audit.md).

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
- Notes: Available actions launch their native or upstream target directly, including Gaming Hub; only missing future apps report an honest phase stub instead of claiming launch success.

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
- Notes: Files, Terminal, Browser, Notes, Store, and Settings each launch their direct target. Wofi remains a generic application launcher and BlackArch tool-picker dialog, not the Store or Settings implementation.

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
- Purpose: "The Void" — a tabbed terminal emulator backed by VTE.
- Variants: Single tab, multiple tabs, active/inactive tab, child-exited (auto-closes tab).
- Tokens used: `color-primary` (active tab underline + bright-cyan ANSI slot), `color-bg-alt`, a dedicated 16-slot ANSI palette derived from the token set, monospace token.
- Used in: `TerminalWindow`/`TerminalPage` in `darkos-terminal.py`; launched via `the-void.sh` from the app rail and other command callers. The `-e CMD` contract is preserved for those callers.
- Notes: Vte.Terminal owns actual emulation (PTY/ANSI/scrollback); this component is chrome only. Normal floating window like FileExplorer, same AT-SPI reasoning. `--cwd DIR` is a DarkOS-specific addition Files uses for "Open Terminal Here."

## Notes
- Purpose: Sidebar-driven notes list + plain-text editor; doubles as a general small-file text editor via `argv[1]`.
- Variants: Notes-list mode (sidebar visible, autosave), standalone file mode (no sidebar, explicit Save button).
- Tokens used: `color-bg-alt`, `color-bg-elevated`, sidebar/toolbar/statusbar classes shared with FileExplorer.
- Used in: `NotesWindow` in `darkos-notes.py`; launched directly by the app rail.
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
- Variants: Settings — real-data tabs (System/Devices/Users/Storage), write-through-to-tokens tabs (Fonts/Icons/Themes/Wallpaper/Motion/Designer), Performance profile loading/available/applying/error states, Services availability/error states, and unfinished Permissions/Accessibility enforcement. Network Center — asynchronous Wi-Fi/Bluetooth status, KDE Connect D-Bus/CLI integration with device acceptance pending, placeholder for Phase 9 Cloud.
- Tokens used: shared sidebar/toolbar/statusbar/terminal-tabs classes throughout; `Gtk.LevelBar` (Storage) and `Gtk.FontChooserWidget`/`Gtk.ColorButton`/`Gtk.Scale` (Fonts/Themes/Designer) are stock widgets, no custom styling needed beyond the usual dark-background node-targeting.
- Used in: `darkos-settings.py`, `darkos-network.py`; the rail's "settings" action launches Settings directly.
- Notes: `darkos_shell/user_settings.py` is the new shared read/write layer — `tokens.py` imports it at module load, so accent color, corner radius, and reduce-motion are live values with hardcoded fallbacks, not a write-only JSON file. Confirmed by direct test (write settings.json, re-import tokens, values change) and by wiring `REDUCE_MOTION` into the HUD's own tick handler as the first real consumer. Two configparser gotchas (default key-lowercasing, and `write()`'s spacing not matching this repo's `.desktop` convention) were caught and fixed in Startup's toggle before shipping — see build-plan.md Phase 5 for detail.
- Performance: `powerprofilesctl list/get` supplies available profiles and current state before enabling the selector. Set rechecks support, uses the system authorization policy, and reads back the result; permission errors, timeouts, and mismatches remain visible. Background requests are bounded and ignore callbacks after window closure. CPU governors and kernel version remain read-only; kernel/scheduler package selection is still open.

## SecurityCenter
- Purpose: Vault (password/secret manager), Privacy preferences, Shield on-demand ClamAV scans, staged Permissions, and a file Encrypt/Decrypt utility.
- Variants: Vault locked (create vs. unlock forms) / unlocked (entry list); Encrypt idle / file chosen / success / wrong-passphrase error.
- Tokens used: shared sidebar/toolbar/terminal-tabs classes; no new CSS needed.
- Used in: `darkos-security.py`.
- Notes: Vault/Encrypt use PBKDF2-HMAC-SHA256 and Fernet. The 2026-09-06 Arch/GTK regressions verify private output modes, wrong-password rejection, round trips, and refusal to overwrite existing outputs or recreate an existing vault. Shield runs cancellable file/folder scans and reports incomplete/error states; a real ClamAV synthetic-signature test passes. Continuous protection, quarantine, and integrity baselines remain open. See ci/phase-7-audit.md.

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
- Notes: Uses `hyprctl -j workspaces`, `hyprctl -j clients`, and `hyprctl dispatch`. Historical checks exercised the actual missing-command path in the original sandbox and parsing/rendering against a schema-accurate test double on `PATH`, including empty workspaces and dispatch buttons. Those checks do not replace target Hyprland acceptance. Shield's separate real-engine evidence is recorded under SecurityCenter.

## Store / DevHub
- Purpose: Phase 6's software-management surface — Store (Search/Installed/Updates/Compatibility across pacman/AUR/Flatpak/Wine/Waydroid) and DevHub (Git/Containers/Virtualization/Plugins/API Client).
- Variants: Store — loading, results/empty results, installed-package lists, available updates, and explicit backend errors. DevHub — Git and API Client success/error states; Containers/Virtualization depend on their installed engines. Earlier sandbox checks recorded unavailable Store backends and real Git/API-client results; current Arch checks are listed below.
- Tokens used: shared toolbar/sidebar/terminal-tabs classes throughout; no new CSS needed.
- Used in: `darkos-store.py`, `darkos-devhub.py`; the rail's "store" action launches Store directly.
- Notes: Store is currently read-only. Backend queries run off GTK with bounded/coalesced requests and explicit errors; eight focused regressions and Arch/GTK startup pass. Package installation remains disabled pending the full Shield installation gate. On-demand scans alone do not unlock installation. DevHub's Git/API-client verification is recorded separately in build-plan.md.

## GamingHub
- Purpose: Phase 7 status and launch surface for installed gaming platforms and compatibility layers.
- Variants: Checking, command absent, command found with a successful or failed probe, and launch requested.
- Tokens used: Shared `app-window`, `sidebar-row`, and `action-button` styling.
- Used in: `darkos-gaming.py`, `darkos-gaming.desktop`, and the rail's `gaming` action.
- Notes: Native launcher discovery reads executable/package metadata without starting Steam; Proton discovery reads files without executing Proton. Bottles also supports an installed `com.usebottles.bottles` Flatpak. Wine configuration and Winetricks have guarded launch actions. Waydroid requires an existing session, displays initialization guidance, and reports command failures. Bottles and standalone Proton are conditional local installations. Real games, Android apps, and target Wayland/hardware behavior still need acceptance.

## Mail

- Purpose: Basic native inbox reading and confirmed plain-text email sending.
- Variants: Account entry, loading/cancelled/failed request, inbox/empty inbox, bounded text preview, compose, review-before-send, and submission result.
- Tokens used: Shared `app-window` / `icon-button` classes and dark styling for stock entry, list, and text-view widgets.
- Used in: `MailWindow` in `darkos-mail.py`, `darkos-mail.desktop`, and the assistant's `mail` launch action.
- Notes: Account details, passwords, and drafts remain in memory for the session. IMAPS opens the inbox read-only; SMTPS submits only after an explicit review/confirmation. Both use certificate-verified implicit TLS. SMTP acceptance is distinguished from delivery confirmation; Mail does not save a Sent copy. HTML, attachments, OAuth, and persisted accounts are not implemented. Automated protocol/UI checks do not establish acceptance against a real mailbox.

## HostedCameraAndRecorder

- Purpose: Webcam capture through GNOME Camera (`snapshot`) and screen/audio capture through Kooha.
- Variants: Upstream device, capture, and error states.
- Tokens used: Upstream app styling with Hyprland window decorations.
- Used in: Profile packages and the assistant's `camera` / `recorder` launch actions.
- Notes: `snapshot` replaces the unavailable Cheese package. These are hosted upstream apps; native Camera/Recorder hubs remain catalog plans. Webcam, microphone, and Wayland capture acceptance remain open.
