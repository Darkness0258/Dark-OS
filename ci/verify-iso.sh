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

for command in awk bash grep lsinitcpio mktemp python readlink stat unsquashfs xorriso; do
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
pkglist="$verify_root/pkglist.x86_64.txt"

printf 'Extracting airootfs.sfs from %s...\n' "$iso_path"
xorriso -osirrox on -indev "$iso_path" \
    -extract /arch/x86_64/airootfs.sfs "$squashfs" \
    -extract /arch/boot/x86_64/initramfs-linux.img "$initramfs" \
    -extract /arch/pkglist.x86_64.txt "$pkglist" >/dev/null 2>&1
[[ -s "$squashfs" ]] || { printf 'ISO contains no non-empty airootfs.sfs\n' >&2; exit 1; }

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
    etc/calamares/modules/partition.conf
    etc/calamares/modules/shellprocess@bootloader-install.conf
    etc/calamares/modules/shellprocess@pacman-keyring.conf
    etc/calamares/modules/welcome.conf
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
    usr/bin/ckbcomp
    usr/bin/unsquashfs
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
    usr/share/calamares/branding/darkos/stylesheet.qss
    usr/share/pacman/keyrings/blackarch.gpg
    usr/share/pacman/keyrings/chaotic.gpg
)
unsquashfs -no-progress -d "$extracted" "$squashfs" "${payload[@]}" >/dev/null

required_files=(
    etc/calamares/settings.conf
    etc/calamares/modules/partition.conf
    etc/calamares/modules/shellprocess@bootloader-install.conf
    etc/calamares/modules/shellprocess@pacman-keyring.conf
    etc/calamares/modules/welcome.conf
    etc/group
    etc/gshadow
    etc/pacman.conf
    etc/pacman.d/blackarch-mirrorlist
    etc/pacman.d/chaotic-mirrorlist
    etc/passwd
    etc/shadow
    etc/systemd/system/pacman-init.service
    usr/bin/calamares
    usr/bin/ckbcomp
    usr/bin/unsquashfs
    usr/share/applications/darkos-installer.desktop
    usr/share/calamares/branding/darkos/stylesheet.qss
    usr/share/pacman/keyrings/blackarch.gpg
    usr/share/pacman/keyrings/chaotic.gpg
)
for relative in "${required_files[@]}"; do
    if [[ ! -s "$extracted/$relative" ]]; then
        printf 'Required ISO file is missing or empty: /%s\n' "$relative" >&2
        exit 1
    fi
done

for relative in usr/bin/calamares usr/bin/ckbcomp usr/bin/unsquashfs; do
    if [[ ! -x "$extracted/$relative" ]]; then
        printf 'Required ISO executable is not executable: /%s\n' "$relative" >&2
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

chaotic_mirrorlist="$extracted/etc/pacman.d/chaotic-mirrorlist"
# These are literal pacman variables as they appear in the mirrorlist.
# shellcheck disable=SC2016
if grep -Fq 'chaotic.cx/chaotic-aur/$repo' "$chaotic_mirrorlist"; then
    printf 'Chaotic-AUR mirrorlist duplicates the repository path\n' >&2
    exit 1
fi
# shellcheck disable=SC2016
grep -Eq '^Server = https://[^/]+\.chaotic\.cx/\$repo/\$arch$' \
    "$chaotic_mirrorlist" || {
    printf 'Chaotic-AUR mirrorlist has no supported HTTPS endpoint\n' >&2
    exit 1
}

settings="$extracted/etc/calamares/settings.conf"
for instance in live-cleanup bootloader-install pacman-keyring; do
    grep -Fq "id: $instance" "$settings" || {
        printf 'Calamares instance is not registered: %s\n' "$instance" >&2
        exit 1
    }
    grep -Fq "config: shellprocess@$instance.conf" "$settings" || {
        printf 'Calamares instance has no explicit config mapping: %s\n' "$instance" >&2
        exit 1
    }
done
for setting in 'disable-cancel-during-exec: true' \
    'hide-back-and-next-during-exec: true'; do
    grep -Fxq "$setting" "$settings" || {
        printf 'Calamares settings are missing: %s\n' "$setting" >&2
        exit 1
    }
done
grep -Fq -- '- shellprocess@bootloader-install' "$settings" || {
    printf 'Calamares does not run the permission-safe bootloader job\n' >&2
    exit 1
}
if grep -Eq '^[[:space:]]+- bootloader[[:space:]]*$' "$settings"; then
    printf 'Calamares still invokes the exit-126-prone direct bootloader job\n' >&2
    exit 1
fi

keyring_job="$extracted/etc/calamares/modules/shellprocess@pacman-keyring.conf"
grep -Fq '/usr/bin/gpgconf --homedir /etc/pacman.d/gnupg --kill all' \
    "$keyring_job" || {
    printf 'Installed-system keyring job does not stop its GnuPG agent\n' >&2
    exit 1
}

partition_config="$extracted/etc/calamares/modules/partition.conf"
for setting in 'luksGeneration: luks1' 'initialSwapChoice: small'; do
    grep -Fq "$setting" "$partition_config" || {
        printf 'Calamares partition configuration is missing: %s\n' "$setting" >&2
        exit 1
    }
done

welcome_config="$extracted/etc/calamares/modules/welcome.conf"
grep -Fq 'internetCheckUrl: https://ping.archlinux.org/nm-check.txt' \
    "$welcome_config" || {
    printf 'Calamares welcome configuration has no supported connectivity URL\n' >&2
    exit 1
}

grep -Fq 'overlays = (self.dock, self.hud, self.controls)' \
    "$extracted/usr/local/bin/darkos-shell.py" || {
    printf 'DarkOS shell does not hide every overlay during installation\n' >&2
    exit 1
}

for package in blackarch-keyring blackarch-mirrorlist calamares ckbcomp \
    chaotic-keyring chaotic-mirrorlist firefox lvm2 mkinitcpio-nfs-utils nbd \
    neovim pv python-cairo ranger squashfs-tools syslinux; do
    grep -Eq "^${package}[[:space:]]" "$pkglist" || {
        printf 'Required package is absent from the ISO package list: %s\n' "$package" >&2
        exit 1
    }
done

printf 'ISO verification passed: critical payload files and modes are valid.\n'
