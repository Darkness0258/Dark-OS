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

for command in curl git makepkg repo-add runuser useradd sha256sum awk sed grep install; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "${command}" >&2
        exit 1
    fi
done

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
    qt6-declarative
    qt6-svg
    yaml-cpp
)
pacman -S --needed --noconfirm "${BUILD_DEPENDENCIES[@]}"

work_root="$(mktemp -d /tmp/darkos-calamares-build.XXXXXX)"
trap 'rm -rf -- "${work_root}"' EXIT
aur_dir="${work_root}/calamares"
srcdest="${work_root}/srcdest"
build_home="${work_root}/home"
mkdir -p "${srcdest}" "${build_home}"

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
grep -Fq "${CALAMARES_SOURCE_URL}" "${pkgbuild}" || {
    printf 'Pinned source URL is missing from the AUR PKGBUILD\n' >&2
    exit 1
}

# Download and verify the release archive ourselves.  makepkg will verify it
# again, but doing this before the build makes a changed/malicious AUR recipe
# fail explicitly instead of silently selecting a different source artifact.
source_archive="${srcdest}/calamares-${CALAMARES_VERSION}.tar.gz"
curl --fail --location --retry 3 --retry-delay 2 --silent --show-error \
    --output "${source_archive}" "${CALAMARES_SOURCE_URL}"
printf '%s  %s\n' "${CALAMARES_SOURCE_SHA256}" "${source_archive}" | sha256sum --check --strict -

# makepkg refuses to run as root.  Use a throw-away unprivileged account and a
# private HOME/SRCDEST so no package cache or build files leak into the image.
builder="darkos-pkgbuild"
if ! id "${builder}" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "${build_home}" --shell /bin/bash "${builder}"
else
    usermod --home "${build_home}" "${builder}"
fi
chown -R "${builder}:${builder}" "${work_root}"

runuser --user "${builder}" -- env HOME="${build_home}" SRCDEST="${srcdest}" \
    makepkg --noconfirm --cleanbuild --clean --nocheck "${pkgbuild}"

mapfile -t built_packages < <(find "${aur_dir}" -maxdepth 1 -type f -name "calamares-*.pkg.tar*" -print)
if [[ "${#built_packages[@]}" -ne 1 ]]; then
    printf 'Expected exactly one Calamares package, found %s\n' "${#built_packages[@]}" >&2
    printf 'Build directory contents:\n' >&2
    find "${aur_dir}" -maxdepth 1 -type f -printf '  %f\n' >&2
    exit 1
fi

install -d -m 0755 "${repo_dir}"
# The destination is a dedicated temporary directory in CI.  Remove only the
# files generated by this script so reruns cannot leave a stale package DB.
find "${repo_dir}" -maxdepth 1 -type f \( -name '*.pkg.tar*' -o -name "${REPO_NAME}.db*" -o -name "${REPO_NAME}.files*" \) -delete
install -m 0644 "${built_packages[0]}" "${repo_dir}/"
repo-add "${repo_dir}/${REPO_NAME}.db.tar.gz" "${repo_dir}/$(basename "${built_packages[0]}")"

printf 'Calamares %s-%s package and %s pacman repository are ready at %s\n' \
    "${CALAMARES_VERSION}" "${CALAMARES_PKGREL}" "${REPO_NAME}" "${repo_dir}"
