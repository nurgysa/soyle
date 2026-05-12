"""Microphone capture with RMS-based silence trimming.

Note: full Silero-VAD is integrated in Recorder class (task 3.2);
this module provides the pure helpers first to enable TDD.
"""
from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from typing import Any

import numpy as np
import sounddevice as sd

from soyle.core.bus import Event, EventBus
from soyle.core.errors import AudioDeviceError


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


@dataclass
class RecordingResult:
    audio: np.ndarray
    duration_ms: int
    rms_peak: float


class Recorder:
    """Captures microphone audio into a queue; emits events through EventBus."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._queue: Queue[np.ndarray] = Queue()
        self._stream: Any = None
        self._sample_rate: int = 16000

    def start(self, sample_rate: int = 16000, device: str = "default") -> None:
        self._ensure_input_device_exists()
        self._sample_rate = sample_rate
        self._queue = Queue()

        def _callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
            self._queue.put(mono)

        self._stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            callback=_callback,
            device=None if device == "default" else device,
        )
        self._stream.start()
        self._bus.emit(Event.RECORDING_STARTED, {"sample_rate": sample_rate})

    def stop(self) -> RecordingResult:
        if self._stream is None:
            return RecordingResult(audio=np.zeros(0, np.float32), duration_ms=0, rms_peak=0.0)

        self._stream.stop()
        self._stream.close()
        self._stream = None

        chunks: list[np.ndarray] = []
        while not self._queue.empty():
            chunks.append(self._queue.get_nowait())

        audio = (
            np.concatenate(chunks).astype(np.float32)
            if chunks
            else np.zeros(0, dtype=np.float32)
        )
        duration_ms = int(len(audio) * 1000 / self._sample_rate)
        rms_peak = compute_rms(audio)

        result = RecordingResult(audio=audio, duration_ms=duration_ms, rms_peak=rms_peak)
        self._bus.emit(
            Event.RECORDING_STOPPED,
            {"audio": audio, "duration_ms": duration_ms, "rms_peak": rms_peak},
        )
        return result

    @staticmethod
    def _ensure_input_device_exists() -> None:
        try:
            devices = sd.query_devices()
        except Exception as exc:
            raise AudioDeviceError(f"could not enumerate audio devices: {exc}") from exc

        has_input = any(
            (d.get("max_input_channels", 0) > 0) for d in devices
        )
        if not has_input:
            raise AudioDeviceError("no microphone device found")
