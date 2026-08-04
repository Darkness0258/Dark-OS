#!/usr/bin/env bash

set -e

echo "Building DarkOS ISO image..."

# Force exec bits on shipped scripts immediately before mkarchiso packs the
# squashfs. This runs in BOTH build paths (CI and local) and after any
# releng-airootfs merge, so it can't be skipped by a stale workflow step or
# a mode dropped during staging. Without this, the live ISO ships scripts
# at 0644 and Calamares' bootloader step fails with 'returned error code
# 126' (found but not executable).
chmod +x airootfs/usr/local/bin/darkos-grub-install.sh \
         airootfs/usr/local/bin/darkos-tty1-login \
         airootfs/usr/local/bin/darkos-tool-groups \
         airootfs/usr/local/bin/darkos-diagnose.sh \
         airootfs/usr/local/bin/darkos-shell.py \
         airootfs/usr/local/bin/the-void.sh \
         airootfs/usr/local/bin/start-hyprland \
         airootfs/usr/local/bin/darkos-firstboot-tools

mkdir -p /tmp/archiso-tmp out
mkarchiso -v -w /tmp/archiso-tmp -o out .
echo "Build complete. Output written to out/"
