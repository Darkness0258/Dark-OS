#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Git Bash paths need conversion for the native Windows Docker CLI, while
# Linux hosts should retain their ordinary absolute path.
if command -v cygpath >/dev/null 2>&1; then
  project_dir="$(cygpath -m "$project_dir")"
fi
MSYS_NO_PATHCONV=1 docker run --rm --privileged \
  --mount "type=bind,source=$project_dir,target=/workspace" \
  darkos-builder
