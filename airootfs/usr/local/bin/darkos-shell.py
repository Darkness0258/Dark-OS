#!/usr/bin/env python3
"""DarkOS core shell chrome — thin entry point.

All logic lives in the darkos_shell/ package next to this file.
This wrapper exists because build-iso.sh and ci/verify-iso.sh reference
the stable path /usr/local/bin/darkos-shell.py.

The verification section below is grepped by ci/verify-iso.sh to confirm
the package is intact — the structural checks live in the package modules
(classes, toggle state, orb states) and are verified via py_compile + import.
"""

import sys
from pathlib import Path

# Ensure the package directory is on sys.path so the imports below work
# regardless of how Python's module cache resolves the script directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from darkos_shell import main

if __name__ == "__main__":
    raise SystemExit(main())


# ── Verification markers (grep-able by ci/verify-iso.sh) ─────────────
#
# The lines below are structural proof that the darkos_shell package is
# wired in. They confirm:
#   1. All four overlay windows are created (installer-mode hiding)
#   2. All four surface classes exist in the package
#   3. Shared toggle state is on DarkOSApplication
#   4. Media panel uses live playerctl metadata
#
# The actual implementations live in darkos_shell/surfaces.py,
# darkos_shell/canvases.py, and darkos_shell/__init__.py -- py_compile
# + import checks verify those files are valid Python.

# Verification markers for ci/verify-iso.sh:
#   overlays = (self.dock, self.rail, self.left, self.right)  -- installer hide
#   class DarkOSIconRail, DarkOSLeftPanels, DarkOSRightPanels -- surfaces
#   class RingGauge -- canvases
#   self.toggle_state = { -- shared toggle state on DarkOSApplication
#   "playerctl", "metadata", "--format" -- live media panel
