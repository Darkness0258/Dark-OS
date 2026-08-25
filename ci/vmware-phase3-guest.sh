#!/usr/bin/env bash
# Fail-closed live-guest verification used by ci/run-vmware-test.ps1.
#
# The host copies this file into the fresh VMware guest and invokes one mode at
# a time.  Every mode writes both a log and a small status file; the host checks
# the vmrun exit code *and* the status file so a VIX launch cannot masquerade as
# a successful guest assertion run.

set -Eeuo pipefail

mode="${1:-}"
log_path="${2:-}"
shift $(( $# >= 2 ? 2 : $# ))

if [[ -z "$mode" || -z "$log_path" ]]; then
    printf 'Usage: %s MODE /tmp/darkos-vmware-LOG [MODE_ARGS...]\n' "$0" >&2
    exit 2
fi

case "$log_path" in
    /tmp/darkos-vmware-*) ;;
    *)
        printf 'Refusing an evidence path outside /tmp/darkos-vmware-*: %s\n' "$log_path" >&2
        exit 2
        ;;
esac

status_path="${log_path}.status"
mkdir -p -- "$(dirname -- "$log_path")"
: >"$log_path"
exec >>"$log_path" 2>&1

result=FAIL
failure_detail="mode did not reach its PASS marker"
declare -a ephemeral_pids=()
btrfs_mount=""

cleanup_ephemeral() {
    local pid
    for pid in "${ephemeral_pids[@]}"; do
        if [[ -n "$pid" ]]; then
            kill "$pid" >/dev/null 2>&1 || true
            wait "$pid" >/dev/null 2>&1 || true
        fi
    done
    if [[ -n "$btrfs_mount" ]] && mountpoint -q -- "$btrfs_mount"; then
        sudo -n umount -- "$btrfs_mount" >/dev/null 2>&1 || true
    fi
}

finish() {
    local rc=$?
    trap - EXIT ERR
    set +e
    cleanup_ephemeral
    if [[ "$result" != PASS && "$rc" -eq 0 ]]; then
        rc=1
    fi
    {
        printf 'RESULT=%s\n' "$result"
        printf 'MODE=%s\n' "$mode"
        printf 'EXIT_CODE=%s\n' "$rc"
        printf 'DETAIL=%s\n' "$failure_detail"
    } >"$status_path"
    exit "$rc"
}

on_error() {
    local rc=$?
    failure_detail="line ${BASH_LINENO[0]}: ${BASH_COMMAND} (exit ${rc})"
    printf 'ASSERTION FAILURE: %s\n' "$failure_detail"
    exit "$rc"
}

trap finish EXIT
trap on_error ERR

log_section() {
    printf '\n=== %s ===\n' "$1"
}

fail() {
    failure_detail="$*"
    printf 'ASSERTION FAILURE: %s\n' "$failure_detail" >&2
    return 1
}

assert_file_nonempty() {
    local path="$1"
    local description="$2"
    [[ -s "$path" ]] || fail "$description is missing or empty: $path"
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local description="$3"
    [[ "$haystack" == *"$needle"* ]] || fail "$description (missing '$needle')"
}

assert_equals() {
    local actual="$1"
    local expected="$2"
    local description="$3"
    [[ "$actual" == "$expected" ]] \
        || fail "$description (expected '$expected', got '$actual')"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

setup_session_environment() {
    local runtime_uid
    local signature_path
    local candidate

    runtime_uid="$(id -u)"
    [[ "$runtime_uid" -ne 0 ]] || fail 'guest verifier must run as the live desktop user, not root'

    export XDG_RUNTIME_DIR="/run/user/${runtime_uid}"
    export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    export DISPLAY="${DISPLAY:-:0}"
    export XDG_CURRENT_DESKTOP=Hyprland
    export GDK_BACKEND=wayland
    export NO_AT_BRIDGE=0

    [[ -S "${XDG_RUNTIME_DIR}/bus" ]] || fail "desktop D-Bus socket is not ready"

    export WAYLAND_DISPLAY=""
    for candidate in "${XDG_RUNTIME_DIR}"/wayland-*; do
        if [[ -S "$candidate" ]]; then
            WAYLAND_DISPLAY="$(basename -- "$candidate")"
            break
        fi
    done
    [[ -n "$WAYLAND_DISPLAY" ]] || fail "no Wayland socket exists in ${XDG_RUNTIME_DIR}"

    signature_path=""
    for candidate in "${XDG_RUNTIME_DIR}"/hypr/*; do
        if [[ -d "$candidate" ]] \
            && { [[ -S "$candidate/.socket.sock" ]] || [[ -S "$candidate/.socket2.sock" ]]; }; then
            signature_path="$candidate"
            break
        fi
    done
    [[ -n "$signature_path" && -d "$signature_path" ]] \
        || fail "no Hyprland instance exists in ${XDG_RUNTIME_DIR}/hypr"
    HYPRLAND_INSTANCE_SIGNATURE="$(basename -- "$signature_path")"
    export HYPRLAND_INSTANCE_SIGNATURE

    printf 'Session user: %s (uid %s)\n' "$(id -un)" "$runtime_uid"
    printf 'XDG_RUNTIME_DIR: %s\n' "$XDG_RUNTIME_DIR"
    printf 'WAYLAND_DISPLAY: %s\n' "$WAYLAND_DISPLAY"
    printf 'HYPRLAND_INSTANCE_SIGNATURE: %s\n' "$HYPRLAND_INSTANCE_SIGNATURE"
}

hypr_json_value() {
    local command_name="$1"
    local key="$2"
    hyprctl "$command_name" -j | python -c \
        'import json,sys; data=json.load(sys.stdin); print(data.get(sys.argv[1], ""))' "$key"
}

session_runtime_present() {
    local runtime_dir
    local candidate
    local hypr_found=0
    local wayland_found=0

    runtime_dir="/run/user/$(id -u)"

    [[ -S "${runtime_dir}/bus" ]] || return 1
    for candidate in "${runtime_dir}"/hypr/*; do
        if [[ -d "$candidate" ]] \
            && { [[ -S "$candidate/.socket.sock" ]] || [[ -S "$candidate/.socket2.sock" ]]; }; then
            hypr_found=1
            break
        fi
    done
    for candidate in "${runtime_dir}"/wayland-*; do
        if [[ -S "$candidate" ]]; then
            wayland_found=1
            break
        fi
    done
    [[ "$hypr_found" -eq 1 && "$wayland_found" -eq 1 ]]
}

wait_for_ready() {
    local timeout="${DARKOS_VM_READY_TIMEOUT:-180}"
    local start=$SECONDS
    local layers=""
    local reason=""

    log_section 'Desktop readiness'
    while (( SECONDS - start < timeout )); do
        reason=""
        if ! session_runtime_present; then
            reason='desktop D-Bus/Hyprland/Wayland sockets are not ready'
        else
            # Call this outside an `if ! function` condition. Bash disables
            # errexit inside functions used as conditions, which could let a
            # failed assertion continue and turn into a false-ready result.
            setup_session_environment >/tmp/darkos-vmware-session-probe.log 2>&1
        fi

        if [[ -n "$reason" ]]; then
            :
        elif ! pgrep -u "$(id -u)" -f '/usr/local/bin/darkos-shell.py' >/dev/null 2>&1; then
            reason='darkos-shell.py is not running'
        elif ! layers="$(hyprctl layers 2>&1)"; then
            reason='hyprctl layers failed'
        elif [[ "$layers" != *'namespace: darkos-dock'* ]]; then
            reason='darkos-dock layer is absent'
        elif [[ "$layers" != *'namespace: darkos-rail'* ]]; then
            reason='darkos-rail layer is absent'
        elif ! pamixer --get-volume >/dev/null 2>&1; then
            reason='PipeWire/PulseAudio volume endpoint is not ready'
        else
            cat /tmp/darkos-vmware-session-probe.log
            printf '%s\n' "$layers"
            printf 'Desktop became ready after %ss.\n' "$((SECONDS - start))"
            return 0
        fi
        printf 'Waiting for desktop (%ss): %s\n' "$((SECONDS - start))" "$reason"
        sleep 3
    done

    cat /tmp/darkos-vmware-session-probe.log 2>/dev/null || true
    fail "desktop did not become ready within ${timeout}s (${reason})"
}

assert_runtime_health() {
    local layers
    local recovery_config
    local config_errors=""

    log_section 'Runtime health'
    setup_session_environment

    [[ -d /run/archiso ]] || fail 'this harness expects the fresh live ISO (/run/archiso is absent)'
    pgrep -x vmtoolsd >/dev/null 2>&1 || fail 'vmtoolsd is not running in the guest'
    pgrep -u "$(id -u)" -f '/usr/local/bin/darkos-shell.py' >/dev/null 2>&1 \
        || fail 'DarkOS shell process is not running'

    recovery_config="${XDG_RUNTIME_DIR}/hypr/${HYPRLAND_INSTANCE_SIGNATURE}/recoverycfg.lua"
    [[ ! -e "$recovery_config" ]] \
        || fail "Hyprland is running its autogenerated recovery config: $recovery_config"

    layers="$(hyprctl layers)"
    # The activity detector deliberately hides the side panels in the default
    # profile. Only the always-visible dock and icon rail are readiness gates;
    # the context tests below exercise real activity-profile transitions.
    for namespace in darkos-dock darkos-rail; do
        assert_contains "$layers" "namespace: ${namespace}" "required layer-shell surface is absent"
    done

    if config_errors="$(hyprctl configerrors 2>/dev/null)"; then
        [[ -z "${config_errors//[[:space:]]/}" ]] \
            || fail "Hyprland reports configuration errors: ${config_errors}"
    fi

    if [[ -s /tmp/hyprland-start.log ]] \
        && grep -Eiq 'Traceback|NameError|ImportError|TypeError|segmentation fault|core dumped' \
            /tmp/hyprland-start.log; then
        printf '%s\n' '--- /tmp/hyprland-start.log ---'
        cat /tmp/hyprland-start.log
        fail 'Hyprland startup log contains a fatal Python/runtime error'
    fi

    printf 'Runtime health assertions passed.\n'
}

assert_phase3_sources() {
    local pycache_root

    log_section 'Phase 3 packaged source and dependency checks'
    require_command python
    require_command pamixer
    require_command hyprctl
    require_command btrfs
    require_command mkfs.btrfs
    if ! command -v parec >/dev/null 2>&1 \
        && ! command -v arecord >/dev/null 2>&1 \
        && ! command -v ffmpeg >/dev/null 2>&1; then
        fail 'no supported microphone recorder is packaged (parec/arecord/ffmpeg)'
    fi

    # The live payload is root-owned. Keep bytecode in a private temporary
    # tree so this unprivileged runtime check never attempts to mutate it.
    pycache_root="$(mktemp -d /tmp/darkos-vmware-pycache.XXXXXX)"
    PYTHONPYCACHEPREFIX="$pycache_root" \
        python -m compileall -q /usr/local/bin/darkos-shell.py /usr/local/bin/darkos_shell
    python - <<'PY'
import os
from pathlib import Path
import sys

sys.path.insert(0, "/usr/local/bin")
from darkos_shell import activity_detector, ai_brain  # noqa: E402

css_text = Path("/usr/local/bin/darkos_shell/css.py").read_text(encoding="utf-8")
surface_text = Path("/usr/local/bin/darkos_shell/surfaces.py").read_text(encoding="utf-8")
application_text = Path("/usr/local/bin/darkos_shell/__init__.py").read_text(encoding="utf-8")
hyprland_text = Path("/etc/xdg/hypr/hyprland.conf").read_text(encoding="utf-8")
assert ".dock-highlight" in css_text, "dock-highlight CSS rule is absent"
for profile in ("coding", "writing", "media"):
    highlight = activity_detector.ACTIVITY_PROFILES[profile]["dock_highlight"]
    assert highlight, f"{profile} has no dock highlight"
    assert f'("{highlight}",' in surface_text, (
        f"{profile} maps to missing dock icon {highlight!r}"
    )

assert '--ptt-start' in application_text and '--ptt-stop' in application_text, (
    "shell controller exposes no global push-to-talk start/stop commands"
)
assert 'bindr = $mainMod, SPACE' in hyprland_text, "Hyprland has no push-to-talk release binding"
assert '--ptt-start' in hyprland_text and '--ptt-stop' in hyprland_text, (
    "Hyprland push-to-talk bindings do not reach both controller commands"
)

previous_key = os.environ.get("OPENROUTER_API_KEY")
os.environ["OPENROUTER_API_KEY"] = "darkos-vm-alias-probe"
try:
    alias_brain = ai_brain.AIBrain()
    assert alias_brain._openrouter_key == "darkos-vm-alias-probe", (
        "documented OPENROUTER_API_KEY alias is not honored"
    )
finally:
    if previous_key is None:
        os.environ.pop("OPENROUTER_API_KEY", None)
    else:
        os.environ["OPENROUTER_API_KEY"] = previous_key

class ExplainActions:
    def explain(self, _target):
        return "DARKOS_VM_FATAL: simulated database timeout"

brain = ai_brain.AIBrain(actions=ExplainActions())
calls = []
responses = iter((
    "I will inspect it.\n[ACTION] explain(active)",
    "The database connection timed out; verify the server and network.",
))

def fake_chat(messages, timeout=30.0):
    calls.append(messages)
    return next(responses)

brain.chat = fake_chat
reply, summary = brain.process_chat("Explain this")
assert len(calls) == 2, "explain workflow did not make its follow-up brain call"
assert "DARKOS_VM_FATAL" in calls[1][-1]["content"], "extracted text was not fed back to the brain"
assert "timed out" in reply and not summary, "explain workflow returned the wrong result split"
print("Explain follow-up logic passed.")
PY

    require_command espeak-ng
    printf 'TTS backend: packaged eSpeak NG\n'
}

assert_tts_playback() {
    local volume_before
    local mute_before
    local setup_status=0
    local python_status=0
    local restore_status=0

    log_section 'Packaged AIBrain TTS playback'
    require_command pactl
    require_command parec
    require_command espeak-ng
    volume_before="$(pamixer --get-volume)"
    mute_before="$(pamixer --get-mute)"
    [[ "$volume_before" =~ ^[0-9]+$ ]] || fail "invalid pre-TTS volume: $volume_before"
    [[ "$mute_before" == true || "$mute_before" == false ]] \
        || fail "invalid pre-TTS mute state: $mute_before"

    # Exercise the public pipeline at a deliberately quiet level. Always
    # restore both volume and mute state before propagating a failure.
    pamixer --set-volume 12 || setup_status=$?
    if [[ "$setup_status" -eq 0 ]]; then
        pamixer --unmute || setup_status=$?
    fi
    if [[ "$setup_status" -ne 0 ]]; then
        pamixer --set-volume "$volume_before" >/dev/null 2>&1 || true
        if [[ "$mute_before" == true ]]; then
            pamixer --mute >/dev/null 2>&1 || true
        else
            pamixer --unmute >/dev/null 2>&1 || true
        fi
        fail "could not prepare the quiet TTS playback state (exit ${setup_status})"
    fi
    python - <<'PY' || python_status=$?
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import wave

os.environ.pop("DARKOS_GROQ_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.ai_brain import AIBrain

capture_path = Path("/tmp/darkos-vmware-tts-monitor.wav")
capture_path.unlink(missing_ok=True)
sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
assert sink, "PipeWire/PulseAudio returned no default sink"
monitor = f"{sink}.monitor"
sources = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
assert any(line.split("\t", 2)[1] == monitor for line in sources.splitlines() if "\t" in line), (
    f"default sink monitor is absent: {monitor}"
)

recorder = subprocess.Popen(
    ["parec", f"--device={monitor}", "--file-format=wav", str(capture_path)],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.PIPE,
    text=True,
)
spoken = False
recorder_stderr = ""
try:
    time.sleep(0.5)
    assert recorder.poll() is None, (
        f"parec exited before TTS playback ({recorder.returncode})"
    )
    brain = AIBrain()
    brain._groq_key = ""

    def forbid_fallback(*_args, **_kwargs):
        raise AssertionError("AIBrain.speak bypassed the packaged eSpeak NG backend")

    brain._try_edge_tts = forbid_fallback
    brain._try_piper_tts = forbid_fallback
    spoken = brain.speak("DarkOS audio pipeline verification", timeout=10.0)
    time.sleep(0.75)
finally:
    if recorder.poll() is None:
        recorder.send_signal(signal.SIGINT)
    try:
        _, recorder_stderr = recorder.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        recorder.kill()
        _, recorder_stderr = recorder.communicate(timeout=5)

assert spoken, f"AIBrain.speak failed through eSpeak NG: {brain.last_error}"
assert capture_path.is_file() and capture_path.stat().st_size > 44, (
    f"sink-monitor WAV was not produced: {capture_path}"
)
with wave.open(str(capture_path), "rb") as captured:
    sample_width = captured.getsampwidth()
    frame_rate = captured.getframerate()
    frame_count = captured.getnframes()
    frames = captured.readframes(frame_count)
assert sample_width in {1, 2, 3, 4}, f"unsupported monitor sample width: {sample_width}"
assert frame_rate > 0 and frame_count >= frame_rate // 4, (
    f"sink-monitor capture is too short: {frame_count} frames at {frame_rate} Hz"
)

samples = []
bits = sample_width * 8
for offset in range(0, len(frames) - sample_width + 1, sample_width):
    raw = frames[offset:offset + sample_width]
    if sample_width == 1:
        value = raw[0] - 128
    else:
        value = int.from_bytes(raw, "little", signed=False)
        if value & (1 << (bits - 1)):
            value -= 1 << bits
    samples.append(value)
peak = max((abs(value) for value in samples), default=0)
rms = (sum(value * value for value in samples) / max(1, len(samples))) ** 0.5
minimum_peak = max(8, (1 << (bits - 1)) // 2000)
assert peak > minimum_peak and rms > minimum_peak / 8, (
    f"sink-monitor WAV is silent (peak={peak}, rms={rms:.2f}, threshold={minimum_peak}); "
    f"parec stderr: {recorder_stderr.strip()}"
)
print(
    "AIBrain.speak reached the default sink monitor through packaged eSpeak NG: "
    f"{frame_count} frames, peak={peak}, rms={rms:.2f}"
)
capture_path.unlink(missing_ok=True)
PY
    pamixer --set-volume "$volume_before" || restore_status=$?
    if [[ "$mute_before" == true ]]; then
        pamixer --mute || restore_status=$?
    else
        pamixer --unmute || restore_status=$?
    fi
    [[ "$restore_status" -eq 0 ]] || fail "could not restore audio state after TTS (exit ${restore_status})"
    [[ "$python_status" -eq 0 ]] || fail "AIBrain.speak failed with exit ${python_status}"
}

assert_audio_and_workspace_actions() {
    local volume_before
    local volume_target
    local volume_after
    local workspace_before
    local workspace_target
    local workspace_after

    log_section 'Live audio and Hyprland actions'
    volume_before="$(pamixer --get-volume)"
    [[ "$volume_before" =~ ^[0-9]+$ ]] || fail "pamixer returned a non-numeric volume: $volume_before"
    if (( volume_before >= 95 )); then
        volume_target=$((volume_before - 1))
    else
        volume_target=$((volume_before + 1))
    fi

    python - "$volume_target" <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import ActionDispatcher
target = int(sys.argv[1])
result = ActionDispatcher().set_volume(target)
assert result == f"Volume set to {target}%.", result
print(result)
PY
    volume_after="$(pamixer --get-volume)"
    assert_equals "$volume_after" "$volume_target" 'ActionDispatcher did not mutate live volume'
    pamixer --set-volume "$volume_before"
    assert_equals "$(pamixer --get-volume)" "$volume_before" 'volume was not restored after the test'

    workspace_before="$(hypr_json_value activeworkspace id)"
    [[ "$workspace_before" =~ ^[0-9]+$ ]] \
        || fail "hyprctl returned an invalid workspace id: $workspace_before"
    if [[ "$workspace_before" == 1 ]]; then
        workspace_target=2
    else
        workspace_target=1
    fi

    python - "$workspace_target" <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import ActionDispatcher
target = sys.argv[1]
result = ActionDispatcher().switch_workspace(target)
assert result == f"Switched to workspace {target}.", result
print(result)
PY
    sleep 1
    workspace_after="$(hypr_json_value activeworkspace id)"
    assert_equals "$workspace_after" "$workspace_target" 'ActionDispatcher did not switch the live workspace'

    python - "$workspace_before" <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import ActionDispatcher
ActionDispatcher().switch_workspace(sys.argv[1])
PY
    sleep 1
    assert_equals "$(hypr_json_value activeworkspace id)" "$workspace_before" \
        'workspace was not restored after the test'

    printf 'Volume: %s -> %s -> %s\n' "$volume_before" "$volume_after" "$(pamixer --get-volume)"
    printf 'Workspace: %s -> %s -> %s\n' \
        "$workspace_before" "$workspace_after" "$(hypr_json_value activeworkspace id)"
}

assert_real_btrfs_snapshot() {
    local temp_root
    local image_path
    local source_subvolume
    local snapshot_name
    local subvolumes

    log_section 'Real Btrfs snapshot-before-act'
    require_command truncate
    require_command mountpoint
    sudo -n true || fail 'passwordless sudo is unavailable in the live guest'

    temp_root="$(mktemp -d /tmp/darkos-vmware-btrfs.XXXXXX)"
    image_path="${temp_root}/filesystem.img"
    btrfs_mount="${temp_root}/mount"
    mkdir -p -- "$btrfs_mount"
    truncate -s 256M -- "$image_path"
    mkfs.btrfs -q -f -- "$image_path"
    sudo -n mount -o loop -- "$image_path" "$btrfs_mount"
    source_subvolume="${btrfs_mount}/root"
    sudo -n btrfs subvolume create "$source_subvolume"
    sudo -n chown "$(id -u):$(id -g)" "$source_subvolume"

    snapshot_name="$(python - "$source_subvolume" <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import ActionDispatcher

dispatcher = ActionDispatcher()
dispatcher._snapshot_enabled = True
dispatcher._snapshot_root = sys.argv[1]
dispatcher._snapshot()
name = dispatcher.latest_snapshot()
assert name and name.startswith("darkos-ai-"), f"snapshot not recorded: {name!r}"
print(name)
PY
)"
    subvolumes="$(sudo -n btrfs subvolume list "$btrfs_mount")"
    assert_contains "$subvolumes" "root/.snapshots/${snapshot_name}" \
        'real btrfs subvolume output does not contain the safety snapshot'
    printf '%s\n' "$subvolumes"

    sudo -n umount -- "$btrfs_mount"
    btrfs_mount=""
}

wait_for_hypr_title() {
    local title="$1"
    local timeout="${2:-20}"
    local start=$SECONDS
    while (( SECONDS - start < timeout )); do
        if hyprctl clients -j | python -c \
            'import json,sys; title=sys.argv[1]; clients=json.load(sys.stdin); raise SystemExit(0 if any(c.get("title")==title and c.get("mapped") for c in clients) else 1)' \
            "$title"; then
            return 0
        fi
        sleep 1
    done
    fail "Hyprland never exposed the expected window: $title"
}

wait_for_hypr_title_absent() {
    local title="$1"
    local timeout="${2:-15}"
    local start=$SECONDS
    while (( SECONDS - start < timeout )); do
        if ! hyprctl clients -j | python -c \
            'import json,sys; title=sys.argv[1]; clients=json.load(sys.stdin); raise SystemExit(0 if any(c.get("title")==title and c.get("mapped") for c in clients) else 1)' \
            "$title"; then
            return 0
        fi
        sleep 1
    done
    fail "Hyprland still exposes a window that should have closed: $title"
}

focus_hypr_title() {
    local title="$1"
    local address
    address="$(hyprctl clients -j | python -c \
        'import json,sys; title=sys.argv[1]; clients=json.load(sys.stdin); print(next((c.get("address", "") for c in clients if c.get("title")==title), ""))' \
        "$title")"
    [[ -n "$address" ]] || fail "could not resolve a Hyprland address for $title"
    if ! hyprctl dispatch focuswindow "address:${address}" >/dev/null 2>&1; then
        hyprctl repl "hl.dispatch(hl.dsp.focus{ window = '${address}' })" >/dev/null
    fi
}

wait_for_hypr_window_match() {
    local needle="$1"
    local timeout="${2:-30}"
    local start=$SECONDS
    while (( SECONDS - start < timeout )); do
        if hyprctl clients -j | python -c \
            'import json,sys; needle=sys.argv[1].casefold(); clients=json.load(sys.stdin); raise SystemExit(0 if any(c.get("mapped") and needle in ((c.get("title", "") + " " + c.get("class", "")).casefold()) for c in clients) else 1)' \
            "$needle"; then
            return 0
        fi
        sleep 1
    done
    fail "Hyprland never exposed a mapped real-app window matching: $needle"
}

focus_hypr_window_match() {
    local needle="$1"
    local address
    address="$(hyprctl clients -j | python -c \
        'import json,sys; needle=sys.argv[1].casefold(); clients=json.load(sys.stdin); print(next((c.get("address", "") for c in clients if c.get("mapped") and needle in ((c.get("title", "") + " " + c.get("class", "")).casefold())), ""))' \
        "$needle")"
    [[ -n "$address" ]] || fail "could not resolve a Hyprland address matching $needle"
    if ! hyprctl dispatch focuswindow "address:${address}" >/dev/null 2>&1; then
        hyprctl repl "hl.dispatch(hl.dsp.focus{ window = '${address}' })" >/dev/null
    fi
}

assert_real_atspi_control() {
    local app_path=/tmp/darkos-vmware-atspi-app.py
    local entry_marker=/tmp/darkos-vmware-atspi-entry.txt
    local entry_title='DarkOS VMware AT-SPI Text'
    local connection_title='Network Connections'
    local connection_dialog='Choose a Connection Type'
    local connection_result
    local cancel_result
    local text_result
    local explain_result
    local start

    log_section 'Real two-app AT-SPI control and explain extraction'
    require_command nm-connection-editor
    rm -f -- "$entry_marker"
    cat >"$app_path" <<'PY'
#!/usr/bin/env python3
import sys
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

marker = sys.argv[1]
window = Gtk.Window(title="DarkOS VMware AT-SPI Text")
window.set_default_size(560, 220)
window.connect("destroy", Gtk.main_quit)
entry = Gtk.Entry()
entry.get_accessible().set_name("DarkOS VM Input")
entry.set_text("DARKOS_VM_FATAL: database connection timeout")
entry.connect("changed", lambda widget: open(marker, "w", encoding="utf-8").write(widget.get_text()))
window.add(entry)

window.show_all()
Gtk.main()
PY

    # Exercise one real packaged desktop application and one deterministic
    # custom target. Both must be visible to Hyprland and AT-SPI before any
    # action is attempted.
    nm-connection-editor >/tmp/darkos-vmware-nm-connection-editor.log 2>&1 &
    ephemeral_pids+=("$!")
    python "$app_path" "$entry_marker" >/tmp/darkos-vmware-atspi-entry.log 2>&1 &
    ephemeral_pids+=("$!")
    wait_for_hypr_title "$connection_title"
    wait_for_hypr_title "$entry_title"

    python - "$connection_title" "$entry_title" <<'PY'
import gi
import sys
import time

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

wanted = set(sys.argv[1:])
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    desktop = Atspi.get_desktop(0)
    frames = set()
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if not app:
            continue
        for j in range(app.get_child_count()):
            child = app.get_child_at_index(j)
            if child and child.get_role_name() == "frame":
                frames.add(child.get_name() or "")
    if wanted <= frames:
        print("AT-SPI frames:", sorted(wanted))
        break
    time.sleep(0.5)
else:
    raise AssertionError(f"AT-SPI did not expose both real apps; saw {sorted(frames)}")
PY

    printf '%s\n' 'Hyprland clients containing both AT-SPI targets:'
    python - "$connection_title" "$entry_title" <<'PY'
import json
import subprocess
import sys

wanted = set(sys.argv[1:])
clients = json.loads(subprocess.check_output(["hyprctl", "clients", "-j"], text=True))
matched = [client for client in clients if client.get("title") in wanted and client.get("mapped")]
assert {client.get("title") for client in matched} == wanted, (
    f"hyprctl did not expose both AT-SPI targets: {matched!r}"
)
print(json.dumps(matched, indent=2, sort_keys=True))
PY

    # Harmlessly activate the real connection editor's Add button and prove
    # that its chooser dialog appears. Cancel it immediately; no connection is
    # created or changed.
    focus_hypr_title "$connection_title"
    connection_result="$(python - <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import _atspi_do_action
print(_atspi_do_action("click", "push button", "Add") or "")
PY
)"
    [[ -n "$connection_result" ]] || fail 'AT-SPI returned no result for the real connection editor Add control'
    wait_for_hypr_title "$connection_dialog"
    python - "$connection_dialog" <<'PY'
import gi
import sys
import time

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

wanted = sys.argv[1]
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    desktop = Atspi.get_desktop(0)
    frames = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if not app:
            continue
        for j in range(app.get_child_count()):
            frame = app.get_child_at_index(j)
            if frame and frame.get_role_name() in {"frame", "dialog"}:
                frames.append(frame.get_name() or "")
    if wanted in frames:
        print(f"Real connection-editor dialog exposed through AT-SPI: {wanted}")
        break
    time.sleep(0.25)
else:
    raise AssertionError(f"AT-SPI never exposed {wanted!r}; saw {frames!r}")
PY
    cancel_result="$(python - <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import _atspi_do_action
print(_atspi_do_action("click", "push button", "Cancel") or "")
PY
)"
    [[ -n "$cancel_result" ]] || fail 'AT-SPI returned no result for the real connection editor Cancel control'
    wait_for_hypr_title_absent "$connection_dialog"

    text_result="$(python - <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import _atspi_do_action
print(_atspi_do_action("set_text", "entry", "DarkOS VM Input", "phase3-atspi-ok") or "")
PY
)"
    [[ -n "$text_result" ]] || fail 'AT-SPI set_text returned no real action result'

    start=$SECONDS
    while [[ "$(cat "$entry_marker" 2>/dev/null || true)" != phase3-atspi-ok \
        && $((SECONDS - start)) -lt 10 ]]; do sleep 1; done
    assert_equals "$(cat "$entry_marker")" phase3-atspi-ok \
        'AT-SPI did not set text in the real GTK entry'

    # Put unique explainable text back into the entry, focus its real window,
    # then create and verify an AT-SPI selection. EditableText.set_text_contents
    # does not guarantee a selection, and explain() deliberately scopes its
    # search to the active frame.
    python - <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import _atspi_do_action
result = _atspi_do_action("set_text", "entry", "DarkOS VM Input", "DARKOS_VM_FATAL: database connection timeout")
assert result, "could not restore explain fixture text"
PY
    focus_hypr_title "$entry_title"
    sleep 1
    python - <<'PY'
import gi
import time

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

accessible_name = "DarkOS VM Input"
expected = "DARKOS_VM_FATAL: database connection timeout"


def find_named(node, depth=0):
    if node is None or depth > 16:
        return None
    try:
        if (node.get_name() or "") == accessible_name:
            return node
        child_count = node.get_child_count()
    except Exception:
        return None
    for index in range(max(0, child_count)):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        match = find_named(child, depth + 1)
        if match is not None:
            return match
    return None


deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    entry = find_named(Atspi.get_desktop(0))
    if entry is not None:
        break
    time.sleep(0.25)
else:
    raise AssertionError(f"could not find AT-SPI entry {accessible_name!r}")

text_iface = entry.get_text_iface()
assert text_iface is not None, "explain fixture exposes no AT-SPI Text interface"
actual = Atspi.Text.get_text(text_iface, 0, -1)
assert actual == expected, f"explain fixture text differs: {actual!r}"

# Remove any toolkit-created selection and create our own through the Text
# interface. This proves extraction consumes a real selection rather than
# accidentally finding unrelated text elsewhere in the accessibility tree.
while Atspi.Text.get_n_selections(text_iface) > 0:
    assert Atspi.Text.remove_selection(text_iface, 0), "could not clear stale AT-SPI selection"
assert Atspi.Text.add_selection(text_iface, 0, len(expected)), (
    "could not create AT-SPI explain selection"
)
selection = Atspi.Text.get_selection(text_iface, 0)
assert selection is not None, "AT-SPI did not report the explain selection"
selected = Atspi.Text.get_text(
    text_iface, selection.start_offset, selection.end_offset
)
assert selected == expected, f"AT-SPI selected unexpected text: {selected!r}"
print("AT-SPI explain selection created and verified.")
PY
    explain_result="$(python - <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.actions import ActionDispatcher
print(ActionDispatcher().explain("active"))
PY
)"
    assert_contains "$explain_result" 'DARKOS_VM_FATAL' \
        'explain() did not extract text from the real accessible app'

    printf 'Connection-editor Add result: %s\n' "$connection_result"
    printf 'Connection-editor Cancel result: %s\n' "$cancel_result"
    printf 'Set-text result: %s\n' "$text_result"
    printf 'Explain extraction: %s\n' "$explain_result"
}

assert_recording_pipeline() {
    log_section 'Microphone recording pipeline'
    python - <<'PY'
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/usr/local/bin")
from darkos_shell.ai_brain import AIBrain
from darkos_shell.assistant_trigger import AssistantTrigger

trigger = AssistantTrigger(AIBrain())
path = trigger._start_recording()
assert path, "no supported recorder was found"
time.sleep(1.5)
assert trigger._recording_process is not None, "recording process was never created"
audio_path = trigger._stop_recording()
assert audio_path == path, f"recording path changed: {path!r} -> {audio_path!r}"
audio = Path(audio_path)
assert audio.exists(), f"recording output does not exist: {audio}"
assert audio.stat().st_size > 44, f"recording output is empty/invalid ({audio.stat().st_size} bytes)"
print(f"Recorder produced {audio.stat().st_size} bytes at {audio}")
audio.unlink(missing_ok=True)
PY
}

prepare_context_window() {
    local profile="${1:-}"
    local title_match
    local label
    local expected_highlight
    local unit
    local detected
    local active_title
    local coding_file=/tmp/darkos-vmware-context.py
    local media_file=/tmp/darkos-vmware-context.html
    local firefox_profile=/tmp/darkos-vmware-firefox-profile

    case "$profile" in
        coding)
            title_match='Neovim - DarkOS VMware Coding Context'
            label='CODING CONTEXT - Terminal icon should glow'
            expected_highlight=terminal
            ;;
        media)
            title_match='Firefox Media - DarkOS VMware Context'
            label='MEDIA CONTEXT - Browser icon should glow'
            expected_highlight=browser
            ;;
        *) fail "unsupported context profile: $profile" ;;
    esac

    log_section "Context highlight: ${profile}"
    setup_session_environment
    cleanup_context_windows

    unit="darkos-vmware-context-${profile}"
    if [[ "$profile" == coding ]]; then
        require_command kitty
        require_command nvim
        cat >"$coding_file" <<PY
#!/usr/bin/env python3
print("$label")
PY
        systemd-run --user --unit "$unit" --collect \
            --setenv="XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}" \
            --setenv="DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS}" \
            --setenv="WAYLAND_DISPLAY=${WAYLAND_DISPLAY}" \
            --setenv="DISPLAY=${DISPLAY}" \
            /usr/bin/kitty --class darkos-vmware-coding \
                --title "$title_match" /usr/bin/nvim --clean "$coding_file"
    else
        require_command firefox
        rm -rf -- "$firefox_profile"
        mkdir -p -- "$firefox_profile"
        cat >"${firefox_profile}/user.js" <<'PREFS'
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionEnabled", false);
PREFS
        cat >"$media_file" <<HTML
<!doctype html><html><head><meta charset="utf-8"><title>$title_match</title></head>
<body style="background:#100d1e;color:#eee;font:28px sans-serif;padding:48px"><h1>$label</h1></body></html>
HTML
        systemd-run --user --unit "$unit" --collect \
            --setenv="XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}" \
            --setenv="DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS}" \
            --setenv="WAYLAND_DISPLAY=${WAYLAND_DISPLAY}" \
            --setenv="DISPLAY=${DISPLAY}" \
            --setenv="MOZ_ENABLE_WAYLAND=1" \
            /usr/bin/firefox --new-instance --no-remote \
                --profile "$firefox_profile" "file://${media_file}"
    fi

    wait_for_hypr_window_match "$title_match" 45
    focus_hypr_window_match "$title_match"
    sleep 1
    detected="$(python - <<'PY'
import sys
sys.path.insert(0, "/usr/local/bin")
from darkos_shell.activity_detector import ActivityDetector
detector = ActivityDetector()
print(detector._detect_activity())
PY
)"
    assert_equals "$detected" "$profile" 'activity detector classified the focused real app incorrectly'

    # The running DarkOSApplication polls every three seconds.  Give it two
    # cycles, then assert it survived the profile transition before the host
    # captures the visual evidence.
    sleep 7
    pgrep -u "$(id -u)" -f '/usr/local/bin/darkos-shell.py' >/dev/null 2>&1 \
        || fail 'DarkOS shell died while applying the context profile'
    active_title="$(hypr_json_value activewindow title)"
    [[ "${active_title,,}" == *"${title_match,,}"* ]] \
        || fail "real context app lost focus before screenshot capture (active: ${active_title})"

    printf 'PROFILE=%s\n' "$profile"
    printf 'ACTIVE_TITLE=%s\n' "$active_title"
    printf 'EXPECTED_DOCK_HIGHLIGHT=%s\n' "$expected_highlight"
    printf 'Real packaged context app is active and ready for host screenshot capture.\n'
}

cleanup_context_windows() {
    local unit
    if [[ -d "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" ]]; then
        for unit in darkos-vmware-context-coding darkos-vmware-context-media; do
            systemctl --user stop "${unit}.service" >/dev/null 2>&1 || true
            systemctl --user reset-failed "${unit}.service" >/dev/null 2>&1 || true
        done
    fi
}

collect_evidence() {
    log_section 'Guest identity and processes'
    date --iso-8601=seconds || true
    uname -a || true
    id || true
    ps auxww || true

    if session_runtime_present; then
        setup_session_environment
    else
        printf 'Desktop session sockets were unavailable during evidence collection.\n'
    fi

    log_section 'Hyprland system information'
    hyprctl systeminfo 2>&1 || true
    log_section 'Hyprland monitors'
    hyprctl monitors -j 2>&1 || true
    log_section 'Hyprland clients'
    hyprctl clients -j 2>&1 || true
    log_section 'Hyprland layers'
    hyprctl layers 2>&1 || true
    log_section 'Hyprland configuration errors'
    hyprctl configerrors 2>&1 || true

    log_section 'Hyprland startup log'
    cat /tmp/hyprland-start.log 2>&1 || true
    log_section 'User journal for this boot'
    journalctl --user -b --no-pager 2>&1 || true
    log_section 'System journal for this boot'
    sudo -n journalctl -b --no-pager 2>&1 || journalctl -b --no-pager 2>&1 || true
    log_section 'Kernel warnings and errors'
    sudo -n dmesg --level=err,warn 2>&1 || true
}

case "$mode" in
    wait-ready)
        wait_for_ready
        result=PASS
        failure_detail='desktop readiness assertions passed'
        ;;
    verify)
        assert_runtime_health
        assert_phase3_sources
        assert_tts_playback
        assert_audio_and_workspace_actions
        assert_real_btrfs_snapshot
        assert_real_atspi_control
        assert_recording_pipeline
        result=PASS
        failure_detail='all automated Phase 3 live-guest assertions passed'
        ;;
    context)
        prepare_context_window "${1:-}"
        result=PASS
        failure_detail="context ${1:-unknown} is ready for screenshot capture"
        ;;
    cleanup)
        setup_session_environment
        cleanup_context_windows
        result=PASS
        failure_detail='guest fixtures cleaned up'
        ;;
    collect)
        collect_evidence
        result=PASS
        failure_detail='guest evidence collected'
        ;;
    *)
        fail "unknown guest verification mode: $mode"
        ;;
esac
