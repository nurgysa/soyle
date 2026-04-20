"""Tests for Transcriber's pure text-post-processing helpers."""
from __future__ import annotations

from whisperflow.core.transcriber import filter_hallucinations, normalize_whitespace


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
