# Headless shell checks

Run the **real** DarkOS shell on a throwaway headless Wayland compositor and
check what it actually does -- without a VM, a GPU, or a display. Written
because the shell is GTK layer-shell code, and nearly all of it used to be
verified only by `py_compile`.

```bash
bash ci/headless/run-all.sh            # all checks, ~2 minutes
bash ci/headless/run-all.sh dock       # or: dock | stall | snip
```

| check | what it proves |
|---|---|
| `dock` (`dock_matrix.py`) | Every dock position x size lays out correctly; the space sway gives a tiled window matches the exclusive zone the dock claims; a change written to `settings.json` reaches the running shell; bad values fall back. Screenshots + `contact-sheet.png` are written to the directory it prints. |
| `stall` (`stall_check.py`) | The shell's GTK main loop is never blocked for long (a 20 ms heartbeat). Run against an emulated empty Hyprland desktop and against no `hyprctl` at all. This is what found `ActivityDetector` freezing the shell for seconds at a time. |
| `snip` (`snip_check.sh`) | `--snip-screen` / `--snip` with real `grim`, `wl-copy`, `wl-paste`: file location, clipboard bytes, a region crop that is pixel-identical to the same crop of a full capture, Esc cancels quietly, hostile selector output is rejected. Only the interactive `slurp` picker is replaced by a shim (it needs a pointer). |

## What this is not

It is **sway, not Hyprland**. Both implement the wlr-layer-shell protocol, so
anchors, margins and exclusive zones should behave the same, but that is an
expectation, not something these checks establish. There is no `hyprctl`
(`stall` fakes one), no GPU, no NetworkManager/logind, no installer, no
boot. None of this replaces booting the ISO; it catches regressions earlier
and cheaper.

A `wl_display_dispatch: Broken pipe` line at the very end of `snip` is the
clipboard helper noticing the compositor exited. It is harmless.

## Requirements

Arch: `pacman -S sway grim wl-clipboard python-gobject gtk3 gtk-layer-shell python-pillow librsvg dbus`

Debian/Ubuntu: `apt install sway grim wl-clipboard python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 python3-pil librsvg2-common dbus`

(`librsvg` matters: without the SVG pixbuf loader every symbolic icon renders
as a placeholder box, which makes screenshots misleading.)

Not wired into CI: the CI container does not install sway.

## Files

- `lib.sh` -- `headless_start [WxH]` / `headless_stop`; sourced by the others.
  Uses an isolated `$HOME` and `$XDG_RUNTIME_DIR`, so it never touches your
  real settings.
- `run-all.sh` -- one fresh compositor per check.
