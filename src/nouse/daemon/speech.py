"""
nouse.daemon.speech — Speech input/output for Nous
=========================================================================

Gives Nous "ears" (hearing) and "voice" (speech).

Hearing (STT — Speech-to-Text):
  - Temporal Lobe (Wernicke's area): language comprehension
  - Captures audio via arecord/ffmpeg
  - Transcribes with Whisper (local) or cloud API
  - Feeds transcriptions into knowledge graph as temporal_lobe concepts

Voice (TTS — Text-to-Speech):
  - Frontal Lobe (Broca's area): speech production
  - Generates speech from Nous's output
  - Uses Piper (local) or edge-tts (cloud) or pyttsx3 (fallback)
  - Speaks what Nous knows — closes the output loop

The speech module completes Nous's sensorimotor loop:
  Hear (Temporal) → Understand (Parietal) → Think (Frontal) → Speak (Broca)

This mirrors the biological dual-stream model:
  - Dorsal stream: "where" pathway (parietal) — spatial/structural
  - Ventral stream: "what" pathway (temporal) — meaning/content
  - Broca's area (frontal): production/articulation
  - Wernicke's area (temporal): comprehension/understanding

Dependencies:
- ffmpeg + arecord for audio capture (always available on Linux)
- whisper (local STT) or cloud API
- piper (local TTS) or edge-tts (cloud) or pyttsx3 (fallback)
"""
from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("nouse.speech")

#: Opt-in-grind (daemon-teststart 2026-10-11): mikrofoninspelning är AV som
#: default. Sätt NOUSE_MIC_ENABLED=1/true/yes/on för explicit samtycke.
#: Legacy NOUSE_SPEECH_LISTEN_ENABLED hedras som alias men parsas strikt
#: ("0"/"false"/"off"/"" = av — tidigare gjorde bool("0") den alltid sann).
_OPT_IN_TRUE = {"1", "true", "yes", "on"}


def _parse_opt_in(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _OPT_IN_TRUE


def is_mic_enabled() -> bool:
    """True endast vid explicit opt-in via NOUSE_MIC_ENABLED (eller legacy
    NOUSE_SPEECH_LISTEN_ENABLED satt till ett sant värde)."""
    if _parse_opt_in(os.getenv("NOUSE_MIC_ENABLED")):
        return True
    return _parse_opt_in(os.getenv("NOUSE_SPEECH_LISTEN_ENABLED"))


#: Aktuell opt-in-status vid import (läs alltid via is_mic_enabled()).
MIC_ENABLED = is_mic_enabled()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: STT model (whisper size: tiny, base, small, medium, large)
STT_MODEL = os.getenv("NOUSE_STT_MODEL", "base")

#: TTS engine: "piper" | "edge-tts" | "pyttsx3" | "none"
TTS_ENGINE = os.getenv("NOUSE_TTS_ENGINE", "none")

#: Audio capture device
AUDIO_DEVICE = os.getenv("NOUSE_AUDIO_DEVICE", "default")

#: Capture sample rate
AUDIO_SAMPLE_RATE = int(os.getenv("NOUSE_AUDIO_SAMPLE_RATE", "16000"))

#: Maximum recording duration (seconds)
MAX_RECORDING_DURATION = int(os.getenv("NOUSE_MAX_RECORDING_DURATION", "30"))

#: Silence detection threshold (0-32768)
SILENCE_THRESHOLD = int(os.getenv("NOUSE_SILENCE_THRESHOLD", "500"))

#: Minimum speech duration to process (seconds)
MIN_SPEECH_DURATION = float(os.getenv("NOUSE_MIN_SPEECH_DURATION", "1.0"))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HearingResult:
    """Result from speech-to-text processing."""
    text: str
    language: str
    confidence: float
    duration: float
    source: str  # "whisper" | "cloud" | "none"


@dataclass
class SpeechOutput:
    """A speech output from Nous."""
    text: str
    audio_path: str | None
    engine: str
    duration: float


# ---------------------------------------------------------------------------
# Audio capture
# ---------------------------------------------------------------------------

def record_audio(duration: float = 5.0, output_path: str | None = None) -> str | None:
    """Record audio from microphone using arecord.

    Returns path to WAV file, or None on failure.

    Kräver explicit opt-in (NOUSE_MIC_ENABLED) — annars ingen inspelning
    och ingen tmpdir.
    """
    if not is_mic_enabled():
        log.info("Microphone disabled (NOUSE_MIC_ENABLED not set) — skipping recording")
        return None
    if output_path is None:
        tmpdir = tempfile.mkdtemp(prefix="nouse_stt_")
        output_path = os.path.join(tmpdir, "recording.wav")

    cmd = [
        "arecord",
        "-f", "S16_LE",         # 16-bit PCM
        "-r", str(AUDIO_SAMPLE_RATE),
        "-c", "1",              # mono
        "-d", str(int(duration)),
        "-D", AUDIO_DEVICE,
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(duration) + 5,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 1000:
                log.info(f"Recorded audio: {output_path} ({size} bytes, {duration:.1f}s)")
                return output_path
        else:
            log.warning(f"arecord failed: {result.stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        log.warning("Audio recording timed out")
        return None
    except FileNotFoundError:
        log.warning("arecord not found — no microphone access")
        return None
    except Exception as e:
        log.warning(f"Audio recording error: {e}")
        return None


# ---------------------------------------------------------------------------
# Speech-to-Text (Hearing — Temporal Lobe / Wernicke's area)
# ---------------------------------------------------------------------------

def _whisper_transcribe(audio_path: str) -> HearingResult | None:
    """Transcribe audio using local Whisper model."""
    try:
        import whisper
        model = whisper.load_model(STT_MODEL)
        result = model.transcribe(audio_path)
        return HearingResult(
            text=result.get("text", "").strip(),
            language=result.get("language", "unknown"),
            confidence=1.0 - min(1.0, result.get("avg_logprob", -0.5) * -2),
            duration=result.get("segments", [{}])[-1].get("end", 0) if result.get("segments") else 0,
            source="whisper",
        )
    except ImportError:
        log.debug("Whisper not installed — pip install openai-whisper")
        return None
    except Exception as e:
        log.warning(f"Whisper transcription failed: {e}")
        return None


def _ffmpeg_silence_detect(audio_path: str) -> float:
    """Detect speech duration using ffmpeg silence detection.

    Returns the duration of non-silent audio in seconds.
    """
    cmd = [
        "ffmpeg",
        "-i", audio_path,
        "-af", f"silencedetect=n={SILENCE_THRESHOLD}:d=0.5",
        "-f", "null", "-",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        # Parse silence_end / silence_start from stderr
        stderr = result.stderr
        speech_duration = 0.0
        in_silence = False
        last_speech_end = 0.0

        for line in stderr.split("\n"):
            if "silence_end" in line:
                # Speech period ended
                parts = line.split("silence_end:")
                if len(parts) > 1:
                    try:
                        end_time = float(parts[1].strip().split()[0])
                        in_silence = False
                    except (ValueError, IndexError):
                        pass
            elif "silence_start" in line:
                # Speech period starts
                parts = line.split("silence_start:")
                if len(parts) > 1:
                    try:
                        start_time = float(parts[1].strip().split()[0])
                        speech_duration += start_time - last_speech_end
                        in_silence = True
                    except (ValueError, IndexError):
                        pass

        # If no silence detected, entire recording is speech
        if speech_duration == 0.0 and "silence_start" not in stderr:
            # Get total duration
            for line in stderr.split("\n"):
                if "Duration:" in line:
                    try:
                        dur_str = line.split("Duration:")[1].split(",")[0].strip()
                        h, m, s = dur_str.split(":")
                        speech_duration = int(h) * 3600 + int(m) * 60 + float(s)
                    except (ValueError, IndexError):
                        pass

        return speech_duration
    except Exception as e:
        log.debug(f"Silence detection failed: {e}")
        return 0.0


def hear(duration: float = 5.0) -> HearingResult | None:
    """Listen and transcribe. Nous's "ears" (Wernicke's area).

    1. Record audio from microphone
    2. Check if speech is present (silence detection)
    3. Transcribe with Whisper
    4. Return structured result
    """
    if not is_mic_enabled():
        log.info("Microphone disabled (NOUSE_MIC_ENABLED not set) — skipping listen")
        return None
    # Record
    tmpdir = tempfile.mkdtemp(prefix="nouse_stt_")
    audio_path = record_audio(duration=duration,
                              output_path=os.path.join(tmpdir, "recording.wav"))
    if not audio_path:
        return None

    # Check for speech
    speech_dur = _ffmpeg_silence_detect(audio_path)
    if speech_dur < MIN_SPEECH_DURATION:
        log.info(f"No speech detected (speech_duration={speech_dur:.1f}s)")
        return None

    # Transcribe
    result = _whisper_transcribe(audio_path)
    if result and result.text:
        log.info(f"Heard: '{result.text[:80]}' (lang={result.language}, "
                 f"confidence={result.confidence:.2f})")
        return result

    return None


# ---------------------------------------------------------------------------
# Text-to-Speech (Voice — Frontal Lobe / Broca's area)
# ---------------------------------------------------------------------------

def _piper_speak(text: str, output_path: str | None = None) -> SpeechOutput | None:
    """Generate speech using Piper (local, fast)."""
    if not output_path:
        tmpdir = tempfile.mkdtemp(prefix="nouse_tts_")
        output_path = os.path.join(tmpdir, "speech.wav")

    try:
        cmd = ["piper", "--model", "en-us-lessac-medium", "--output_file", output_path]
        result = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            return SpeechOutput(
                text=text,
                audio_path=output_path,
                engine="piper",
                duration=os.path.getsize(output_path) / (16000 * 2),  # rough estimate
            )
    except FileNotFoundError:
        log.debug("Piper not installed")
    except Exception as e:
        log.warning(f"Piper TTS failed: {e}")

    return None


def _edge_tts_speak(text: str, output_path: str | None = None) -> SpeechOutput | None:
    """Generate speech using edge-tts (Microsoft, cloud)."""
    if not output_path:
        tmpdir = tempfile.mkdtemp(prefix="nouse_tts_")
        output_path = os.path.join(tmpdir, "speech.mp3")

    try:
        import asyncio
        import edge_tts

        async def _speak():
            communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
            await communicate.save(output_path)

        asyncio.run(_speak())

        if os.path.exists(output_path):
            return SpeechOutput(
                text=text,
                audio_path=output_path,
                engine="edge-tts",
                duration=os.path.getsize(output_path) / 16000,  # rough
            )
    except ImportError:
        log.debug("edge-tts not installed — pip install edge-tts")
    except Exception as e:
        log.warning(f"edge-tts failed: {e}")

    return None


def _pyttsx3_speak(text: str) -> SpeechOutput | None:
    """Generate speech using pyttsx3 (local, always available)."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        return SpeechOutput(
            text=text,
            audio_path=None,  # direct to speakers
            engine="pyttsx3",
            duration=len(text) / 10.0,  # rough estimate
        )
    except ImportError:
        log.debug("pyttsx3 not installed — pip install pyttsx3")
    except Exception as e:
        log.warning(f"pyttsx3 failed: {e}")

    return None


def speak(text: str, output_path: str | None = None) -> SpeechOutput | None:
    """Speak text. Nous's "voice" (Broca's area).

    Tries: piper → edge-tts → pyttsx3 → logs text only.
    """
    if TTS_ENGINE == "none":
        log.info(f"[Speech] {text[:100]}")
        return None

    # Try selected engine first, then fallbacks
    engines = [TTS_ENGINE] if TTS_ENGINE != "auto" else ["piper", "edge-tts", "pyttsx3"]

    for engine_name in engines:
        if engine_name == "piper":
            result = _piper_speak(text, output_path)
        elif engine_name == "edge-tts":
            result = _edge_tts_speak(text, output_path)
        elif engine_name == "pyttsx3":
            result = _pyttsx3_speak(text)
        else:
            continue

        if result:
            return result

    # No TTS available — log only
    log.info(f"[No TTS] {text[:100]}")
    return SpeechOutput(
        text=text,
        audio_path=None,
        engine="none",
        duration=0.0,
    )


# ---------------------------------------------------------------------------
# Continuous listening mode (for daemon integration)
# ---------------------------------------------------------------------------

class SpeechListener:
    """Continuous speech listener for daemon integration.

    Runs in the main loop, periodically listening for speech input.
    Transcribed text is fed into the knowledge graph as temporal_lobe
    concepts (Wernicke's area for comprehension).
    """

    def __init__(self, field: Any = None, interval: float = 60.0):
        self.field = field
        self.interval = interval
        self._last_listen = 0.0
        # Opt-in-grind: aldrig aktiv utan NOUSE_MIC_ENABLED (strikt parsad;
        # legacy NOUSE_SPEECH_LISTEN_ENABLED accepteras som alias).
        self._enabled = is_mic_enabled()
        if self._enabled:
            log.info("Speech listener enabled (microphone opt-in active)")
        else:
            log.info("Speech listener disabled (NOUSE_MIC_ENABLED not set) — opt-in required")

    def tick(self) -> HearingResult | None:
        """Called each daemon cycle. Listens if interval has elapsed."""
        if not is_mic_enabled():
            return None
        if not self._enabled:
            return None

        now = time.time()
        if now - self._last_listen < self.interval:
            return None

        self._last_listen = now
        result = hear(duration=5.0)

        if result and result.text and self.field:
            self._inject_hearing(result)

        return result

    def _inject_hearing(self, result: HearingResult) -> None:
        """Inject heard text into the knowledge graph.

        Speech comprehension goes to temporal_lobe (Wernicke's area).
        """
        try:
            from nouse.daemon.brain_atlas import classify_domain

            # Extract key concepts from the transcribed text
            words = result.text.split()
            concepts = [w.lower() for w in words if len(w) > 3][:5]

            for concept in concepts:
                region = classify_domain(concept)
                if hasattr(self.field, "inject"):
                    self.field.inject(
                        src="speech_input",
                        rel="heard",
                        tgt=concept,
                        metadata={
                            "source": "speech",
                            "region": region,
                            "language": result.language,
                            "confidence": result.confidence,
                            "timestamp": time.time(),
                        },
                    )
        except Exception as e:
            log.debug(f"Speech injection failed: {e}")


class SpeechSpeaker:
    """Speech output for daemon integration.

    Speaks Nous's findings, reflections, and important observations.
    Maps to Broca's area (Frontal Lobe) — speech production.
    """

    def __init__(self, field: Any = None):
        self.field = field
        self._last_spoken = ""
        self._min_interval = 30.0
        self._last_time = 0.0

    def say(self, text: str) -> SpeechOutput | None:
        """Speak text, with deduplication and rate limiting.

        Won't repeat the same text within _min_interval seconds.
        """
        now = time.time()
        if text == self._last_spoken and now - self._last_time < self._min_interval:
            return None

        self._last_spoken = text
        self._last_time = now

        return speak(text)

    def announce_finding(self, finding: dict) -> SpeechOutput | None:
        """Announce a significant finding from Nous's cognitive cycle.

        Only speaks high-confidence, high-priority findings.
        """
        confidence = finding.get("confidence", 0)
        priority = finding.get("priority", 0)

        if confidence < 0.7 or priority < 0.8:
            return None

        text = finding.get("summary", finding.get("text", ""))
        if not text:
            return None

        return self.say(text)