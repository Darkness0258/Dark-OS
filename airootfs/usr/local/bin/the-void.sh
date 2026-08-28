#!/bin/bash
# DarkOS terminal launcher ("The Void"), now backed by the native
# darkos-terminal.py (GTK3 + VTE) instead of kitty.
#
# VTE renders through Cairo/Pango, not an OpenGL context, so the old
# kitty-era VM software-rendering workaround (LIBGL_ALWAYS_SOFTWARE)
# isn't needed here. kitty itself stays installed for
# ci/vmware-phase3-guest.sh, which spawns it directly under its own
# window class — unrelated to this launcher.
exec /usr/local/bin/darkos-terminal.py "$@"
