"""The recording composition used by SoyleApp._finish_inference.

Mirrors the gate without booting Qt (same approach as test_monthly_limit):
should_record + build_entry + HistoryStore.append, exactly as the app
composes them.
"""
from __future__ import annotations

from pathlib import Path

from soyle.core.history import HistoryStore, build_entry, should_record


def _record(store: HistoryStore, *, text: str, raw: str, enabled: bool) -> None:
    # mode is hardcoded "polish"; the app sources it from cfg.postprocess.mode
    # at call time, but the gate logic is independent of the mode value.
    # Keyword args mirror the app's build_entry call so a param-order change
    # cannot silently build the wrong entry here.
    if should_record(text, enabled=enabled):
        store.append(
            build_entry(
                processed_text=text,
                raw_text=raw,
                language="ru",
                mode="polish",
                fallback=False,
            )
        )


def test_records_when_enabled_and_nonempty(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    _record(store, text="привет", raw="привет сырой", enabled=True)
    entries = store.all()
    assert len(entries) == 1
    assert entries[0].processed_text == "привет"
    assert entries[0].raw_text == "привет сырой"


def test_skips_when_disabled(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    _record(store, text="привет", raw="r", enabled=False)
    assert store.all() == []


def test_skips_when_empty(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    _record(store, text="   ", raw="", enabled=True)
    assert store.all() == []
