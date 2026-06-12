"""Tests for soyle.core.transcriber dataclasses.

The Transcriber class itself loads a real WhisperModel and is exercised
manually per docs/MANUAL_TESTS.md. This file covers the pure-data parts
(TranscriptResult dataclass shape) that don't need a GPU.
"""
from __future__ import annotations

from soyle.core.transcriber import TranscriptResult


def test_transcript_result_defaults_are_backward_compatible() -> None:
    """TranscriptResult must construct without the new fields — positionally.

    PR A added language_probability and all_language_probs with defaults to
    keep existing tests + callers compiling. Positional construction is the
    stronger check: it also fails if someone inserts a future field in the
    middle of the field order, which kwargs construction would mask.
    """
    result = TranscriptResult("hello", "en", 100, [])
    assert result.language_probability == 0.0
    assert result.all_language_probs is None
