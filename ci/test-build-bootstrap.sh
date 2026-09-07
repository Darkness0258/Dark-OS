#!/usr/bin/env bash
# Run with Git Bash or Linux Bash. All network/package commands are mocked;
# the only files changed are fixtures in a fresh temporary directory.
set -Eeuo pipefail

ci_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$ci_dir/blackarch-keyring.sh"
fixture_dir="$(mktemp -d)"
trap 'rm -f -- "$fixture_dir/pacman.conf" "$fixture_dir/pacman.first.conf" "$fixture_dir/blackarch.db" "$fixture_dir/chaotic-aur.db"; rmdir -- "$fixture_dir"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

printf '%s\n' '[options]' 'SigLevel = Required DatabaseOptional' 'NoConfirm' \
  '[core]' 'Include = /etc/pacman.d/mirrorlist' \
  '[chaotic-aur]' 'Server = https://stale.invalid' \
  '[extra]' 'Include = /etc/pacman.d/mirrorlist' \
  '[blackarch]' 'SigLevel = Never' \
  '[blackarch]' 'Server = https://duplicate.invalid' > "$fixture_dir/pacman.conf"
darkos_configure_build_repositories "$fixture_dir/pacman.conf" /fixture/mirrors
cp "$fixture_dir/pacman.conf" "$fixture_dir/pacman.first.conf"
darkos_configure_build_repositories "$fixture_dir/pacman.conf" /fixture/mirrors
cmp -s "$fixture_dir/pacman.conf" "$fixture_dir/pacman.first.conf" \
  || fail 'repeated configuration must be byte-for-byte idempotent'
for repository in chaotic-aur blackarch core extra; do
  [[ "$(grep -cFx "[$repository]" "$fixture_dir/pacman.conf")" == 1 ]] \
    || fail "repository missing or duplicated: $repository"
done
[[ "$(grep -cFx 'SigLevel = Required DatabaseOptional TrustedOnly' "$fixture_dir/pacman.conf")" == 2 ]] \
  || fail 'both third-party repositories must require trusted package signatures'
if grep -Eq 'NoConfirm|stale\.invalid|duplicate\.invalid|SigLevel = Never' "$fixture_dir/pacman.conf"; then
  fail 'stale bootstrap configuration was retained'
fi
grep -qFx 'Include = /fixture/mirrors/blackarch-mirrorlist' "$fixture_dir/pacman.conf" \
  || fail 'BlackArch mirrorlist must be registered before synchronization'

curl_calls=0
verification_calls=0
download_status=0
signature_status=0
curl() { curl_calls=$((curl_calls + 1)); return "$download_status"; }
pacman-key() {
  [[ "$1" == --verify ]] || fail 'test attempted to modify a real keyring'
  verification_calls=$((verification_calls + 1))
  return "$signature_status"
}

darkos_download_signed_chaotic example.pkg.tar.zst /fixture/example.pkg.tar.zst
[[ "$curl_calls" == 2 && "$verification_calls" == 1 ]] \
  || fail 'package and detached signature must both download and verify'
signature_status=1
curl_calls=0
verification_calls=0
if darkos_download_signed_chaotic example.pkg.tar.zst /fixture/example.pkg.tar.zst 2>/dev/null; then
  fail 'invalid signatures must fail closed'
fi
[[ "$curl_calls" == 4 && "$verification_calls" == 2 ]] \
  || fail 'signature failure must exhaust both mirrors then stop'
download_status=1
verification_calls=0
if darkos_download_signed_chaotic example.pkg.tar.zst /fixture/example.pkg.tar.zst 2>/dev/null; then
  fail 'failed downloads must not be accepted'
fi
[[ "$verification_calls" == 0 ]] || fail 'failed download must not verify stale files'

installed_version=2
installed_name=chaotic-keyring
install_calls=0
pacman() {
  case "$1" in
    -Qp) printf '%s 1\n' "$installed_name" ;;
    -Q) printf 'chaotic-keyring %s\n' "$installed_version" ;;
    -U) install_calls=$((install_calls + 1)) ;;
    *) fail 'unexpected bootstrap identity command' ;;
  esac
}
darkos_install_bootstrap_package chaotic-keyring /fixture/keyring.pkg.tar.zst
[[ "$install_calls" == 0 ]] || fail 'bootstrap downgraded a newer installed keyring'
installed_version=0
darkos_install_bootstrap_package chaotic-keyring /fixture/keyring.pkg.tar.zst
[[ "$install_calls" == 1 ]] || fail 'bootstrap did not install a newer verified keyring'
installed_name=unrelated-package
if darkos_install_bootstrap_package chaotic-keyring /fixture/keyring.pkg.tar.zst 2>/dev/null; then
  fail 'bootstrap accepted an unrelated signed package'
fi

sync_calls=0
sync_success_after=1
pacman() {
  [[ "$*" == '-Syy --noconfirm' ]] || fail 'test attempted a package transaction'
  sync_calls=$((sync_calls + 1))
  [[ "$sync_calls" -ge "$sync_success_after" ]]
}
if darkos_sync_build_repositories "$fixture_dir" 2>/dev/null; then
  fail 'sync must fail if repository databases are missing'
fi
[[ "$sync_calls" == 3 ]] || fail 'failed sync must stop after three attempts'
printf 'fixture\n' > "$fixture_dir/blackarch.db"
printf 'fixture\n' > "$fixture_dir/chaotic-aur.db"
sync_calls=0
sync_success_after=4
if darkos_sync_build_repositories "$fixture_dir" 2>/dev/null; then
  fail 'stale databases must not hide a failed synchronization'
fi
sync_calls=0
sync_success_after=2
darkos_sync_build_repositories "$fixture_dir"
[[ "$sync_calls" == 2 ]] || fail 'successful retry must stop immediately'

docker() { return 37; }
export -f docker
if bash "$ci_dir/rebuild.sh"; then
  fail 'rebuild must propagate Docker failure'
else
  [[ "$?" == 37 ]] || fail 'rebuild changed the Docker exit status'
fi
printf 'Build bootstrap regression checks passed.\n'
