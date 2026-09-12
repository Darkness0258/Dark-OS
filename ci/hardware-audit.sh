#!/usr/bin/env bash
# Run this ON the real machine, inside the live Hyprland session, once
# darkos-shell is up. Covers the mechanical half of the Step 1 audit --
# it can't judge whether motion "feels" right, but it can catch the class
# of bug this project has hit before: a surface that's defined and
# imported but never actually mapped (see progress-tracker.md).
#
# Usage: bash hardware-audit.sh   (no args, no root needed)

set -uo pipefail
fail=0

echo "== process =="
if pgrep -f "darkos-shell.py" > /dev/null; then
    echo "  ok: darkos-shell.py is running"
else
    echo "  FAIL: darkos-shell.py is not running -- nothing else below is meaningful"
    fail=1
fi

echo ""
echo "== layer-shell surfaces (hyprctl layers) =="
if ! command -v hyprctl > /dev/null; then
    echo "  skip: hyprctl not on PATH -- are you inside the real Hyprland session?"
else
    layers_out="$(hyprctl layers 2>&1)"
    for ns in darkos-dock darkos-hud darkos-rail darkos-left darkos-right; do
        if echo "$layers_out" | grep -q "$ns"; then
            echo "  ok: $ns is mapped"
        else
            echo "  FAIL: $ns not found in hyprctl layers -- defined in surfaces.py but not actually on screen"
            fail=1
        fi
    done
fi

echo ""
echo "== monitor / refresh rate (for the Step 2 performance check) =="
if command -v hyprctl > /dev/null; then
    hyprctl monitors | grep -E "Monitor|@ " | sed 's/^/  /'
else
    echo "  skip: hyprctl not available"
fi

echo ""
echo "== quick GTK warning capture =="
echo "  hyprctl can't show you what darkos-shell printed at launch (exec-once"
echo "  doesn't redirect it anywhere). To actually see GTK CSS/theme warnings"
echo "  for this session, kill the running instance and relaunch it capturing"
echo "  output, then work through the visual checklist against ui-rules.md:"
echo "    pkill -f darkos-shell.py"
echo "    python /usr/local/bin/darkos-shell.py 2>&1 | tee ~/darkos-shell.log"

echo ""
if [ "$fail" -eq 0 ]; then
    echo "== summary: mechanical checks passed. Now the part only eyes can do: =="
else
    echo "== summary: at least one mechanical check failed -- see FAIL lines above =="
fi
echo "  walk Command Center, dock, and every panel against ui-rules.md's Motion"
echo "  and Layout sections. Note anything that stutters, pops unexpectedly,"
echo "  or renders in the wrong color -- that's the punch list Step 1 wants."
