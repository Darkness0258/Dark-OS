#!/bin/bash
# DarkOS GRUB installer wrapper.
#
# Calamares' bootloader module runs:
#   chroot <root> <grubInstall> --target=x86_64-efi --efi-directory=<esp>
#                                --bootloader-id=DarkOS --force
# (check_target_env_call in src/modules/bootloader/main.py)
#
# Plain grub-install tries to write a boot entry to firmware NVRAM via
# efibootmgr. In VMs and chroots there is no EFI runtime, so that write
# fails and grub-install exits 1 — leaving the installed system
# unbootable while Calamares reports success.
#
# This wrapper passes Calamares' args through unchanged and appends:
#   --removable  -> install to the firmware-fallback path
#                   (\\EFI\\BOOT\\BOOTX64.EFI), which VMware/VirtualBox
#                   firmware checks even with no NVRAM entry
#   --no-nvram   -> belt-and-suspenders, never touch NVRAM
#
# If grub-install succeeds but grub.cfg is missing (the grubcfg module
# underperforms), this also generates it.
#
# Everything is logged to /boot/grub/install.log on the installed system
# so failures are diagnosable instead of swallowed by Calamares.
#
# NOTE: must be executable (755) — set via profiledef.sh file_permissions
# and stored 100755 in git so CI checks it out executable.

set -u

LOG=/boot/grub/install.log
mkdir -p /boot/grub

{
    echo "=== DarkOS GRUB install (wrapper) ==="
    echo "Date: $(date)"
    echo "Args received from Calamares: $*"
    echo ""
    echo "--- Mounted filesystems ---"
    mount 2>&1
    echo ""
    echo "--- ESP at /boot/efi ---"
    findmnt /boot/efi 2>&1 || ls -la /boot/efi 2>&1
    echo ""
    echo "--- grub-install (passthrough args + --removable --no-nvram) ---"
} > "$LOG" 2>&1

grub-install "$@" --removable --no-nvram >> "$LOG" 2>&1
STATUS=$?

echo "" >> "$LOG"
echo "--- grub-install exit code: $STATUS ---" >> "$LOG"

# Ensure grub.cfg exists even if the grubcfg module underperformed.
if [ "$STATUS" -eq 0 ] && [ ! -f /boot/grub/grub.cfg ]; then
    echo "--- grub.cfg missing — generating with grub-mkconfig ---" >> "$LOG"
    grub-mkconfig -o /boot/grub/grub.cfg >> "$LOG" 2>&1
    STATUS=$?
    echo "--- grub-mkconfig exit code: $STATUS ---" >> "$LOG"
fi

exit "$STATUS"
