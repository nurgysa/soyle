"""Local dictation history — newest-first, capped JSON log.

Stored at %APPDATA%/Soyle/history.json as:
    {"version": 1, "entries": [ {entry}, ... ]}   # newest first

Mirrors core/usage.py: plain JSON, broken-file recovery, bounded size.
Local-only by design — history is NOT part of cloud sync, so transcripts
never leave the device.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

log = structlog.get_logger()

MAX_ENTRIES = 100


@dataclass(frozen=True)
class HistoryEntry:
    timestamp: str       # ISO 8601 UTC, microsecond precision; unique delete key
    processed_text: str
    raw_text: str
    language: str
    mode: str
    fallback: bool


def build_entry(
    processed_text: str,
    raw_text: str,
    language: str,
    mode: str,
    fallback: bool,
    *,
    now: datetime | None = None,
) -> HistoryEntry:
    """Build a HistoryEntry stamped now (UTC, microsecond precision).

    `now` is injectable so tests get a deterministic timestamp.
    """
    stamp = (now or datetime.now(tz=UTC)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return HistoryEntry(
        timestamp=stamp,
        processed_text=processed_text,
        raw_text=raw_text,
        language=language,
        mode=mode,
        fallback=fallback,
    )


def should_record(text: str, *, enabled: bool) -> bool:
    """History records only non-empty text, and only when enabled."""
    return enabled and bool(text.strip())


class HistoryStore:
    """JSON-backed, newest-first, capped at MAX_ENTRIES."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: list[HistoryEntry] = self._load()

    def append(self, entry: HistoryEntry) -> None:
        """Prepend newest, drop the oldest beyond the cap, persist."""
        self._entries.insert(0, entry)
        del self._entries[MAX_ENTRIES:]
        self._save()

    def all(self) -> list[HistoryEntry]:
        """Newest-first snapshot (a copy — callers may not mutate internals)."""
        return list(self._entries)

    def delete(self, timestamp: str) -> None:
        """Remove the entry whose timestamp matches (no-op if absent)."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.timestamp != timestamp]
        if len(self._entries) != before:
            self._save()

    def clear(self) -> None:
        """Wipe all entries."""
        self._entries = []
        self._save()

    # -- internals --

    def _load(self) -> list[HistoryEntry]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("history_load_failed", error=str(exc), path=str(self._path))
            return []
        if not isinstance(raw, dict):
            return []
        rows = raw.get("entries", [])
        if not isinstance(rows, list):
            return []
        out: list[HistoryEntry] = []
        for item in rows:
            try:
                out.append(HistoryEntry(**item))
            except TypeError:
                continue  # skip malformed rows, keep the rest
        return out[:MAX_ENTRIES]

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "entries": [asdict(e) for e in self._entries]}
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("history_save_failed", error=str(exc), path=str(self._path))
