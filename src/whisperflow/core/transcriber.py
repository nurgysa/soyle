"""Whisper inference wrapper.

Part 1: pure text-cleanup helpers (this file).
Part 2: Transcriber class using faster-whisper (task 4.3).
"""
from __future__ import annotations

import re

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
