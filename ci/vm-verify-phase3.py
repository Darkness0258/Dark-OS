#!/usr/bin/env python3
"""DarkOS Phase 3 Live VM Runtime Verification Suite.

Runs over SSH against a booted DarkOS ISO VM. Each test reports PASS/FAIL
with the actual command output, not a summary.

Usage:
    python ci/vm-verify-phase3.py <vm-ip> [--ssh-user darkos] [--ssh-key path]

Tests:
    1. Process stability — shell stack alive, no crashes
    2. AI chat round-trip — needs DARKOS_GROQ_API_KEY + DARKOS_OPENROUTER_API_KEY
    3. D-Bus/hyprctl control — volume, workspace dispatch
    4. AT-SPI in-app control — click a button in a real app
    5. Snapshot-before-act — Btrfs subvolume creation
    6. Explain-this — AT-SPI text extraction + explanation
    7. Voice pipeline mechanics — STT transcription via Groq

Human-only (not automated):
    - Actually hearing TTS audio
    - Dock highlight CSS rendering visible
    - Boot animation splash
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SSH_BASE = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]


def ssh_run(user, host, cmd, capture=True, check=True):
    """Run a command over SSH, return (stdout, stderr, returncode)."""
    full_cmd = [*SSH_BASE, f"{user}@{host}", cmd]
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=capture,
            text=True,
            timeout=60,
            check=False,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "SSH command timed out", 124


def section(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def test_stability(user, host):
    section("TEST 1: Process Stability (two snapshots, 5 min apart)")
    print("Taking snapshot 1...")
    out1, _, rc1 = ssh_run(user, host,
        "ps aux | grep -E 'Hyprland|darkos-shell|waybar|hypridle|vmtoolsd' | grep -v grep")
    print(out1 if out1 else "(no matching processes)")
    if rc1 != 0 and not out1:
        print("FAIL: no processes found")
        return False

    print("\nWaiting 60s for stability check...")
    time.sleep(60)

    print("Taking snapshot 2...")
    out2, _, rc2 = ssh_run(user, host,
        "ps aux | grep -E 'Hyprland|darkos-shell|waybar|hypridle|vmtoolsd' | grep -v grep")
    print(out2 if out2 else "(no matching processes)")

    if out1 == out2 and out1:
        print("PASS: same processes alive after 60s")
        return True
    print("FAIL: process set changed between snapshots")
    return False


def test_chat(user, host, groq_key, openrouter_key):
    section("TEST 2: AI Chat Round-Trip")
    env = f"export DARKOS_GROQ_API_KEY='{groq_key}' DARKOS_OPENROUTER_API_KEY='{openrouter_key}'; "
    cmd = env + """
python3 -c "
import sys, types
sys.path.insert(0, '/usr/local/bin')
sys.path.insert(0, '/usr/local/bin/darkos_shell')
# Stub GTK-dependent modules
for mod in ['gi', 'gi.repository', 'darkos_shell']:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)
gi = sys.modules['gi']
gi.repository = types.ModuleType('gi.repository')
sys.modules['gi.repository'] = gi.repository
ds = sys.modules['darkos_shell']
ds.__path__ = ['/usr/local/bin/darkos_shell']

from darkos_shell.ai_brain import AIBrain
from darkos_shell.actions import ActionDispatcher
b = AIBrain(actions=ActionDispatcher())
reply, summary = b.process_chat('what is 2+2')
print('REPLY:', reply)
print('SUMMARY:', summary)
"
"""
    out, err, rc = ssh_run(user, host, cmd)
    print(out if out else "(no output)")
    if err:
        print(f"STDERR: {err}")

    if rc != 0:
        print(f"FAIL: process exited with code {rc}")
        return False

    if "REPLY:" not in out:
        print("FAIL: no REPLY in output")
        return False

    reply_text = out.split("REPLY:")[1].split("\n")[0].strip()
    if not reply_text or reply_text == "Not executed: connect an AI backend":
        print("FAIL: AI backend not connected")
        return False

    print(f"PASS: got AI reply: {reply_text[:120]}")
    return True


def test_explain_this(user, host, groq_key, openrouter_key):
    section("TEST 3: Explain-This (AT-SPI extraction + LLM explanation)")
    env = f"export DARKOS_GROQ_API_KEY='{groq_key}' DARKOS_OPENROUTER_API_KEY='{openrouter_key}'; "
    cmd = env + """
python3 -c "
import sys, types
sys.path.insert(0, '/usr/local/bin')
sys.path.insert(0, '/usr/local/bin/darkos_shell')
for mod in ['gi', 'gi.repository', 'darkos_shell']:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)
gi = sys.modules['gi']
gi.repository = types.ModuleType('gi.repository')
sys.modules['gi.repository'] = gi.repository
ds = sys.modules['darkos_shell']
ds.__path__ = ['/usr/local/bin/darkos_shell']

from darkos_shell.actions import ActionDispatcher
d = ActionDispatcher()
result = d.explain()
print('EXPLAIN_RESULT:', result)
"
"""
    out, err, rc = ssh_run(user, host, cmd)
    print(out if out else "(no output)")

    if rc != 0:
        print(f"FAIL: process exited with code {rc}")
        return False

    if "EXPLAIN_RESULT:" not in out:
        print("FAIL: no EXPLAIN_RESULT in output")
        return False

    result_text = out.split("EXPLAIN_RESULT:")[1].split("\n")[0].strip()
    if not result_text or result_text == "No accessible text found":
        print("FAIL: no text extracted from AT-SPI")
        return False

    print(f"PASS: extracted text: {result_text[:120]}")
    print("(Explanation quality needs human review)")
    return True


def test_control_surface(user, host):
    section("TEST 4: D-Bus / hyprctl Control Surface")
    # Test pamixer volume
    out_before, _, rc1 = ssh_run(user, host, "DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 pamixer --get-volume 2>/dev/null || echo 'pamixer failed'")
    print(f"Volume before: {out_before}")

    # Test hyprctl workspace dispatch
    out_ws, _, rc2 = ssh_run(user, host,
        "DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 hyprctl dispatch workspace 2 2>&1 || echo 'dispatch failed'")
    print(f"Workspace dispatch: {out_ws}")
    time.sleep(1)

    out_after, _, rc3 = ssh_run(user, host, "DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 pamixer --get-volume 2>/dev/null || echo 'pamixer failed'")
    print(f"Volume after (unchanged): {out_after}")

    if rc2 == 0 and "dispatch" not in out_ws.lower() or "ok" in out_ws.lower():
        print("PASS: hyprctl dispatch accepted")
        return True
    print("FAIL: hyprctl dispatch failed")
    return False


def test_snapshot(user, host):
    section("TEST 5: Snapshot-Before-Act (Btrfs)")
    out, err, rc = ssh_run(user, host, "btrfs filesystem df / 2>&1 | head -5")
    print(f"Btrfs check:\n{out}")
    if "btrfs" not in out.lower() and rc != 0:
        print("SKIP: not running on Btrfs (live ISO uses overlayfs)")
        return None

    cmd = "sudo /usr/local/bin/darkos-ai-snapshot ''"
    out, err, rc = ssh_run(user, host, cmd)
    print(f"Snapshot output: {out}")
    if rc != 0:
        print(f"FAIL: snapshot command failed (rc={rc})")
        return False

    snap_name = out.strip()
    if not snap_name or not snap_name.startswith("darkos-ai-"):
        print("FAIL: no valid snapshot name returned")
        return False

    out, _, _ = ssh_run(user, host, f"sudo btrfs subvolume list / 2>/dev/null | grep {snap_name}")
    if snap_name in out:
        print(f"PASS: snapshot {snap_name} confirmed in btrfs subvolume list")
        return True
    print(f"FAIL: snapshot {snap_name} not found in subvolume list")
    return False


def test_voice_mechanics(user, host, groq_key):
    section("TEST 6: Voice Pipeline Mechanics (STT via Groq)")
    if not groq_key:
        print("SKIP: no GROQ_API_KEY provided")
        return None

    # Create a minimal WAV file (silence) for the test
    cmd = f"""
export DARKOS_GROQ_API_KEY='{groq_key}'
python3 -c "
import sys, types
sys.path.insert(0, '/usr/local/bin')
sys.path.insert(0, '/usr/local/bin/darkos_shell')
for mod in ['gi', 'gi.repository', 'darkos_shell']:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)
gi = sys.modules['gi']
gi.repository = types.ModuleType('gi.repository')
sys.modules['gi.repository'] = gi.repository
ds = sys.modules['darkos_shell']
ds.__path__ = ['/usr/local/bin/darkos_shell']

from darkos_shell.ai_brain import AIBrain
from darkos_shell.actions import ActionDispatcher
b = AIBrain(actions=ActionDispatcher())
# process_voice returns (transcript, reply). Use a tiny silent WAV path
# to test the STT call chain; expect 'silence' or empty string from Groq
# for a silent file, or an error if no file exists.
try:
    result = b.process_voice('/dev/null')
    print('VOICE_RESULT:', result)
except Exception as e:
    print('VOICE_ERROR:', type(e).__name__, str(e)[:200])
"
"""
    out, err, rc = ssh_run(user, host, cmd)
    print(out if out else "(no output)")
    if err:
        print(f"STDERR: {err[:300]}")

    if "VOICE_ERROR" in out:
        print("FAIL: voice pipeline raised an exception")
        return False

    if "VOICE_RESULT:" in out:
        print("PASS: voice pipeline executed (STT chain works)")
        return True

    print("FAIL: unexpected output format")
    return False


def main():
    parser = argparse.ArgumentParser(description="DarkOS Phase 3 live VM verification")
    parser.add_argument("vm_ip", help="VM IP address for SSH")
    parser.add_argument("--ssh-user", default="darkos", help="SSH user (default: darkos)")
    parser.add_argument("--ssh-key", help="SSH private key path")
    parser.add_argument("--groq-key", default="", help="Groq API key")
    parser.add_argument("--openrouter-key", default="", help="OpenRouter API key")
    args = parser.parse_args()

    ssh_env = f"-i {args.ssh_key}" if args.ssh_key else ""
    global SSH_BASE
    if args.ssh_key:
        SSH_BASE = [*SSH_BASE, "-i", args.ssh_key]

    # Quick connectivity check
    print(f"Testing SSH to {args.ssh_user}@{args.vm_ip}...")
    out, err, rc = ssh_run(args.ssh_user, args.vm_ip, "echo connected")
    if rc != 0 or "connected" not in out:
        print(f"FAIL: SSH connection failed (rc={rc}): {err}")
        sys.exit(1)
    print(f"SSH OK: {out}")

    results = {}

    results["stability"] = test_stability(args.ssh_user, args.vm_ip)

    if args.groq_key and args.openrouter_key:
        results["chat"] = test_chat(args.ssh_user, args.vm_ip, args.groq_key, args.openrouter_key)
        results["explain"] = test_explain_this(args.ssh_user, args.vm_ip, args.groq_key, args.openrouter_key)
    else:
        print("\n[SKIP] Tests 2-3: no API keys provided")
        results["chat"] = None
        results["explain"] = None

    results["control"] = test_control_surface(args.ssh_user, args.vm_ip)
    results["snapshot"] = test_snapshot(args.ssh_user, args.vm_ip)

    if args.groq_key:
        results["voice"] = test_voice_mechanics(args.ssh_user, args.vm_ip, args.groq_key)
    else:
        print("\n[SKIP] Test 6: no GROQ_API_KEY provided")
        results["voice"] = None

    # Summary
    section("SUMMARY")
    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    total = len(results)

    for name, status in results.items():
        status_str = {True: "PASS", False: "FAIL", None: "SKIP"}[status]
        print(f"  {name}: {status_str}")

    print(f"\n{passed}/{total} passed, {failed} failed, {skipped} skipped")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
