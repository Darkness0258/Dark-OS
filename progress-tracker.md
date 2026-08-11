# Progress Tracker

## Current Status

Updated: 2026-08-11

Phase 1 is verified complete; see `README.md#phase-1-verification`. Phase 2 shell chrome is implemented in source and awaiting final packaged-ISO and booted-VM validation before roadmap completion is claimed.

- Top bar: tray, display, Bluetooth, network, sound, battery, avatar, control, and power modules implemented.
- AI Core: ring language and five activity states implemented; backend remains intentionally disconnected.
- Left zone: persistent icon rail, AI preview chat, honest weather stub, and live system gauges implemented.
- Right zone: grouped notification surface, shared controls, live media metadata, and calendar implemented.
- Dock: existing launchers retained; AI Orb now includes the brief error state.
- Session chrome: secure hyprlock/hypridle path, ReGreet login, and Plymouth boot theme implemented.

## Verification

- Passed Python compilation, Bash syntax checks, ShellCheck, JSON/TOML parsing, LF checks, and Git executable-mode checks.
- Hyprland 0.56.1 reports `config ok` for the shipped configuration and layer rules.
- Pending: fresh Docker ISO build, `ci/verify-iso.sh` against that artifact, and visual/interaction testing in a booted VM.

## Structural Decisions

- Shell surfaces use GTK3/PyGObject and `gtk-layer-shell`; no Qt rewrite.
- Left and right panels are independent TOP-layer windows with state owned by `DarkOSApplication`.
- Locking uses `hyprlock` and `hypridle`; no cosmetic layer-shell lock surface.
- Installed login uses greetd/ReGreet under Cage; the live-session autologin remains isolated.
