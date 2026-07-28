#!/usr/bin/env bash

set -e

echo "Building DarkOS ISO image..."
mkdir -p /tmp/archiso-tmp out
mkarchiso -v -w /tmp/archiso-tmp -o out .
echo "Build complete. Output written to out/"
