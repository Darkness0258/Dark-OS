#!/usr/bin/env bash
# Build DarkOS' first-party Calamares API-key view module against the exact
# pinned Calamares package produced by build-calamares.sh, then add the module
# package to the same local pacman repository.

set -Eeuo pipefail

readonly CALAMARES_VERSION="3.4.2"
readonly CALAMARES_PKGREL="2"
readonly MODULE_NAME="darkosapikeys"
readonly MODULE_PACKAGE="darkos-calamares-apikeys"
readonly MODULE_VERSION="1.0.0"
readonly MODULE_PKGREL="1"
readonly REPO_NAME="darkos-local"

repo_dir="${1:-}"
project_dir="${2:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
module_dir="${project_dir}/calamares-modules/${MODULE_NAME}"

if [[ "${EUID}" -ne 0 ]]; then
    printf 'build-darkos-calamares-module.sh must run as root\n' >&2
    exit 1
fi
[[ -n "${repo_dir}" && -d "${repo_dir}" ]] || {
    printf 'Usage: %s <local-repository-directory> [project-directory]\n' "${0##*/}" >&2
    exit 2
}
[[ -f "${module_dir}/CMakeLists.txt" ]] || {
    printf 'DarkOS Calamares module source is missing: %s\n' "${module_dir}" >&2
    exit 1
}

command -v pacman >/dev/null 2>&1 || {
    printf 'Required command not found: pacman\n' >&2
    exit 1
}

# A verified cached Calamares package makes build-calamares.sh return before it
# installs build dependencies. Keep this first-party package build independently
# reproducible by installing the exact consumer toolchain it needs here too.
readonly BUILD_DEPENDENCIES=(
    base-devel
    cmake
    extra-cmake-modules
    kcoreaddons
    kpmcore
    libglvnd
    libpwquality
    ninja
    python
    qt6-base
    qt6-declarative
    qt6-svg
    qt6-tools
    qt6-translations
    yaml-cpp
)
pacman -S --needed --noconfirm "${BUILD_DEPENDENCIES[@]}"

for command in awk basename bash bsdtar cat chown cmake dirname find grep \
    install makepkg mkdir mktemp ninja pacman pwd readelf repo-add rm runuser \
    sed sha256sum tar useradd userdel xargs; do
    command -v "${command}" >/dev/null 2>&1 || {
        printf 'Required command not found: %s\n' "${command}" >&2
        exit 1
    }
done

mapfile -d '' -t calamares_candidates < <(
    find "${repo_dir}" -maxdepth 1 -type f -name 'calamares-*.pkg.tar*' \
        ! -name '*.sig' -print0
)
calamares_packages=()
for candidate in "${calamares_candidates[@]}"; do
    read -r package_name package_version < <(pacman -Qp "${candidate}")
    if [[ "${package_name}" == calamares \
        && "${package_version}" == "${CALAMARES_VERSION}-${CALAMARES_PKGREL}" ]]; then
        calamares_packages+=("${candidate}")
    fi
done
if [[ "${#calamares_packages[@]}" -ne 1 ]]; then
    printf 'Expected exactly one Calamares %s-%s package in %s, found %s\n' \
        "${CALAMARES_VERSION}" "${CALAMARES_PKGREL}" "${repo_dir}" \
        "${#calamares_packages[@]}" >&2
    exit 1
fi
calamares_package="${calamares_packages[0]}"

work_root="$(mktemp -d /tmp/darkos-calamares-module.XXXXXX)"
sdk_root="${work_root}/sdk"
package_root="${work_root}/package"
build_home="${work_root}/home"
build_tmp="${work_root}/tmp"
builder="darkos-module-$$"
builder_created=0

cleanup() {
    local status=$?
    if [[ "${builder_created}" == 1 ]]; then
        if ! userdel --remove "${builder}" >/dev/null 2>&1; then
            printf 'Warning: could not remove temporary build user: %s\n' "${builder}" >&2
        fi
    fi
    rm -rf -- "${work_root}"
    return "${status}"
}
trap cleanup EXIT

mkdir -p "${sdk_root}" "${package_root}" "${build_home}" "${build_tmp}"
printf 'Extracting the verified Calamares %s-%s SDK...\n' \
    "${CALAMARES_VERSION}" "${CALAMARES_PKGREL}"
bsdtar -xf "${calamares_package}" -C "${sdk_root}"

calamares_cmake="${sdk_root}/usr/lib/cmake/Calamares/CalamaresConfig.cmake"
[[ -s "${calamares_cmake}" ]] || {
    printf 'Pinned Calamares package does not contain its CMake consumer SDK\n' >&2
    exit 1
}
[[ -s "${sdk_root}/usr/include/libcalamares/Job.h" \
    && -s "${sdk_root}/usr/include/libcalamares/viewpages/ViewStep.h" ]] || {
    printf 'Pinned Calamares package does not contain required public headers\n' >&2
    exit 1
}

# The upstream SDK is relocatable except for the two imported library paths
# recorded by Arch's package build. Redirect only those four exact metadata
# entries to this private SDK; the package itself remains byte-for-byte intact.
calamares_targets="${sdk_root}/usr/lib/cmake/Calamares/CalamaresTargets-release.cmake"
calamares_export="${sdk_root}/usr/lib/cmake/Calamares/CalamaresTargets.cmake"
[[ -s "${calamares_targets}" ]] || {
    printf 'Pinned Calamares package does not contain release target metadata\n' >&2
    exit 1
}
[[ -s "${calamares_export}" ]] || {
    printf 'Pinned Calamares package does not contain exported target metadata\n' >&2
    exit 1
}
absolute_target_count="$(grep -Foc '"/usr/lib/libcalamares' "${calamares_targets}")"
[[ "${absolute_target_count}" == 4 ]] || {
    printf 'Expected four pinned Calamares absolute target entries, found %s\n' \
        "${absolute_target_count}" >&2
    exit 1
}
sed -i "s|\"/usr/lib/libcalamares|\"${sdk_root}/usr/lib/libcalamares|g" \
    "${calamares_targets}"
grep -Fq '"/usr/lib/libcalamares' "${calamares_targets}" && {
    printf 'Could not relocate the private Calamares SDK target metadata\n' >&2
    exit 1
}
import_prefix_count="$(grep -Foc 'set(_IMPORT_PREFIX "/usr")' "${calamares_export}")"
[[ "${import_prefix_count}" == 1 ]] || {
    printf 'Expected one pinned Calamares import prefix, found %s\n' \
        "${import_prefix_count}" >&2
    exit 1
}
sed -i "s|set(_IMPORT_PREFIX \"/usr\")|set(_IMPORT_PREFIX \"${sdk_root}/usr\")|" \
    "${calamares_export}"

if find "${module_dir}" -type f -print0 | xargs -0 grep -Il $'\r' | grep -q .; then
    printf 'CRLF bytes found in DarkOS Calamares module sources\n' >&2
    exit 1
fi

source_archive="${package_root}/${MODULE_NAME}-${MODULE_VERSION}.tar.gz"
tar --sort=name --owner=0 --group=0 --numeric-owner \
    -czf "${source_archive}" -C "${module_dir}/.." "${MODULE_NAME}"
source_sha="$(sha256sum "${source_archive}" | awk '{print $1}')"

cat > "${package_root}/PKGBUILD" <<PKGBUILD
pkgname=${MODULE_PACKAGE}
pkgver=${MODULE_VERSION}
pkgrel=${MODULE_PKGREL}
pkgdesc='DarkOS optional API-key page for Calamares'
arch=('x86_64')
license=('GPL-3.0-or-later')
depends=('calamares=${CALAMARES_VERSION}-${CALAMARES_PKGREL}')
makedepends=('cmake' 'extra-cmake-modules' 'kcoreaddons' 'ninja' 'qt6-base')
options=('!debug')
source=('${MODULE_NAME}-${MODULE_VERSION}.tar.gz')
sha256sums=('${source_sha}')

build() {
    cmake -S "\${srcdir}/${MODULE_NAME}" -B "\${srcdir}/build" -G Ninja \\
        -DCMAKE_BUILD_TYPE=Release \\
        -DCMAKE_INSTALL_PREFIX=/usr \\
        -DCMAKE_PREFIX_PATH="\${DARKOS_CALAMARES_SDK:?}"
    cmake --build "\${srcdir}/build" --verbose
}

package() {
    DESTDIR="\${pkgdir}" cmake --install "\${srcdir}/build"
}
PKGBUILD

useradd --system --no-create-home --home-dir "${build_home}" --shell /bin/bash "${builder}"
builder_created=1
chown -R "${builder}:${builder}" "${work_root}"

printf 'Building %s %s-%s against Calamares %s-%s...\n' \
    "${MODULE_PACKAGE}" "${MODULE_VERSION}" "${MODULE_PKGREL}" \
    "${CALAMARES_VERSION}" "${CALAMARES_PKGREL}"
runuser --user "${builder}" -- env \
    HOME="${build_home}" \
    TMPDIR="${build_tmp}" \
    DARKOS_CALAMARES_SDK="${sdk_root}/usr" \
    bash -c 'cd -- "$1" && exec makepkg --nodeps --noconfirm --cleanbuild --clean --nocheck' \
    bash "${package_root}"

mapfile -d '' -t module_candidates < <(
    find "${package_root}" -maxdepth 1 -type f \
        -name "${MODULE_PACKAGE}-*.pkg.tar*" ! -name '*.sig' -print0
)
module_archives=()
for candidate in "${module_candidates[@]}"; do
    read -r candidate_name candidate_version < <(pacman -Qp "${candidate}")
    if [[ "${candidate_name}" == "${MODULE_PACKAGE}" ]]; then
        module_archives+=("${candidate}")
    fi
done
if [[ "${#module_archives[@]}" -ne 1 ]]; then
    printf 'Expected exactly one %s package, found %s\n' \
        "${MODULE_PACKAGE}" "${#module_archives[@]}" >&2
    exit 1
fi
module_archive="${module_archives[0]}"
read -r built_name built_version < <(pacman -Qp "${module_archive}")
[[ "${built_name}" == "${MODULE_PACKAGE}" \
    && "${built_version}" == "${MODULE_VERSION}-${MODULE_PKGREL}" ]] || {
    printf 'Unexpected module package identity: %s %s\n' \
        "${built_name:-<missing>}" "${built_version:-<missing>}" >&2
    exit 1
}

plugin_dir="usr/lib/calamares/modules/${MODULE_NAME}"
for relative in \
    "${plugin_dir}/module.desc" \
    "${plugin_dir}/libcalamares_viewmodule_${MODULE_NAME}.so"; do
    bsdtar -tf "${module_archive}" | grep -Fxq "${relative}" || {
        printf 'Module package is missing /%s\n' "${relative}" >&2
        exit 1
    }
done

validation_root="${work_root}/validation"
mkdir -p "${validation_root}"
bsdtar -xf "${module_archive}" -C "${validation_root}" \
    "${plugin_dir}/module.desc" \
    "${plugin_dir}/libcalamares_viewmodule_${MODULE_NAME}.so"
plugin_file="${validation_root}/${plugin_dir}/libcalamares_viewmodule_${MODULE_NAME}.so"
descriptor_file="${validation_root}/${plugin_dir}/module.desc"
[[ -x "${plugin_file}" ]] || {
    printf 'Built Calamares module is not executable\n' >&2
    exit 1
}
dynamic_section="$(readelf -d "${plugin_file}")"
if grep -Eq '\((RPATH|RUNPATH)\)' <<< "${dynamic_section}"; then
    printf 'Built Calamares module retained a build-time library search path\n' >&2
    exit 1
fi
for soname in libcalamaresui.so.3.4 libcalamares.so.3.4; do
    grep -Fq "Shared library: [${soname}]" <<< "${dynamic_section}" || {
        printf 'Built Calamares module is missing dependency %s\n' "${soname}" >&2
        exit 1
    }
done
for descriptor_line in \
    'type: "viewmodule"' \
    'name: "darkosapikeys"' \
    'interface: "qtplugin"' \
    'load: "libcalamares_viewmodule_darkosapikeys.so"' \
    'noconfig: true'; do
    grep -Fxq "${descriptor_line}" "${descriptor_file}" || {
        printf 'Built Calamares descriptor is missing: %s\n' "${descriptor_line}" >&2
        exit 1
    }
done

install -m 0644 "${module_archive}" "${repo_dir}/"
repo-add "${repo_dir}/${REPO_NAME}.db.tar.gz" \
    "${repo_dir}/$(basename "${module_archive}")"
printf '%s  %s\n' "$(sha256sum "${module_archive}" | awk '{print $1}')" \
    "${repo_dir}/$(basename "${module_archive}")"
printf '%s %s-%s is available in %s\n' \
    "${MODULE_PACKAGE}" "${MODULE_VERSION}" "${MODULE_PKGREL}" "${repo_dir}"
