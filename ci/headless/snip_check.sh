#!/bin/bash
# Real `darkos-window-fx.py --snip-screen` / `--snip` against a headless compositor:
# real grim, real wl-copy/wl-paste. Only the interactive region picker (slurp) is
# replaced by a shim, because it needs a pointer. Run through run-all.sh, or
# inside a session started with lib.sh.
set -u
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
FX="$DARKOS_BIN/darkos-window-fx.py"
SHOTS="$HOME/Pictures/Screenshots"
WORK=$(mktemp -d); trap 'kill ${GRAD:-0} 2>/dev/null; rm -rf "$WORK"' EXIT
fails=0
ok()  { echo "  PASS $1"; }
bad() { echo "  FAIL $1"; fails=$((fails + 1)); }

# slurp shims: pick 100,100 400x300 / user presses Esc / hostile output
mkdir -p "$WORK/ok" "$WORK/cancel" "$WORK/bad"
printf '#!/bin/sh\necho "100,100 400x300"\n' > "$WORK/ok/slurp"
printf '#!/bin/sh\nexit 1\n' > "$WORK/cancel/slurp"
printf '#!/bin/sh\necho "0,0 10x10; touch %s/PWNED"\n' "$WORK" > "$WORK/bad/slurp"
chmod +x "$WORK"/*/slurp

# A full-screen gradient, so a wrong crop offset would show up in the pixels.
cat > "$WORK/gradient.py" <<'PY'
import gi; gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
import cairo
w = Gtk.Window(); w.fullscreen(); da = Gtk.DrawingArea(); w.add(da)
def draw(widget, cr):
    a = widget.get_allocation(); g = cairo.LinearGradient(0, 0, a.width, a.height)
    g.add_color_stop_rgb(0, .9, .1, .1); g.add_color_stop_rgb(.5, .1, .8, .2); g.add_color_stop_rgb(1, .1, .2, .9)
    cr.set_source(g); cr.paint()
da.connect("draw", draw); w.show_all(); Gtk.main()
PY
python3 "$WORK/gradient.py" >/dev/null 2>&1 & GRAD=$!
sleep 2.5

echo "== full screen: --snip-screen"
python3 "$FX" --snip-screen; rc=$?
[ $rc -eq 0 ] && ok "exit 0" || bad "exit $rc"
FULL=$(ls "$SHOTS"/*.png 2>/dev/null | head -1)
[ -n "$FULL" ] && ok "saved as ~/Pictures/Screenshots/$(basename "$FULL")" || bad "nothing saved"
python3 -c "from PIL import Image; assert Image.open('$FULL').size == (1920, 1080)" && ok "PNG is 1920x1080" || bad "wrong size"
sleep 0.5
wl-paste --list-types 2>/dev/null | grep -qx image/png && ok "clipboard offers image/png" || bad "clipboard has no image/png"
wl-paste --type image/png 2>/dev/null | cmp -s - "$FULL" && ok "clipboard bytes == saved file" || bad "clipboard differs from the file"

sleep 1.2  # filenames have one-second resolution
echo "== region (picker says 100,100 400x300)"
PATH="$WORK/ok:$PATH" python3 "$FX" --snip; rc=$?
[ $rc -eq 0 ] && ok "exit 0" || bad "exit $rc"
REG=$(ls -t "$SHOTS"/*.png | head -1)
python3 - "$FULL" "$REG" <<'PY' && ok "400x300, pixel-identical to that crop of the full capture" || bad "region does not match the crop"
import sys
from PIL import Image, ImageChops
full, reg = (Image.open(p).convert("RGB") for p in sys.argv[1:3])
assert reg.size == (400, 300), reg.size
assert ImageChops.difference(full.crop((100, 100, 500, 400)), reg).getbbox() is None
PY

echo "== user cancels the selection"
count=$(ls "$SHOTS" | wc -l)
PATH="$WORK/cancel:$PATH" python3 "$FX" --snip; rc=$?
[ $rc -eq 0 ] && ok "cancelling is not an error" || bad "exit $rc"
[ "$(ls "$SHOTS" | wc -l)" -eq "$count" ] && ok "no file created" || bad "a file was created"

echo "== hostile selector output"
PATH="$WORK/bad:$PATH" python3 "$FX" --snip; rc=$?
[ $rc -eq 1 ] && ok "rejected" || bad "exit $rc"
[ ! -e "$WORK/PWNED" ] && ok "injected command did not run" || bad "INJECTED COMMAND RAN"
[ "$(ls "$SHOTS" | wc -l)" -eq "$count" ] && ok "no file created" || bad "a file was created"

echo "== timing: key binds capture at once, the search box asks for a delay"
sleep 1.2
python3 - "$FX" <<'PY' && ok "--delay 1 waits about a second longer than a plain capture" || bad "--delay did not delay"
import subprocess, sys, time
fx = sys.argv[1]
def took(*extra):
    start = time.monotonic()
    subprocess.run([sys.executable, fx, "--snip-screen", *extra], check=True)
    return time.monotonic() - start
plain, delayed = took(), took("--delay", "1")
print(f"   plain {plain:.2f}s, with --delay 1: {delayed:.2f}s")
assert delayed - plain >= 0.8, (plain, delayed)
PY

echo "snip check: $fails failure(s)"
exit $fails
