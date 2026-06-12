"""Tests for soyle.core.transcriber dataclasses.

The Transcriber class itself loads a real WhisperModel and is exercised
manually per docs/MANUAL_TESTS.md. This file covers the pure-data parts
(TranscriptResult dataclass shape) that don't need a GPU.
"""
from __future__ import annotations


def test_transcript_result_defaults_are_backward_compatible() -> None:
    """TranscriptResult must construct without the new fields (positional or kwargs).

    PR A added language_probability and all_language_probs with defaults to
    keep existing tests + callers compiling. If someone removes the defaults
    later, this test fails loudly so they remember to update everything.
    """
    from soyle.core.transcriber import TranscriptResult

    result = TranscriptResult(
        raw_text="hello",
        language="en",
        duration_ms=100,
        segments=[],
    )
    assert result.language_probability == 0.0
    assert result.all_language_probs is None
