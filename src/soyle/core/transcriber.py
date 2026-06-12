"""Whisper inference wrapper.

Part 1: pure text-cleanup helpers (this file).
Part 2: Transcriber class using faster-whisper (task 4.3).
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import structlog
from faster_whisper import WhisperModel

from soyle.core.errors import CudaOOMError, CudaUnavailableError, ModelNotLoadedError

_log = structlog.get_logger(__name__)


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


@dataclass(frozen=True)
class WhisperModelPreset:
    """Curated Whisper checkpoint with UX hints.

    `model_id` is what gets passed to `WhisperModel(...)`. The other fields
    are for the settings dropdown — not used at inference.
    """
    model_id: str
    params: str  # e.g. "244M", "1.55B"
    note: str    # multilingual quality/speed hint shown in the dropdown

    @property
    def display_label(self) -> str:
        return f"{self.model_id}  ·  {self.params}  ·  {self.note}"


# Order is what the dropdown shows top-to-bottom. Keep the recommended
# default (large-v3-turbo) prominent — it's the best multilingual quality
# / speed trade-off for the typical KZ+RU+EN dictation user. For users
# whose dictation is predominantly Kazakh (especially pure-KZ utterances
# with diacritics Қ/Ң/Ө/Ү/Ұ/Һ/І), large-v3 noticeably outperforms turbo
# at the cost of ~3× decode time and ~2× VRAM. Notes target a Russian-
# speaking user picking between speed and recognition quality.
WHISPER_MODELS: tuple[WhisperModelPreset, ...] = (
    WhisperModelPreset(
        "large-v3-turbo",
        params="809M",
        note="рекомендую — ≈large-v3 по качеству для RU/EN, ~3× быстрее; KZ норм",
    ),
    WhisperModelPreset(
        "large-v3",
        params="1.55B",
        note="лучшее качество, особенно для KZ; тяжело без GPU",
    ),
    WhisperModelPreset(
        "medium",
        params="769M",
        note="компромисс — KZ заметно хуже, средне по скорости",
    ),
    WhisperModelPreset(
        "small",
        params="244M",
        note="быстро, KZ слабый — для смешанной диктовки не подходит",
    ),
)


@dataclass
class TranscriptResult:
    raw_text: str
    language: str
    duration_ms: int
    segments: list[dict[str, Any]]
    language_probability: float = 0.0
    all_language_probs: list[tuple[str, float]] | None = None


class Transcriber:
    """Singleton-style Whisper wrapper; load once, transcribe many."""

    def __init__(
        self,
        model: str = "large-v3-turbo",
        device: str = "auto",
        compute_type: str = "int8",
        language: str | None = None,
        initial_prompt: str = "",
    ) -> None:
        self._model_name = model
        self._device_pref = device
        self._compute_type = compute_type
        self._language = language
        self._initial_prompt = initial_prompt
        self._model: WhisperModel | None = None
        self._actual_device: str = "cpu"

    def set_initial_prompt(self, prompt: str) -> None:
        """Update the glossary hint used on the next transcribe call."""
        self._initial_prompt = prompt

    def set_language(self, language: str | None) -> None:
        """Update the forced-language code (or None for auto-detect).

        Hot-swappable: only affects subsequent transcribe() calls. The model
        itself doesn't need to be reloaded — language is just an argument to
        WhisperModel.transcribe.
        """
        self._language = language

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

        audio_sec = len(audio) / sample_rate
        _log.info(
            "transcribe_start",
            audio_sec=round(audio_sec, 2),
            device=self._actual_device,
        )
        t_start = time.monotonic()
        try:
            segments_iter, info = self._model.transcribe(
                audio,
                beam_size=1,
                vad_filter=False,
                language=self._language,
                condition_on_previous_text=False,
                initial_prompt=self._initial_prompt or None,
            )
            _log.info(
                "transcribe_decoded",
                decoded_sec=round(time.monotonic() - t_start, 2),
                lang=info.language,
                lang_prob=round(info.language_probability, 3),
            )
            # Diagnostic logging for auto-detect path. Surfaces the top-5
            # language candidates and warns on low-confidence picks. KZ
            # often shows up as az/tr/uz/ar in the top-5 even when the
            # picked language is something else — this lets us see that
            # without rebuilding the model. See research notes:
            # docs/research/2026-05-23-kz-detection-root-cause.md
            if self._language is None and info.all_language_probs:
                top5 = sorted(info.all_language_probs, key=lambda x: -x[1])[:5]
                top5_rounded = [(lang, round(p, 3)) for lang, p in top5]
                _log.info("language_candidates", top5=top5_rounded)
                if info.language_probability < 0.5:
                    _log.warning(
                        "low_confidence_detection",
                        lang=info.language,
                        prob=round(info.language_probability, 3),
                        top5=top5_rounded,
                    )
            segments = [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in segments_iter
            ]
            _log.info(
                "transcribe_end",
                total_sec=round(time.monotonic() - t_start, 2),
                n_segments=len(segments),
            )
        except RuntimeError as exc:
            _log.error("transcribe_error", error=str(exc))
            msg = str(exc).lower()
            if "out of memory" in msg or ("cuda" in msg and "memory" in msg):
                raise CudaOOMError(str(exc)) from exc
            raise ModelNotLoadedError(str(exc)) from exc

        raw_text = filter_hallucinations(" ".join(s["text"] for s in segments).strip())
        duration_ms = int(info.duration * 1000) if info.duration else 0
        language = info.language or ""
        language_probability = float(info.language_probability or 0.0)
        all_language_probs = (
            list(info.all_language_probs) if info.all_language_probs else None
        )

        return TranscriptResult(
            raw_text=raw_text,
            language=language,
            duration_ms=duration_ms,
            segments=segments,
            language_probability=language_probability,
            all_language_probs=all_language_probs,
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
    # np.interp's return type is typed as Any in numpy's stubs;
    # .astype(np.float32) narrows the runtime dtype but mypy still
    # sees an Any. Explicit cast keeps the public signature honest.
    return cast(np.ndarray, np.interp(y, x, audio).astype(np.float32))
