"""
nouse.daemon.camera — Camera module for embodied environment perception
=========================================================================

Gives Nous "eyes" to observe its physical environment via webcam.
Maps to Occipital Lobe (visual processing) + Parietal Lobe (spatial awareness).

Capabilities:
1. Capture frames from webcam
2. Process frames with vision model (llava / Gemini)
3. Extract concepts and spatial information
4. Feed observations into knowledge graph
5. Continuous observation mode for environment monitoring

The camera is Nous's way of "seeing" the world — not just reading about it
but directly perceiving it.  This is the embodied perception that
Gemini Robotics ER provides for robots, but adapted for a knowledge system.

Dependencies:
- /dev/video0 (or other V4L2 device)
- ffmpeg for frame capture (always available)
- Vision model (llava via Ollama, or Gemini API)
- Pillow for image preprocessing
"""
from __future__ import annotations

import io
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("nouse.camera")

#: Opt-in-grind (daemon-teststart 2026-10-11): kameran är AV som default.
#: Sätt NOUSE_CAMERA_ENABLED=1/true/yes/on för explicit samtycke.
_OPT_IN_TRUE = {"1", "true", "yes", "on"}


def is_camera_enabled() -> bool:
    """True endast vid explicit opt-in via NOUSE_CAMERA_ENABLED."""
    return (os.getenv("NOUSE_CAMERA_ENABLED", "") or "").strip().lower() in _OPT_IN_TRUE


#: Aktuell opt-in-status vid import (läs alltid via is_camera_enabled()).
CAMERA_ENABLED = is_camera_enabled()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Camera device path
CAMERA_DEVICE = os.getenv("NOUSE_CAMERA_DEVICE", "/dev/video0")

#: Capture resolution
CAMERA_WIDTH = int(os.getenv("NOUSE_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("NOUSE_CAMERA_HEIGHT", "720"))

#: Capture quality (1-31, lower = better)
CAMERA_QUALITY = int(os.getenv("NOUSE_CAMERA_QUALITY", "5"))

#: Interval between automatic captures (seconds, 0 = disabled)
CAMERA_INTERVAL = int(os.getenv("NOUSE_CAMERA_INTERVAL", "0"))

#: Maximum consecutive capture failures before giving up
CAMERA_MAX_FAILURES = int(os.getenv("NOUSE_CAMERA_MAX_FAILURES", "5"))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CameraObservation:
    """A single camera observation."""
    timestamp: float
    image_path: str
    description: str
    concepts: list[str]
    spatial_info: dict
    confidence: float
    source: str  # "camera"


# ---------------------------------------------------------------------------
# Frame capture
# ---------------------------------------------------------------------------

def capture_frame(output_path: str | None = None) -> str | None:
    """Capture a single frame from the camera.

    Uses ffmpeg for V4L2 capture — reliable and available on most Linux systems.
    Returns path to captured image, or None on failure.

    Kräver explicit opt-in (NOUSE_CAMERA_ENABLED) — annars ingen capture
    och ingen tmpdir.
    """
    if not is_camera_enabled():
        log.info("Camera disabled (NOUSE_CAMERA_ENABLED not set) — skipping capture")
        return None
    if output_path is None:
        tmpdir = tempfile.mkdtemp(prefix="nouse_cam_")
        output_path = os.path.join(tmpdir, "frame.jpg")

    # Check if camera device exists
    if not os.path.exists(CAMERA_DEVICE):
        log.warning(f"Camera device not found: {CAMERA_DEVICE}")
        return None

    cmd = [
        "ffmpeg",
        "-y",                    # overwrite output
        "-f", "v4l2",           # Video4Linux2 input
        "-i", CAMERA_DEVICE,    # device path
        "-frames:v", "1",      # capture single frame
        "-video_size", f"{CAMERA_WIDTH}x{CAMERA_HEIGHT}",
        "-q:v", str(CAMERA_QUALITY),
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 1000:  # at least 1KB
                log.info(f"Captured frame: {output_path} ({size} bytes)")
                return output_path
            else:
                log.warning(f"Frame too small ({size} bytes), likely blank")
                return None
        else:
            log.warning(f"ffmpeg capture failed: {result.stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        log.warning("Camera capture timed out")
        return None
    except Exception as e:
        log.warning(f"Camera capture error: {e}")
        return None


def capture_sequence(n_frames: int = 3, interval: float = 1.0) -> list[str]:
    """Capture multiple frames with interval between captures.

    Useful for observing changes in the environment over time.
    Returns list of image paths.
    """
    if not is_camera_enabled():
        log.info("Camera disabled (NOUSE_CAMERA_ENABLED not set) — skipping sequence")
        return []
    paths = []
    for i in range(n_frames):
        tmpdir = tempfile.mkdtemp(prefix="nouse_cam_")
        path = os.path.join(tmpdir, f"frame_{i:03d}.jpg")
        result = capture_frame(output_path=path)
        if result:
            paths.append(result)
        if i < n_frames - 1:
            time.sleep(interval)
    return paths


# ---------------------------------------------------------------------------
# Observation pipeline
# ---------------------------------------------------------------------------

def observe(vision_model: Any = None) -> CameraObservation | None:
    """Capture and process a single camera observation.

    1. Capture frame from camera
    2. Process with vision model
    3. Return structured observation
    """
    if not is_camera_enabled():
        log.info("Camera disabled (NOUSE_CAMERA_ENABLED not set) — skipping observation")
        return None
    # Capture
    tmpdir = tempfile.mkdtemp(prefix="nouse_cam_")
    image_path = capture_frame(output_path=os.path.join(tmpdir, "observation.jpg"))
    if not image_path:
        return None

    # Process with vision model
    description = ""
    concepts: list[str] = []
    spatial_info: dict = {}
    confidence = 0.0
    source = "camera"

    try:
        from nouse.daemon.vision import describe_image
        result = describe_image(image_path)
        description = result.description
        concepts = result.concepts
        spatial_info = result.spatial_info
        confidence = result.confidence
        source = f"camera+{result.source}"
    except Exception as e:
        log.warning(f"Vision processing failed: {e}")
        # Heuristic: use timestamp and file metadata
        description = f"Camera observation at {time.strftime('%H:%M:%S')}"
        confidence = 0.1

    return CameraObservation(
        timestamp=time.time(),
        image_path=image_path,
        description=description,
        concepts=concepts,
        spatial_info=spatial_info,
        confidence=confidence,
        source=source,
    )


def observe_environment(duration: float = 30.0, interval: float = 5.0) -> list[CameraObservation]:
    """Observe the environment for a period of time.

    Captures frames at regular intervals and processes them.
    This is Nous "watching" its environment.
    """
    if not is_camera_enabled():
        log.info("Camera disabled (NOUSE_CAMERA_ENABLED not set) — skipping observation")
        return []
    observations: list[CameraObservation] = []
    start = time.time()

    while time.time() - start < duration:
        obs = observe()
        if obs:
            observations.append(obs)
            log.info(f"Observation: {len(obs.concepts)} concepts, "
                     f"confidence={obs.confidence:.2f}")

        elapsed = time.time() - start
        remaining = duration - elapsed
        if remaining > interval:
            time.sleep(interval)

    log.info(f"Environment observation complete: {len(observations)} frames "
             f"over {duration:.0f}s")
    return observations


# ---------------------------------------------------------------------------
# Continuous observation mode (for daemon integration)
# ---------------------------------------------------------------------------

class CameraWatcher:
    """Continuous camera watcher for daemon integration.

    Runs in the main loop, capturing frames at configured intervals.
    Observations are fed into the knowledge graph via the field surface.
    """

    def __init__(self, field: Any = None, interval: int = 0):
        self.field = field
        self.interval = interval or CAMERA_INTERVAL
        self._last_capture = 0.0
        self._consecutive_failures = 0
        # Opt-in-grind: aldrig aktiv utan NOUSE_CAMERA_ENABLED, oavsett
        # interval-argument från daemonen. Enhetsnärvaro kontrolleras
        # separat vid capture (capture_frame loggar saknad enhet).
        self._enabled = is_camera_enabled()
        if self._enabled:
            log.info("Camera watcher enabled (NOUSE_CAMERA_ENABLED=1)")
        else:
            log.info("Camera watcher disabled (NOUSE_CAMERA_ENABLED not set) — opt-in required")

    def tick(self) -> CameraObservation | None:
        """Called each daemon cycle. Captures frame if interval has elapsed.

        Returns observation if captured, None otherwise.
        """
        if not is_camera_enabled():
            return None
        if not self._enabled or self.interval <= 0:
            return None

        if self._consecutive_failures >= CAMERA_MAX_FAILURES:
            return None

        now = time.time()
        if now - self._last_capture < self.interval:
            return None

        self._last_capture = now
        obs = observe()

        if obs:
            self._consecutive_failures = 0
            # Feed into field if available
            if self.field and obs.concepts:
                self._inject_observation(obs)
        else:
            self._consecutive_failures += 1

        return obs

    def _inject_observation(self, obs: CameraObservation) -> None:
        """Inject camera observation into the knowledge graph.

        Visual concepts go to occipital_lobe, spatial info to parietal_lobe.
        """
        try:
            from nouse.daemon.brain_atlas import classify_domain

            for concept in obs.concepts[:5]:
                region = classify_domain(concept)
                # Write as episode with brain region context
                obs_text = (
                    f"[Camera] {obs.description} "
                    f"(region={region}, confidence={obs.confidence:.2f})"
                )
                if hasattr(self.field, "inject"):
                    self.field.inject(
                        src="camera",
                        rel="observes",
                        tgt=concept,
                        metadata={
                            "source": "camera",
                            "region": region,
                            "confidence": obs.confidence,
                            "timestamp": obs.timestamp,
                        },
                    )
        except Exception as e:
            log.debug(f"Camera injection failed: {e}")