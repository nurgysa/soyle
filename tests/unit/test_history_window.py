"""Tests for the history window + its pure helpers."""
from __future__ import annotations

from datetime import UTC, datetime

from soyle.ui.history_window import format_relative

_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


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
