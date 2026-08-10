#!/usr/bin/env bash
# Build the pinned AUR Calamares package and expose it through a local pacman
# repository.  Arch no longer ships Calamares in the official repositories,
# and relying on a third-party binary repository made the ISO build fail as
# soon as that repository dropped the package.  This script intentionally
# fails closed: the AUR revision, package version, and source checksum are all
# pinned and verified before makepkg is allowed to run.

set -Eeuo pipefail

readonly AUR_URL="https://aur.archlinux.org/calamares.git"
readonly AUR_COMMIT="167151beb537c06cb75c8dbfd409799ba308bb66"
readonly CALAMARES_VERSION="3.4.2"
readonly CALAMARES_PKGREL="2"
readonly CALAMARES_SOURCE_SHA256="733bbbb00dc9f84874bd5c22960952f317ea2537565431179fa2152b2fbfdccc"
readonly CALAMARES_SOURCE_URL="https://codeberg.org/Calamares/calamares/releases/download/v${CALAMARES_VERSION}/calamares-${CALAMARES_VERSION}.tar.gz"
readonly REPO_NAME="darkos-local"

repo_dir="${1:-/tmp/darkos-calamares-repo}"
if [[ "${EUID}" -ne 0 ]]; then
    printf 'build-calamares.sh must run as root (it creates an isolated build user)\n' >&2
    exit 1
fi

for command in bash chown curl find git grep head install makepkg mkdir mktemp \
    pacman repo-add rm runuser sha256sum sed useradd userdel; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "${command}" >&2
        exit 1
    fi
done

verify_package_identity() {
    local package="$1"
    local package_name package_version
    read -r package_name package_version < <(pacman -Qp "${package}")
    [[ "${package_name}" == calamares && "${package_version}" == "${CALAMARES_VERSION}-${CALAMARES_PKGREL}" ]] || {
        printf 'Unexpected built package identity: %s %s\n' \
            "${package_name:-<missing>}" "${package_version:-<missing>}" >&2
        return 1
    }
}

publish_local_repo() {
    local package="$1"
    install -d -m 0755 "${repo_dir}"
    # Remove only artifacts owned by this dedicated local repository.
    find "${repo_dir}" -maxdepth 1 -type f \
        \( -name '*.pkg.tar*' -o -name "${REPO_NAME}.db*" -o -name "${REPO_NAME}.files*" \) -delete
    install -m 0644 "${package}" "${repo_dir}/"
    repo-add "${repo_dir}/${REPO_NAME}.db.tar.gz" "${repo_dir}/$(basename "${package}")"
}

# A caller may reuse a package produced by an earlier verified run. Reuse is
# opt-in and requires the caller to provide its SHA-256, so a stale or modified
# cache cannot silently bypass the pinned-source build.
if [[ -n "${DARKOS_CALAMARES_PACKAGE:-}" ]]; then
    [[ -s "${DARKOS_CALAMARES_PACKAGE}" ]] || {
        printf 'Cached Calamares package is missing: %s\n' "${DARKOS_CALAMARES_PACKAGE}" >&2
        exit 1
    }
    [[ "${DARKOS_CALAMARES_PACKAGE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || {
        printf 'DARKOS_CALAMARES_PACKAGE_SHA256 must contain 64 lowercase hex characters.\n' >&2
        exit 1
    }
    printf '%s  %s\n' "${DARKOS_CALAMARES_PACKAGE_SHA256}" "${DARKOS_CALAMARES_PACKAGE}" \
        | sha256sum --check --strict -
    verify_package_identity "${DARKOS_CALAMARES_PACKAGE}"
    publish_local_repo "${DARKOS_CALAMARES_PACKAGE}"
    printf 'Reused verified Calamares %s-%s package at %s\n' \
        "${CALAMARES_VERSION}" "${CALAMARES_PKGREL}" "${DARKOS_CALAMARES_PACKAGE}"
    exit 0
fi

# Install every dependency declared by the pinned recipe while we still have a
# real root filesystem.  Running makepkg with --syncdeps as the unprivileged
# builder would require an interactive sudo setup; installing this fixed list
# here keeps the CI job non-interactive and makes missing package names fail
# before compilation starts.
readonly BUILD_DEPENDENCIES=(
    base-devel
    cmake
    extra-cmake-modules
    libglvnd
    ninja
    qt6-tools
    qt6-translations
    kcoreaddons
    kpmcore
    libpwquality
    python
    qt6-declarative
    qt6-svg
    yaml-cpp
)
pacman -S --needed --noconfirm "${BUILD_DEPENDENCIES[@]}"

work_root="$(mktemp -d /tmp/darkos-calamares-build.XXXXXX)"
builder="darkos-pkgbuild-$$"
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
aur_dir="${work_root}/calamares"
srcdest="${work_root}/srcdest"
build_home="${work_root}/home"
build_tmp="${work_root}/tmp"
mkdir -p "${srcdest}" "${build_home}" "${build_tmp}"

printf 'Fetching Calamares AUR revision %s...\n' "${AUR_COMMIT}"
git clone --filter=blob:none --no-checkout "${AUR_URL}" "${aur_dir}"
git -C "${aur_dir}" fetch --depth=1 origin "${AUR_COMMIT}"
git -C "${aur_dir}" checkout --detach "${AUR_COMMIT}"

pkgbuild="${aur_dir}/PKGBUILD"
[[ -s "${pkgbuild}" ]] || { printf 'AUR checkout did not contain PKGBUILD\n' >&2; exit 1; }

pkgver="$(sed -nE 's/^pkgver=([^[:space:]]+).*$/\1/p' "${pkgbuild}" | head -n1)"
pkgrel="$(sed -nE 's/^pkgrel=([^[:space:]]+).*$/\1/p' "${pkgbuild}" | head -n1)"
[[ "${pkgver}" == "${CALAMARES_VERSION}" ]] || {
    printf 'Unexpected Calamares pkgver: %s (expected %s)\n' "${pkgver}" "${CALAMARES_VERSION}" >&2
    exit 1
}
[[ "${pkgrel}" == "${CALAMARES_PKGREL}" ]] || {
    printf 'Unexpected Calamares pkgrel: %s (expected %s)\n' "${pkgrel}" "${CALAMARES_PKGREL}" >&2
    exit 1
}
pkgbuild_sha="$(sed -nE "s/^sha256sums=\('[[:space:]]*([0-9a-f]{64})'[[:space:]]*\).*$/\1/p" "${pkgbuild}" | head -n1)"
[[ "${pkgbuild_sha}" == "${CALAMARES_SOURCE_SHA256}" ]] || {
    printf 'Unexpected source checksum in AUR PKGBUILD: %s (expected %s)\n' \
        "${pkgbuild_sha:-<missing>}" "${CALAMARES_SOURCE_SHA256}" >&2
    exit 1
}
# shellcheck disable=SC2016 # Match literal variables in the pinned URL template.
if ! grep -Fxq 'url="https://codeberg.org/Calamares/calamares"' "${pkgbuild}" \
    || ! grep -Fq 'releases/download/v$pkgver/$_pkgname-$pkgver.$_pkgext' "${pkgbuild}"; then
    printf 'Unexpected source URL in the AUR PKGBUILD\n' >&2
    exit 1
fi

# Download and verify the release archive ourselves.  makepkg will verify it
# again, but doing this before the build makes a changed/malicious AUR recipe
# fail explicitly instead of silently selecting a different source artifact.
source_archive="${srcdest}/calamares-${CALAMARES_VERSION}.tar.gz"
curl --fail --location --retry 3 --retry-delay 2 --retry-all-errors --silent --show-error \
    --output "${source_archive}" "${CALAMARES_SOURCE_URL}"
printf '%s  %s\n' "${CALAMARES_SOURCE_SHA256}" "${source_archive}" | sha256sum --check --strict -

# makepkg refuses to run as root. Use a per-run unprivileged account and a
# private HOME/SRCDEST so neither package files nor an account leak from a
# successful or failed local build.
useradd --system --create-home --home-dir "${build_home}" --shell /bin/bash "${builder}"
builder_created=1
chown -R "${builder}:${builder}" "${work_root}"

# shellcheck disable=SC2016 # $1 is expanded by the child Bash, not this one.
runuser --user "${builder}" -- env HOME="${build_home}" SRCDEST="${srcdest}" \
    TMPDIR="${build_tmp}" \
    bash -c 'cd -- "$1" && exec makepkg --noconfirm --cleanbuild --clean --nocheck' \
    bash "${aur_dir}"

mapfile -t package_archives < <(
    find "${aur_dir}" -maxdepth 1 -type f -name "calamares-*.pkg.tar*" ! -name '*.sig' -print
)
main_packages=()
for archive in "${package_archives[@]}"; do
    read -r archive_name _archive_version < <(pacman -Qp "${archive}")
    if [[ "${archive_name}" == calamares ]]; then
        main_packages+=("${archive}")
    fi
done
if [[ "${#main_packages[@]}" -ne 1 ]]; then
    printf 'Expected exactly one main Calamares package, found %s\n' "${#main_packages[@]}" >&2
    printf 'Build directory contents:\n' >&2
    find "${aur_dir}" -maxdepth 1 -type f -printf '  %f\n' >&2
    exit 1
fi
built_package="${main_packages[0]}"

verify_package_identity "${built_package}"
publish_local_repo "${built_package}"

printf 'Calamares %s-%s package and %s pacman repository are ready at %s\n' \
    "${CALAMARES_VERSION}" "${CALAMARES_PKGREL}" "${REPO_NAME}" "${repo_dir}"
