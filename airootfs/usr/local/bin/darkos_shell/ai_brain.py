#!/usr/bin/env python3
"""Phase 3 AI brain: STT + LLM + TTS with cloud-first, local fallback.

Cloud providers (Groq Whisper, OpenRouter, edge-tts) are preferred because
the target hardware (i5-6440HQ, no CUDA) cannot run a capable local LLM.
Local fallback covers offline basic commands.

All public methods return within their timeout — the shell UI never blocks
on an AI backend call.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class AIBrain:
    """Voice + text AI backend with graceful degradation."""

    def __init__(self):
        self._groq_key = os.environ.get("DARKOS_GROQ_API_KEY", "")
        self._openrouter_key = os.environ.get("DARKOS_OPENROUTER_API_KEY", "")
        self._model = os.environ.get("DARKOS_LLM_MODEL", "meta-llama/llama-4-maverick:free")
        self._stt_model = os.environ.get("DARKOS_STT_MODEL", "whisper-large-v3")
        self._tts_voice = os.environ.get("DARKOS_TTS_VOICE", "en-US-AriaNeural")
        self._local_whisper = os.environ.get("DARKOS_LOCAL_WHISPER", "")
        self._local_llm = os.environ.get("DARKOS_LOCAL_LLM", "")
        self._offline_mode = False
        self._last_error = None

    # ── Public API ─────────────────────────────────────────────────────

    def process_voice(self, audio_path: str, timeout: float = 15.0) -> str:
        """Transcribe audio to text. Returns empty string on failure."""
        if self._try_groq_stt(audio_path, timeout):
            return self._last_result
        if self._try_local_whisper(audio_path, timeout):
            return self._last_result
        return ""

    def chat(self, messages: list, timeout: float = 30.0) -> str:
        """Send messages to the brain. Returns error stub on failure."""
        if self._try_openrouter(messages, timeout):
            return self._last_result
        if self._try_local_llm(messages, timeout):
            return self._last_result
        return "Not executed: no AI backend is reachable."

    def speak(self, text: str, timeout: float = 10.0) -> bool:
        """Convert text to speech and play it."""
        if self._try_edge_tts(text, timeout):
            return True
        if self._try_piper_tts(text, timeout):
            return True
        return False

    @property
    def available(self) -> bool:
        """True if at least one backend is reachable."""
        return not self._offline_mode or bool(self._local_whisper or self._local_llm)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # ── Cloud STT: Groq Whisper ────────────────────────────────────────

    def _try_groq_stt(self, audio_path: str, timeout: float) -> bool:
        if not self._groq_key:
            return False
        try:
            import urllib.request
            boundary = "----FormBoundaryDarkOS"
            with open(audio_path, "rb") as fh:
                audio_data = fh.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="model"\r\n\r\n'
                f"{self._stt_model}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="audio.webm"\r\n'
                f"Content-Type: audio/webm\r\n\r\n"
            ).encode("utf-8") + audio_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                data=body,
                headers={
                    "Authorization": f"Bearer {self._groq_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            self._last_result = result.get("text", "").strip()
            self._last_error = None
            self._offline_mode = False
            return bool(self._last_result)
        except Exception as exc:
            self._last_error = f"Groq STT failed: {exc}"
            return False

    # ── Local STT: whisper.cpp or faster-whisper ───────────────────────

    def _try_local_whisper(self, audio_path: str, timeout: float) -> bool:
        binary = self._local_whisper or _find_binary(["whisper", "whisper-cli", "faster-whisper"])
        if not binary:
            return False
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_base = str(Path(tmp) / "transcript")
                cmd = [binary, "-m", "base.en", "-otxt", "-of", out_base, audio_path]
                completed = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout
                )
                txt_path = out_base + ".txt"
                if Path(txt_path).exists():
                    self._last_result = Path(txt_path).read_text(encoding="utf-8").strip()
                else:
                    self._last_result = ""
                self._last_error = None
                return bool(self._last_result)
        except Exception as exc:
            self._last_error = f"Local STT failed: {exc}"
            return False

    # ── Cloud Brain: OpenRouter ────────────────────────────────────────

    def _try_openrouter(self, messages: list, timeout: float) -> bool:
        if not self._openrouter_key:
            return False
        try:
            import urllib.request
            payload = json.dumps({
                "model": self._model,
                "messages": messages,
                "max_tokens": 1024,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {self._openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://darkos.dev",
                    "X-Title": "DarkOS Assistant",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            self._last_result = (
                result.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            self._last_error = None
            self._offline_mode = False
            return bool(self._last_result)
        except Exception as exc:
            self._last_error = f"OpenRouter failed: {exc}"
            return False

    # ── Local Brain: Ollama or compatible ──────────────────────────────

    def _try_local_llm(self, messages: list, timeout: float) -> bool:
        endpoint = os.environ.get("DARKOS_LOCAL_LLM_ENDPOINT", "http://localhost:11434")
        try:
            import urllib.request
            payload = json.dumps({
                "model": self._model,
                "messages": messages,
                "stream": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{endpoint}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            self._last_result = result.get("message", {}).get("content", "")
            self._last_error = None
            self._offline_mode = True
            return bool(self._last_result)
        except Exception as exc:
            self._last_error = f"Local LLM failed: {exc}"
            return False

    # ── Cloud TTS: edge-tts ────────────────────────────────────────────

    def _try_edge_tts(self, text: str, timeout: float) -> bool:
        try:
            edge_tts = _import_or_warn("edge_tts", "pip install edge-tts")
            if edge_tts is None:
                return False
            import asyncio
            mp3_path = tempfile.mktemp(suffix=".mp3")
            async def _speak():
                communicate = edge_tts.Communicate(text, self._tts_voice)
                await communicate.save(mp3_path)
            asyncio.run(_speak())
            if not Path(mp3_path).exists():
                return False
            _play_audio(mp3_path, timeout)
            Path(mp3_path).unlink(missing_ok=True)
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = f"edge-tts failed: {exc}"
            return False

    # ── Local TTS: Piper ───────────────────────────────────────────────

    def _try_piper_tts(self, text: str, timeout: float) -> bool:
        piper = _find_binary(["piper"])
        if not piper:
            return False
        try:
            model = os.environ.get("DARKOS_PIPER_MODEL", "")
            if not model or not Path(model).exists():
                self._last_error = "Piper model path not set (DARKOS_PIPER_MODEL)"
                return False
            wav_path = tempfile.mktemp(suffix=".wav")
            cmd = [piper, "--model", model, "--output_file", wav_path]
            completed = subprocess.run(
                cmd, input=text, text=True, capture_output=True, timeout=timeout
            )
            if completed.returncode != 0 or not Path(wav_path).exists():
                return False
            _play_audio(wav_path, timeout)
            Path(wav_path).unlink(missing_ok=True)
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = f"Piper TTS failed: {exc}"
            return False


# ── Helpers ─────────────────────────────────────────────────────────

def _find_binary(names: list[str]) -> str | None:
    """Return the first binary found on PATH, or None."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def _import_or_warn(module: str, install_hint: str):
    """Import a module, printing a warning if missing."""
    import importlib
    try:
        return importlib.import_module(module)
    except ImportError:
        print(
            f"DarkOS: optional module '{module}' not found — {install_hint}",
            file=sys.stderr,
        )
        return None


def _play_audio(path: str, timeout: float):
    """Play an audio file using the system's default player."""
    players = ["ffplay", "paplay", "aplay", "mpv"]
    player = _find_binary(players)
    if player is None:
        return
    try:
        if player == "ffplay":
            subprocess.run(
                [player, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                timeout=timeout,
            )
        elif player == "paplay":
            subprocess.run([player, path], timeout=timeout)
        else:
            subprocess.run([player, path], timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        pass
