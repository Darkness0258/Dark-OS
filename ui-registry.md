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
