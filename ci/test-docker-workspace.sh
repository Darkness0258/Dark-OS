#!/usr/bin/env bash
# Safe fixture-only regression for Windows bind-mount staging/publication.
set -Eeuo pipefail
ci_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$ci_dir/docker-build-iso.sh"
fixture=$(mktemp -d /tmp/darkos-docker-test.XXXXXX)
trap 'rm -rf -- "$fixture"' EXIT
mkdir -p "$fixture/source/.git" "$fixture/source/out" \
    "$fixture/source/airootfs/usr/local/bin" "$fixture/staged" "$fixture/published"
printf 'private git metadata\n' > "$fixture/source/.git/test"
printf 'old image\n' > "$fixture/source/out/old.iso"
printf '#!/bin/bash\nexit 0\n' > "$fixture/source/airootfs/usr/local/bin/darkos-test"
chmod 0777 "$fixture/source/airootfs/usr/local/bin/darkos-test"
darkos_stage_docker_source "$fixture/source" "$fixture/staged"
[[ ! -e "$fixture/staged/.git" && ! -e "$fixture/staged/out" ]]
cmp "$fixture/source/airootfs/usr/local/bin/darkos-test" "$fixture/staged/airootfs/usr/local/bin/darkos-test"
chmod 0755 "$fixture/staged/airootfs/usr/local/bin/darkos-test"
[[ "$(stat -c '%a' "$fixture/staged/airootfs/usr/local/bin/darkos-test")" == 755 ]]
printf 'verified fixture image\n' > "$fixture/staged/darkos.iso"
darkos_publish_docker_iso "$fixture/staged/darkos.iso" "$fixture/published"
cmp "$fixture/staged/darkos.iso" "$fixture/published/darkos.iso"
if darkos_publish_docker_iso "$fixture/staged/missing.iso" "$fixture/published" 2>/dev/null; then
    printf 'Missing source image was published\n' >&2
    exit 1
fi
[[ ! -e "$fixture/published/missing.iso" ]]
cmp "$fixture/staged/darkos.iso" "$fixture/published/darkos.iso"
[[ -z "$(find "$fixture/published" -name '.darkos-iso.*' -print)" ]]
printf 'Docker workspace staging and publication checks passed.\n'
