"""Integration tests for Transcriber with real Whisper model."""
from __future__ import annotations

import json
import wave
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pytest

from soyle.core.transcriber import Transcriber

pytestmark = pytest.mark.gpu


def _load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        frames = w.readframes(w.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sr


@pytest.fixture(scope="module")
def transcriber() -> Transcriber:
    t = Transcriber(model="large-v3-turbo", device="auto", compute_type="int8")
    t.warm_up()
    return t


def test_short_ru(transcriber: Transcriber, audio_fixture_dir: Path) -> None:
    wav = audio_fixture_dir / "short_ru.wav"
    if not wav.exists():
        pytest.skip("short_ru.wav fixture not recorded yet")

    audio, sr = _load_wav(wav)
    result = transcriber.transcribe(audio, sample_rate=sr)

    expected = json.loads((audio_fixture_dir / "expected.json").read_text())["short_ru.wav"]
    ratio = SequenceMatcher(None, result.raw_text.lower(), expected["expected_text"].lower()).ratio()
    assert ratio >= expected["min_similarity"], f"got '{result.raw_text}', expected ~'{expected['expected_text']}'"
    assert result.language == "ru"


def test_silence_returns_empty(transcriber: Transcriber, audio_fixture_dir: Path) -> None:
    wav = audio_fixture_dir / "silence.wav"
    if not wav.exists():
        pytest.skip("silence.wav fixture not recorded yet")

    audio, sr = _load_wav(wav)
    result = transcriber.transcribe(audio, sample_rate=sr)

    assert result.raw_text == ""
