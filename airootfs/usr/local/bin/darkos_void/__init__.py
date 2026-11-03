#!/usr/bin/env python3
"""The Void's non-GTK logic — importable and unit-testable without a display.

This package holds everything The Void (`darkos-terminal.py`) needs that
is not itself a GTK widget, so it can be exercised by plain `ci/test-void.py`
tests with no `xvfb-run`:

- engagement: the engagement workspace (name, target, notes folder, the
  TARGET/ENGAGEMENT_DIR env pair new shells get)
- catalogue: the BlackArch tool catalogue (group -> tools, $TARGET command
  expansion, installed-state lookup via `pacman -Qq`)
- linkify: regex classification for clickable scrollback text (URLs, IPv4,
  CIDR, hashes, CVE ids) and the context-menu actions each kind offers
- commands: the command palette's command list and its filter
- session_log: the `script -qfe` argv/shell-line builders for per-pane
  session logging

`darkos-terminal.py` is the only file in The Void that imports GTK/VTE; it
wires these modules to real widgets.
"""
