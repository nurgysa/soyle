"""User custom-dictionary storage.

Terms are persisted in ``%APPDATA%\\Söyle\\dictionary.toml`` as a
simple list of strings. They are used in two places:

1. ``Transcriber`` passes them as the faster-whisper ``initial_prompt``
   so the decoder is biased toward the correct spelling.
2. ``PostProcess`` injects them into the LLM system prompt so the polish
   stage preserves them verbatim.

Storage format::

    version = 1
    terms = ["Söyle", "OpenRouter", "Astana"]
"""
from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path

import tomli_w
from platformdirs import user_config_path

APP_NAME = "Söyle"
MAX_TERMS = 200  # faster-whisper initial_prompt tolerates ~224 tokens; leave headroom


def default_dictionary_path() -> Path:
    """Return ``%APPDATA%\\Söyle\\dictionary.toml`` on Windows."""
    return user_config_path(APP_NAME, appauthor=False, roaming=True) / "dictionary.toml"


class DictionaryStore:
    """Load/save a de-duplicated, order-preserving list of terms."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_dictionary_path()

    @property
    def path(self) -> Path:
        return self._path

    # ---- Load / save ----

    def load(self) -> list[str]:
        if not self._path.exists():
            return []
        try:
            raw = tomllib.loads(self._path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            self._backup_broken()
            return []
        terms = raw.get("terms", [])
        if not isinstance(terms, list):
            return []
        return [str(t).strip() for t in terms if str(t).strip()]

    def save(self, terms: list[str]) -> None:
        cleaned = _dedupe_preserving_order(t.strip() for t in terms if t.strip())
        if len(cleaned) > MAX_TERMS:
            cleaned = cleaned[:MAX_TERMS]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("wb") as f:
            tomli_w.dump({"version": 1, "terms": cleaned}, f)

    # ---- Mutations ----

    def add(self, term: str) -> list[str]:
        term = term.strip()
        if not term:
            return self.load()
        current = self.load()
        if term in current:
            return current
        current.append(term)
        self.save(current)
        return current

    def remove(self, term: str) -> list[str]:
        current = self.load()
        try:
            current.remove(term)
        except ValueError:
            return current
        self.save(current)
        return current

    def clear(self) -> None:
        self.save([])

    # ---- Rendering helpers for callers ----

    def as_whisper_prompt(self) -> str:
        """Return a Whisper-friendly hint string, or '' if empty.

        Kept short so it fits within faster-whisper's initial_prompt budget.
        """
        terms = self.load()
        if not terms:
            return ""
        return "Glossary: " + ", ".join(terms) + "."

    def as_llm_instruction(self) -> str:
        """Return a clause for the LLM polish system prompt, or '' if empty."""
        terms = self.load()
        if not terms:
            return ""
        return (
            "Preserve these proper nouns and technical terms verbatim "
            "(do not translate or change case): " + ", ".join(terms) + "."
        )

    # ---- Internals ----

    def _backup_broken(self) -> None:
        if not self._path.exists():
            return
        # Symlink-attack defence — see ConfigStore._backup_broken for rationale.
        if self._path.is_symlink():
            self._path.unlink()
            return
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
        backup = self._path.with_suffix(f".toml.broken-{ts}")
        self._path.rename(backup)


def _dedupe_preserving_order(items: object) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
