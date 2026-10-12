#!/bin/bash
# Run every headless check, each in its own fresh compositor session.
#   bash ci/headless/run-all.sh [dock|stall|snip ...]     (default: all)
# Not wired into CI: it needs sway, which the CI container does not install.
set -u
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
headless_need sway grim wl-copy wl-paste dbus-run-session python3 || {
  echo "Install the tools listed in ci/headless/README.md first." >&2; exit 2; }
python3 -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('GtkLayerShell','0.1'); from PIL import Image" 2>/dev/null || {
  echo "Need python3 with PyGObject, Gtk 3, gtk-layer-shell and Pillow (see README.md)." >&2; exit 2; }

want=("$@"); [ ${#want[@]} -eq 0 ] && want=(dock stall snip)
failed=()

session() {  # session <name> <fresh-compositor commands...>
  local name="$1"; shift
  echo; echo "################ $name ################"
  ( headless_start 1920x1080 || exit 1
    trap headless_stop EXIT
    "$@" ) || failed+=("$name")
}

stub_hyprctl_dir() {  # an EMPTY Hyprland desktop: IPC answers (rc 0) but nothing is open
  local d; d=$(mktemp -d)
  printf '#!/bin/bash\ncase "$*" in *clients*) echo "[]";; *) echo "{}";; esac\n' > "$d/hyprctl"
  chmod +x "$d/hyprctl"; echo "$d"
}

for check in "${want[@]}"; do
  case "$check" in
    dock)  session "dock position/size matrix" bash -c "dbus-run-session -- python3 '$HEADLESS_DIR/dock_matrix.py' 2>&1 | grep -v 'dbus-daemon\|SpiRegistry'; exit \${PIPESTATUS[0]}" ;;
    stall) stub=$(stub_hyprctl_dir)
           session "main-loop stalls, empty Hyprland desktop" bash -c "PATH='$stub':\$PATH dbus-run-session -- python3 '$HEADLESS_DIR/stall_check.py' 2>&1 | grep -v 'dbus-daemon\|SpiRegistry'; exit \${PIPESTATUS[0]}"
           session "main-loop stalls, no hyprctl at all" bash -c "dbus-run-session -- python3 '$HEADLESS_DIR/stall_check.py' 2>&1 | grep -v 'dbus-daemon\|SpiRegistry'; exit \${PIPESTATUS[0]}"
           rm -rf "$stub" ;;
    snip)  session "screenshot snip" bash "$HEADLESS_DIR/snip_check.sh" ;;
    *) echo "unknown check: $check (dock|stall|snip)" >&2; exit 2 ;;
  esac
done

echo
if [ ${#failed[@]} -eq 0 ]; then echo "ALL HEADLESS CHECKS PASSED"; exit 0; fi
echo "FAILED: ${failed[*]}"; exit 1
