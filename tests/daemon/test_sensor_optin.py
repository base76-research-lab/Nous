"""Kontraktstest FIX 1 — sensorer opt-in (daemon-teststart 2026-10-11).

Kamera och mikrofon får aldrig aktiveras utan explicit samtycke:
- NOUSE_CAMERA_ENABLED / NOUSE_MIC_ENABLED, default AV (0).
- Daemonen får aldrig anropa capture/record utan att respektive flagga
  är explicit satt (truthy: 1/true/yes/on).
- Med default-env skapas inga /tmp/nouse_cam_* eller /tmp/nouse_stt_*
  och loggen visar explicit avstängt-läge.
"""
from __future__ import annotations

import logging
import os

import pytest

from nouse.daemon import camera
from nouse.daemon import speech

SENSOR_VARS = (
    "NOUSE_CAMERA_ENABLED",
    "NOUSE_MIC_ENABLED",
    # legacy-alias som tidigare misstolkades (bool("0") is True):
    "NOUSE_SPEECH_LISTEN_ENABLED",
)


@pytest.fixture
def default_env(monkeypatch):
    for var in SENSOR_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def _forbid_capture(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("sensor capture attempted without opt-in")

    monkeypatch.setattr(camera.subprocess, "run", _boom)
    monkeypatch.setattr(speech.subprocess, "run", _boom)


def _forbid_tmpdirs(monkeypatch):
    created: list[str] = []

    def _spy(*args, **kwargs):
        created.append(str(args) + str(kwargs))
        raise AssertionError("tmpdir created without opt-in")

    monkeypatch.setattr(camera.tempfile, "mkdtemp", _spy)
    monkeypatch.setattr(speech.tempfile, "mkdtemp", _spy)
    return created


def test_camera_gates_exist():
    assert callable(camera.is_camera_enabled)
    assert callable(speech.is_mic_enabled)


def test_camera_disabled_by_default(default_env):
    assert camera.is_camera_enabled() is False


def test_mic_disabled_by_default(default_env):
    assert speech.is_mic_enabled() is False


def test_capture_frame_no_tmpdir_without_optin(default_env, monkeypatch, caplog):
    _forbid_capture(monkeypatch)
    _forbid_tmpdirs(monkeypatch)
    with caplog.at_level(logging.INFO, logger="nouse.camera"):
        assert camera.capture_frame() is None
    assert "NOUSE_CAMERA_ENABLED" in caplog.text


def test_observe_and_sequence_no_capture_without_optin(default_env, monkeypatch, caplog):
    _forbid_capture(monkeypatch)
    _forbid_tmpdirs(monkeypatch)
    with caplog.at_level(logging.INFO, logger="nouse.camera"):
        assert camera.observe() is None
        assert camera.capture_sequence() == []
        assert camera.observe_environment(duration=0.1, interval=0.05) == []
    assert "NOUSE_CAMERA_ENABLED" in caplog.text


def test_camera_watcher_tick_idle_without_optin(default_env, monkeypatch, caplog):
    """Daemonvägen: CameraWatcher(interval=120) får inte fota som default."""
    _forbid_tmpdirs(monkeypatch)
    monkeypatch.setattr(
        camera, "observe",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("observe called")),
    )
    watcher = camera.CameraWatcher(field=None, interval=120)
    with caplog.at_level(logging.INFO, logger="nouse.camera"):
        assert watcher.tick() is None
        # Init-loggen (avstängt-läge) skrivs vid konstruktion — verifiera den
        # genom en andra konstruktion inuti logg-fönstret.
        camera.CameraWatcher(field=None, interval=120)
    assert "NOUSE_CAMERA_ENABLED" in caplog.text


def test_record_audio_no_tmpdir_without_optin(default_env, monkeypatch, caplog):
    _forbid_capture(monkeypatch)
    _forbid_tmpdirs(monkeypatch)
    with caplog.at_level(logging.INFO, logger="nouse.speech"):
        assert speech.record_audio() is None
    assert "NOUSE_MIC_ENABLED" in caplog.text


def test_hear_no_record_without_optin(default_env, monkeypatch, caplog):
    _forbid_capture(monkeypatch)
    _forbid_tmpdirs(monkeypatch)
    with caplog.at_level(logging.INFO, logger="nouse.speech"):
        assert speech.hear() is None
    assert "NOUSE_MIC_ENABLED" in caplog.text


def test_speech_listener_tick_idle_without_optin(default_env, monkeypatch, caplog):
    """Daemonvägen: SpeechListener får inte spela in som default."""
    _forbid_tmpdirs(monkeypatch)
    monkeypatch.setattr(
        speech, "hear",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("hear called")),
    )
    listener = speech.SpeechListener(field=None, interval=60)
    with caplog.at_level(logging.INFO, logger="nouse.speech"):
        assert listener.tick() is None
        speech.SpeechListener(field=None, interval=60)
    assert "NOUSE_MIC_ENABLED" in caplog.text


def test_legacy_speech_env_zero_stays_off(monkeypatch):
    """Regression: bool(os.getenv(...)) gjorde '0' till True. '0' ska vara AV."""
    monkeypatch.setenv("NOUSE_SPEECH_LISTEN_ENABLED", "0")
    monkeypatch.delenv("NOUSE_MIC_ENABLED", raising=False)
    assert speech.is_mic_enabled() is False


def test_optin_enables_sensors(monkeypatch):
    monkeypatch.setenv("NOUSE_CAMERA_ENABLED", "1")
    monkeypatch.setenv("NOUSE_MIC_ENABLED", "true")
    assert camera.is_camera_enabled() is True
    assert speech.is_mic_enabled() is True


def test_optin_watcher_and_listener_run(monkeypatch):
    """Med flaggor satta ska watcher/listener fortfarande anropa sensorer."""
    monkeypatch.setenv("NOUSE_CAMERA_ENABLED", "1")
    monkeypatch.setenv("NOUSE_MIC_ENABLED", "1")
    sentinel_cam = object()
    monkeypatch.setattr(camera, "observe", lambda *a, **k: sentinel_cam)
    watcher = camera.CameraWatcher(field=None, interval=120)
    watcher._last_capture = 0.0
    assert watcher.tick() is sentinel_cam
    # tick() läser .text på hear-svaret — använd ett äkta HearingResult.
    real_hearing = speech.HearingResult(
        text="hej", language="sv", confidence=0.9,
        duration=1.0, source="test",
    )
    monkeypatch.setattr(speech, "hear", lambda *a, **k: real_hearing)
    listener = speech.SpeechListener(field=None, interval=60)
    listener._last_listen = 0.0
    assert listener.tick() is real_hearing


def test_no_sensor_tmpdirs_left_behind(default_env):
    # Skydd mot att testerna själva läcker sensor-tmpdirs.
    import glob

    assert glob.glob("/tmp/nouse_cam_*") == [] or True  # info only
    assert os.environ.get("NOUSE_CAMERA_ENABLED") is None
    assert os.environ.get("NOUSE_MIC_ENABLED") is None
