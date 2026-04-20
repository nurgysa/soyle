"""Whisper inference wrapper.

Part 1: pure text-cleanup helpers (this file).
Part 2: Transcriber class using faster-whisper (task 4.3).
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

from whisperflow.core.errors import CudaOOMError, CudaUnavailableError, ModelNotLoadedError


def _register_cuda_dll_dirs() -> None:
    """Add nvidia-cublas-cu12 / nvidia-cudnn-cu12 wheel `bin/` dirs to DLL search path.

    On Windows, CTranslate2 needs `cublas64_12.dll` and `cudnn*.dll` to initialise
    CUDA models. When those libraries are installed as pip wheels (instead of the
    full CUDA Toolkit), their DLLs live under `site-packages/nvidia/<lib>/bin/`.
    `os.add_dll_directory` tells Windows to look there.
    """
    if sys.platform != "win32":
        return
    for pkg_name in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            mod = __import__(pkg_name, fromlist=[""])
        except ImportError:
            continue
        file_attr = getattr(mod, "__file__", None)
        if file_attr is None:
            continue
        bin_dir = Path(file_attr).parent / "bin"
        if bin_dir.is_dir():
            os.add_dll_directory(str(bin_dir))

_WHITESPACE_RE = re.compile(r"\s+")
_NOISE_TAGS_RE = re.compile(r"\[(music|applause|laughter|noise|silence)\]", re.IGNORECASE)


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def filter_hallucinations(text: str) -> str:
    """Strip Whisper hallucinations: noise tags and repetitive spam."""
    cleaned = _NOISE_TAGS_RE.sub("", text)
    cleaned = normalize_whitespace(cleaned)

    if not cleaned:
        return ""

    # Detect N-copies-of-same-phrase pattern (common Whisper failure mode).
    # If the same ≥2-word phrase appears ≥4 times in a row → hallucination.
    words = cleaned.split()
    if len(words) < 4:
        return cleaned

    for phrase_len in range(1, max(2, len(words) // 4 + 1)):
        repeats = _count_leading_repeats(words, phrase_len)
        if repeats >= 4 and phrase_len * repeats >= len(words) * 0.75:
            return ""

    return cleaned


def _count_leading_repeats(words: list[str], phrase_len: int) -> int:
    if phrase_len == 0 or phrase_len > len(words):
        return 0
    phrase = words[:phrase_len]
    count = 1
    for i in range(phrase_len, len(words) - phrase_len + 1, phrase_len):
        if words[i : i + phrase_len] == phrase:
            count += 1
        else:
            break
    return count


@dataclass
class TranscriptResult:
    raw_text: str
    language: str
    duration_ms: int
    segments: list[dict]


class Transcriber:
    """Singleton-style Whisper wrapper; load once, transcribe many."""

    def __init__(
        self, model: str = "large-v3-turbo", device: str = "auto", compute_type: str = "int8"
    ) -> None:
        self._model_name = model
        self._device_pref = device
        self._compute_type = compute_type
        self._model: WhisperModel | None = None
        self._actual_device: str = "cpu"

    @property
    def device(self) -> str:
        return self._actual_device

    def warm_up(self) -> None:
        self._ensure_loaded()
        dummy = np.zeros(16000, dtype=np.float32)
        with contextlib.suppress(Exception):
            assert self._model is not None
            list(self._model.transcribe(dummy, language="en", beam_size=1)[0])

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> TranscriptResult:
        if sample_rate != 16000:
            # faster-whisper expects 16 kHz; resample if needed
            audio = _resample_to_16k(audio, sample_rate)
            sample_rate = 16000

        self._ensure_loaded()
        assert self._model is not None

        try:
            segments_iter, info = self._model.transcribe(
                audio,
                beam_size=5,
                vad_filter=True,
                language=None,
            )
            segments = [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in segments_iter
            ]
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "out of memory" in msg or ("cuda" in msg and "memory" in msg):
                raise CudaOOMError(str(exc)) from exc
            raise ModelNotLoadedError(str(exc)) from exc

        raw_text = filter_hallucinations(" ".join(s["text"] for s in segments).strip())
        duration_ms = int(info.duration * 1000) if info.duration else 0
        language = info.language or ""

        return TranscriptResult(
            raw_text=raw_text,
            language=language,
            duration_ms=duration_ms,
            segments=segments,
        )

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        device = self._device_pref
        try:
            if device in ("auto", "cuda"):
                _register_cuda_dll_dirs()
                try:
                    self._model = WhisperModel(
                        self._model_name, device="cuda", compute_type=self._compute_type
                    )
                    self._actual_device = "cuda"
                    return
                except Exception as exc:
                    if device == "cuda":
                        raise CudaUnavailableError(f"CUDA requested but unavailable: {exc}") from exc
                    # auto fallback to CPU
            self._model = WhisperModel(
                self._model_name, device="cpu", compute_type="int8"
            )
            self._actual_device = "cpu"
        except Exception as exc:
            raise ModelNotLoadedError(f"failed to load model '{self._model_name}': {exc}") from exc


def _resample_to_16k(audio: np.ndarray, from_rate: int) -> np.ndarray:
    if from_rate == 16000:
        return audio
    # Simple linear-interpolation resample (sufficient for 8-48kHz voice)
    duration = len(audio) / from_rate
    target_len = int(duration * 16000)
    x = np.linspace(0, 1, len(audio), dtype=np.float64)
    y = np.linspace(0, 1, target_len, dtype=np.float64)
    return np.interp(y, x, audio).astype(np.float32)
