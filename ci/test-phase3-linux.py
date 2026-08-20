#!/usr/bin/env python3
"""DarkOS Phase 3 Unit & Mock Subprocess Test Suite.

Tests Phase 3 action argument parsing, regex dispatching, and subprocess
call formatting using mock shell utilities in a temporary sandbox directory.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.request
from pathlib import Path

# Add darkos_shell to Python path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "airootfs" / "usr" / "local" / "bin"))
sys.path.insert(0, str(repo_root / "airootfs" / "usr" / "local" / "bin" / "darkos_shell"))

import actions
import ai_brain
import activity_detector
# assistant_trigger imports darkos_shell.ai_brain, while importing the full
# package would require GTK in this focused headless harness. Register the
# already-loaded brain module under its packaged name.
darkos_shell_stub = types.ModuleType("darkos_shell")
darkos_shell_stub.__path__ = []
sys.modules.setdefault("darkos_shell", darkos_shell_stub)
sys.modules.setdefault("darkos_shell.ai_brain", ai_brain)
import assistant_trigger

print("=" * 60)
print(" DARKOS PHASE 3 UNIT AND MOCK VERIFICATION SUITE")
print("=" * 60)

# Create a temporary sandbox bin directory for mock system utilities where needed
temp_dir = tempfile.mkdtemp(prefix="darkos-test-")
bin_dir = Path(temp_dir) / "bin"
bin_dir.mkdir(parents=True, exist_ok=True)
os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

# Helper to create mock executable scripts
def create_mock(name, script_content):
    p = bin_dir / name
    p.write_text(f"#!/usr/bin/env bash\n{script_content}\n")
    p.chmod(0o755)
    return p

# ── 1. Snapshot-Before-Act Verification ─────────────────────────────
print("\n[TEST 1] Snapshot-before-act verification...")
# Setup a mock btrfs command that creates snapshot subvolumes in .snapshots
btrfs_log = Path(temp_dir) / "btrfs.log"
create_mock("btrfs", f"""
echo "$@" >> "{btrfs_log}"
if [ "$1" = "subvolume" ] && [ "$2" = "snapshot" ]; then
    mkdir -p "$4"
    echo "Create snapshot of '$3' in '$4'"
    exit 0
fi
if [ "$1" = "subvolume" ] && [ "$2" = "list" ]; then
    find "{temp_dir}/.snapshots" -maxdepth 1 -mindepth 1 -type d | while read -r d; do
        b=$(basename "$d")
        echo "ID 256 gen 10 top level 5 path .snapshots/$b"
    done
    exit 0
fi
exit 0
""")

dispatcher = actions.ActionDispatcher()
# Point snapshot root to our sandbox
dispatcher._snapshot_enabled = True
dispatcher._snapshot_root = temp_dir

print("Triggering mutating action: set_volume(60)")
res = dispatcher.set_volume(60)
print(f"Action result: {res}")

snap_name = dispatcher.latest_snapshot()
print(f"Recorded snapshot: {snap_name}")
assert snap_name and snap_name.startswith("darkos-ai-"), f"Snapshot not recorded! Got {snap_name}"

# Query btrfs subvolume list
btrfs_list_out = subprocess.check_output(["btrfs", "subvolume", "list", temp_dir], text=True)
print("Raw 'btrfs subvolume list' output:")
print(btrfs_list_out.strip())
assert snap_name in btrfs_list_out, "Snapshot missing from subvolume list!"
print(">>> TEST 1 PASSED: Snapshot-before-act created verified btrfs snapshot.")

# A Btrfs system must fail closed if both direct and privileged snapshot
# creation fail. The protected action must never run without its safety net.
create_mock("btrfs", "exit 1")
create_mock("sudo", "exit 1")
blocked_dispatcher = actions.ActionDispatcher()
blocked_dispatcher._snapshot_enabled = True
blocked_dispatcher._snapshot_root = temp_dir
try:
    blocked_dispatcher.set_volume(50)
except actions.SnapshotError as exc:
    print(f"Snapshot failure correctly blocked action: {exc}")
else:
    raise AssertionError("Mutating action ran after snapshot failure")

# Restore the successful Btrfs mock for later protected actions.
create_mock("btrfs", f"""
echo "$@" >> "{btrfs_log}"
if [ "$1" = "subvolume" ] && [ "$2" = "snapshot" ]; then
    mkdir -p "$4"
    echo "Create snapshot of '$3' in '$4'"
    exit 0
fi
if [ "$1" = "subvolume" ] && [ "$2" = "list" ]; then
    find "{temp_dir}/.snapshots" -maxdepth 1 -mindepth 1 -type d | while read -r d; do
        b=$(basename "$d")
        echo "ID 256 gen 10 top level 5 path .snapshots/$b"
    done
    exit 0
fi
exit 0
""")

# ── 2. D-Bus / Hyprctl / Pamixer Control Verification ───────────────
print("\n[TEST 2] D-Bus / hyprctl / pamixer control verification...")
vol_file = Path(temp_dir) / "volume.txt"
vol_file.write_text("25")

create_mock("pamixer", f"""
if [ "$1" = "--get-volume" ]; then
    cat "{vol_file}"
    exit 0
fi
if [ "$1" = "--set-volume" ]; then
    echo "$2" > "{vol_file}"
    exit 0
fi
""")

hypr_state = Path(temp_dir) / "hypr_state.json"
hypr_state.write_text(json.dumps({"workspace": 1, "clients": []}))

create_mock("hyprctl", f"""
if [ "$1" = "clients" ]; then
    cat "{hypr_state}" | grep -o '"clients": *\\[[^]]*\\]' || echo "[]"
    exit 0
fi
if [ "$1" = "dispatch" ] && [ "$2" = "workspace" ]; then
    echo "Switched to workspace $3"
    exit 0
fi
if [ "$1" = "activewindow" ]; then
    echo '{{"title": "Terminal - the-void", "class": "the-void"}}'
    exit 0
fi
""")

# Text action markers do not receive provider-side schema validation. Invalid
# numeric types/ranges must be rejected before either a safety snapshot or a
# system command is attempted.
snapshot_before_invalid = dispatcher.latest_snapshot()
for invalid in (-1, 101, True, 20.5):
    invalid_result = dispatcher.set_volume(invalid)
    assert invalid_result.startswith("Volume error:"), invalid_result
    assert dispatcher.latest_snapshot() == snapshot_before_invalid
assert vol_file.read_text() == "25"

for invalid in (9, 101, False, 55.5):
    invalid_result = dispatcher.set_brightness(invalid)
    assert invalid_result.startswith("Brightness error:"), invalid_result
    assert dispatcher.latest_snapshot() == snapshot_before_invalid

for invalid in (0, 11, True, 2.5, "2.0"):
    invalid_result = dispatcher.switch_workspace(invalid)
    assert invalid_result.startswith("Workspace error:"), invalid_result
    assert dispatcher.latest_snapshot() == snapshot_before_invalid

# Test Volume Change
vol_before = subprocess.check_output(["pamixer", "--get-volume"], text=True).strip()
print(f"Volume before: {vol_before}%")
vol_action_res = dispatcher.set_volume(85)
print(f"Dispatcher output: {vol_action_res}")
vol_after = subprocess.check_output(["pamixer", "--get-volume"], text=True).strip()
print(f"Volume after: {vol_after}%")
assert vol_before == "25" and vol_after == "85", f"Volume change mismatch! {vol_before} -> {vol_after}"

# Test Workspace Switch
ws_action_res = dispatcher.switch_workspace("4")
print(f"Workspace action output: {ws_action_res}")
assert "Switched to workspace 4" in ws_action_res

print(">>> TEST 2 PASSED: D-Bus/hyprctl OS controls verified with before/after state.")

# ── 3. AT-SPI Generic In-App Control ────────────────────────────────
print("\n[TEST 3] AT-SPI generic control verification...")
# Test _atspi_do_action function
test_payload_click = json.dumps({"action": "click", "args": ["button", "Save"]})
test_payload_set_text = json.dumps({"action": "set_text", "args": ["entry", "Search", "DarkOS Query"]})

print("Testing AT-SPI action argument unpacking and payload structure:")
print(f"Click payload: {test_payload_click}")
print(f"Set text payload: {test_payload_set_text}")

# Test dispatcher wrappers without pretending a mock tree is a live AT-SPI app.
atspi_calls = []
real_atspi_do_action = actions._atspi_do_action
actions._atspi_do_action = lambda action, *args: (
    atspi_calls.append((action, args))
    or ("Clicked push button matching 'Submit'." if action == "click"
        else "Set entry 'Username'.")
)
click_res = dispatcher.atspi_click("push button", "Submit")
text_res = dispatcher.atspi_set_text("entry", "Username", "root")
assert click_res == "Clicked push button matching 'Submit'."
assert text_res == "Set entry 'Username'."
assert atspi_calls == [
    ("click", ("push button", "Submit")),
    ("set_text", ("entry", "Username", "root")),
]

def fail_atspi(_action, *_args):
    raise RuntimeError("no accessible control matched")

actions._atspi_do_action = fail_atspi
failure = dispatcher.atspi_click("push button", "Missing")
assert failure.startswith("Could not click") and "no accessible control" in failure
actions._atspi_do_action = real_atspi_do_action
print(f"Honest missing-control result: {failure}")
print(">>> TEST 3 PASSED: AT-SPI action dispatcher verified.")

# ── 4. Voice Round-Trip Pipeline ────────────────────────────────────
print("\n[TEST 4] Voice round-trip pipeline verification...")
brain = ai_brain.AIBrain(actions=dispatcher)

# Verify a WAV recording is uploaded with matching filename/content type.
dummy_audio = Path(temp_dir) / "sample.wav"
dummy_audio.write_bytes(b"RIFF" + (b"\0" * 64))
captured_request = {}

class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload

real_urlopen = urllib.request.urlopen

def fake_urlopen(request, timeout):
    captured_request["data"] = request.data
    captured_request["headers"] = dict(request.header_items())
    captured_request["timeout"] = timeout
    return FakeResponse(b'{"text":"hello darkos"}')

brain._groq_key = "test-key"
urllib.request.urlopen = fake_urlopen
try:
    stt_res = brain.process_voice(str(dummy_audio))
finally:
    urllib.request.urlopen = real_urlopen
assert stt_res == "hello darkos"
assert b'filename="sample.wav"' in captured_request["data"]
assert b"Content-Type: audio/wav" in captured_request["data"]
print(f"Mock Groq transcription: '{stt_res}' with valid WAV metadata")

# Exercise the real recorder process lifecycle. The mock parec emits a small
# WAV-like stream and records its arguments, proving we request a WAV container
# rather than writing headerless PCM under a misleading suffix.
recorder_log = Path(temp_dir) / "recorder.log"
create_mock("parec", f"""
printf '%s\\n' "$*" > "{recorder_log}"
trap 'exit 0' TERM
printf 'RIFF'
head -c 64 /dev/zero
while :; do sleep 0.1; done
""")
trigger = assistant_trigger.AssistantTrigger(brain)
recordings = []
trigger.add_listener(recordings.append)
assert trigger.on_push_to_talk_start() is True
time.sleep(0.2)
assert trigger.on_push_to_talk_stop() is True
assert len(recordings) == 1
recording_path = Path(recordings[0])
assert recording_path.suffix == ".wav"
assert recording_path.read_bytes().startswith(b"RIFF")
assert "--file-format=wav" in recorder_log.read_text()
recording_path.unlink()

# Verify the packaged local TTS fallback reports success only when its command
# actually succeeds, and ffplay receives noninteractive audio-only arguments.
playback_log = Path(temp_dir) / "playback.log"
create_mock("ffplay", f'printf "%s\\n" "$*" > "{playback_log}"; exit 0')
assert ai_brain._play_audio(str(dummy_audio), 2.0) is True
ffplay_args = playback_log.read_text()
assert "-nodisp" in ffplay_args and "-autoexit" in ffplay_args

espeak_log = Path(temp_dir) / "espeak.log"
create_mock("espeak-ng", f'printf "%s\\n" "$*" > "{espeak_log}"; exit 0')
brain._groq_key = ""
assert brain.speak("DarkOS voice test", timeout=2.0) is True
assert "DarkOS voice test" in espeak_log.read_text()
print(">>> TEST 4 PASSED: STT metadata and successful TTS playback routes verified.")

# ── 5. Chat Round-Trip & Action Execution ───────────────────────────
print("\n[TEST 5] Chat round-trip and multi-action execution...")
# Simulate OpenRouter response with embedded action markers
simulated_chat_reply = (
    "Adjusting system settings now.\n"
    "[ACTION] set_volume(70)\n"
    "[ACTION] switch_workspace(3)\n"
)
actions_summary, pending_explain = ai_brain._dispatch_actions(
    simulated_chat_reply, dispatcher
)
print("Input LLM reply:")
print(simulated_chat_reply.strip())
print("Executed actions summary:")
print(actions_summary)
assert "Volume set to 70%." in actions_summary
assert "Switched to workspace 3." in actions_summary
assert pending_explain is None

# Private/inherited methods must never be reachable from model output.
blocked_summary, _ = ai_brain._dispatch_actions(
    "[ACTION] latest_snapshot()", dispatcher
)
assert "unsupported action 'latest_snapshot'" in blocked_summary

# Every provider request must receive the action contract as a system prompt.
prepared = ai_brain._with_system_prompt([{"role": "user", "content": "volume 20"}])
assert prepared[0]["role"] == "system"
assert "[ACTION] set_volume(0-100)" in prepared[0]["content"]

tool_reply = ai_brain._message_to_reply({
    "content": "Changing it now.",
    "tool_calls": [{
        "function": {
            "name": "set_volume",
            "arguments": '{"level": 42}',
        }
    }],
})
assert tool_reply == "Changing it now.\n[ACTION] set_volume(42)"

# Exercise the actual OpenRouter request builder and native tool-call response
# conversion without making a network request or requiring a real credential.
openrouter_request = {}

def fake_openrouter_urlopen(request, timeout):
    openrouter_request["payload"] = json.loads(request.data.decode("utf-8"))
    openrouter_request["headers"] = dict(request.header_items())
    openrouter_request["timeout"] = timeout
    return FakeResponse(json.dumps({
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "switch_workspace",
                        "arguments": '{"index": 2}',
                    }
                }],
            }
        }]
    }).encode("utf-8"))

brain._openrouter_key = "test-openrouter-key"
urllib.request.urlopen = fake_openrouter_urlopen
try:
    provider_reply = brain.chat([{"role": "user", "content": "workspace two"}])
finally:
    urllib.request.urlopen = real_urlopen
assert provider_reply == "[ACTION] switch_workspace(2)"
assert openrouter_request["payload"]["model"] == "openrouter/free"
assert openrouter_request["payload"]["messages"][0]["role"] == "system"
assert openrouter_request["payload"]["tools"] == ai_brain._OPENROUTER_TOOLS
assert openrouter_request["payload"]["tool_choice"] == "auto"

# Public operations must not race through AIBrain's provider result slot.
concurrent_brain = ai_brain.AIBrain()
concurrent_results = {}

def delayed_provider(messages, _timeout):
    concurrent_brain._last_result = messages[-1]["content"]
    time.sleep(0.05)
    return True

concurrent_brain._try_openrouter = delayed_provider
workers = [
    threading.Thread(
        target=lambda value=value: concurrent_results.setdefault(
            value,
            concurrent_brain.chat([{"role": "user", "content": value}]),
        )
    )
    for value in ("alpha", "beta")
]
for worker in workers:
    worker.start()
for worker in workers:
    worker.join()
assert concurrent_results == {"alpha": "alpha", "beta": "beta"}

assert ai_brain._parse_args(r'"entry", "Search", "say \"hello, DarkOS\""') == [
    "entry", "Search", 'say "hello, DarkOS"'
]
try:
    ai_brain._parse_args('__import__("os").system("false")')
except ValueError:
    pass
else:
    raise AssertionError("action parser accepted executable Python syntax")

# The explain action must cause a second brain call and return an explanation,
# not the extracted error text or machine-readable marker.
class ExplainActions:
    @staticmethod
    def explain(_target):
        return "FATAL: database connection timed out"

explain_brain = ai_brain.AIBrain(actions=ExplainActions())
chat_calls = []
chat_replies = iter([
    'I will inspect that.\n[ACTION] explain("active")',
    "The app could not reach its database before the timeout. Check the service and network.",
])

def fake_chat(messages, timeout=30.0):
    chat_calls.append(messages)
    return next(chat_replies)

explain_brain.chat = fake_chat
explanation, explain_summary = explain_brain.process_chat("Explain this error")
assert len(chat_calls) == 2
assert "FATAL: database connection timed out" in chat_calls[1][-1]["content"]
assert "could not reach its database" in explanation
assert "[ACTION]" not in explanation
assert explain_summary == ""
print(f"Explain follow-up response: {explanation}")
print(">>> TEST 5 PASSED: Chat action extraction and execution verified.")

# ── 6. Context-Aware Shell Activity Detection ───────────────────────
print("\n[TEST 6] Context-aware shell activity classification...")
detector = activity_detector.ActivityDetector()
events_received = []
detector.add_listener(lambda name, data: events_received.append((name, data["dock_highlight"])))

test_cases = [
    ("nvim /etc/darkos.conf", "coding", "terminal"),
    ("Steam - Proton", "gaming", "store"),
    ("LibreOffice Writer", "writing", "notes"),
    ("mpv sample.mkv", "media", "browser"),
    ("System Monitor", "default", None),
]

for title, expected_prof, expected_dock in test_cases:
    # Set active window mock output
    create_mock("hyprctl", f"""
if [ "$1" = "activewindow" ]; then
    echo '{{"title": "{title}", "class": "app"}}'
    exit 0
fi
""")
    # Force detector poll
    detected = detector._detect_activity()
    profile_data = activity_detector.ACTIVITY_PROFILES.get(detected)
    print(f"Window: '{title}' -> Detected: '{detected}' | Dock highlight: '{profile_data['dock_highlight']}'")
    assert detected == expected_prof, f"Expected {expected_prof}, got {detected}"
    assert profile_data["dock_highlight"] == expected_dock

detector._notify_listeners("coding")
assert events_received[-1] == ("coding", "terminal")

print(">>> TEST 6 PASSED: Context-aware detector accurately identifies app workloads.")

# ── 7. Explain This Workflow ─────────────────────────────────────────
print("\n[TEST 7] 'Explain this' text extraction and workflow...")
# Verify the extraction helper carries the real active-window identity into
# the AT-SPI subprocess and returns its selected-text result. The live VMware
# verifier exercises the embedded tree walk against two real GTK apps.
real_command = actions._command
extraction_calls = []

def scoped_extraction_command(cmd, timeout=5.0):
    extraction_calls.append(cmd)
    if cmd[:3] == ["hyprctl", "activewindow", "-j"]:
        return json.dumps({"title": "Focused Error Window", "class": "error-app"})
    if cmd[:2] == ["python3", "-c"]:
        identity = json.loads(cmd[3])
        assert identity == {"title": "Focused Error Window", "class": "error-app"}
        assert "scoped_frames" in cmd[2] and "selected_text" in cmd[2]
        return "SELECTED_FATAL: focused database timeout"
    raise AssertionError(f"unexpected extraction command: {cmd}")

actions._command = scoped_extraction_command
try:
    scoped_text = actions._atspi_get_selected_text()
finally:
    actions._command = real_command
assert scoped_text == "SELECTED_FATAL: focused database timeout"
assert len(extraction_calls) == 2

create_mock("hyprctl", """
if [ "$1" = "activewindow" ]; then
    echo '{"title": "Error: segmentation fault at 0x7fff489", "class": "app"}'
    exit 0
fi
""")
extracted = dispatcher.explain("active")
print(f"Extracted error text: '{extracted}'")
assert "segmentation fault" in extracted

print("\n" + "=" * 60)
print(" ALL 7 UNIT AND MOCK VERIFICATION GROUPS PASSED")
print("=" * 60)
shutil.rmtree(temp_dir, ignore_errors=True)
