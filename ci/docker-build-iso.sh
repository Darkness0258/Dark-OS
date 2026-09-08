#!/usr/bin/env bash
set -Eeuo pipefail

darkos_stage_docker_source() {
    local source_root="$1" build_root="$2"
    # Windows bind mounts expose synthetic 0777 modes and may ignore chmod.
    # Build on a Linux filesystem so exact payload modes remain enforceable.
    tar -C "$source_root" --exclude='./.git' --exclude='./out' \
        --exclude='./.claude' --exclude='__pycache__' -cf - . \
        | tar -C "$build_root" -xf -
}

darkos_publish_docker_iso() (
    set -Eeuo pipefail
    local source_iso="$1" output_dir="$2" pending
    pending=$(mktemp "$output_dir/.darkos-iso.XXXXXX")
    trap 'rm -f -- "$pending"' EXIT
    cp -- "$source_iso" "$pending" || exit "$?"
    cmp -s "$source_iso" "$pending" || exit "$?"
    chmod 0644 "$pending" || exit "$?"
    mv -f -- "$pending" "$output_dir/$(basename "$source_iso")"
)

main() (
    set -Eeuo pipefail
    cd /workspace
    export DARKOS_BUILD_SHA="${DARKOS_BUILD_SHA:-$(git -c safe.directory=/workspace rev-parse HEAD)}"
    local build_root
    build_root=$(mktemp -d /tmp/darkos-docker-source.XXXXXX)
    cleanup() {
        if [[ "${DARKOS_KEEP_WORK:-0}" == 1 ]]; then
            printf 'Preserving Linux source workspace: %s\n' "$build_root"
        else
            rm -rf -- "$build_root"
        fi
    }
    trap cleanup EXIT
    darkos_stage_docker_source /workspace "$build_root"
    cd "$build_root"
    source ci/blackarch-keyring.sh
    printf '==> Seeding Chaotic-AUR and BlackArch mirrorlists and keyrings...\n'
    darkos_seed_build_repositories
    printf '==> Starting DarkOS ISO Build in %s...\n' "$build_root"
    bash build-iso.sh

    # Publish only after build-iso.sh has passed its embedded-payload checks.
    # A failed copy never replaces the previous verified image on the host.
    [[ -s out/darkos.iso ]] || { printf 'Verified stable ISO is missing\n' >&2; exit 1; }
    mkdir -p /workspace/out
    for iso in out/darkos-*.iso out/darkos.iso; do
        [[ -s "$iso" ]] || { printf 'Verified ISO is missing: %s\n' "$iso" >&2; exit 1; }
        darkos_publish_docker_iso "$iso" /workspace/out
    done
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
