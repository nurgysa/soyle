"""Tests for Recorder's pure VAD-trim function."""
from __future__ import annotations

import math
from unittest.mock import MagicMock

import numpy as np
import pytest

from soyle.core.bus import Event, EventBus
from soyle.core.errors import AudioDeviceError
from soyle.core.recorder import Recorder, compute_rms, normalize_level, trim_silence_endpoints


def test_compute_rms_of_silence_is_zero() -> None:
    audio = np.zeros(16000, dtype=np.float32)
    assert compute_rms(audio) == 0.0


def test_compute_rms_of_tone() -> None:
    # 1-second 440 Hz tone at amplitude 0.5
    t = np.linspace(0, 1, 16000, endpoint=False, dtype=np.float32)
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    rms = compute_rms(tone)
    # Expected RMS of a sine wave = amplitude / sqrt(2)
    assert 0.34 < rms < 0.36


def test_trim_silence_leaves_speech_intact() -> None:
    # 0.5s silence + 1.0s "speech" (noise) + 0.5s silence
    sr = 16000
    silence = np.zeros(sr // 2, dtype=np.float32)
    speech = (np.random.default_rng(42).standard_normal(sr) * 0.2).astype(np.float32)
    audio = np.concatenate([silence, speech, silence])

    trimmed = trim_silence_endpoints(audio, sample_rate=sr, threshold_rms=0.05, pad_ms=50)

    # Trimmed should be ~1.0s ± 100ms
    assert sr * 0.8 < len(trimmed) < sr * 1.2


def test_trim_silence_on_all_silence_returns_empty() -> None:
    audio = np.zeros(16000, dtype=np.float32)
    trimmed = trim_silence_endpoints(audio, sample_rate=16000, threshold_rms=0.05)
    assert len(trimmed) == 0


def test_trim_silence_preserves_short_clip() -> None:
    sr = 16000
    speech = (np.random.default_rng(42).standard_normal(sr // 2) * 0.3).astype(np.float32)
    trimmed = trim_silence_endpoints(speech, sample_rate=sr, threshold_rms=0.05)
    assert len(trimmed) >= sr * 0.4  # lost at most ~20%


def _make_mock_sd(mocker, chunks: list[np.ndarray]):
    """Replace sounddevice.InputStream with one that yields given chunks via callback."""
    mock_sd = mocker.patch("soyle.core.recorder.sd")
    state = {"stream": None, "callback": None}

    def fake_input_stream(**kwargs):
        stream = MagicMock()
        state["callback"] = kwargs["callback"]

        def start() -> None:
            for chunk in chunks:
                # sounddevice passes (indata, frames, time_info, status)
                state["callback"](chunk.reshape(-1, 1), len(chunk), None, None)

        stream.start = MagicMock(side_effect=start)
        stream.stop = MagicMock()
        stream.close = MagicMock()
        state["stream"] = stream
        return stream

    mock_sd.InputStream = fake_input_stream
    mock_sd.query_devices.return_value = [{"name": "default", "max_input_channels": 1}]
    return mock_sd


def test_recorder_captures_audio(qtbot, mocker) -> None:
    rng = np.random.default_rng(0)
    chunks = [rng.standard_normal(1600).astype(np.float32) for _ in range(3)]
    _make_mock_sd(mocker, chunks)

    bus = EventBus()
    rec = Recorder(bus=bus)
    rec.start(sample_rate=16000)
    result = rec.stop()

    assert result.audio.shape[0] == 4800  # 3 x 1600
    assert result.duration_ms == pytest.approx(300, abs=10)


def test_recorder_emits_started_and_stopped(qtbot, mocker) -> None:
    _make_mock_sd(mocker, [np.zeros(1600, dtype=np.float32)])

    bus = EventBus()
    events: list[str] = []
    bus.subscribe(Event.RECORDING_STARTED, lambda _: events.append("start"))
    bus.subscribe(Event.RECORDING_STOPPED, lambda _: events.append("stop"))

    rec = Recorder(bus=bus)
    rec.start()
    rec.stop()

    assert events == ["start", "stop"]


def test_recorder_raises_when_no_input_device(mocker) -> None:
    mock_sd = mocker.patch("soyle.core.recorder.sd")
    mock_sd.query_devices.return_value = [{"name": "Speakers", "max_input_channels": 0}]

    bus = EventBus()
    rec = Recorder(bus=bus)
    with pytest.raises(AudioDeviceError):
        rec.start()


def test_normalize_level_zero_is_zero() -> None:
    assert normalize_level(0.0) == 0.0


def test_normalize_level_at_ref_is_one() -> None:
    assert normalize_level(0.15, ref=0.15) == 1.0


def test_normalize_level_clamps_above_ref() -> None:
    assert normalize_level(1.0, ref=0.15) == 1.0


def test_normalize_level_negative_is_zero() -> None:
    assert normalize_level(-0.5) == 0.0


def test_normalize_level_sqrt_curve_midpoint() -> None:
    # quarter of ref energy -> sqrt(0.25) = 0.5 of the bar
    assert math.isclose(normalize_level(0.15 * 0.25, ref=0.15), 0.5, abs_tol=1e-9)


def test_current_level_zero_before_any_frame() -> None:
    rec = Recorder(bus=EventBus())
    assert rec.current_level() == 0.0


def test_current_level_reflects_last_frame() -> None:
    rec = Recorder(bus=EventBus())
    frame = np.full(160, 0.1, dtype=np.float32)
    rec._on_frame(frame)
    assert rec.current_level() > 0.0


def test_current_level_resets_after_stop() -> None:
    rec = Recorder(bus=EventBus())
    rec._on_frame(np.full(160, 0.1, dtype=np.float32))
    rec.stop()
    assert rec.current_level() == 0.0
