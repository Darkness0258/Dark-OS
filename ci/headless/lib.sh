# Source me (do not run). Helpers to run the DarkOS shell's GTK layer-shell code
# against a throwaway headless wlroots compositor (sway): no GPU, no display, no VM.
#
#   source ci/headless/lib.sh
#   headless_need sway grim || exit 1
#   headless_start 1920x1080 || exit 1
#   ... run things with WAYLAND_DISPLAY / SWAYSOCK set ...
#   headless_stop
#
# Needs: sway grim python-gobject gtk3 gtk-layer-shell (see README.md).

HEADLESS_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HEADLESS_DIR/../.." && pwd)
export DARKOS_BIN="$REPO/airootfs/usr/local/bin"

headless_need() {
  local missing=0 tool
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || { echo "missing tool: $tool" >&2; missing=1; }
  done
  return $missing
}

headless_start() {  # headless_start [WIDTHxHEIGHT]
  local res="${1:-1920x1080}"
  HEADLESS_TMP=$(mktemp -d)   # short path: Wayland socket paths are limited to ~100 chars
  export XDG_RUNTIME_DIR="$HEADLESS_TMP/run"
  mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
  printf 'output HEADLESS-1 resolution %s position 0 0\nxwayland disable\ndefault_border none\ndefault_floating_border none\ngaps inner 0\n' \
    "$res" > "$HEADLESS_TMP/sway.conf"
  WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=1 \
    setsid sway --unsupported-gpu -c "$HEADLESS_TMP/sway.conf" >"$HEADLESS_TMP/sway.log" 2>&1 &
  SWAY_PID=$!
  local _
  for _ in $(seq 1 80); do
    ls "$XDG_RUNTIME_DIR" 2>/dev/null | grep -q '^wayland-[0-9]*$' && break
    sleep 0.25
  done
  WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR" | grep '^wayland-[0-9]*$' | head -1)
  SWAYSOCK=$(ls "$XDG_RUNTIME_DIR"/sway-ipc.*.sock 2>/dev/null | head -1)
  export WAYLAND_DISPLAY SWAYSOCK
  if ! kill -0 "$SWAY_PID" 2>/dev/null || [ -z "$WAYLAND_DISPLAY" ]; then
    echo "sway failed to start:" >&2; cat "$HEADLESS_TMP/sway.log" >&2; return 1
  fi
  # An isolated home so a run never reads or writes the developer's real settings.
  export GDK_BACKEND=wayland HOME="$HEADLESS_TMP/home"
  export XDG_CONFIG_HOME="$HOME/.config" XDG_CACHE_HOME="$HOME/.cache" XDG_DATA_HOME="$HOME/.local/share"
  export PYTHONWARNINGS=ignore::SyntaxWarning
  mkdir -p "$HOME"
  echo "headless sway up: $WAYLAND_DISPLAY ${res} (pid $SWAY_PID)"
}

headless_stop() {
  [ -n "${SWAY_PID:-}" ] && kill "$SWAY_PID" 2>/dev/null
  [ -n "${HEADLESS_TMP:-}" ] && rm -rf "$HEADLESS_TMP"
  true
}
