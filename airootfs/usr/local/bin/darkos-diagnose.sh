#!/bin/bash
# DarkOS bootloader diagnostic — collects the installed system's
# bootloader state into one labeled report. Writes to a log file AND
# stdout, so a garbled VM console during the run can't hide the evidence:
# after it finishes, run `sudo cat` on the log path printed at the end.
#
# Usage:  sudo darkos-diagnose
#
# Detects the installed root (ext4) and ESP (vfat) itself, mounts both,
# verifies each mount with `mountpoint -q` (aborts loudly instead of
# checking an empty dir), reports the five checks, and always unmounts.

set -u
set -o pipefail
umask 077

LOG_DIR=/var/log/darkos

if [ "$EUID" -ne 0 ]; then
    printf '%s\n' 'darkos-diagnose must run as root (use: sudo darkos-diagnose).' >&2
    exit 1
fi

# Logs must not live in a world-writable directory. A unique file in this
# root-owned directory prevents a caller from pre-creating a symlink that a
# privileged diagnostic run would otherwise follow.
if [ -L "$LOG_DIR" ]; then
    printf 'Refusing symbolic-link diagnostic log directory: %s\n' "$LOG_DIR" >&2
    exit 1
fi
if ! mkdir -p -- "$LOG_DIR"; then
    printf 'Could not create diagnostic log directory: %s\n' "$LOG_DIR" >&2
    exit 1
fi
if [ ! -d "$LOG_DIR" ] || [ -L "$LOG_DIR" ]; then
    printf 'Diagnostic log path is not a safe directory: %s\n' "$LOG_DIR" >&2
    exit 1
fi
if ! chown root:root "$LOG_DIR" || ! chmod 0750 "$LOG_DIR"; then
    printf 'Could not secure diagnostic log directory: %s\n' "$LOG_DIR" >&2
    exit 1
fi
LOG="$(mktemp "${LOG_DIR}/darkos-diagnose.XXXXXX.log")" || {
    printf 'Could not create diagnostic log under: %s\n' "$LOG_DIR" >&2
    exit 1
}
if ! chmod 0640 "$LOG"; then
    printf 'Could not secure diagnostic log: %s\n' "$LOG" >&2
    exit 1
fi
MNT="$(mktemp -d /tmp/darkos-diag.XXXXXX)" || {
    printf '%s\n' 'Could not create a temporary diagnostic mount directory.' >&2
    exit 1
}

# Only physical-disk partitions count. The live ISO itself exposes vfat
# (ARCHISO_EFI on a loop device) and squashfs — naive fstype detection
# would pick the live media's EFI instead of the installed disk's ESP.
PHYS_RE='^/dev/(nvme[0-9]+n[0-9]+p[0-9]+|sd[a-z]+[0-9]+|vd[a-z]+[0-9]+|xvd[a-z]+[0-9]+|mmcblk[0-9]+p[0-9]+|hd[a-z]+[0-9]+)$'

log() { echo "$@" | tee -a "$LOG"; }

is_physical_partition() {
    [[ "$1" =~ $PHYS_RE ]]
}

is_esp_parttype() {
    case "${1,,}" in
        c12a7328-f81f-11d2-ba4b-00a0c93ec93b|0xef|ef) return 0 ;;
        *) return 1 ;;
    esac
}

select_target_partitions() {
    local device fstype dev_type parttype root esp root_parent esp_parent
    local -a root_candidates=()
    local -a esp_candidates=()
    local -a pairs=()
    local -a matching_esps=()

    while IFS= read -r device; do
        [ -n "$device" ] || continue
        is_physical_partition "$device" || continue
        fstype="$(lsblk -dnro FSTYPE "$device" 2>>"$LOG" || true)"
        dev_type="$(lsblk -dnro TYPE "$device" 2>>"$LOG" || true)"
        parttype="$(lsblk -dnro PARTTYPE "$device" 2>>"$LOG" || true)"
        [ "$dev_type" = part ] || continue
        if [ "$fstype" = ext4 ]; then
            root_candidates+=("$device")
        elif [ "$fstype" = vfat ] && is_esp_parttype "$parttype"; then
            esp_candidates+=("$device")
        fi
    done < <(lsblk -dnro NAME 2>>"$LOG")

    for root in "${root_candidates[@]}"; do
        root_parent="$(lsblk -dnro PKNAME "$root" 2>>"$LOG" || true)"
        [ -n "$root_parent" ] || continue
        matching_esps=()
        for esp in "${esp_candidates[@]}"; do
            esp_parent="$(lsblk -dnro PKNAME "$esp" 2>>"$LOG" || true)"
            if [ "$esp_parent" = "$root_parent" ]; then
                matching_esps+=("$esp")
            fi
        done
        if [ "${#matching_esps[@]}" -eq 1 ]; then
            pairs+=("${root}|${matching_esps[0]}")
        fi
    done

    case "${#pairs[@]}" in
        1)
            IFS='|' read -r ROOT ESP <<< "${pairs[0]}"
            ;;
        0)
            log "ABORT: no unambiguous ext4 root and ESP-typed FAT partition pair was found on one physical disk."
            return 1
            ;;
        *)
            log "ABORT: multiple installed root/ESP pairs were found: ${pairs[*]}"
            return 1
            ;;
    esac
}

cleanup() {
    umount -R "$MNT" 2>/dev/null
    rmdir "$MNT" 2>/dev/null
}
trap cleanup EXIT

log "=== DarkOS bootloader diagnostic ==="
log "Date: $(date)"
log ""

# --- 1. Detect partitions --------------------------------------------
log "--- Full partition map (lsblk -f) ---"
lsblk -f | tee -a "$LOG"
log ""

log "--- Selecting an unambiguous installed root/ESP pair ---"
if ! select_target_partitions; then
    exit 1
fi
log "Selected root: $ROOT"
log "Selected ESP:  $ESP"
log ""

# --- 2. Mount and verify ----------------------------------------------
log "--- Mounting $ROOT read-only at $MNT ---"
mount -o ro "$ROOT" "$MNT" >> "$LOG" 2>&1
if ! mountpoint -q "$MNT"; then
    log "ABORT: failed to mount $ROOT at $MNT. Output above."
    exit 1
fi
log "  mounted OK"

if [ ! -d "$MNT/boot/efi" ]; then
    log "ABORT: selected root has no /boot/efi mount point."
    exit 1
fi
log "--- Mounting $ESP read-only at $MNT/boot/efi ---"
mount -o ro "$ESP" "$MNT/boot/efi" >> "$LOG" 2>&1
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
