#!/usr/bin/env bash
# Fail the build if critical installer/runtime files are missing or lose their
# Unix metadata inside the final squashfs. This checks the artifact users boot,
# not merely the Git index or pre-build staging directory.

set -Eeuo pipefail

if (($# != 1)); then
    printf 'Expected exactly one ISO path; got %d\n' "$#" >&2
    printf 'Usage: %s /path/to/darkos.iso\n' "$0" >&2
    exit 2
fi

iso_path="$1"
if [[ ! -s "$iso_path" ]]; then
    printf 'Usage: %s /path/to/darkos.iso\n' "$0" >&2
    exit 2
fi

for command in awk bash grep lsinitcpio mktemp python readlink stat \
    unsquashfs wc xorriso; do
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
for relative in usr/bin/plymouthd \
    usr/share/plymouth/themes/darkos/darkos.png \
    usr/share/plymouth/themes/darkos/darkos.plymouth \
    usr/share/plymouth/themes/darkos/darkos.script; do
    grep -Fxq "$relative" "$initramfs_files" || {
        printf 'DarkOS boot-animation file is absent from the initramfs: /%s\n' \
            "$relative" >&2
        exit 1
    }
done

payload=(
    etc/calamares/settings.conf
    etc/darkos-build-sha
    etc/calamares/modules/mount.conf
    etc/calamares/modules/partition.conf
    etc/calamares/modules/services-systemd.conf
    etc/calamares/modules/shellprocess@bootloader-install.conf
    etc/calamares/modules/shellprocess@fix-greeter-groups.conf
    etc/calamares/modules/shellprocess@pacman-keyring.conf
    etc/calamares/modules/welcome.conf
    etc/group
    etc/gshadow
    etc/greetd/config.toml
    etc/greetd/regreet.css
    etc/greetd/regreet.toml
    etc/pacman.conf
    etc/pacman.d/blackarch-mirrorlist
    etc/pacman.d/chaotic-mirrorlist
    etc/passwd
    etc/shadow
    etc/sudoers.d/darkos-ai-snapshot
    etc/plymouth/plymouthd.conf
    etc/xdg/hypr/hypridle.conf
    etc/xdg/hypr/hyprland.conf
    etc/xdg/hypr/hyprlock.conf
    etc/xdg/waybar/config
    etc/xdg/waybar/style.css
    etc/systemd/system/multi-user.target.wants/NetworkManager.service
    etc/systemd/system/multi-user.target.wants/bluetooth.service
    etc/systemd/system/multi-user.target.wants/darkos-grub-repair.service
    etc/systemd/system/multi-user.target.wants/pacman-init.service
    etc/systemd/system/multi-user.target.wants/seatd.service
    etc/systemd/system/multi-user.target.wants/sshd.service
    etc/systemd/system/multi-user.target.wants/vmtoolsd.service
    etc/systemd/system/pacman-init.service
    root/.automated_script.sh
    root/.gnupg
    usr/bin/calamares
    usr/bin/cage
    usr/bin/ckbcomp
    usr/bin/hypridle
    usr/bin/hyprlock
    usr/bin/plymouth-set-default-theme
    usr/bin/regreet
    usr/bin/unsquashfs
    usr/bin/arecord
    usr/bin/aplay
    usr/bin/brightnessctl
    usr/bin/btrfs
    usr/bin/espeak-ng
    usr/bin/pamixer
    usr/bin/playerctl
    usr/bin/vmtoolsd
    usr/local/bin/Installation_guide
    usr/local/bin/choose-mirror
    usr/local/bin/darkos-ai-snapshot
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-firstboot-tools
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-installer
    usr/local/bin/darkos-lock
    usr/local/bin/darkos-shell.py
    usr/local/bin/darkos_shell/__init__.py
    usr/local/bin/darkos_shell/ai_brain.py
    usr/local/bin/darkos_shell/activity_detector.py
    usr/local/bin/darkos_shell/actions.py
    usr/local/bin/darkos_shell/assistant_trigger.py
    usr/local/bin/darkos_shell/canvases.py
    usr/local/bin/darkos_shell/css.py
    usr/local/bin/darkos_shell/system_sampler.py
    usr/local/bin/darkos_shell/surfaces.py
    usr/local/bin/darkos_shell/tokens.py
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-tty1-login
    usr/local/bin/ensure-network
    usr/local/bin/start-hyprland
    usr/local/bin/the-void.sh
    usr/local/bin/livecd-sound
    usr/share/applications/darkos-installer.desktop
    usr/share/backgrounds/darkos/darkos-wallpaper.png
    usr/share/icons/darkos/darkos.png
    usr/share/calamares/branding/darkos/icons/darkos.png
    usr/share/calamares/branding/darkos/stylesheet.qss
    usr/share/plymouth/themes/darkos/darkos.png
    usr/share/plymouth/themes/darkos/darkos.plymouth
    usr/share/plymouth/themes/darkos/darkos.script
    usr/share/wayland-sessions/darkos.desktop
    var/lib/AccountsService/users/greeter
    usr/share/pacman/keyrings/blackarch.gpg
    usr/share/pacman/keyrings/chaotic.gpg
)
unsquashfs -no-progress -d "$extracted" "$squashfs" "${payload[@]}" >/dev/null

required_files=(
    etc/calamares/settings.conf
    etc/darkos-build-sha
    etc/calamares/modules/mount.conf
    etc/calamares/modules/partition.conf
    etc/calamares/modules/services-systemd.conf
    etc/calamares/modules/shellprocess@bootloader-install.conf
    etc/calamares/modules/shellprocess@fix-greeter-groups.conf
    etc/calamares/modules/shellprocess@pacman-keyring.conf
    etc/calamares/modules/welcome.conf
    etc/group
    etc/gshadow
    etc/greetd/config.toml
    etc/greetd/regreet.css
    etc/greetd/regreet.toml
    etc/pacman.conf
    etc/pacman.d/blackarch-mirrorlist
    etc/pacman.d/chaotic-mirrorlist
    etc/passwd
    etc/shadow
    etc/sudoers.d/darkos-ai-snapshot
    etc/plymouth/plymouthd.conf
    etc/xdg/hypr/hypridle.conf
    etc/xdg/hypr/hyprland.conf
    etc/xdg/hypr/hyprlock.conf
    etc/xdg/waybar/config
    etc/xdg/waybar/style.css
    etc/systemd/system/pacman-init.service
    usr/bin/calamares
    usr/bin/cage
    usr/bin/ckbcomp
    usr/bin/hypridle
    usr/bin/hyprlock
    usr/bin/plymouth-set-default-theme
    usr/bin/regreet
    usr/bin/unsquashfs
    usr/bin/arecord
    usr/bin/brightnessctl
    usr/bin/btrfs
    usr/bin/espeak-ng
    usr/bin/pamixer
    usr/bin/playerctl
    usr/bin/vmtoolsd
    usr/local/bin/darkos-ai-snapshot
    usr/share/applications/darkos-installer.desktop
    usr/share/backgrounds/darkos/darkos-wallpaper.png
    usr/share/icons/darkos/darkos.png
    usr/share/calamares/branding/darkos/icons/darkos.png
    usr/share/calamares/branding/darkos/stylesheet.qss
    usr/share/plymouth/themes/darkos/darkos.png
    usr/share/plymouth/themes/darkos/darkos.plymouth
    usr/share/plymouth/themes/darkos/darkos.script
    usr/share/wayland-sessions/darkos.desktop
    var/lib/AccountsService/users/greeter
    usr/share/pacman/keyrings/blackarch.gpg
    usr/share/pacman/keyrings/chaotic.gpg
)
for relative in "${required_files[@]}"; do
    if [[ ! -s "$extracted/$relative" ]]; then
        printf 'Required ISO file is missing or empty: /%s\n' "$relative" >&2
        exit 1
    fi
done

build_sha_file="$extracted/etc/darkos-build-sha"
if [[ "$(wc -l < "$build_sha_file")" -ne 1 ]]; then
    printf 'ISO build identity must contain exactly one line\n' >&2
    exit 1
fi
IFS= read -r build_sha < "$build_sha_file" || {
    printf 'Could not read ISO build identity\n' >&2
    exit 1
}
if [[ ! "$build_sha" =~ ^[0-9a-f]{8}$ ]]; then
    printf 'ISO build identity is missing or invalid: %s\n' "$build_sha" >&2
    exit 1
fi
[[ "$(stat -c '%a' "$build_sha_file")" == 644 ]] || {
    printf 'ISO build identity does not have mode 0644\n' >&2
    exit 1
}
grub_repair="$extracted/usr/local/bin/darkos-grub-install.sh"
for build_identity_wiring in \
    'BUILD_SHA_FILE=/etc/darkos-build-sha' \
    'IFS= read -r BUILD_SHA < "$BUILD_SHA_FILE"' \
    "printf 'built_from=%s\\n' \"\$BUILD_SHA\""; do
    grep -Fq "$build_identity_wiring" "$grub_repair" || {
        printf 'Bootloader repair build identity is not wired: %s\n' \
            "$build_identity_wiring" >&2
        exit 1
    }
done

for relative in usr/bin/arecord usr/bin/brightnessctl usr/bin/btrfs \
    usr/bin/calamares usr/bin/cage usr/bin/ckbcomp usr/bin/espeak-ng \
    usr/bin/hypridle usr/bin/hyprlock usr/bin/pamixer usr/bin/playerctl \
    usr/bin/plymouth-set-default-theme usr/bin/regreet usr/bin/unsquashfs \
    usr/bin/vmtoolsd; do
    if [[ ! -x "$extracted/$relative" ]]; then
        printf 'Required ISO executable is not executable: /%s\n' "$relative" >&2
        exit 1
    fi
done

python - "$extracted" <<'PY'
import json
from pathlib import Path
import sys
import tomllib

root = Path(sys.argv[1])
waybar = json.loads((root / "etc/xdg/waybar/config").read_text(encoding="utf-8"))
required_modules = {
    "tray",
    "backlight",
    "custom/bluetooth",
    "network",
    "pulseaudio",
    "battery",
    "custom/avatar",
}
missing_modules = required_modules.difference(waybar["modules-right"])
if missing_modules:
    raise SystemExit(f"Waybar is missing required top-bar modules: {sorted(missing_modules)}")
if "timeout 2 bluetoothctl show" not in waybar["custom/bluetooth"].get("exec", ""):
    raise SystemExit("Waybar Bluetooth status query is not time-bounded")

greetd = tomllib.loads((root / "etc/greetd/config.toml").read_text(encoding="utf-8"))
command = greetd["default_session"]["command"]
if "cage" not in command or "regreet" not in command:
    raise SystemExit("greetd does not launch ReGreet under Cage")
if "GDK_DISABLE=dmabuf,vulkan" not in command or "GSK_RENDERER=cairo" not in command:
    raise SystemExit("greetd is missing the verified VMware-safe ReGreet renderer settings")
if greetd["default_session"].get("user") != "greeter":
    raise SystemExit("greetd does not run ReGreet as the greeter account")

regreet = tomllib.loads((root / "etc/greetd/regreet.toml").read_text(encoding="utf-8"))
if regreet.get("background", {}).get("path") != "/usr/share/backgrounds/darkos/darkos-wallpaper.png":
    raise SystemExit("ReGreet does not use the DarkOS wallpaper")

greeter_avatar = (root / "var/lib/AccountsService/users/greeter").read_text(encoding="utf-8")
if "Icon=/usr/share/icons/darkos/darkos.png" not in greeter_avatar:
    raise SystemExit("ReGreet greeter account does not use the DarkOS app icon as avatar")
PY

cmp -s \
    "$extracted/usr/share/calamares/branding/darkos/icons/darkos.png" \
    "$extracted/usr/share/plymouth/themes/darkos/darkos.png" || {
    printf 'Plymouth does not contain the canonical DarkOS logo\n' >&2
    exit 1
}

hyprland_config="$extracted/etc/xdg/hypr/hyprland.conf"
# shellcheck disable=SC2016 # $mainMod is literal Hyprland configuration.
for setting in 'exec-once = hypridle' 'exec-once = nm-applet --indicator' \
    'exec-once = blueman-applet' 'bind = $mainMod, L, exec, loginctl lock-session' \
    'bind = $mainMod, SPACE, exec, python /usr/local/bin/darkos-shell.py --ptt-start' \
    'bindr = $mainMod, SPACE, exec, python /usr/local/bin/darkos-shell.py --ptt-stop' \
    'match:namespace ^(waybar|darkos-(dock|hud|rail|left|right))$' \
    'blur on' 'ignore_alpha 0.08'; do
    grep -Fq "$setting" "$hyprland_config" || {
        printf 'Hyprland shell configuration is missing: %s\n' "$setting" >&2
        exit 1
    }
done
if grep -Eq '^exec-once = (pipewire|pipewire-pulse|wireplumber)$' "$hyprland_config"; then
    printf 'Hyprland must not race systemd user activation for the PipeWire stack\n' >&2
    exit 1
fi

hypridle_config="$extracted/etc/xdg/hypr/hypridle.conf"
for setting in 'lock_cmd = pidof hyprlock || /usr/local/bin/darkos-lock' \
    'before_sleep_cmd = loginctl lock-session' \
    'on-timeout = loginctl lock-session'; do
    grep -Fq "$setting" "$hypridle_config" || {
        printf 'hypridle configuration is missing: %s\n' "$setting" >&2
        exit 1
    }
done
lock_launcher="$extracted/usr/local/bin/darkos-lock"
for setting in '/sys/module/vmwgfx' 'LIBGL_ALWAYS_SOFTWARE=1' \
    'exec /usr/bin/hyprlock "$@"'; do
    grep -Fq "$setting" "$lock_launcher" || {
        printf 'DarkOS lock launcher is missing: %s\n' "$setting" >&2
        exit 1
    }
done
grep -Fq 'screencopy_mode = 1' "$extracted/etc/xdg/hypr/hyprlock.conf" || {
    printf 'hyprlock does not use the VMware-safe CPU screencopy mode\n' >&2
    exit 1
}
if grep -Fq 'hyprctl dispatch dpms off' "$hypridle_config"; then
    printf 'hypridle must not disable outputs while hyprlock owns the session lock\n' >&2
    exit 1
fi

grep -Fq 'Theme=darkos' "$extracted/etc/plymouth/plymouthd.conf" || {
    printf 'Plymouth does not select the DarkOS theme\n' >&2
    exit 1
}
grep -Fq 'Exec=dbus-run-session -- /usr/local/bin/start-hyprland' \
    "$extracted/usr/share/wayland-sessions/darkos.desktop" || {
    printf 'DarkOS Wayland session does not launch the supported wrapper\n' >&2
    exit 1
}
grep -Fq 'exec /usr/bin/start-hyprland "$@"' \
    "$extracted/usr/local/bin/start-hyprland" || {
    printf 'DarkOS session wrapper does not delegate to the upstream launcher\n' >&2
    exit 1
}

[[ "$(stat -c '%a' "$extracted/etc/shadow")" == 600 ]] || {
    printf 'Live /etc/shadow does not have mode 0600\n' >&2
    exit 1
}
[[ "$(stat -c '%a' "$extracted/etc/gshadow")" == 600 ]] || {
    printf 'Live /etc/gshadow does not have mode 0600\n' >&2
    exit 1
}
snapshot_sudoers="$extracted/etc/sudoers.d/darkos-ai-snapshot"
[[ "$(stat -c '%a' "$snapshot_sudoers")" == 440 ]] || {
    printf 'AI snapshot sudoers policy does not have mode 0440\n' >&2
    exit 1
}
grep -Fxq '%wheel ALL=(root) NOPASSWD: /usr/local/bin/darkos-ai-snapshot ""' \
    "$snapshot_sudoers" || {
    printf 'AI snapshot sudoers policy is broader than the no-argument helper\n' >&2
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
    usr/local/bin/darkos-ai-snapshot
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-firstboot-tools
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-installer
    usr/local/bin/darkos-lock
    usr/local/bin/darkos-shell.py
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-tty1-login
    usr/local/bin/ensure-network
    usr/local/bin/start-hyprland
    usr/local/bin/the-void.sh
    usr/local/bin/livecd-sound
)
readonly library_modules=(
    usr/local/bin/darkos_shell/__init__.py
    usr/local/bin/darkos_shell/ai_brain.py
    usr/local/bin/darkos_shell/activity_detector.py
    usr/local/bin/darkos_shell/actions.py
    usr/local/bin/darkos_shell/assistant_trigger.py
    usr/local/bin/darkos_shell/canvases.py
    usr/local/bin/darkos_shell/css.py
    usr/local/bin/darkos_shell/system_sampler.py
    usr/local/bin/darkos_shell/surfaces.py
    usr/local/bin/darkos_shell/tokens.py
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
for relative in "${library_modules[@]}"; do
    path="$extracted/$relative"
    if [[ ! -f "$path" ]]; then
        printf 'ISO library module is missing: /%s\n' "$relative" >&2
        exit 1
    fi
    if grep -q $'\r' "$path"; then
        printf 'ISO library module contains CRLF data: /%s\n' "$relative" >&2
        exit 1
    fi
    python -m py_compile "$path"
done

declare -A service_targets=(
    [NetworkManager]="/usr/lib/systemd/system/NetworkManager.service"
    [bluetooth]="/usr/lib/systemd/system/bluetooth.service"
    [darkos-grub-repair]="../darkos-grub-repair.service"
    [ensure-network]="../ensure-network.service"
    [pacman-init]="../pacman-init.service"
    [seatd]="/usr/lib/systemd/system/seatd.service"
    [sshd]="/usr/lib/systemd/system/sshd.service"
    [vmtoolsd]="/usr/lib/systemd/system/vmtoolsd.service"
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
for instance in live-cleanup bootloader-install pacman-keyring fix-greeter-groups; do
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
for setting in 'defaultFileSystemType: btrfs' 'luksGeneration: luks1' \
    'initialSwapChoice: small'; do
    grep -Fq "$setting" "$partition_config" || {
        printf 'Calamares partition configuration is missing: %s\n' "$setting" >&2
        exit 1
    }
done

mount_config="$extracted/etc/calamares/modules/mount.conf"
python - "$mount_config" <<'PY'
from pathlib import Path
import sys

import yaml

path = Path(sys.argv[1])
try:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, yaml.YAMLError) as exc:
    raise SystemExit(f"Invalid Calamares mount configuration: {exc}") from exc

if not isinstance(config, dict):
    raise SystemExit("Calamares mount configuration must be a YAML mapping")

expected_subvolumes = {
    "/": "/@",
    "/home": "/@home",
    "/var/cache": "/@cache",
    "/var/log": "/@log",
}
subvolumes = config.get("btrfsSubvolumes")
if not isinstance(subvolumes, list):
    raise SystemExit("Calamares mount configuration has no Btrfs subvolume list")
actual_subvolumes = {}
for entry in subvolumes:
    if not isinstance(entry, dict) or set(entry) != {"mountPoint", "subvolume"}:
        raise SystemExit(f"Invalid Calamares Btrfs subvolume entry: {entry!r}")
    mount_point = entry["mountPoint"]
    if mount_point in actual_subvolumes:
        raise SystemExit(f"Duplicate Calamares Btrfs mount point: {mount_point}")
    actual_subvolumes[mount_point] = entry["subvolume"]
if actual_subvolumes != expected_subvolumes:
    raise SystemExit(
        "Calamares Btrfs layout does not mount the installed root from /@: "
        f"{actual_subvolumes!r}"
    )
if config.get("btrfsSwapSubvol") != "/@swap":
    raise SystemExit("Calamares Btrfs swap subvolume is not /@swap")

extra_mounts = config.get("extraMounts")
if not isinstance(extra_mounts, list):
    raise SystemExit("Calamares mount configuration has no extra chroot mounts")
extra_by_mountpoint = {
    entry.get("mountPoint"): entry
    for entry in extra_mounts
    if isinstance(entry, dict) and isinstance(entry.get("mountPoint"), str)
}
expected_extra_mounts = {
    "/proc": ("proc", "proc"),
    "/sys": ("sys", "sysfs"),
    "/dev": ("/dev", None),
    "/run": ("tmpfs", "tmpfs"),
    "/run/udev": ("/run/udev", None),
    "/sys/firmware/efi/efivars": ("efivarfs", "efivarfs"),
}
for mount_point, (device, filesystem) in expected_extra_mounts.items():
    entry = extra_by_mountpoint.get(mount_point)
    if not entry or entry.get("device") != device or entry.get("fs") != filesystem:
        raise SystemExit(f"Calamares essential mount is invalid: {mount_point}")
for mount_point in ("/dev", "/run/udev"):
    if extra_by_mountpoint[mount_point].get("options") != ["bind"]:
        raise SystemExit(f"Calamares essential bind mount is invalid: {mount_point}")
if extra_by_mountpoint["/sys/firmware/efi/efivars"].get("efi") is not True:
    raise SystemExit("Calamares EFI variables mount is not EFI-gated")

mount_options = config.get("mountOptions")
if not isinstance(mount_options, list):
    raise SystemExit("Calamares mount configuration has no filesystem options")
options_by_filesystem = {
    entry.get("filesystem"): entry.get("options")
    for entry in mount_options
    if isinstance(entry, dict)
}
if options_by_filesystem.get("btrfs") != ["defaults", "compress=zstd:1"]:
    raise SystemExit("Calamares Btrfs mount options are missing compression")
if options_by_filesystem.get("efi") != ["defaults", "umask=0077"]:
    raise SystemExit("Calamares EFI mount options do not protect firmware files")
PY

welcome_config="$extracted/etc/calamares/modules/welcome.conf"
grep -Fq 'internetCheckUrl: https://ping.archlinux.org/nm-check.txt' \
    "$welcome_config" || {
    printf 'Calamares welcome configuration has no supported connectivity URL\n' >&2
    exit 1
}

services_config="$extracted/etc/calamares/modules/services-systemd.conf"
grep -Fq '  - name: greetd' "$services_config" || {
    printf 'Calamares does not enable the installed-system login greeter\n' >&2
    exit 1
}

shell_source="$extracted/usr/local/bin/darkos-shell.py"
shell_pkg="$extracted/usr/local/bin/darkos_shell"
# Overlays tuple is defined in darkos_shell/__init__.py (DarkOSApplication)
grep -Fq 'overlays = (self.dock, self.rail, self.left, self.right)' \
    "$shell_pkg/__init__.py" "$shell_source" || {
    printf 'DarkOS shell does not hide every overlay during installation\n' >&2
    exit 1
}
for component in 'class DarkOSIconRail' 'class DarkOSLeftPanels' \
    'class DarkOSRightPanels' 'class RingGauge' \
    'class AIOrbCanvas'; do
    grep -Fq "$component" "$shell_pkg/"*.py "$shell_source" || {
        printf 'DarkOS shell component is missing: %s\n' "$component" >&2
        exit 1
    }
done
if grep -Fq 'class DarkOSSidePanels' "$shell_pkg/"*.py "$shell_source"; then
    printf 'Legacy combined DarkOSSidePanels still exists\n' >&2
    exit 1
fi
if grep -Fq -- '-gtk-icon-size:' "$shell_pkg/"*.py "$shell_source"; then
    printf 'DarkOS shell uses the invalid GTK3 CSS property -gtk-icon-size\n' >&2
    exit 1
fi
grep -Fq '("sleeping", "listening", "thinking", "speaking", "error")' \
    "$shell_pkg/__init__.py" "$shell_source" || {
    printf 'AI Orb does not expose all five required click states\n' >&2
    exit 1
}
# HUD identity is baked into the wallpaper image; verify the asset shipped.
wallpaper="$extracted/usr/share/backgrounds/darkos/darkos-wallpaper.png"
if [[ ! -s "$wallpaper" ]]; then
    printf 'DarkOS wallpaper is missing or empty\n' >&2
    exit 1
fi
if ! grep -q $'\x89PNG' "$wallpaper"; then
    printf 'DarkOS wallpaper is not a valid PNG\n' >&2
    exit 1
fi
grep -Fq 'self.toggle_state = {' "$shell_pkg/__init__.py" "$shell_source" || {
    printf 'Shell shared toggle state is not owned by DarkOSApplication\n' >&2
    exit 1
}
grep -Fq '"playerctl", "metadata", "--format"' "$shell_pkg/surfaces.py" "$shell_source" || {
    printf 'Media panel does not read live playerctl metadata\n' >&2
    exit 1
}
grep -Fq 'process_chat' "$shell_pkg/__init__.py" "$shell_source" || {
    printf 'AI chat is not wired to the brain\n' >&2
    exit 1
}
grep -Fq 'process_chat' "$shell_pkg/surfaces.py" "$shell_source" || {
    printf 'Chat entry does not call process_chat\n' >&2
    exit 1
}
grep -Fq 'ActionDispatcher' "$shell_pkg/__init__.py" "$shell_source" || {
    printf 'Action dispatcher not wired in\n' >&2
    exit 1
}
grep -Fq '"openrouter/free"' "$shell_pkg/ai_brain.py" || {
    printf 'AI brain does not use the supported OpenRouter free router by default\n' >&2
    exit 1
}
grep -Fq '_ALLOWED_ACTIONS = frozenset' "$shell_pkg/ai_brain.py" || {
    printf 'AI action dispatch has no explicit allowlist\n' >&2
    exit 1
}

grep -Fq 'plymouth-set-default-theme darkos' \
    "$extracted/usr/local/bin/darkos-grub-install.sh" || {
    printf 'Installed-system initramfs does not select the DarkOS Plymouth theme\n' >&2
    exit 1
}
grep -Fq "set_grub_option GRUB_CMDLINE_LINUX_DEFAULT" \
    "$extracted/usr/local/bin/darkos-grub-install.sh" || {
    printf 'Installed GRUB configuration does not request the boot splash\n' >&2
    exit 1
}

for package in adwaita-icon-theme alsa-utils blackarch-keyring blackarch-mirrorlist \
    btrfs-progs brightnessctl calamares cage ckbcomp chaotic-keyring \
    chaotic-mirrorlist espeak-ng firefox greetd greetd-regreet gtk3 \
    gtk-layer-shell hypridle hyprlock inter-font lvm2 mkinitcpio-nfs-utils \
    nbd neovim open-vm-tools pamixer pipewire pipewire-pulse playerctl \
    plymouth pv python-cairo python-gobject ranger rtkit squashfs-tools \
    syslinux wireplumber blueman accountsservice; do
    grep -Eq "^${package}[[:space:]]" "$pkglist" || {
        printf 'Required package is absent from the ISO package list: %s\n' "$package" >&2
        exit 1
    }
done

printf 'ISO verification passed: critical payload files and modes are valid.\n'
