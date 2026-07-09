"""Tests for the history window + its pure helpers."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from soyle.core.history import HistoryStore, build_entry
from soyle.ui.history_window import HistoryWindow, format_relative

_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


def _seed(tmp_path: Path) -> HistoryStore:
    store = HistoryStore(tmp_path / "history.json")
    store.append(build_entry("первый processed", "первый raw", "ru", "polish", False,
                             now=datetime(2026, 6, 16, 9, 0, 0, tzinfo=UTC)))
    store.append(build_entry("второй processed", "второй raw", "kk", "rewrite", False,
                             now=datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)))
    return store


def test_relative_just_now() -> None:
    ts = "2026-06-16T11:59:30.000000Z"
    assert format_relative(ts, now=_NOW) == "только что"


def test_relative_minutes() -> None:
    ts = "2026-06-16T11:45:00.000000Z"
    assert "15" in format_relative(ts, now=_NOW)
    assert "мин" in format_relative(ts, now=_NOW)


def test_relative_hours() -> None:
    ts = "2026-06-16T09:00:00.000000Z"
    assert "3" in format_relative(ts, now=_NOW)
    assert "ч" in format_relative(ts, now=_NOW)


def test_relative_yesterday() -> None:
    ts = "2026-06-15T10:00:00.000000Z"
    assert format_relative(ts, now=_NOW) == "вчера"


def test_relative_older_is_date() -> None:
    ts = "2026-06-10T10:00:00.000000Z"
    assert format_relative(ts, now=_NOW) == "10.06.2026"


def test_relative_unparseable_returns_input() -> None:
    assert format_relative("garbage", now=_NOW) == "garbage"


def test_window_lists_newest_first_and_autoselects(qtbot, tmp_path: Path) -> None:
    store = _seed(tmp_path)
    win = HistoryWindow(store, on_inject=lambda _t: None)
    qtbot.addWidget(win)
    win.show()

    assert win._list.count() == 2
    # Newest ("второй") is row 0 and auto-selected; detail shows it.
    assert win._list.currentRow() == 0
    assert "второй processed" in win._detail_processed.text()


def test_selecting_row_updates_detail(qtbot, tmp_path: Path) -> None:
    store = _seed(tmp_path)
    win = HistoryWindow(store, on_inject=lambda _t: None)
    qtbot.addWidget(win)
    win.show()

    win._list.setCurrentRow(1)  # the older "первый"
    assert "первый processed" in win._detail_processed.text()
    assert "первый raw" in win._detail_raw.text()


def test_empty_store_shows_no_rows(qtbot, tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    win = HistoryWindow(store, on_inject=lambda _t: None)
    qtbot.addWidget(win)
    win.show()
    assert win._list.count() == 0
