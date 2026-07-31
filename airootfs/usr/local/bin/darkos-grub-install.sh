#!/bin/bash
# DarkOS GRUB installer wrapper.
#
# Calamares' bootloader module runs `grub-install --force`, which tries
# to write a boot entry to firmware NVRAM. In VMs and chroots there is
# no EFI runtime, so that write fails and grub-install exits 1 — leaving
# the installed system unbootable while Calamares reports success.
#
# This wrapper adds --removable, which skips the NVRAM write and instead
# installs GRUB to the firmware-fallback path (\EFI\BOOT\BOOTX64.EFI).
# VMware/VirtualBox firmware checks that path even when no NVRAM entry
# exists. Everything is logged to /boot/grub/install.log so failures
# are diagnosable.
#
# NOTE: must be executable (755) — profiledef.sh sets this on the ISO.

set -u

LOG=/boot/grub/install.log
mkdir -p /boot/grub

{
    echo "=== DarkOS GRUB install (wrapper) ==="
    echo "Date: $(date)"
    echo ""
    echo "--- Mounted filesystems ---"
    mount 2>&1
    echo ""
    echo "--- /boot/efi contents ---"
    ls -la /boot/efi 2>&1
    echo ""
    echo "--- grub-install (--removable skips NVRAM write) ---"
} > "$LOG" 2>&1

grub-install \
    --target=x86_64-efi \
    --efi-directory=/boot/efi \
    --bootloader-id=DarkOS \
    --force \
    --removable >> "$LOG" 2>&1

STATUS=$?

echo "" >> "$LOG"
echo "--- grub-install exit code: $STATUS ---" >> "$LOG"

exit "$STATUS"
