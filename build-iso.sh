#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly project_dir
readonly releng_profile="/usr/share/archiso/configs/releng"
readonly out_dir="${project_dir}/out"
readonly vmware_iso="${out_dir}/darkos.iso"

if (( EUID != 0 )); then
    printf 'DarkOS ISO builds must run as root. Use: sudo bash build-iso.sh\n' >&2
    exit 1
fi

for command in awk bash chmod cmp cp find git grep head install ln lsinitcpio mkarchiso mktemp pacman readlink rm stat tee unsquashfs xorriso; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        printf 'Required build command not found: %s\n' "${command}" >&2
        printf 'Run this build on Arch Linux with archiso, base-devel, and mkinitcpio installed.\n' >&2
        exit 1
    fi
done

build_sha_candidate="${DARKOS_BUILD_SHA:-${GITHUB_SHA:-}}"
if [[ -z "${build_sha_candidate}" ]]; then
    build_sha_candidate="$(
        git -c safe.directory="${project_dir}" -C "${project_dir}" \
            rev-parse --verify HEAD 2>/dev/null || true
    )"
fi
build_sha_candidate="${build_sha_candidate,,}"
if [[ ! "${build_sha_candidate}" =~ ^[0-9a-f]{8}([0-9a-f]{32}|[0-9a-f]{56})?$ ]]; then
    printf '%s\n' \
        'Could not determine Git build identity; build from a checkout or set DARKOS_BUILD_SHA.' >&2
    exit 1
fi
build_sha="${build_sha_candidate:0:8}"
readonly build_sha

[[ -d "${releng_profile}/airootfs" && -d "${releng_profile}/efiboot" ]] || {
    printf 'The Archiso releng profile is incomplete at %s; reinstall archiso.\n' "${releng_profile}" >&2
    exit 1
}

# Every executable shipped by DarkOS is listed once here.  The source checkout
# and staged profile are repaired and checked before mkarchiso runs, and the
# actual SquashFS is extracted and checked after the ISO is built.  A stale
# work directory or a lost Windows executable bit can therefore never produce
# another silently broken ISO.
readonly runtime_scripts=(
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-tty1-login
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-installer
    usr/local/bin/darkos-lock
    usr/local/bin/darkos-shell.py
    usr/local/bin/the-void.sh
    usr/local/bin/start-hyprland
    usr/local/bin/darkos-firstboot-tools
    usr/local/bin/Installation_guide
    usr/local/bin/choose-mirror
    usr/local/bin/livecd-sound
    root/.automated_script.sh
)

readonly bash_scripts=(
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-tty1-login
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-installer
    usr/local/bin/darkos-lock
    usr/local/bin/the-void.sh
    usr/local/bin/start-hyprland
    usr/local/bin/darkos-firstboot-tools
    usr/local/bin/Installation_guide
    usr/local/bin/choose-mirror
    usr/local/bin/livecd-sound
    root/.automated_script.sh
)
readonly python_scripts=(
    usr/local/bin/darkos-shell.py
    usr/local/bin/darkos_shell/__init__.py
    usr/local/bin/darkos_shell/ai_brain.py
    usr/local/bin/darkos_shell/activity_detector.py
    usr/local/bin/darkos_shell/assistant_trigger.py
    usr/local/bin/darkos_shell/canvases.py
    usr/local/bin/darkos_shell/css.py
    usr/local/bin/darkos_shell/system_sampler.py
    usr/local/bin/darkos_shell/surfaces.py
    usr/local/bin/darkos_shell/tokens.py
)

# Files that must be byte-identical between source and squashfs but are not
# runtime executables (no mode-755 / shebang enforcement — they're library modules).
readonly cmp_scripts=(
    usr/local/bin/darkos_shell/__init__.py
    usr/local/bin/darkos_shell/ai_brain.py
    usr/local/bin/darkos_shell/activity_detector.py
    usr/local/bin/darkos_shell/assistant_trigger.py
    usr/local/bin/darkos_shell/canvases.py
    usr/local/bin/darkos_shell/css.py
    usr/local/bin/darkos_shell/system_sampler.py
    usr/local/bin/darkos_shell/surfaces.py
    usr/local/bin/darkos_shell/tokens.py
)

readonly archiso_hook_packages=(
    mkinitcpio-nfs-utils
    nbd
    pv
    syslinux
)

readonly runtime_symlinks=(
    etc/systemd/system/multi-user.target.wants/NetworkManager.service
    etc/systemd/system/multi-user.target.wants/bluetooth.service
    etc/systemd/system/multi-user.target.wants/darkos-grub-repair.service
    etc/systemd/system/multi-user.target.wants/seatd.service
)

declare -Ar runtime_symlink_targets=(
    [etc/systemd/system/multi-user.target.wants/NetworkManager.service]="/usr/lib/systemd/system/NetworkManager.service"
    [etc/systemd/system/multi-user.target.wants/bluetooth.service]="/usr/lib/systemd/system/bluetooth.service"
    [etc/systemd/system/multi-user.target.wants/darkos-grub-repair.service]="../darkos-grub-repair.service"
    [etc/systemd/system/multi-user.target.wants/seatd.service]="/usr/lib/systemd/system/seatd.service"
)

assert_source_symlinks() {
    local relative path actual
    for relative in "${runtime_symlinks[@]}"; do
        path="${project_dir}/airootfs/${relative}"
        if [[ -L "${path}" ]]; then
            actual="$(readlink "${path}")"
        elif [[ -f "${path}" ]]; then
            IFS= read -r actual < "${path}" || true
            actual="${actual%$'\r'}"
        else
            printf 'Missing runtime symlink source: /%s\n' "${relative}" >&2
            return 1
        fi
        [[ "${actual}" == "${runtime_symlink_targets[${relative}]}" ]] || {
            printf 'Wrong runtime symlink target for /%s: %s (expected %s)\n' \
                "${relative}" "${actual:-<empty>}" \
                "${runtime_symlink_targets[${relative}]}" >&2
            return 1
        }
    done
}

repair_staged_symlinks() {
    local root="$1"
    local relative path target
    for relative in "${runtime_symlinks[@]}"; do
        path="${root}/${relative}"
        target="${runtime_symlink_targets[${relative}]}"
        rm -f -- "${path}"
        ln -s -- "${target}" "${path}"
        [[ -L "${path}" && "$(readlink "${path}")" == "${target}" ]] || {
            printf 'Could not stage runtime symlink: /%s -> %s\n' \
                "${relative}" "${target}" >&2
            return 1
        }
    done
}

assert_archiso_hook_packages() {
    local package
    for package in "${archiso_hook_packages[@]}"; do
        grep -Eq "^${package}([[:space:]]|$)" "${project_dir}/packages.x86_64" || {
            printf 'packages.x86_64 is missing ArchISO hook dependency: %s\n' "${package}" >&2
            return 1
        }
    done
}

assert_profile_permissions() (
    # Reproduce mkarchiso's loading scope. A `declare -A file_permissions` in
    # profiledef.sh becomes local to load_profile() and leaves this map empty.
    declare -A file_permissions=()
    declare -A expected_permissions=(
        ["/etc/gshadow"]="0:0:600"
        ["/etc/shadow"]="0:0:600"
        ["/etc/sudoers.d"]="0:0:750"
        ["/etc/sudoers.d/darkos"]="0:0:440"
        ["/root"]="0:0:750"
        ["/root/.automated_script.sh"]="0:0:755"
        ["/root/.gnupg"]="0:0:700"
        ["/etc/darkos-build-sha"]="0:0:644"
        ["/usr/local/bin/choose-mirror"]="0:0:755"
        ["/usr/local/bin/Installation_guide"]="0:0:755"
        ["/usr/local/bin/livecd-sound"]="0:0:755"
    )
    local relative
    for relative in "${runtime_scripts[@]}"; do
        expected_permissions["/${relative}"]="0:0:755"
    done

    load_profile() {
        # shellcheck source=profiledef.sh
        source "${project_dir}/profiledef.sh"
    }
    load_profile

    for relative in "${!expected_permissions[@]}"; do
        if [[ "${file_permissions[${relative}]:-}" != "${expected_permissions[${relative}]}" ]]; then
            printf 'Invalid or invisible profile permission for %s: %s (expected %s)\n' \
                "${relative}" "${file_permissions[${relative}]:-missing}" \
                "${expected_permissions[${relative}]}" >&2
            return 1
        fi
    done
)

assert_runtime_scripts() {
    local root="$1"
    local label="$2"
    local repair_mode="$3"
    local relative file first_line mode

    for relative in "${runtime_scripts[@]}"; do
        file="${root}/${relative}"
        [[ -f "${file}" ]] || {
            printf 'Missing runtime executable in %s: /%s\n' "${label}" "${relative}" >&2
            return 1
        }

        if [[ "${repair_mode}" == repair ]]; then
            chmod 0755 "${file}"
        fi

        mode="$(stat -c '%a' "${file}")"
        [[ "${mode}" == 755 ]] || {
            printf 'Wrong mode in %s: /%s is %s (expected 755)\n' "${label}" "${relative}" "${mode}" >&2
            return 1
        }

        IFS= read -r first_line < "${file}" || true
        [[ "${first_line}" == '#!'* ]] || {
            printf 'Missing shebang in %s: /%s\n' "${label}" "${relative}" >&2
            return 1
        }
        if LC_ALL=C grep -q $'\r' "${file}"; then
            printf 'CRLF bytes found in %s: /%s (this causes exit code 126)\n' "${label}" "${relative}" >&2
            return 1
        fi
    done
}

printf 'Checking DarkOS runtime executables before staging...\n'
assert_archiso_hook_packages
assert_source_symlinks
assert_profile_permissions
assert_runtime_scripts "${project_dir}/airootfs" 'source profile' repair
for relative in "${bash_scripts[@]}"; do
    bash -n "${project_dir}/airootfs/${relative}"
done
for relative in "${python_scripts[@]}"; do
    python -m py_compile "${project_dir}/airootfs/${relative}"
done
for relative in "${cmp_scripts[@]}"; do
    cmp -s "${project_dir}/airootfs/${relative}" "${stage_profile}/airootfs/${relative}" || {
        printf 'Packaged library module differs from source: /%s\n' "${relative}" >&2
        return 1
    }
done

stage_profile="$(mktemp -d /tmp/darkos-archiso-profile.XXXXXX)"
work_dir="$(mktemp -d /tmp/darkos-archiso-work.XXXXXX)"
repo_dir="$(mktemp -d /tmp/darkos-calamares-repo.XXXXXX)"
verify_parent="$(mktemp -d /tmp/darkos-rootfs-check.XXXXXX)"

cleanup() {
    if [[ "${DARKOS_KEEP_WORK:-0}" == 1 ]]; then
        printf 'Preserving build directories:\n  %s\n  %s\n  %s\n  %s\n' \
            "${stage_profile}" "${work_dir}" "${repo_dir}" "${verify_parent}"
        return
    fi
    rm -rf -- "${stage_profile}" "${work_dir}" "${repo_dir}" "${verify_parent}"
}
trap cleanup EXIT

printf 'Staging a fresh Archiso releng profile...\n'
cp -a "${releng_profile}/airootfs" "${stage_profile}/"
cp -a "${releng_profile}/efiboot" "${stage_profile}/"
cp -a "${project_dir}/airootfs/." "${stage_profile}/airootfs/"
# A local Python syntax check can leave ignored bytecode beside the source.
# `cp -a` deliberately copies ignored files too, so strip those caches from
# the staged payload rather than silently shipping host-specific bytecode.
find "${stage_profile}/airootfs/usr/local/bin" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "${stage_profile}/airootfs/usr/local/bin" -depth -type d -name '__pycache__' -empty -delete
repair_staged_symlinks "${stage_profile}/airootfs"

# Reuse the canonical DarkOS logo in Plymouth without storing a second binary
# copy in Git. Both the live initramfs and the installed system consume this
# staged theme directory.
install -Dm0644 \
    "${project_dir}/airootfs/usr/share/calamares/branding/darkos/icons/darkos.png" \
    "${stage_profile}/airootfs/usr/share/plymouth/themes/darkos/darkos.png"

# The releng profile owns the live initramfs config. Add Plymouth after
# udev in the staged copy so the live-USB boot shows the splash. This
# file (archiso.conf) is live-ISO-only; the INSTALLED system gets the
# mkinitcpio package's stock /etc/mkinitcpio.conf, which darkos-grub-
# install.sh handles at first boot (with its own udev/systemd fallback
# and a grep assertion, then mkinitcpio -P).
archiso_mkinitcpio="${stage_profile}/airootfs/etc/mkinitcpio.conf.d/archiso.conf"
[[ -f "${archiso_mkinitcpio}" ]] || {
    printf 'Staged Archiso mkinitcpio configuration is missing: %s\n' \
        "${archiso_mkinitcpio}" >&2
    exit 1
}
if ! grep -Eq '^[[:space:]]*HOOKS=.*[[:space:](]plymouth[[:space:])]' \
    "${archiso_mkinitcpio}"; then
    # Anchor on udev, which is the first block-device hook in the Archiso
    # releng HOOKS array. sed exits 0 on zero matches, so the grep below
    # is the real assertion: a silent no-op must fail the build.
    sed -i -E \
        '/^[[:space:]]*HOOKS=/ s/([[:space:](])udev([[:space:])])/\1udev plymouth\2/' \
        "${archiso_mkinitcpio}" || {
        printf 'sed failed while adding Plymouth to live initramfs HOOKS\n' >&2
        exit 1
    }
fi
# Fail closed: confirm the resolved HOOKS= line actually contains plymouth.
if ! grep -Eq '^[[:space:]]*HOOKS=.*[[:space:](]plymouth[[:space:])]' \
    "${archiso_mkinitcpio}"; then
    printf 'Could not enable Plymouth in the live Archiso initramfs\n' >&2
    exit 1
fi

# systemd-boot reads these entries directly from the live EFI image. Request
# the splash there as well as in the GRUB config generated for installations.
mapfile -d '' -t live_loader_entries < <(
    find "${stage_profile}/efiboot/loader/entries" -maxdepth 1 -type f \
        -name '*linux.conf' -print0
)
[[ "${#live_loader_entries[@]}" -gt 0 ]] || {
    printf 'No live systemd-boot Linux entries were staged\n' >&2
    exit 1
}
for loader_entry in "${live_loader_entries[@]}"; do
    sed -i -E \
        '/^options[[:space:]]/ { /(^|[[:space:]])splash([[:space:]]|$)/! s/$/ quiet splash/; }' \
        "${loader_entry}"
    grep -Eq '^options[[:space:]].*[[:space:]]quiet[[:space:]]+splash([[:space:]]|$)' \
        "${loader_entry}" || {
        printf 'Live boot entry has no quiet splash options: %s\n' \
            "${loader_entry}" >&2
        exit 1
    }
done

# Allow future custom boot assets without losing the releng defaults.
for asset in efiboot syslinux grub; do
    if [[ -d "${project_dir}/${asset}" ]]; then
        mkdir -p "${stage_profile}/${asset}"
        cp -a "${project_dir}/${asset}/." "${stage_profile}/${asset}/"
    fi
done
install -m 0644 "${project_dir}/packages.x86_64" "${stage_profile}/packages.x86_64"
install -m 0644 "${project_dir}/profiledef.sh" "${stage_profile}/profiledef.sh"
printf '%s\n' "${build_sha}" > "${stage_profile}/airootfs/etc/darkos-build-sha"
chmod 0644 "${stage_profile}/airootfs/etc/darkos-build-sha"

expected_iso="$(bash -c '
    set -Eeuo pipefail
    declare -A file_permissions=()
    source "$1"
    printf "%s/%s-%s-%s.iso\n" "$2" "$iso_name" "$iso_version" "$arch"
' bash "${stage_profile}/profiledef.sh" "${out_dir}")"
case "${expected_iso}" in
    "${out_dir}/"*.iso) ;;
    *)
        printf 'Refusing unexpected ISO output path: %s\n' "${expected_iso}" >&2
        exit 1
        ;;
esac

assert_runtime_scripts "${stage_profile}/airootfs" 'staged profile' repair
for relative in "${bash_scripts[@]}"; do
    bash -n "${stage_profile}/airootfs/${relative}"
done
for relative in "${python_scripts[@]}"; do
    python -m py_compile "${stage_profile}/airootfs/${relative}"
done
for relative in "${cmp_scripts[@]}"; do
    cmp -s "${project_dir}/airootfs/${relative}" "${stage_profile}/airootfs/${relative}" || {
        printf 'Packaged library module differs from source at staged profile: /%s\n' "${relative}" >&2
        return 1
    }
done

printf 'Building the pinned Calamares package and local pacman repository...\n'
bash "${project_dir}/ci/build-calamares.sh" "${repo_dir}"
[[ -s "${repo_dir}/darkos-local.db.tar.gz" ]] || {
    printf 'Calamares build did not create the local pacman repository database.\n' >&2
    exit 1
}

# Put the verified local repository first, ahead of all network repositories,
# so packages.x86_64 always resolves the pinned Calamares build.
awk -v repo_url="file://${repo_dir}" '
    function emit_local_repo() {
        print ""
        print "[darkos-local]"
        print "SigLevel = Optional TrustAll"
        print "Server = " repo_url
        print ""
        inserted = 1
    }
    /^\[/ && $0 != "[options]" && !inserted { emit_local_repo() }
    { print }
    END { if (!inserted) emit_local_repo() }
' "${project_dir}/pacman.conf" > "${stage_profile}/pacman.conf"

mkdir -p "${out_dir}"
if [[ -e "${expected_iso}" ]]; then
    printf 'Removing stale ISO output before build: %s\n' "${expected_iso}"
    rm -f -- "${expected_iso}"
fi
printf 'Building DarkOS ISO from a clean work directory...\n'
build_log="${verify_parent}/mkarchiso.log"
mkarchiso -v -C "${stage_profile}/pacman.conf" -w "${work_dir}" -o "${out_dir}" "${stage_profile}" \
    2>&1 | tee "${build_log}"
if grep -Eq '^==> ERROR:|^==> WARNING: errors were encountered during the build\.' "${build_log}"; then
    printf 'mkarchiso reported an incomplete initramfs; refusing to publish the ISO.\n' >&2
    grep -E '^==> ERROR:|^==> WARNING: errors were encountered during the build\.' \
        "${build_log}" >&2
    exit 1
fi
[[ -s "${expected_iso}" ]] || {
    printf 'mkarchiso did not produce the expected ISO: %s\n' "${expected_iso}" >&2
    exit 1
}

mapfile -d '' -t rootfs_images < <(find "${work_dir}" -type f -name airootfs.sfs -print0)
if [[ "${#rootfs_images[@]}" -ne 1 ]]; then
    printf 'Expected one built airootfs.sfs, found %s. The ISO will not be released.\n' "${#rootfs_images[@]}" >&2
    exit 1
fi

printf 'Verifying executable modes inside the built SquashFS...\n'
verify_root="${verify_parent}/rootfs"
unsquashfs -quiet -dest "${verify_root}" "${rootfs_images[0]}" "${runtime_scripts[@]}"
assert_runtime_scripts "${verify_root}" 'built SquashFS' check
for relative in "${runtime_scripts[@]}"; do
    cmp -s "${project_dir}/airootfs/${relative}" "${verify_root}/${relative}" || {
        printf 'Packaged runtime executable differs from source: /%s\n' "${relative}" >&2
        exit 1
    }
done
for relative in "${bash_scripts[@]}"; do
    bash -n "${verify_root}/${relative}"
done
for relative in "${python_scripts[@]}"; do
    python -m py_compile "${verify_root}/${relative}"
done
for relative in "${cmp_scripts[@]}"; do
    cmp -s "${project_dir}/airootfs/${relative}" "${verify_root}/${relative}" || {
        printf 'Packaged library module differs from source in built SquashFS: /%s\n' "${relative}" >&2
        exit 1
    }
done

printf 'Verifying the payload embedded in the final ISO...\n'
bash "${project_dir}/ci/verify-iso.sh" "${expected_iso}"

# VMware's checked-in test machine always points at out/darkos.iso. Update
# that stable name only after the versioned image has passed every payload
# check, so a local VM can never silently keep booting an older installer.
printf 'Publishing verified VMware ISO at %s...\n' "${vmware_iso}"
ln -f "${expected_iso}" "${vmware_iso}"
cmp -s "${expected_iso}" "${vmware_iso}" || {
    printf 'Verified VMware ISO does not match the versioned build artifact.\n' >&2
    exit 1
}

printf 'Build complete and packaged executables verified. Output written to %s/\n' "${out_dir}"
