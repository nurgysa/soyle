"""Tests for Transcriber's pure text-post-processing helpers."""
from __future__ import annotations

from soyle.core.transcriber import (
    WHISPER_MODELS,
    Transcriber,
    filter_hallucinations,
    normalize_whitespace,
)


def test_normalize_whitespace_collapses_spaces() -> None:
    assert normalize_whitespace("  hello  world  ") == "hello world"
    assert normalize_whitespace("line1\n\nline2") == "line1 line2"


def test_filter_hallucinations_removes_repeat_spam() -> None:
    # 4 copies of "Subscribe!" with spaces → treat as hallucination
    text = "Subscribe! Subscribe! Subscribe! Subscribe!"
    assert filter_hallucinations(text) == ""


def test_filter_hallucinations_allows_natural_repetition() -> None:
    # "Yes yes yes" is natural speech, not hallucination
    text = "Yes yes yes I agree"
    assert filter_hallucinations(text) == "Yes yes yes I agree"


def test_filter_hallucinations_strips_music_tag() -> None:
    text = "[Music] hello world"
    assert filter_hallucinations(text) == "hello world"


def test_filter_hallucinations_handles_empty() -> None:
    assert filter_hallucinations("") == ""
    assert filter_hallucinations("   ") == ""


def test_filter_hallucinations_preserves_real_speech() -> None:
    text = "Привет, это обычное предложение."
    assert filter_hallucinations(text) == text


def test_whisper_models_cover_expected_checkpoints() -> None:
    """The dropdown must offer the four canonical multilingual checkpoints.

    Order matters for UX (recommended at the top), and labels feed the UI
    directly — keep the contract pinned so a refactor can't silently drop
    a model or swap the recommended one.
    """
    ids = [p.model_id for p in WHISPER_MODELS]
    assert ids == ["large-v3-turbo", "large-v3", "medium", "small"]
    # display_label format must contain the model id (used by the parser
    # in SettingsWindow._resolve_combo_model_id when user types custom).
    for preset in WHISPER_MODELS:
        assert preset.display_label.startswith(preset.model_id + "  ·  ")


def test_set_language_updates_without_loading_model() -> None:
    """set_language must be hot-swappable — it should NOT trigger model load.

    The Transcriber constructor stores the language but lazy-loads the model;
    set_language must update the attribute directly so it takes effect on the
    next transcribe() call without restarting.
    """
    t = Transcriber(language="ru")
    # No call to transcribe() / warm_up() — model must remain None.
    assert t._model is None
    t.set_language("kk")
    assert t._language == "kk"
    assert t._model is None
    t.set_language(None)
    assert t._language is None
    assert t._model is None
