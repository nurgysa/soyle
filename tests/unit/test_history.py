"""Tests for HistoryStore — local capped dictation log."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from soyle.core.history import MAX_ENTRIES, HistoryEntry, HistoryStore, build_entry, should_record


def test_build_entry_stamps_microsecond_iso() -> None:
    fixed = datetime(2026, 6, 16, 10, 32, 5, 123456, tzinfo=UTC)
    entry = build_entry("обработанный", "сырой", "ru", "polish", False, now=fixed)
    assert entry.timestamp == "2026-06-16T10:32:05.123456Z"
    assert entry.processed_text == "обработанный"
    assert entry.raw_text == "сырой"
    assert entry.language == "ru"
    assert entry.mode == "polish"
    assert entry.fallback is False


def test_should_record_gates_on_enabled_and_nonempty() -> None:
    assert should_record("текст", enabled=True) is True
    assert should_record("текст", enabled=False) is False
    assert should_record("   ", enabled=True) is False
    assert should_record("", enabled=True) is False


# ---------------------------------------------------------------------------
# Task 2: HistoryStore append + cap + all()
# ---------------------------------------------------------------------------

def _entry(n: int) -> HistoryEntry:
    return build_entry(
        f"processed-{n}", f"raw-{n}", "ru", "polish", False,
        now=datetime(2026, 6, 16, 10, 0, n % 60, n, tzinfo=UTC),
    )


def test_append_prepends_newest_first(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.append(_entry(1))
    store.append(_entry(2))
    texts = [e.processed_text for e in store.all()]
    assert texts == ["processed-2", "processed-1"]


def test_append_enforces_cap_dropping_oldest(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    for n in range(MAX_ENTRIES + 5):
        store.append(_entry(n))
    entries = store.all()
    assert len(entries) == MAX_ENTRIES
    # Newest kept, oldest five dropped.
    assert entries[0].processed_text == f"processed-{MAX_ENTRIES + 4}"
    assert entries[-1].processed_text == "processed-5"


# ---------------------------------------------------------------------------
# Task 3: HistoryStore delete + clear
# ---------------------------------------------------------------------------

def test_delete_removes_one_by_timestamp(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.append(_entry(1))
    store.append(_entry(2))
    target = store.all()[0].timestamp  # the newest (entry 2)
    store.delete(target)
    remaining = [e.processed_text for e in store.all()]
    assert remaining == ["processed-1"]


def test_clear_empties_store(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.append(_entry(1))
    store.clear()
    assert store.all() == []


# ---------------------------------------------------------------------------
# Task 4: HistoryStore load + persistence + broken-file recovery
# ---------------------------------------------------------------------------

def test_entries_persist_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    HistoryStore(path).append(_entry(1))
    reopened = HistoryStore(path)
    assert [e.processed_text for e in reopened.all()] == ["processed-1"]


def test_on_disk_shape_has_version_and_entries(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    HistoryStore(path).append(_entry(1))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert isinstance(raw["entries"], list)
    assert raw["entries"][0]["processed_text"] == "processed-1"


def test_load_survives_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")
    store = HistoryStore(path)
    assert store.all() == []
    store.append(_entry(1))  # still works after recovery
    assert len(store.all()) == 1


def test_load_skips_malformed_rows(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "entries": [
                {"timestamp": "t", "processed_text": "ok", "raw_text": "r",
                 "language": "ru", "mode": "polish", "fallback": False},
                {"garbage": True},
            ],
        }),
        encoding="utf-8",
    )
    store = HistoryStore(path)
    assert [e.processed_text for e in store.all()] == ["ok"]


def test_load_caps_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    rows = [
        {"timestamp": f"t{n}", "processed_text": f"p{n}", "raw_text": "r",
         "language": "ru", "mode": "polish", "fallback": False}
        for n in range(MAX_ENTRIES + 10)
    ]
    path.write_text(json.dumps({"version": 1, "entries": rows}), encoding="utf-8")
    assert len(HistoryStore(path).all()) == MAX_ENTRIES


# ---------------------------------------------------------------------------
# Review follow-ups (code-quality minors)
# ---------------------------------------------------------------------------

def test_empty_store_returns_empty_list(tmp_path: Path) -> None:
    # Exercises the missing-file branch of _load (distinct from clear()).
    store = HistoryStore(tmp_path / "history.json")
    assert store.all() == []


def test_unicode_survives_round_trip(tmp_path: Path) -> None:
    # The app dictates Cyrillic/Kazakh — prove ensure_ascii=False round-trips.
    path = tmp_path / "history.json"
    fixed = datetime(2026, 6, 16, 10, 0, 1, tzinfo=UTC)
    entry = build_entry("обработанный текст", "сырой текст 🎙", "ru", "polish", False, now=fixed)
    HistoryStore(path).append(entry)
    reopened = HistoryStore(path).all()
    assert reopened[0].processed_text == "обработанный текст"
    assert reopened[0].raw_text == "сырой текст 🎙"


def test_delete_nonexistent_timestamp_is_noop(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.append(_entry(1))
    store.delete("does-not-exist")
    assert len(store.all()) == 1
