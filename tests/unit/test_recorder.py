"""Tests for Recorder's pure VAD-trim function."""
from __future__ import annotations

import numpy as np

from whisperflow.core.recorder import compute_rms, trim_silence_endpoints


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
