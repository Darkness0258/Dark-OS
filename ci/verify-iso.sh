#!/usr/bin/env bash
# Fail the build if critical installer/runtime files are missing or lose their
# Unix metadata inside the final squashfs. This checks the artifact users boot,
# not merely the Git index or pre-build staging directory.

set -Eeuo pipefail

iso_path="${1:-}"
if [[ -z "$iso_path" || ! -s "$iso_path" ]]; then
    printf 'Usage: %s /path/to/darkos.iso\n' "$0" >&2
    exit 2
fi

for command in bash bsdtar grep mktemp python stat unsquashfs; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'ISO verification requires %s\n' "$command" >&2
        exit 127
    fi
done

verify_root="$(mktemp -d /tmp/darkos-iso-verify.XXXXXX)"
trap 'rm -rf -- "$verify_root"' EXIT
squashfs="$verify_root/airootfs.sfs"
extracted="$verify_root/root"

printf 'Extracting airootfs.sfs from %s...\n' "$iso_path"
bsdtar -xOf "$iso_path" arch/x86_64/airootfs.sfs >"$squashfs"
[[ -s "$squashfs" ]] || { printf 'ISO contains no non-empty airootfs.sfs\n' >&2; exit 1; }

payload=(
    etc/calamares/settings.conf
    etc/calamares/modules/shellprocess@bootloader-install.conf
    etc/pacman.conf
    etc/systemd/system/multi-user.target.wants/NetworkManager.service
    usr/bin/calamares
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-firstboot-tools
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-installer
    usr/local/bin/darkos-shell.py
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-tty1-login
    usr/local/bin/start-hyprland
    usr/local/bin/the-void.sh
    usr/share/applications/darkos-installer.desktop
)
unsquashfs -no-progress -d "$extracted" "$squashfs" "${payload[@]}" >/dev/null

required_files=(
    etc/calamares/settings.conf
    etc/calamares/modules/shellprocess@bootloader-install.conf
    etc/pacman.conf
    usr/bin/calamares
    usr/share/applications/darkos-installer.desktop
)
for relative in "${required_files[@]}"; do
    if [[ ! -s "$extracted/$relative" ]]; then
        printf 'Required ISO file is missing or empty: /%s\n' "$relative" >&2
        exit 1
    fi
done

scripts=(
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-firstboot-tools
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-installer
    usr/local/bin/darkos-shell.py
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-tty1-login
    usr/local/bin/start-hyprland
    usr/local/bin/the-void.sh
)
for relative in "${scripts[@]}"; do
    path="$extracted/$relative"
    if [[ ! -f "$path" || ! -x "$path" ]]; then
        mode="$(stat -c '%A (%a)' "$path" 2>/dev/null || printf missing)"
        printf 'ISO script is not executable: /%s [%s]\n' "$relative" "$mode" >&2
        exit 1
    fi
    if grep -q $'\r' "$path"; then
        printf 'ISO script contains CRLF data: /%s\n' "$relative" >&2
        exit 1
    fi
done

for relative in "${scripts[@]}"; do
    case "$relative" in
        *.py) python -m py_compile "$extracted/$relative" ;;
        *) bash -n "$extracted/$relative" ;;
    esac
done

if [[ ! -L "$extracted/etc/systemd/system/multi-user.target.wants/NetworkManager.service" ]]; then
    printf 'NetworkManager live-session enablement is not a symlink\n' >&2
    exit 1
fi

settings="$extracted/etc/calamares/settings.conf"
grep -Fq -- '- shellprocess@bootloader-install' "$settings" || {
    printf 'Calamares does not run the permission-safe bootloader job\n' >&2
    exit 1
}
if grep -Eq '^[[:space:]]+- bootloader[[:space:]]*$' "$settings"; then
    printf 'Calamares still invokes the exit-126-prone direct bootloader job\n' >&2
    exit 1
fi

printf 'ISO verification passed: critical payload files and modes are valid.\n'
