"""Microphone capture with RMS-based silence trimming.

Note: full Silero-VAD is integrated in Recorder class (task 3.2);
this module provides the pure helpers first to enable TDD.
"""
from __future__ import annotations

import numpy as np


def compute_rms(audio: np.ndarray) -> float:
    """Root-mean-square of a mono float32 audio array."""
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def trim_silence_endpoints(
    audio: np.ndarray,
    sample_rate: int,
    threshold_rms: float = 0.02,
    frame_ms: int = 20,
    pad_ms: int = 50,
) -> np.ndarray:
    """Trim leading and trailing silence using RMS energy per frame.

    - threshold_rms: frames quieter than this are silence.
    - frame_ms: analysis window size.
    - pad_ms: keep this many ms around the detected speech for naturalness.
    """
    if audio.size == 0:
        return audio

    frame_samples = max(1, int(sample_rate * frame_ms / 1000))
    pad_samples = int(sample_rate * pad_ms / 1000)

    num_frames = len(audio) // frame_samples
    if num_frames == 0:
        return audio

    frames = audio[: num_frames * frame_samples].reshape(num_frames, frame_samples)
    rms_per_frame = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))

    speech_mask = rms_per_frame > threshold_rms
    if not np.any(speech_mask):
        return np.zeros(0, dtype=audio.dtype)

    first = int(np.argmax(speech_mask))
    last = num_frames - int(np.argmax(speech_mask[::-1]))

    start = max(0, first * frame_samples - pad_samples)
    end = min(len(audio), last * frame_samples + pad_samples)
    return audio[start:end]
