#!/bin/bash
# DarkOS bootloader repair. This is used in the Calamares target chroot and
# by darkos-grub-repair.service as a first-boot safety net.

set -u
set -o pipefail

umask 022

LOG=/boot/grub/install.log
MARKER=/var/lib/darkos-grub-repair.done
LOCK=/run/lock/darkos-grub-repair.lock
ESP_MOUNT=/boot/efi
ESP_DEVICE=
FALLBACK_ESP=
GRUB_CFG_TMP=
MARKER_TMP=

stderr() { printf '%s\n' "$*" >&2; }

if [ "$EUID" -ne 0 ]; then
    stderr "ERROR: darkos-grub-install.sh must run as root"
    exit 1
fi

# Never alter the live ISO. Calamares runs this script inside the installed
# target, where /run/archiso is not present.
if [ -d /run/archiso ]; then
    stderr "ERROR: refusing to install GRUB into the live ISO"
    exit 1
fi

for command in awk cat findfs findmnt flock grep grub-install grub-mkconfig \
    lsblk mkinitcpio mount mountpoint mv readlink rm sed tee; do
    if ! command -v "$command" >/dev/null 2>&1; then
        stderr "ERROR: required command is missing: $command"
        exit 1
    fi
done

if ! mkdir -p /boot/grub "$ESP_MOUNT" /run/lock; then
    stderr "ERROR: could not create bootloader working directories"
    exit 1
fi

# Refuse to follow a planted link when this root-owned service opens its log.
if [ -L "$LOG" ]; then
    stderr "ERROR: refusing to write through symbolic-link log: $LOG"
    exit 1
fi
if ! touch "$LOG"; then
    stderr "ERROR: cannot write bootloader log: $LOG"
    exit 1
fi

log() { printf '%s\n' "$*" | tee -a "$LOG"; }
fail() {
    log "ERROR: $*"
    log "--- repair failed; completion marker was not written ---"
    exit 1
}
cleanup() {
    [ -z "$GRUB_CFG_TMP" ] || rm -f -- "$GRUB_CFG_TMP"
    [ -z "$MARKER_TMP" ] || rm -f -- "$MARKER_TMP"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

# Serialize Calamares, systemd, and any manual invocation. A concurrent run
# must not replace a validated grub.cfg or marker out from under this one.
exec 9>"$LOCK" || fail "cannot open repair lock: $LOCK"
if ! flock -n 9; then
    fail "another DarkOS bootloader repair is already running"
fi

log ""
log "=== DarkOS bootloader repair ==="
log "Date: $(date --iso-8601=seconds 2>/dev/null || date)"

# A marker describes the most recent complete run. Remove it before changing
# boot artifacts so a failed manual rerun is retried on the next boot.
if ! rm -f -- "$MARKER"; then
    fail "could not remove stale completion marker: $MARKER"
fi

is_physical_partition() {
    [[ "$1" =~ ^/dev/(nvme[0-9]+n[0-9]+p[0-9]+|sd[a-z]+[0-9]+|vd[a-z]+[0-9]+|xvd[a-z]+[0-9]+|mmcblk[0-9]+p[0-9]+|hd[a-z]+[0-9]+)$ ]]
}

is_esp_parttype() {
    case "${1,,}" in
        c12a7328-f81f-11d2-ba4b-00a0c93ec93b|0xef|ef) return 0 ;;
        *) return 1 ;;
    esac
}

resolve_device_spec() {
    local spec="$1"
    local resolved

    case "$spec" in
        /dev/*) resolved=$(readlink -f -- "$spec" 2>/dev/null) || return 1 ;;
        UUID=*|LABEL=*|PARTUUID=*|PARTLABEL=*)
            resolved=$(findfs "$spec" 2>/dev/null) || return 1
            resolved=$(readlink -f -- "$resolved" 2>/dev/null) || return 1
            ;;
        *) return 1 ;;
    esac
    printf '%s\n' "$resolved"
}

validate_mounted_esp() {
    local source fstype options dev_type dev_fstype parttype

    if ! mountpoint -q "$ESP_MOUNT"; then
        log "  $ESP_MOUNT is not a mount point"
        return 1
    fi

    source=$(findmnt -n -M "$ESP_MOUNT" -o SOURCE 2>>"$LOG") || return 1
    fstype=$(findmnt -n -M "$ESP_MOUNT" -o FSTYPE 2>>"$LOG") || return 1
    options=$(findmnt -n -M "$ESP_MOUNT" -o OPTIONS 2>>"$LOG") || return 1
    # findmnt may suffix a subdirectory as /dev/foo[/path]. That can never be
    # a valid whole ESP mount, but strip it so the rejection message is clear.
    source=${source%%\[*}
    source=$(readlink -f -- "$source" 2>/dev/null) || {
        log "  cannot resolve mounted source: $source"
        return 1
    }

    if ! is_physical_partition "$source"; then
        log "  mounted source is not a supported physical-disk partition: $source"
        return 1
    fi

    dev_type=$(lsblk -dnro TYPE "$source" 2>>"$LOG") || return 1
    dev_fstype=$(lsblk -dnro FSTYPE "$source" 2>>"$LOG") || return 1
    parttype=$(lsblk -dnro PARTTYPE "$source" 2>>"$LOG") || return 1

    if [ "$dev_type" != part ]; then
        log "  mounted source is not a partition (TYPE=$dev_type): $source"
        return 1
    fi
    if [ "$fstype" != vfat ] || [ "$dev_fstype" != vfat ]; then
        log "  ESP must be FAT (mount=$fstype, device=$dev_fstype): $source"
        return 1
    fi
    if ! is_esp_parttype "$parttype"; then
        log "  partition does not have an EFI System Partition type: $source (PARTTYPE=${parttype:-missing})"
        return 1
    fi
    case ",$options," in
        *,rw,*) ;;
        *)
            log "  ESP is not mounted read-write: $source ($options)"
            return 1
            ;;
    esac

    ESP_DEVICE="$source"
    return 0
}

select_fallback_esp() {
    local root_spec root_device root_parent dev fstype dev_type parttype parent
    local -a all_candidates=()
    local -a same_disk_candidates=()

    root_spec=$(awk '$1 !~ /^#/ && $2 == "/" { print $1; exit }' /etc/fstab 2>/dev/null || true)
    root_device=
    root_parent=
    if [ -n "$root_spec" ]; then
        root_device=$(resolve_device_spec "$root_spec" 2>/dev/null || true)
        if [ -n "$root_device" ]; then
            root_parent=$(lsblk -dnro PKNAME "$root_device" 2>/dev/null || true)
        fi
    fi

    while read -r dev fstype dev_type parttype; do
        [ "$fstype" = vfat ] || continue
        [ "$dev_type" = part ] || continue
        is_physical_partition "$dev" || continue
        is_esp_parttype "$parttype" || continue
        all_candidates+=("$dev")
        parent=$(lsblk -dnro PKNAME "$dev" 2>/dev/null || true)
        if [ -n "$root_parent" ] && [ "$parent" = "$root_parent" ]; then
            same_disk_candidates+=("$dev")
        fi
    done < <(lsblk -nrpo NAME,FSTYPE,TYPE,PARTTYPE 2>>"$LOG")

    if [ "${#same_disk_candidates[@]}" -eq 1 ]; then
        FALLBACK_ESP="${same_disk_candidates[0]}"
        return 0
    fi
    if [ "${#same_disk_candidates[@]}" -gt 1 ]; then
        log "  multiple ESPs exist on the installed root disk: ${same_disk_candidates[*]}"
        return 1
    fi
    if [ "${#all_candidates[@]}" -eq 1 ]; then
        FALLBACK_ESP="${all_candidates[0]}"
        return 0
    fi
    if [ "${#all_candidates[@]}" -eq 0 ]; then
        log "  no physical FAT partition with an ESP partition type was found"
    else
        log "  ESP selection is ambiguous: ${all_candidates[*]}"
    fi
    return 1
}

set_grub_option() {
    local key="$1"
    local value="$2"

    if grep -Eq "^[[:space:]]*${key}=" /etc/default/grub; then
        sed -i -E "s|^[[:space:]]*${key}=.*|${key}=${value}|" /etc/default/grub \
            || fail "could not set $key in /etc/default/grub"
    else
        printf '%s=%s\n' "$key" "$value" >>/etc/default/grub \
            || fail "could not append $key to /etc/default/grub"
    fi
}

log "--- Ensuring a standard mkinitcpio preset ---"
if ! mkdir -p /etc/mkinitcpio.d; then
    fail "could not create /etc/mkinitcpio.d"
fi
if ! cat >/etc/mkinitcpio.d/linux.preset <<'PRESET'
ALL_config="/etc/mkinitcpio.conf"
ALL_kver="/boot/vmlinuz-linux"
PRESETS=('default' 'fallback')
default_image="/boot/initramfs-linux.img"
fallback_image="/boot/initramfs-linux-fallback.img"
default_options=""
fallback_options="-S autodetect"
PRESET
then
    fail "could not write /etc/mkinitcpio.d/linux.preset"
fi

log "--- Removing the live-ISO mkinitcpio drop-in ---"
if ! rm -f -- /etc/mkinitcpio.conf.d/archiso.conf; then
    fail "could not remove /etc/mkinitcpio.conf.d/archiso.conf"
fi

if [ ! -s /boot/vmlinuz-linux ]; then
    fail "/boot/vmlinuz-linux is missing or empty"
fi
if [ ! -f /etc/mkinitcpio.conf ]; then
    fail "/etc/mkinitcpio.conf is missing"
fi

log "--- Building initramfs (mkinitcpio -P) ---"
mkinitcpio -P >>"$LOG" 2>&1
status=$?
log "--- mkinitcpio exit code: $status ---"
if [ "$status" -ne 0 ]; then
    fail "mkinitcpio failed"
fi
if [ ! -s /boot/initramfs-linux.img ]; then
    fail "mkinitcpio reported success but /boot/initramfs-linux.img is missing or empty"
fi
if [ ! -s /boot/initramfs-linux-fallback.img ]; then
    fail "mkinitcpio reported success but /boot/initramfs-linux-fallback.img is missing or empty"
fi

log "--- Forcing GRUB to text mode for broad firmware/VM compatibility ---"
if [ ! -e /etc/default/grub ] && ! touch /etc/default/grub; then
    fail "could not create /etc/default/grub"
fi
if [ ! -f /etc/default/grub ] || [ -L /etc/default/grub ]; then
    fail "/etc/default/grub is not a safe regular file"
fi
set_grub_option GRUB_TERMINAL_OUTPUT console
set_grub_option GRUB_GFXPAYLOAD_LINUX text

log "--- Locating and validating the EFI System Partition ---"
if mountpoint -q "$ESP_MOUNT"; then
    if ! validate_mounted_esp; then
        fail "$ESP_MOUNT is mounted, but it is not a valid writable physical ESP"
    fi
    log "  validated existing ESP mount: $ESP_DEVICE"
else
    if awk '$1 !~ /^#/ && $2 == "/boot/efi" { found=1 } END { exit !found }' /etc/fstab 2>/dev/null; then
        log "  mounting $ESP_MOUNT from /etc/fstab"
        mount "$ESP_MOUNT" >>"$LOG" 2>&1
        status=$?
        if [ "$status" -eq 0 ] || mountpoint -q "$ESP_MOUNT"; then
            if ! validate_mounted_esp; then
                fail "/etc/fstab mounted an invalid ESP at $ESP_MOUNT"
            fi
            log "  validated fstab ESP: $ESP_DEVICE"
        else
            log "  fstab mount failed; attempting an unambiguous physical-disk fallback"
        fi
    fi

    if ! mountpoint -q "$ESP_MOUNT"; then
        if ! select_fallback_esp; then
            fail "could not select an unambiguous physical ESP"
        fi
        log "  mounting fallback ESP: $FALLBACK_ESP"
        if ! mount "$FALLBACK_ESP" "$ESP_MOUNT" >>"$LOG" 2>&1; then
            fail "could not mount fallback ESP: $FALLBACK_ESP"
        fi
        if ! validate_mounted_esp; then
            fail "fallback partition failed ESP validation: $FALLBACK_ESP"
        fi
        log "  validated fallback ESP: $ESP_DEVICE"
    fi
fi

log "--- Installing GRUB to the UEFI fallback path ---"
grub-install \
    --target=x86_64-efi \
    --efi-directory="$ESP_MOUNT" \
    --bootloader-id=DarkOS \
    --no-nvram \
    --removable >>"$LOG" 2>&1
status=$?
log "--- grub-install exit code: $status ---"
if [ "$status" -ne 0 ]; then
    fail "grub-install failed"
fi
if [ ! -s "$ESP_MOUNT/EFI/BOOT/BOOTX64.EFI" ]; then
    fail "grub-install reported success but EFI/BOOT/BOOTX64.EFI is missing or empty"
fi

# Generate and validate beside the live config. A failed generator must not
# truncate a previously bootable grub.cfg.
log "--- Generating and validating grub.cfg ---"
GRUB_CFG_TMP="/boot/grub/.grub.cfg.darkos.$$"
if ! rm -f -- "$GRUB_CFG_TMP"; then
    fail "could not clear temporary grub.cfg"
fi
grub-mkconfig -o "$GRUB_CFG_TMP" >>"$LOG" 2>&1
status=$?
log "--- grub-mkconfig exit code: $status ---"
if [ "$status" -ne 0 ]; then
    fail "grub-mkconfig failed; the previous grub.cfg was preserved"
fi
# Do not match variables such as menuentry_id_option: require a real command.
if ! grep -Eq '^[[:space:]]*menuentry[[:space:]]+' "$GRUB_CFG_TMP"; then
    fail "generated grub.cfg contains no real menuentry command"
fi
if ! grep -Eq '^[[:space:]]*linux(efi)?[[:space:]]+.*vmlinuz-linux' "$GRUB_CFG_TMP"; then
    fail "generated grub.cfg contains no DarkOS Linux kernel command"
fi
if ! grep -Eq '^[[:space:]]*initrd(efi)?[[:space:]]+.*initramfs-linux\.img' "$GRUB_CFG_TMP"; then
    fail "generated grub.cfg contains no standard DarkOS initramfs command"
fi
if ! mv -f -- "$GRUB_CFG_TMP" /boot/grub/grub.cfg; then
    fail "could not atomically install the validated grub.cfg"
fi
GRUB_CFG_TMP=

if ! mkdir -p /var/lib; then
    fail "could not create /var/lib for the completion marker"
fi
MARKER_TMP="/var/lib/.darkos-grub-repair.done.$$"
if ! {
    printf 'completed_at=%s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    printf 'esp_device=%s\n' "$ESP_DEVICE"
    printf 'efi_loader=%s\n' 'EFI/BOOT/BOOTX64.EFI'
} >"$MARKER_TMP"; then
    fail "could not write temporary completion marker"
fi
if ! mv -f -- "$MARKER_TMP" "$MARKER"; then
    fail "could not atomically install the completion marker"
fi
MARKER_TMP=

log "--- repair complete; validated config and marker written ---"
exit 0
