#!/usr/bin/env bash
set -Eeuo pipefail

# Guest-side stages for a real VMware/Calamares installed-flow test.  The host
# copies this file and vmware-calamares-atspi.py to /tmp and invokes one mode at
# a time through vmrun.  No mode prints a credential value.

mode="${1:-}"
log_path="${2:-}"
shift "$(( $# >= 2 ? 2 : $# ))"

case "$log_path" in
    /tmp/darkos-vmware-installed-*.log) ;;
    *) printf 'invalid log path\n' >&2; exit 2 ;;
esac
status_path="${log_path%.log}.status"
helper=/tmp/darkos-vmware-calamares-atspi.py

exec > >(tee "$log_path") 2>&1
trap 'rc=$?; if (( rc == 0 )); then printf "RESULT=PASS\nEXIT_CODE=0\n" >"$status_path"; else printf "RESULT=FAIL\nEXIT_CODE=%s\n" "$rc" >"$status_path"; fi' EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

require_file() {
    [[ -f "$1" ]] || fail "required file is missing: $1"
}

setup_session_environment() {
    local runtime_uid candidate signature_path=""
    runtime_uid="$(id -u)"
    [[ "$runtime_uid" -ne 0 ]] || fail 'must run as the active desktop user, not root'
    export XDG_RUNTIME_DIR="/run/user/${runtime_uid}"
    export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    export DISPLAY="${DISPLAY:-:0}"
    export XDG_CURRENT_DESKTOP=Hyprland
    export GDK_BACKEND=wayland
    export NO_AT_BRIDGE=0
    export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1
    [[ -S "${XDG_RUNTIME_DIR}/bus" ]] || fail 'desktop D-Bus socket is not ready'
    export WAYLAND_DISPLAY=""
    for candidate in "${XDG_RUNTIME_DIR}"/wayland-*; do
        if [[ -S "$candidate" ]]; then
            WAYLAND_DISPLAY="$(basename -- "$candidate")"
            break
        fi
    done
    [[ -n "$WAYLAND_DISPLAY" ]] || fail 'Wayland socket is not ready'
    for candidate in "${XDG_RUNTIME_DIR}"/hypr/*; do
        if [[ -d "$candidate" ]] && { [[ -S "$candidate/.socket.sock" ]] || [[ -S "$candidate/.socket2.sock" ]]; }; then
            signature_path="$candidate"
            break
        fi
    done
    [[ -n "$signature_path" ]] || fail 'Hyprland instance is not ready'
    export HYPRLAND_INSTANCE_SIGNATURE="$(basename -- "$signature_path")"
    printf 'session uid=%s gid=%s\n' "$(id -u)" "$(id -g)"
}

process_environment_value() {
    local process_id="$1" variable_name="$2"
    python - "$process_id" "$variable_name" <<'PY'
from pathlib import Path
import sys

pid, name = sys.argv[1], sys.argv[2]
prefix = name.encode() + b"="
matches = [item[len(prefix):] for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if item.startswith(prefix)]
if len(matches) != 1 or b"\0" in matches[0] or b"\n" in matches[0]:
    raise SystemExit(1)
sys.stdout.write(matches[0].decode("utf-8", "strict"))
PY
}

setup_greeter_environment() {
    local greeter_uid
    [[ "$EUID" -eq 0 ]] || fail 'greeter automation must run as root through authenticated VMware Tools'
    mapfile -t greeter_pids < <(pgrep -x regreet)
    [[ "${#greeter_pids[@]}" -eq 1 ]] || fail "expected one ReGreet process, found ${#greeter_pids[@]}"
    greeter_pid="${greeter_pids[0]}"
    greeter_uid="$(id -u greeter)"
    [[ "$(stat -c '%u' "/proc/${greeter_pid}")" == "$greeter_uid" ]] \
        || fail 'ReGreet process does not belong to the greeter account'
    greeter_runtime_dir="$(process_environment_value "$greeter_pid" XDG_RUNTIME_DIR)" \
        || fail 'ReGreet has no safe XDG_RUNTIME_DIR'
    greeter_session_bus="$(process_environment_value "$greeter_pid" DBUS_SESSION_BUS_ADDRESS)" \
        || fail 'ReGreet has no safe D-Bus session address'
    greeter_wayland_display="$(process_environment_value "$greeter_pid" WAYLAND_DISPLAY)" \
        || fail 'ReGreet has no safe Wayland display'
    greeter_atspi_bus="$(process_environment_value "$greeter_pid" AT_SPI_BUS_ADDRESS 2>/dev/null || true)"
    [[ -S "${greeter_runtime_dir}/${greeter_wayland_display}" ]] || fail 'ReGreet Wayland socket is not ready'
    printf 'greeter uid=%s pid=%s\n' "$greeter_uid" "$greeter_pid"
}

run_as_greeter() {
    local -a environment=(
        "XDG_RUNTIME_DIR=${greeter_runtime_dir}"
        "DBUS_SESSION_BUS_ADDRESS=${greeter_session_bus}"
        "WAYLAND_DISPLAY=${greeter_wayland_display}"
        'GDK_BACKEND=wayland'
        'NO_AT_BRIDGE=0'
    )
    if [[ -n "$greeter_atspi_bus" ]]; then
        environment+=("AT_SPI_BUS_ADDRESS=${greeter_atspi_bus}")
    fi
    runuser --user greeter -- env "${environment[@]}" python "$helper" --app-contains regreet "$@"
}

wait_for_installer_client() {
    local deadline=$((SECONDS + 30))
    while (( SECONDS < deadline )); do
        if hyprctl clients -j | python -c 'import json,sys; cs=json.load(sys.stdin); raise SystemExit(not any("calamares" in ((c.get("class","")+" "+c.get("title","")).casefold()) and c.get("mapped") for c in cs))'; then
            return 0
        fi
        sleep 1
    done
    fail 'Calamares did not expose a mapped Hyprland client within 30 seconds'
}

case "$mode" in
    launch)
        [[ -e /run/archiso ]] || fail 'launch mode is only valid in the live ISO'
        require_file "$helper"
        setup_session_environment
        command -v darkos-installer >/dev/null 2>&1 || fail 'darkos-installer is unavailable'
        systemctl --user reset-failed darkos-vmware-calamares.service >/dev/null 2>&1 || true
        systemd-run --user --unit=darkos-vmware-calamares --collect \
            --setenv="DISPLAY=$DISPLAY" \
            --setenv="WAYLAND_DISPLAY=$WAYLAND_DISPLAY" \
            --setenv="XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" \
            --setenv="DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS" \
            --setenv="HYPRLAND_INSTANCE_SIGNATURE=$HYPRLAND_INSTANCE_SIGNATURE" \
            --setenv=NO_AT_BRIDGE=0 \
            --setenv=QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 -- darkos-installer
        wait_for_installer_client
        printf 'Calamares client is mapped\n'
        ;;
    inspect)
        [[ -e /run/archiso ]] || fail 'inspect mode is only valid in the live ISO'
        require_file "$helper"
        output_path="${1:-}"
        case "$output_path" in
            /tmp/darkos-vmware-installed-*.json) ;;
            *) fail 'inspection output path must be under /tmp with the test prefix' ;;
        esac
        setup_session_environment
        python "$helper" inspect --output "$output_path"
        ;;
    stage)
        [[ -e /run/archiso ]] || fail 'stage mode is only valid in the live ISO'
        require_file "$helper"
        plan_path="${1:-}"
        stage_name="${2:-}"
        timeout="${3:-20}"
        case "$plan_path" in
            /tmp/darkos-vmware-installed-*.json) ;;
            *) fail 'plan path must be under /tmp with the test prefix' ;;
        esac
        [[ -n "$stage_name" ]] || fail 'stage name is required'
        [[ "$timeout" =~ ^[0-9]+([.][0-9]+)?$ ]] || fail 'stage timeout must be numeric'
        setup_session_environment
        python "$helper" --timeout "$timeout" run-stage --plan "$plan_path" --stage "$stage_name"
        ;;
    verify-installed)
        [[ ! -e /run/archiso ]] || fail 'still booted from the live ISO'
        require_file "$helper"
        setup_session_environment
        python "$helper" verify-installed
        ;;
    verify-live-preflight)
        [[ -e /run/archiso ]] || fail 'plugin preflight requires the live ISO'
        [[ "$EUID" -eq 0 ]] || fail 'plugin preflight must run as root'
        require_file "$helper"
        python "$helper" verify-live-preflight
        ;;
    verify-live-logs)
        [[ -e /run/archiso ]] || fail 'Calamares log verification requires the live ISO'
        [[ "$EUID" -eq 0 ]] || fail 'Calamares log verification must run as root'
        require_file "$helper"
        python "$helper" verify-live-logs
        ;;
    inspect-greeter)
        [[ ! -e /run/archiso ]] || fail 'greeter inspection requires the installed system'
        require_file "$helper"
        output_path="${1:-}"
        case "$output_path" in
            /tmp/darkos-vmware-installed-*.json) ;;
            *) fail 'greeter inspection output path must use the test prefix under /tmp' ;;
        esac
        setup_greeter_environment
        run_as_greeter inspect --output "$output_path"
        ;;
    stage-greeter)
        [[ ! -e /run/archiso ]] || fail 'greeter automation requires the installed system'
        require_file "$helper"
        plan_path="${1:-}"
        stage_name="${2:-}"
        timeout="${3:-20}"
        case "$plan_path" in
            /tmp/darkos-vmware-installed-*.json) ;;
            *) fail 'greeter plan path must use the test prefix under /tmp' ;;
        esac
        [[ -n "$stage_name" ]] || fail 'greeter stage name is required'
        [[ "$timeout" =~ ^[0-9]+([.][0-9]+)?$ ]] || fail 'greeter timeout must be numeric'
        setup_greeter_environment
        run_as_greeter --timeout "$timeout" run-stage --plan "$plan_path" --stage "$stage_name"
        ;;
    *)
        fail 'unsupported mode; expected launch, inspect, stage, verify-live-preflight, verify-live-logs, inspect-greeter, stage-greeter, or verify-installed'
        ;;
esac
