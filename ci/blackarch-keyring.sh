#!/usr/bin/env bash
# Reviewed BlackArch trust anchor shared by GitHub Actions and the local
# Docker builder. Update all three values together only after independently
# validating the new archive's provenance and SHA-256.

readonly BLACKARCH_KEYRING_VERSION="20251011"
readonly BLACKARCH_KEYRING_ARCHIVE="blackarch-keyring-${BLACKARCH_KEYRING_VERSION}.tar.gz"
readonly BLACKARCH_KEYRING_SHA256="e4934a37b018dda1df6403147c11c3e8efdc543419f10be485c7836e19f3cfbe"

# Replace only the two repositories managed by this bootstrap. Repeated runs
# preserve unrelated host settings without duplicating sections or retaining
# stale mirror/signature overrides from a previous bootstrap.
darkos_configure_build_repositories() (
  set -Eeuo pipefail
  local pacman_config="${1:-/etc/pacman.conf}"
  local mirror_dir="${2:-/etc/pacman.d}"
  local staged_config
  staged_config="$(mktemp "${pacman_config}.darkos.XXXXXX")"
  trap 'rm -f -- "$staged_config"' EXIT
  awk '
    /^[[:space:]]*\[/ {
      section = $0
      sub(/^[[:space:]]*\[/, "", section)
      sub(/\].*$/, "", section)
      skip = (section == "chaotic-aur" || section == "blackarch")
    }
    !skip && !/^[[:space:]]*NoConfirm[[:space:]]*($|#)/ { lines[++count] = $0 }
    END {
      while (count > 0 && lines[count] ~ /^[[:space:]]*$/) count--
      for (i = 1; i <= count; i++) print lines[i]
    }
  ' "$pacman_config" > "$staged_config"
  printf '\n[chaotic-aur]\nSigLevel = Required DatabaseOptional TrustedOnly\nInclude = %s/chaotic-mirrorlist\n\n[blackarch]\nSigLevel = Required DatabaseOptional TrustedOnly\nInclude = %s/blackarch-mirrorlist\n' \
    "$mirror_dir" "$mirror_dir" >> "$staged_config"
  chmod --reference="$pacman_config" "$staged_config"
  mv -f -- "$staged_config" "$pacman_config"
)

darkos_download_signed_chaotic() {
  local package="$1" destination="$2" mirror
  for mirror in https://cdn-mirror.chaotic.cx/chaotic-aur https://geo-mirror.chaotic.cx/chaotic-aur; do
    if curl --fail --location --retry 3 --retry-all-errors --connect-timeout 15 --max-time 90 \
         --output "$destination" "$mirror/$package" \
      && curl --fail --location --retry 3 --retry-all-errors --connect-timeout 15 --max-time 90 \
         --output "$destination.sig" "$mirror/$package.sig" \
      && pacman-key --verify "$destination.sig" "$destination"; then
      return 0
    fi
  done
  printf 'Could not download and verify Chaotic-AUR package: %s\n' "$package" >&2
  return 1
}

darkos_install_bootstrap_package() {
  local expected="$1" archive="$2" identity name version installed comparison
  identity=$(pacman -Qp "$archive") || return "$?"
  read -r name version <<< "$identity"
  if [[ "$name" != "$expected" || -z "$version" ]]; then
    printf 'Unexpected bootstrap package identity: %s\n' "$identity" >&2
    return 1
  fi
  if installed=$(pacman -Q "$expected" 2>/dev/null); then
    installed="${installed#* }"
    comparison=$(vercmp "$installed" "$version") || return "$?"
    if (( comparison >= 0 )); then
      printf 'Keeping installed %s %s (bootstrap offers %s).\n' "$expected" "$installed" "$version"
      return 0
    fi
  fi
  pacman -U --needed --noconfirm "$archive"
}

darkos_sync_build_repositories() {
  local sync_dir="${1:-/var/lib/pacman/sync}" attempt
  for attempt in 1 2 3; do
    if pacman -Syy --noconfirm \
      && test -s "$sync_dir/blackarch.db" \
      && test -s "$sync_dir/chaotic-aur.db"; then
      return 0
    fi
  done
  printf 'Could not synchronize the BlackArch and Chaotic-AUR repositories.\n' >&2
  return 1
}

# Shared by both isolated build environments. No downloaded bootstrap script
# is executed; the BlackArch keyring is hash-pinned and Chaotic packages must
# have a valid detached signature before pacman sees a local package path.
darkos_seed_build_repositories() (
  set -Eeuo pipefail
  local bootstrap_dir package attempt
  bootstrap_dir="$(mktemp -d /tmp/darkos-keyrings.XXXXXX)"
  trap 'rm -f -- "$bootstrap_dir/$BLACKARCH_KEYRING_ARCHIVE" "$bootstrap_dir/chaotic-keyring.pkg.tar.zst" "$bootstrap_dir/chaotic-keyring.pkg.tar.zst.sig" "$bootstrap_dir/chaotic-mirrorlist.pkg.tar.zst" "$bootstrap_dir/chaotic-mirrorlist.pkg.tar.zst.sig"; rmdir -- "$bootstrap_dir"' EXIT
  export TERM=xterm
  mkdir -p /etc/pacman.d /usr/share/pacman/keyrings
  pacman-key --init
  pacman-key --populate archlinux
  for attempt in 1 2 3; do
    if pacman-key --recv-key 3056513887B78AEB --keyserver keyserver.ubuntu.com; then
      break
    fi
    if [ "$attempt" -eq 3 ]; then
      printf 'Could not import the Chaotic-AUR signing key.\n' >&2
      exit 1
    fi
  done
  pacman-key --lsign-key 3056513887B78AEB
  for package in chaotic-keyring.pkg.tar.zst chaotic-mirrorlist.pkg.tar.zst; do
    darkos_download_signed_chaotic "$package" "$bootstrap_dir/$package"
    darkos_install_bootstrap_package "${package%.pkg.tar.zst}" "$bootstrap_dir/$package"
    if [[ "$package" == chaotic-keyring.pkg.tar.zst ]]; then
      # --needed skips package hooks if the keyring is already installed.
      # Populate explicitly so a rebuilt trust database still gets its keys.
      pacman-key --populate chaotic
    fi
  done

  curl --fail --location --retry 3 --retry-all-errors --connect-timeout 15 --max-time 90 \
    --output "$bootstrap_dir/$BLACKARCH_KEYRING_ARCHIVE" \
    "https://www.blackarch.org/keyring/$BLACKARCH_KEYRING_ARCHIVE"
  printf '%s  %s\n' "$BLACKARCH_KEYRING_SHA256" "$bootstrap_dir/$BLACKARCH_KEYRING_ARCHIVE" \
    | sha256sum --check --strict -
  tar -xzf "$bootstrap_dir/$BLACKARCH_KEYRING_ARCHIVE" --strip-components=1 \
    -C /usr/share/pacman/keyrings
  pacman-key --populate blackarch
  printf '%s\n' 'Server = https://blackarch.org/blackarch/$repo/os/$arch' \
    > /etc/pacman.d/blackarch-mirrorlist
  darkos_configure_build_repositories
  darkos_sync_build_repositories
)
