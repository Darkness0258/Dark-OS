#!/bin/bash
# DarkOS GRUB installer wrapper.
#
# Self-contained: finds the ESP, mounts it at /boot/efi if not already
# mounted, installs GRUB with --removable (writes to the firmware
# fallback path \EFI\BOOT\BOOTX64.EFI that VMware always checks, and
# skips the NVRAM write that fails in VMs), then generates grub.cfg.
#
# This runs on first boot of the INSTALLED system (via
# darkos-grub-repair.service), where the root filesystem is writable,
# so chmod and mounts both work — unlike the Calamares chroot, which
# is a read-only squashfs and can never run grub-install.
#
# Logs everything to /boot/grub/install.log for diagnosis.

set -u

LOG=/boot/grub/install.log
mkdir -p /boot/grub /boot/efi

log() {
    echo "$@" | tee -a "$LOG"
}

: > "$LOG"
log "=== DarkOS GRUB install (wrapper) ==="
log "Date: $(date)"
log ""

# --- Ensure the ESP is mounted at /boot/efi -------------------------
# Prefer /etc/fstab: Calamares' fstab module writes the real ESP there
# (matching partition.conf efiMountPoint: /boot/efi), so a plain
# `mount /boot/efi` resolves the correct device. The lsblk scan is only
# a fallback — trusting "first vfat partition" is fragile (a Windows
# recovery partition or leftover USB would steal the install).
if ! mountpoint -q /boot/efi; then
    if grep -qE '^[^#].* /boot/efi ' /etc/fstab; then
        log "ESP: mounting /boot/efi per /etc/fstab"
        mount /boot/efi >> "$LOG" 2>&1 && log "  OK" || log "  mount failed, falling back to lsblk scan"
    fi
fi

if ! mountpoint -q /boot/efi; then
    log "ESP not mounted — searching for vfat partition (fallback)"
    ESP=$(lsblk -nro NAME,FSTYPE | awk '$2=="vfat" {print $1; exit}')
    if [ -n "$ESP" ]; then
        log "Found ESP: /dev/$ESP — mounting"
        mount "/dev/$ESP" /boot/efi >> "$LOG" 2>&1
    else
        log "WARNING: no vfat partition found — ESP mount skipped"
    fi
else
    log "ESP already mounted at /boot/efi"
fi

log ""
log "--- Mounted filesystems ---"
mount | grep -iE "efi|boot" >> "$LOG" 2>&1
log ""
log "--- /boot/efi contents ---"
ls -la /boot/efi >> "$LOG" 2>&1
log ""

# --- Install GRUB ----------------------------------------------------
log "--- grub-install (--removable skips NVRAM write) ---"
grub-install \
    --target=x86_64-efi \
    --efi-directory=/boot/efi \
    --bootloader-id=DarkOS \
    --force \
    --removable >> "$LOG" 2>&1
STATUS=$?
log "--- grub-install exit code: $STATUS ---"

if [ "$STATUS" -eq 0 ] && [ ! -f /boot/grub/grub.cfg ]; then
    log "--- grub.cfg missing — generating ---"
    grub-mkconfig -o /boot/grub/grub.cfg >> "$LOG" 2>&1
    STATUS=$?
    log "--- grub-mkconfig exit code: $STATUS ---"
fi

exit "$STATUS"
