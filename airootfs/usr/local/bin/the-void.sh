#!/bin/bash
# DarkOS terminal launcher ("The Void", backed by kitty).
#
# kitty needs OpenGL 3.3+. VMware's virtual GPU often only exposes an
# older version through Mesa, so kitty aborts at context creation.
# Force software rendering ONLY when running inside a VM; real
# Strip -e flag if passed by standard terminal launcher callers
if [ "${1:-}" = "-e" ]; then
    shift
fi

if systemd-detect-virt --vm >/dev/null 2>&1; then
    exec env LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe kitty --title "The Void" "$@"
else
    exec kitty --title "The Void" "$@"
fi
