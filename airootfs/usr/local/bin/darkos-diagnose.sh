#!/bin/bash
# DarkOS bootloader diagnostic — collects the installed system's
# bootloader state into one labeled report. Writes to a log file AND
# stdout, so a garbled VM console during the run can't hide the evidence:
# after it finishes, just `cat /tmp/darkos-diagnose.log`.
#
# Usage:  sudo darkos-diagnose
#
# Detects the installed root (ext4) and ESP (vfat) itself, mounts both,
# verifies each mount with `mountpoint -q` (aborts loudly instead of
# checking an empty dir), reports the five checks, and always unmounts.

set -u
set -o pipefail

LOG="${DARKOS_DIAG_LOG:-/tmp/darkos-diagnose.log}"
MNT="$(mktemp -d /tmp/darkos-diag.XXXXXX)"

# Only physical-disk partitions count. The live ISO itself exposes vfat
# (ARCHISO_EFI on a loop device) and squashfs — naive fstype detection
# would pick the live media's EFI instead of the installed disk's ESP.
PHYS_RE='^/dev/(nvme[0-9]+n[0-9]+p|sd[a-z]+|vd[a-z]+|mmcblk[0-9]+p|hd[a-z]+)[0-9]+$'

log() { echo "$@" | tee -a "$LOG"; }

cleanup() {
    umount -R "$MNT" 2>/dev/null
    rmdir "$MNT" 2>/dev/null
}
trap cleanup EXIT

: > "$LOG"
log "=== DarkOS bootloader diagnostic ==="
log "Date: $(date)"
log ""

# --- 1. Detect partitions --------------------------------------------
log "--- Full partition map (lsblk -f) ---"
lsblk -f | tee -a "$LOG"
log ""

ROOT="$(lsblk -nrpo NAME,FSTYPE | awk -v re="$PHYS_RE" '$2=="ext4" && $1 ~ re {print $1; exit}')"
ESP="$(lsblk -nrpo NAME,FSTYPE | awk -v re="$PHYS_RE" '$2=="vfat" && $1 ~ re {print $1; exit}')"

if [ -z "$ROOT" ]; then
    log "ABORT: no ext4 root partition on a physical disk found. Is the install complete?"
    exit 1
fi
if [ -z "$ESP" ]; then
    log "ABORT: no vfat ESP on a physical disk found."
    exit 1
fi
log "Selected root: $ROOT"
log "Selected ESP:  $ESP"
log ""

# --- 2. Mount and verify ----------------------------------------------
log "--- Mounting $ROOT at $MNT ---"
mount "$ROOT" "$MNT" >> "$LOG" 2>&1
if ! mountpoint -q "$MNT"; then
    log "ABORT: failed to mount $ROOT at $MNT. Output above."
    exit 1
fi
log "  mounted OK"

mkdir -p "$MNT/boot/efi"
log "--- Mounting $ESP at $MNT/boot/efi ---"
mount "$ESP" "$MNT/boot/efi" >> "$LOG" 2>&1
if ! mountpoint -q "$MNT/boot/efi"; then
    log "ABORT: failed to mount $ESP at $MNT/boot/efi. Output above."
    exit 1
fi
log "  mounted OK"
log ""

# --- 3. Labeled checks ------------------------------------------------
log "=== 1. Repair completion marker ==="
if [ -e "$MNT/var/lib/darkos-grub-repair.done" ]; then
    log "PRESENT — in-install bootloader step succeeded"
else
    log "ABSENT — in-install bootloader step did not complete"
fi
log ""

log "=== 2. /boot/grub/install.log ==="
if [ -f "$MNT/boot/grub/install.log" ]; then
    cat "$MNT/boot/grub/install.log" | tee -a "$LOG"
else
    log "does not exist"
fi
log ""

log "=== 3. ESP contents ==="
if [ -d "$MNT/boot/efi/EFI" ]; then
    find "$MNT/boot/efi/EFI" -printf '%M %u %g %s %p\n' | sort | tee -a "$LOG"
else
    log "EFI/ directory does not exist on the ESP — nothing was written to it"
fi
log ""

log "=== 4. grub.cfg boot entries ==="
if [ -f "$MNT/boot/grub/grub.cfg" ]; then
    if grep -qi "menuentry" "$MNT/boot/grub/grub.cfg"; then
        log "HAS boot entries:"
        grep -i "menuentry" "$MNT/boot/grub/grub.cfg" | tee -a "$LOG"
    else
        log "grub.cfg exists but has NO menuentry lines (empty menu)"
    fi
else
    log "grub.cfg does not exist"
fi
log ""

log "=== 5. Repair service enabled (installed system) ==="
service_link="$MNT/etc/systemd/system/multi-user.target.wants/darkos-grub-repair.service"
if [ -L "$service_link" ]; then
    printf '%s -> %s\n' "$service_link" "$(readlink "$service_link")" | tee -a "$LOG"
else
    log "(darkos-grub-repair not enabled in multi-user.target.wants)"
fi
log ""

log "=== Done — full log: $LOG ==="
