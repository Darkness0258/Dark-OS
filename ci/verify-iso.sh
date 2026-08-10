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

for command in awk bash bsdtar grep lsinitcpio mktemp python readlink stat unsquashfs; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'ISO verification requires %s\n' "$command" >&2
        exit 127
    fi
done

verify_root="$(mktemp -d /tmp/darkos-iso-verify.XXXXXX)"
trap 'rm -rf -- "$verify_root"' EXIT
squashfs="$verify_root/airootfs.sfs"
extracted="$verify_root/root"
initramfs="$verify_root/initramfs-linux.img"

printf 'Extracting airootfs.sfs from %s...\n' "$iso_path"
bsdtar -xOf "$iso_path" arch/x86_64/airootfs.sfs >"$squashfs"
[[ -s "$squashfs" ]] || { printf 'ISO contains no non-empty airootfs.sfs\n' >&2; exit 1; }

bsdtar -xOf "$iso_path" arch/boot/x86_64/initramfs-linux.img >"$initramfs"
[[ -s "$initramfs" ]] || { printf 'ISO contains no non-empty live initramfs\n' >&2; exit 1; }
initramfs_files="$verify_root/initramfs-files.txt"
lsinitcpio -l "$initramfs" >"$initramfs_files"
for relative in usr/bin/ipconfig usr/bin/memdiskfind usr/bin/nbd-client \
    usr/bin/nfsmount usr/bin/pv; do
    grep -Fxq "$relative" "$initramfs_files" || {
        printf 'Required ArchISO hook file is absent from the initramfs: /%s\n' \
            "$relative" >&2
        exit 1
    }
done

payload=(
    etc/calamares/settings.conf
    etc/calamares/modules/shellprocess@bootloader-install.conf
    etc/group
    etc/gshadow
    etc/pacman.conf
    etc/pacman.d/blackarch-mirrorlist
    etc/pacman.d/chaotic-mirrorlist
    etc/passwd
    etc/shadow
    etc/systemd/system/multi-user.target.wants/NetworkManager.service
    etc/systemd/system/multi-user.target.wants/bluetooth.service
    etc/systemd/system/multi-user.target.wants/darkos-grub-repair.service
    etc/systemd/system/multi-user.target.wants/pacman-init.service
    etc/systemd/system/multi-user.target.wants/seatd.service
    etc/systemd/system/pacman-init.service
    root/.automated_script.sh
    root/.gnupg
    usr/bin/calamares
    usr/local/bin/Installation_guide
    usr/local/bin/choose-mirror
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-firstboot-tools
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-installer
    usr/local/bin/darkos-shell.py
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-tty1-login
    usr/local/bin/start-hyprland
    usr/local/bin/the-void.sh
    usr/local/bin/livecd-sound
    usr/share/applications/darkos-installer.desktop
    usr/share/pacman/keyrings/blackarch.gpg
    usr/share/pacman/keyrings/chaotic.gpg
)
unsquashfs -no-progress -d "$extracted" "$squashfs" "${payload[@]}" >/dev/null

required_files=(
    etc/calamares/settings.conf
    etc/calamares/modules/shellprocess@bootloader-install.conf
    etc/group
    etc/gshadow
    etc/pacman.conf
    etc/pacman.d/blackarch-mirrorlist
    etc/pacman.d/chaotic-mirrorlist
    etc/passwd
    etc/shadow
    etc/systemd/system/pacman-init.service
    usr/bin/calamares
    usr/share/applications/darkos-installer.desktop
    usr/share/pacman/keyrings/blackarch.gpg
    usr/share/pacman/keyrings/chaotic.gpg
)
for relative in "${required_files[@]}"; do
    if [[ ! -s "$extracted/$relative" ]]; then
        printf 'Required ISO file is missing or empty: /%s\n' "$relative" >&2
        exit 1
    fi
done

[[ "$(stat -c '%a' "$extracted/etc/shadow")" == 600 ]] || {
    printf 'Live /etc/shadow does not have mode 0600\n' >&2
    exit 1
}
[[ "$(stat -c '%a' "$extracted/etc/gshadow")" == 600 ]] || {
    printf 'Live /etc/gshadow does not have mode 0600\n' >&2
    exit 1
}

# The live account databases are layered into the image before package
# installation. Verify package-created system identities were merged and that
# every passwd/group entry still has its corresponding shadow record.
awk -F: '
    NR == FNR { groups[$3] = $1; next }
    !($4 in groups) {
        printf "passwd user %s references missing primary GID %s\n", $1, $4 > "/dev/stderr"
        bad = 1
    }
    END { exit bad }
' "$extracted/etc/group" "$extracted/etc/passwd"

awk -F: '
    NR == FNR { shadow[$1] = 1; next }
    !($1 in shadow) {
        printf "passwd user %s has no shadow entry\n", $1 > "/dev/stderr"
        bad = 1
    }
    END { exit bad }
' "$extracted/etc/shadow" "$extracted/etc/passwd"

awk -F: '
    NR == FNR { gshadow[$1] = 1; next }
    !($1 in gshadow) {
        printf "group %s has no gshadow entry\n", $1 > "/dev/stderr"
        bad = 1
    }
    END { exit bad }
' "$extracted/etc/gshadow" "$extracted/etc/group"

awk -F: '$1 == "darkos" && $3 == 1000 && $4 == 1000 { found = 1 } END { exit !found }' \
    "$extracted/etc/passwd" || {
    printf 'Live darkos account does not use UID:GID 1000:1000\n' >&2
    exit 1
}
awk -F: '$1 == "darkos" && $3 == 1000 { found = 1 } END { exit !found }' \
    "$extracted/etc/group" || {
    printf 'Live darkos primary group is missing or does not use GID 1000\n' >&2
    exit 1
}

scripts=(
    root/.automated_script.sh
    usr/local/bin/Installation_guide
    usr/local/bin/choose-mirror
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-firstboot-tools
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-installer
    usr/local/bin/darkos-shell.py
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-tty1-login
    usr/local/bin/start-hyprland
    usr/local/bin/the-void.sh
    usr/local/bin/livecd-sound
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

[[ "$(stat -c '%a' "$extracted/root/.gnupg")" == 700 ]] || {
    printf 'Live root GnuPG directory does not have mode 0700\n' >&2
    exit 1
}

for relative in "${scripts[@]}"; do
    case "$relative" in
        *.py) python -m py_compile "$extracted/$relative" ;;
        *) bash -n "$extracted/$relative" ;;
    esac
done

declare -A service_targets=(
    [NetworkManager]="/usr/lib/systemd/system/NetworkManager.service"
    [bluetooth]="/usr/lib/systemd/system/bluetooth.service"
    [darkos-grub-repair]="../darkos-grub-repair.service"
    [pacman-init]="../pacman-init.service"
    [seatd]="/usr/lib/systemd/system/seatd.service"
)
for service in "${!service_targets[@]}"; do
    link="$extracted/etc/systemd/system/multi-user.target.wants/${service}.service"
    if [[ ! -L "$link" ]]; then
        printf '%s live-session enablement is not a symlink\n' "$service" >&2
        exit 1
    fi
    if [[ "$(readlink "$link")" != "${service_targets[$service]}" ]]; then
        printf '%s live-session enablement has the wrong target\n' "$service" >&2
        exit 1
    fi
done

pacman_init="$extracted/etc/systemd/system/pacman-init.service"
for command in 'ExecStart=/usr/bin/pacman-key --init' \
    'ExecStart=/usr/bin/pacman-key --populate'; do
    grep -Fxq "$command" "$pacman_init" || {
        printf 'Live pacman-init service is missing command: %s\n' "$command" >&2
        exit 1
    }
done

runtime_pacman="$extracted/etc/pacman.conf"
if grep -Fq 'TrustAll' "$runtime_pacman"; then
    printf 'Runtime pacman.conf disables package-signature trust checks\n' >&2
    exit 1
fi
for repository in chaotic-aur blackarch; do
    grep -Fq "[$repository]" "$runtime_pacman" || {
        printf 'Runtime pacman.conf is missing repository: %s\n' "$repository" >&2
        exit 1
    }
done

settings="$extracted/etc/calamares/settings.conf"
grep -Fq -- '- shellprocess@bootloader-install' "$settings" || {
    printf 'Calamares does not run the permission-safe bootloader job\n' >&2
    exit 1
}
if grep -Eq '^[[:space:]]+- bootloader[[:space:]]*$' "$settings"; then
    printf 'Calamares still invokes the exit-126-prone direct bootloader job\n' >&2
    exit 1
fi

pkglist="$verify_root/pkglist.x86_64.txt"
bsdtar -xOf "$iso_path" arch/pkglist.x86_64.txt >"$pkglist"
for package in blackarch-keyring blackarch-mirrorlist calamares chaotic-keyring \
    chaotic-mirrorlist firefox mkinitcpio-nfs-utils nbd neovim pv python-cairo \
    ranger syslinux; do
    grep -Eq "^${package}[[:space:]]" "$pkglist" || {
        printf 'Required package is absent from the ISO package list: %s\n' "$package" >&2
        exit 1
    }
done

printf 'ISO verification passed: critical payload files and modes are valid.\n'
