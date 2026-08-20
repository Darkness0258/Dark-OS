#!/usr/bin/env bash
set -Eeuo pipefail

cd /workspace

printf '==> Initializing pacman keys...\n'
export TERM=xterm
mkdir -p /etc/pacman.d
pacman-key --init
pacman-key --populate archlinux

printf '==> Installing ISO and AUR build dependencies...\n'
pacman -Sy --noconfirm archlinux-keyring || true
pacman -Syu --needed --noconfirm archiso base-devel curl desktop-file-utils git mkinitcpio pacman-contrib python python-yaml squashfs-tools dosfstools efibootmgr grub libisoburn mtools pv rsync

printf '==> Seeding Chaotic-AUR and BlackArch mirrorlists and keyrings...\n'
for attempt in 1 2 3; do
  pacman-key --recv-key 3056513887B78AEB --keyserver keyserver.ubuntu.com && break
  if [ "$attempt" -eq 3 ]; then exit 1; fi
done
pacman-key --lsign-key 3056513887B78AEB

download_chaotic() {
  local pkg="$1"
  for url in "https://cdn-mirror.chaotic.cx/chaotic-aur/${pkg}" "https://geo-mirror.chaotic.cx/chaotic-aur/${pkg}"; do
    if curl --fail --location --retry 5 --retry-connrefused --retry-delay 2 --connect-timeout 15 -m 60 --output "/tmp/${pkg}" "${url}"; then
      return 0
    fi
  done
  return 1
}

download_chaotic "chaotic-keyring.pkg.tar.zst"
pacman -U --needed --noconfirm "/tmp/chaotic-keyring.pkg.tar.zst"

download_chaotic "chaotic-mirrorlist.pkg.tar.zst"
pacman -U --needed --noconfirm "/tmp/chaotic-mirrorlist.pkg.tar.zst"

printf '%s\n' 'Server = https://blackarch.org/blackarch/$repo/os/$arch' > /etc/pacman.d/blackarch-mirrorlist
curl --fail --location --retry 3 --retry-all-errors --output /tmp/strap.sh https://blackarch.org/strap.sh
chmod +x /tmp/strap.sh
(cd /tmp && ./strap.sh)

printf '%s\n' 'Server = https://blackarch.org/blackarch/$repo/os/$arch' > /etc/pacman.d/blackarch-mirrorlist
for attempt in 1 2 3; do
  pacman -Syy --noconfirm && test -s /var/lib/pacman/sync/blackarch.db && break
  if [ "$attempt" -eq 3 ]; then exit 1; fi
done

printf '==> Starting DarkOS ISO Build...\n'
git config --global --add safe.directory /workspace
export DARKOS_BUILD_SHA="$(git rev-parse HEAD)"
bash build-iso.sh
