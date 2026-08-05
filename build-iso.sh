#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly project_dir
readonly releng_profile="/usr/share/archiso/configs/releng"
readonly out_dir="${project_dir}/out"

if (( EUID != 0 )); then
    printf 'DarkOS ISO builds must run as root. Use: sudo bash build-iso.sh\n' >&2
    exit 1
fi

for command in awk bash chmod cmp cp find grep head install mkarchiso mktemp pacman rm stat unsquashfs; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        printf 'Required build command not found: %s\n' "${command}" >&2
        printf 'Run this build on an up-to-date Arch Linux host with archiso and base-devel installed.\n' >&2
        exit 1
    fi
done

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
    usr/local/bin/darkos-shell.py
    usr/local/bin/the-void.sh
    usr/local/bin/start-hyprland
    usr/local/bin/darkos-firstboot-tools
)

readonly bash_scripts=(
    usr/local/bin/darkos-grub-install.sh
    usr/local/bin/darkos-tty1-login
    usr/local/bin/darkos-tool-groups
    usr/local/bin/darkos-diagnose.sh
    usr/local/bin/darkos-installer
    usr/local/bin/the-void.sh
    usr/local/bin/start-hyprland
    usr/local/bin/darkos-firstboot-tools
)

assert_profile_permissions() (
    # Reproduce mkarchiso's loading scope. A `declare -A file_permissions` in
    # profiledef.sh becomes local to load_profile() and leaves this map empty.
    declare -A file_permissions=()
    declare -A expected_permissions=(
        ["/etc/shadow"]="0:0:600"
        ["/etc/sudoers.d/darkos"]="0:0:440"
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
assert_profile_permissions
assert_runtime_scripts "${project_dir}/airootfs" 'source profile' repair
for relative in "${bash_scripts[@]}"; do
    bash -n "${project_dir}/airootfs/${relative}"
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

# Allow future custom boot assets without losing the releng defaults.
for asset in efiboot syslinux grub; do
    if [[ -d "${project_dir}/${asset}" ]]; then
        mkdir -p "${stage_profile}/${asset}"
        cp -a "${project_dir}/${asset}/." "${stage_profile}/${asset}/"
    fi
done
install -m 0644 "${project_dir}/packages.x86_64" "${stage_profile}/packages.x86_64"
install -m 0644 "${project_dir}/profiledef.sh" "${stage_profile}/profiledef.sh"

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
mkarchiso -v -C "${stage_profile}/pacman.conf" -w "${work_dir}" -o "${out_dir}" "${stage_profile}"
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

printf 'Verifying the payload embedded in the final ISO...\n'
bash "${project_dir}/ci/verify-iso.sh" "${expected_iso}"

printf 'Build complete and packaged executables verified. Output written to %s/\n' "${out_dir}"
