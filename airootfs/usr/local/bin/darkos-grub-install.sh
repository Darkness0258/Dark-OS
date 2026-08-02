#!/bin/bash
# DarkOS bootloader repair — the single source of truth for making the
# installed system bootable. Runs BOTH during install (via the Calamares
# bootloader module, in the writable install chroot) AND on first boot
# (via darkos-grub-repair.service) as a safety net.
#
# Job, in order:
#   1. Ensure a STANDARD mkinitcpio preset (the live ISO's 'archiso'
#      preset is wrong for a real disk).
#   2. Drop the live-ISO archiso drop-in so mkinitcpio uses the standard
#      config.
#   3. Build the initramfs (mkinitcpio -P) — WITHOUT this the kernel
#      can't load the NVMe driver and panics with
#      "VFS: Unable to mount root fs on unknown-block(0,0)".
#   4. Force GRUB + kernel to TEXT mode (VMware can't draw gfxterm,
#      which shows a blank screen with a blinking cursor).
#   5. Install GRUB to the ESP with --removable (the fallback path
#      VMware checks; skips the NVRAM write that fails in VMs).
#   6. Regenerate grub.cfg.
#   7. Write the completion marker ONLY if a real menuentry exists.
#
# Logs everything to /boot/grub/install.log for diagnosis.

set -u
set -o pipefail

LOG=/boot/grub/install.log
mkdir -p /boot/grub /boot/efi

log() { echo "$@" | tee -a "$LOG"; }

: > "$LOG"
log "=== DarkOS bootloader repair ==="
log "Date: $(date)"
log ""

# --- 1. Standard mkinitcpio preset -----------------------------------
log "--- Ensuring standard mkinitcpio preset ---"
mkdir -p /etc/mkinitcpio.d
cat > /etc/mkinitcpio.d/linux.preset <<'PRESET'
ALL_config="/etc/mkinitcpio.conf"
ALL_kver="/boot/vmlinuz-linux"
PRESETS=('default' 'fallback')
default_image="/boot/initramfs-linux.img"
fallback_image="/boot/initramfs-linux-fallback.img"
default_options=""
fallback_options="-S autodetect"
PRESET
log "  written /etc/mkinitcpio.d/linux.preset"

# --- 2. Drop the live-ISO archiso drop-in -----------------------------
log "--- Dropping live-ISO archiso mkinitcpio drop-in ---"
rm -f /etc/mkinitcpio.conf.d/archiso.conf
log "  removed /etc/mkinitcpio.conf.d/archiso.conf (if present)"

# --- 3. Build the initramfs -------------------------------------------
log "--- Building initramfs (mkinitcpio -P) ---"
if [ -f /boot/vmlinuz-linux ]; then
    mkinitcpio -P >> "$LOG" 2>&1
    MKSTATUS=$?
    log "--- mkinitcpio exit code: $MKSTATUS ---"
else
    log "WARNING: /boot/vmlinuz-linux missing — skipping initramfs build"
    MKSTATUS=0
fi

# --- 4. Force GRUB to text mode (VMware compatibility) ----------------
log "--- Forcing GRUB to text mode (VMware compat) ---"
[ -f /etc/default/grub ] || touch /etc/default/grub
grep -q '^GRUB_TERMINAL_OUTPUT=' /etc/default/grub || echo 'GRUB_TERMINAL_OUTPUT=console' >> /etc/default/grub
grep -q '^GRUB_GFXPAYLOAD_LINUX=' /etc/default/grub || echo 'GRUB_GFXPAYLOAD_LINUX=text' >> /etc/default/grub
log "  GRUB_TERMINAL_OUTPUT=console + GRUB_GFXPAYLOAD_LINUX=text ensured"

# --- 5. Ensure the ESP is mounted at /boot/efi -------------------------
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

# --- 6. Install GRUB ----------------------------------------------------
log "--- grub-install (--removable skips NVRAM write) ---"
grub-install \
    --target=x86_64-efi \
    --efi-directory=/boot/efi \
    --bootloader-id=DarkOS \
    --force \
    --removable >> "$LOG" 2>&1
STATUS=$?
log "--- grub-install exit code: $STATUS ---"

# --- 7. Regenerate grub.cfg (always — existing may be incomplete) ------
if [ "$STATUS" -eq 0 ]; then
    log "--- regenerating grub.cfg ---"
    grub-mkconfig -o /boot/grub/grub.cfg >> "$LOG" 2>&1
    STATUS=$?
    log "--- grub-mkconfig exit code: $STATUS ---"
fi

# --- 8. Completion marker — ONLY if genuinely bootable -----------------
if [ "$STATUS" -eq 0 ] && grep -q "menuentry" /boot/grub/grub.cfg 2>/dev/null; then
    mkdir -p /var/lib
    touch /var/lib/darkos-grub-repair.done
    log "--- repair complete — marker written ---"
else
    log "--- NOT marked complete (grub-mkconfig failed or grub.cfg has no menu entries) ---"
fi

exit "$STATUS"
