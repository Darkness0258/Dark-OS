#!/usr/bin/env python3
"""Wake-word and push-to-talk trigger for the AI assistant.

Two modes:
- **push-to-talk**: hold a keybinding (default: SUPER+SPACE) to record, release
  to send. Simple, reliable, no false positives.
- **wake-word**: continuously listen for a keyword (e.g. "Hey DarkOS") using a
  local wake-word engine. More natural but heavier on CPU.

The trigger emits a callback with audio bytes (from a temp file) on activation.
"""

import os
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from darkos_shell.ai_brain import AIBrain


class AssistantTrigger:
    """Dispatches AI activation via push-to-talk or wake-word."""

    MODE_PUSH_TO_TALK = "push-to-talk"
    MODE_WAKE_WORD = "wake-word"

    def __init__(self, brain: AIBrain, mode: str | None = None):
        self.brain = brain
        self.mode = mode or os.environ.get("DARKOS_TRIGGER_MODE", self.MODE_PUSH_TO_TALK)
        self._active = False
        self._listeners = []
        self._wake_word_process = None
        self._wake_word_thread = None
        self._recording_process = None
        self._recording_path = None
        self._recording_sink = None

    @property
    def is_recording(self) -> bool:
        return self._active and self._recording_process is not None

    def start(self):
        """Begin listening for activation."""
        if self.mode == self.MODE_WAKE_WORD:
            self._start_wake_word()
        # push-to-talk is triggered by keybinding; no background work needed

    def stop(self):
        """Stop all listening."""
        self._active = False
        self._stop_wake_word()
        self._stop_recording()

    def add_listener(self, callback):
        """Register callback(audio_path: str) for when the assistant activates."""
        self._listeners.append(callback)

    def on_push_to_talk_start(self):
        """Begin recording (called from keybinding press)."""
        if self._active:
            return True
        path = self._start_recording()
        self._active = path is not None
        return self._active

    def on_push_to_talk_stop(self):
        """Stop recording and dispatch (called from keybinding release)."""
        if not self._active:
            return False
        self._active = False
        audio_path = self._stop_recording()
        if audio_path:
            self._dispatch(audio_path)
            return True
        return False

    def on_wake_word_detected(self):
        """Called by the wake-word engine when the keyword is heard."""
        self._dispatch_wake()

    # ── Push-to-talk recording ─────────────────────────────────────────

    def _start_recording(self):
        recorder = _find_binary(["parec", "arecord", "ffmpeg"])
        if not recorder:
            return None
        recorder_name = Path(recorder).name
        suffix = ".webm" if recorder_name == "ffmpeg" else ".wav"
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self._recording_path = path
        try:
            if recorder_name == "parec":
                # parec otherwise emits headerless raw PCM. Groq accepts WAV,
                # so explicitly request a WAV container matching the suffix.
                cmd = [
                    recorder, "--file-format=wav", "--format=s16le",
                    "--rate=16000", "--channels=1", "--latency-msec=100",
                ]
                self._recording_sink = open(path, "wb")
                self._recording_process = subprocess.Popen(
                    cmd, stdout=self._recording_sink, stderr=subprocess.DEVNULL
                )
            elif recorder_name == "arecord":
                cmd = [
                    recorder, "-q", "-f", "S16_LE", "-r", "16000",
                    "-c", "1", "-d", "30", path,
                ]
                self._recording_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            else:
                cmd = [
                    recorder, "-f", "pulse", "-i", "default", "-ar", "16000",
                    "-ac", "1", "-c:a", "libopus", "-y", path,
                ]
                self._recording_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            return path
        except (OSError, ValueError):
            if self._recording_sink is not None:
                self._recording_sink.close()
                self._recording_sink = None
            Path(path).unlink(missing_ok=True)
            self._recording_path = None
            self._recording_process = None
            return None

    def _stop_recording(self):
        if self._recording_process is None:
            if self._recording_sink is not None:
                self._recording_sink.close()
                self._recording_sink = None
            return None
        try:
            self._recording_process.terminate()
            self._recording_process.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self._recording_process.kill()
            except OSError:
                pass
        proc = self._recording_process
        self._recording_process = None
        path = self._recording_path
        self._recording_path = None
        if self._recording_sink is not None:
            self._recording_sink.close()
            self._recording_sink = None
        if not path or not Path(path).is_file() or Path(path).stat().st_size <= 44:
            if path:
                Path(path).unlink(missing_ok=True)
            return None
        return path

    # ── Wake-word engine ───────────────────────────────────────────────

    def _start_wake_word(self):
        """Launch a local wake-word detection process."""
        engine = _find_binary(["openwakeword", "porcupine"])
        if not engine:
            print(
                "DarkOS: no wake-word engine found. "
                "Install openwakeword or set DARKOS_TRIGGER_MODE=push-to-talk.",
                file=sys.stderr,
            )
            return
        try:
            self._wake_word_process = subprocess.Popen(
                [engine, "--model", "hey_darkos"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            self._wake_word_thread = threading.Thread(
                target=self._monitor_wake_word,
                daemon=True,
            )
            self._wake_word_thread.start()
        except (OSError, ValueError):
            pass

    def _monitor_wake_word(self):
        """Consume detector output and dispatch on a positive detection."""
        process = self._wake_word_process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            normalized = line.strip().lower()
            if not normalized:
                continue
            detected = False
            try:
                event = json.loads(normalized)
                detected = bool(event.get("detected"))
                if not detected:
                    score = float(event.get("score", 0.0))
                    detected = score >= 0.5
            except (TypeError, ValueError, json.JSONDecodeError):
                detected = (
                    "hey_darkos" in normalized or "hey darkos" in normalized
                ) and any(word in normalized for word in ("detect", "trigger", "wake"))
            if detected:
                self.on_wake_word_detected()

    def _stop_wake_word(self):
        if self._wake_word_process is not None:
            try:
                self._wake_word_process.terminate()
                self._wake_word_process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self._wake_word_process.kill()
                except OSError:
                    pass
            self._wake_word_process = None
            self._wake_word_thread = None

    # ── Dispatch ───────────────────────────────────────────────────────

    def _dispatch(self, audio_path: str):
        if audio_path and Path(audio_path).exists():
            for callback in self._listeners:
                try:
                    callback(audio_path)
                except Exception:
                    pass

    def _dispatch_wake(self):
        # Wake-word activated: record 5s of audio then dispatch
        path = self._start_recording()
        if path is None:
            return
        # Record for 5 seconds after wake word
        import time as _time
        _time.sleep(5.0)
        audio_path = self._stop_recording()
        self._dispatch(audio_path)


# ── Helpers ─────────────────────────────────────────────────────────

def _find_binary(names: list[str]) -> str | None:
    """Return the first binary found on PATH, or None."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None
