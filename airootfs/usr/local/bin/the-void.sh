#!/bin/bash
# DarkOS terminal launcher ("The Void"), backed by the native
# darkos-terminal.py (GTK3 + VTE).
#
# VTE renders through Cairo/Pango, not an OpenGL context, so no VM
# software-rendering workaround (LIBGL_ALWAYS_SOFTWARE) is needed here.
exec /usr/local/bin/darkos-terminal.py "$@"
