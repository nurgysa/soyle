"""Unit tests for KzAwareTranscriber routing logic.

Pattern: FakeTranscriber records calls and returns canned
TranscriptResult instances. No real Whisper model is loaded.
Routing decisions are tested as pure functions of detection info.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from soyle.core.kz_aware_transcriber import KzAwareTranscriber
from soyle.core.transcriber import TranscriptResult


def _make_result(
    *,
    text: str = "primary text",
    language: str = "ru",
    language_probability: float = 0.98,
    all_language_probs: list[tuple[str, float]] | None = None,
) -> TranscriptResult:
    """Build a TranscriptResult with sensible defaults for routing tests."""
    return TranscriptResult(
        raw_text=text,
        language=language,
        duration_ms=1000,
        segments=[{"start": 0.0, "end": 1.0, "text": text}],
        language_probability=language_probability,
        all_language_probs=all_language_probs,
    )


def _raise_runtime_error() -> None:
    raise RuntimeError("warm_up failed: model dir missing")


class FakeTranscriber:
    """Drop-in fake satisfying the Transcriber duck-type used by KzAware."""

    def __init__(self, result_factory: Callable[[], TranscriptResult]) -> None:
        self.result_factory = result_factory
        self.transcribe_calls: list[tuple[tuple[int, ...], int]] = []
        self.warm_up_calls: int = 0
        self.initial_prompts: list[str] = []
        self.languages: list[str | None] = []

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> TranscriptResult:
        self.transcribe_calls.append((audio.shape, sample_rate))
        return self.result_factory()

    def warm_up(self) -> None:
        self.warm_up_calls += 1

    def set_initial_prompt(self, prompt: str) -> None:
        self.initial_prompts.append(prompt)

    def set_language(self, language: str | None) -> None:
        self.languages.append(language)

    @property
    def device(self) -> str:
        return "cpu"


@pytest.fixture
def audio() -> np.ndarray:
    """Dummy 1s @ 16kHz silence — content irrelevant for routing tests."""
    return np.zeros(16000, dtype=np.float32)


# ---- Routing decisions ----


def test_route_to_primary_when_ru_detected(audio: np.ndarray) -> None:
    """High-confidence Russian → no KZ routing, factory never called."""
    primary = FakeTranscriber(lambda: _make_result(language="ru", language_probability=0.98))
    factory_calls = [0]

    def factory() -> FakeTranscriber:
        factory_calls[0] += 1
        return FakeTranscriber(lambda: _make_result(text="kz"))

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=factory)
    result = wrapper.transcribe(audio, 16000)

    assert result.language == "ru"
    assert result.raw_text == "primary text"
    assert factory_calls[0] == 0  # never invoked


def test_route_to_kz_when_kk_detected(audio: np.ndarray) -> None:
    """Detected language == kk → route, factory creates kz, kz transcribes."""
    primary = FakeTranscriber(lambda: _make_result(language="kk", language_probability=0.7))
    kz = FakeTranscriber(lambda: _make_result(text="каzах text", language="kk"))

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=lambda: kz)
    result = wrapper.transcribe(audio, 16000)

    assert result.raw_text == "каzах text"
    assert kz.transcribe_calls == [(audio.shape, 16000)]


def test_route_to_kz_when_turkic_low_conf(audio: np.ndarray) -> None:
    """Detected az with prob<0.6 → route to KZ."""
    primary = FakeTranscriber(lambda: _make_result(language="az", language_probability=0.35))
    kz = FakeTranscriber(lambda: _make_result(text="kz output"))

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=lambda: kz)
    result = wrapper.transcribe(audio, 16000)

    assert result.raw_text == "kz output"


def test_no_route_when_turkic_high_conf(audio: np.ndarray) -> None:
    """Detected az with prob>=0.6 → trust primary, no KZ route."""
    primary = FakeTranscriber(lambda: _make_result(language="az", language_probability=0.85))
    factory_calls = [0]

    def factory() -> FakeTranscriber:
        factory_calls[0] += 1
        return FakeTranscriber(lambda: _make_result())

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=factory)
    result = wrapper.transcribe(audio, 16000)

    assert result.language == "az"
    assert factory_calls[0] == 0


def test_route_when_kk_in_top5(audio: np.ndarray) -> None:
    """Primary picked ar with prob 0.4, but kk in top-5 with prob 0.15 → route."""
    primary = FakeTranscriber(
        lambda: _make_result(
            language="ar",
            language_probability=0.4,
            all_language_probs=[("ar", 0.4), ("kk", 0.15), ("ru", 0.1)],
        )
    )
    kz = FakeTranscriber(lambda: _make_result(text="kz output"))

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=lambda: kz)
    result = wrapper.transcribe(audio, 16000)

    assert result.raw_text == "kz output"


def test_no_route_when_kk_top5_prob_too_low(audio: np.ndarray) -> None:
    """kk present in top-5 but with prob 0.05 (< 0.10 threshold) → not routed."""
    primary = FakeTranscriber(
        lambda: _make_result(
            language="ar",
            language_probability=0.7,
            all_language_probs=[("ar", 0.7), ("kk", 0.05), ("ru", 0.1)],
        )
    )
    factory_calls = [0]

    def factory() -> FakeTranscriber:
        factory_calls[0] += 1
        return FakeTranscriber(lambda: _make_result())

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=factory)
    result = wrapper.transcribe(audio, 16000)

    assert result.language == "ar"
    assert factory_calls[0] == 0


def test_no_route_at_exact_turkic_threshold(audio: np.ndarray) -> None:
    """prob exactly 0.6 does NOT route — the comparison is strict `<`."""
    primary = FakeTranscriber(lambda: _make_result(language="az", language_probability=0.6))
    factory_calls = [0]

    def factory() -> FakeTranscriber:
        factory_calls[0] += 1
        return FakeTranscriber(lambda: _make_result())

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=factory)
    result = wrapper.transcribe(audio, 16000)

    assert result.language == "az"
    assert factory_calls[0] == 0


def test_route_at_exact_top5_threshold(audio: np.ndarray) -> None:
    """kk in top-5 with prob exactly 0.10 DOES route — the comparison is `>=`."""
    primary = FakeTranscriber(
        lambda: _make_result(
            language="ar",
            language_probability=0.7,
            all_language_probs=[("ar", 0.7), ("kk", 0.10)],
        )
    )
    kz = FakeTranscriber(lambda: _make_result(text="kz output"))

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=lambda: kz)
    result = wrapper.transcribe(audio, 16000)

    assert result.raw_text == "kz output"


# ---- Lazy load + failure handling ----


def test_lazy_load_only_first_time(audio: np.ndarray) -> None:
    """Two KZ-routes in a row → factory called exactly once, kz cached."""
    primary = FakeTranscriber(lambda: _make_result(language="kk"))
    kz = FakeTranscriber(lambda: _make_result(text="kz", language="kk"))
    factory_calls = [0]

    def factory() -> FakeTranscriber:
        factory_calls[0] += 1
        return kz

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=factory)
    wrapper.transcribe(audio, 16000)
    wrapper.transcribe(audio, 16000)

    assert factory_calls[0] == 1
    assert len(kz.transcribe_calls) == 2


def test_load_failure_invokes_toast_once(audio: np.ndarray) -> None:
    """Factory raises on first attempt → toast fires once; attempt 2 short-circuits on the failed-once flag (factory not called again)."""
    primary = FakeTranscriber(lambda: _make_result(language="kk"))
    factory_calls = [0]

    def failing_factory() -> FakeTranscriber:
        factory_calls[0] += 1
        raise RuntimeError("model not found")

    toasts: list[str] = []
    wrapper = KzAwareTranscriber(primary=primary, kz_factory=failing_factory)
    wrapper.set_failure_toast_callback(lambda msg: toasts.append(msg))

    wrapper.transcribe(audio, 16000)
    wrapper.transcribe(audio, 16000)

    assert len(toasts) == 1
    assert "KZ recognition недоступен" in toasts[0]
    assert factory_calls[0] == 1


def test_load_failure_returns_primary_fallback(audio: np.ndarray) -> None:
    """When KZ model fails to load, wrapper returns primary's result, not None."""
    primary = FakeTranscriber(lambda: _make_result(text="primary fallback", language="kk"))

    def failing_factory() -> FakeTranscriber:
        raise RuntimeError("disk full")

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=failing_factory)
    result = wrapper.transcribe(audio, 16000)

    assert result.raw_text == "primary fallback"


def test_failure_without_toast_callback_does_not_crash(audio: np.ndarray) -> None:
    """No toast registered (test environment) → log only, no AttributeError."""
    primary = FakeTranscriber(lambda: _make_result(language="kk"))

    def failing_factory() -> FakeTranscriber:
        raise RuntimeError("missing")

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=failing_factory)
    # set_failure_toast_callback NOT called.
    result = wrapper.transcribe(audio, 16000)

    assert result.language == "kk"  # primary's result returned


def test_warm_up_failure_falls_back_permanently(audio: np.ndarray) -> None:
    """Factory succeeds but warm_up() raises → BOTH calls fall back to primary.

    This is the real production failure path: Transcriber.__init__ only
    stores config; the model actually loads inside warm_up(). A partially
    constructed (never-warmed) KZ model must not be cached and returned
    on the second call.
    """
    primary = FakeTranscriber(lambda: _make_result(text="primary fallback", language="kk"))
    kz = FakeTranscriber(lambda: _make_result(text="kz"))
    kz.warm_up = _raise_runtime_error  # type: ignore[method-assign]
    factory_calls = [0]

    def factory() -> FakeTranscriber:
        factory_calls[0] += 1
        return kz

    toasts: list[str] = []
    wrapper = KzAwareTranscriber(primary=primary, kz_factory=factory)
    wrapper.set_failure_toast_callback(lambda msg: toasts.append(msg))

    r1 = wrapper.transcribe(audio, 16000)
    r2 = wrapper.transcribe(audio, 16000)

    assert r1.raw_text == "primary fallback"
    assert r2.raw_text == "primary fallback"  # NOT the never-warmed kz model
    assert kz.transcribe_calls == []  # kz never used for transcription
    assert factory_calls[0] == 1  # failed-once flag short-circuits attempt 2
    assert len(toasts) == 1


# ---- API forwarding ----


def test_set_initial_prompt_forwards_to_both_when_kz_loaded(audio: np.ndarray) -> None:
    """After KZ lazy-load, set_initial_prompt forwards to primary AND kz."""
    primary = FakeTranscriber(lambda: _make_result(language="kk"))
    kz = FakeTranscriber(lambda: _make_result(text="kz", language="kk"))
    wrapper = KzAwareTranscriber(primary=primary, kz_factory=lambda: kz)

    # Trigger lazy load.
    wrapper.transcribe(audio, 16000)
    # Now set the prompt.
    wrapper.set_initial_prompt("Glossary: Söyle, Astana.")

    assert primary.initial_prompts == ["Glossary: Söyle, Astana."]
    assert kz.initial_prompts == ["Glossary: Söyle, Astana."]


def test_set_initial_prompt_doesnt_force_kz_load() -> None:
    """set_initial_prompt called before any transcribe → kz never loaded."""
    primary = FakeTranscriber(lambda: _make_result())
    factory_calls = [0]

    def factory() -> FakeTranscriber:
        factory_calls[0] += 1
        return FakeTranscriber(lambda: _make_result())

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=factory)
    wrapper.set_initial_prompt("hint")

    assert primary.initial_prompts == ["hint"]
    assert factory_calls[0] == 0


def test_set_language_only_forwards_to_primary(audio: np.ndarray) -> None:
    """KZ model is always lang=kk — wrapper does NOT forward set_language."""
    primary = FakeTranscriber(lambda: _make_result(language="kk"))
    kz = FakeTranscriber(lambda: _make_result(text="kz", language="kk"))
    wrapper = KzAwareTranscriber(primary=primary, kz_factory=lambda: kz)

    wrapper.transcribe(audio, 16000)  # triggers kz load
    wrapper.set_language("ru")

    assert primary.languages == ["ru"]
    assert kz.languages == []  # untouched


def test_warm_up_only_primary() -> None:
    """warm_up() forwards to primary only — KZ stays lazy by design."""
    primary = FakeTranscriber(lambda: _make_result())
    kz = FakeTranscriber(lambda: _make_result())
    wrapper = KzAwareTranscriber(primary=primary, kz_factory=lambda: kz)

    wrapper.warm_up()

    assert primary.warm_up_calls == 1
    assert kz.warm_up_calls == 0


# ---- Edge cases ----


def test_all_language_probs_none_skips_top5_signal(audio: np.ndarray) -> None:
    """When primary returns all_language_probs=None, signal (c) is skipped.

    Signals (a) lang==kk and (b) turkic+low-conf still evaluate normally.
    Here: detected ar, prob 0.85 (high), all_language_probs None → no route.
    """
    primary = FakeTranscriber(
        lambda: _make_result(
            language="ar",
            language_probability=0.85,
            all_language_probs=None,
        )
    )
    factory_calls = [0]

    def factory() -> FakeTranscriber:
        factory_calls[0] += 1
        return FakeTranscriber(lambda: _make_result())

    wrapper = KzAwareTranscriber(primary=primary, kz_factory=factory)
    result = wrapper.transcribe(audio, 16000)

    assert result.language == "ar"
    assert factory_calls[0] == 0
