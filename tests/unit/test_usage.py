"""Tests for UsageTracker — JSON-backed daily cost aggregation."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from whisperflow.core.usage import UsageTracker


def _today() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


def test_record_and_today(tmp_path: Path) -> None:
    t = UsageTracker(tmp_path / "usage.json")
    t.record(0.001)
    t.record(0.002)
    cost, n = t.today()
    assert cost == 0.003
    assert n == 2


def test_this_month_aggregates_multiple_days(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    now = datetime.now(tz=UTC)
    month_prefix = now.strftime("%Y-%m-")
    # Seed the file with two days in the current month + one way older.
    path.write_text(
        json.dumps({
            f"{month_prefix}01": {"cost_usd": 0.01, "requests": 3},
            f"{month_prefix}15": {"cost_usd": 0.02, "requests": 5},
            "2020-01-01": {"cost_usd": 9.99, "requests": 999},
        }),
        encoding="utf-8",
    )
    t = UsageTracker(path)
    cost, n = t.this_month()
    # The "2020-01-01" old entry should be trimmed on next save, but this_month
    # already filters by prefix so it's ignored regardless.
    assert cost == 0.03
    assert n == 8


def test_trims_old_entries_on_save(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    old_day = (datetime.now(tz=UTC).date() - timedelta(days=60)).isoformat()
    path.write_text(
        json.dumps({old_day: {"cost_usd": 1.0, "requests": 10}}),
        encoding="utf-8",
    )
    t = UsageTracker(path)
    # Trigger a save, which runs trimming.
    t.record(0.0001)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert old_day not in persisted
    assert _today() in persisted


def test_load_survives_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text("{not json", encoding="utf-8")
    t = UsageTracker(path)
    # Corrupt file → empty state; new records still work.
    t.record(0.005)
    cost, n = t.today()
    assert cost == 0.005
    assert n == 1


def test_summary_line_formatting(tmp_path: Path) -> None:
    t = UsageTracker(tmp_path / "usage.json")
    t.record(0.0012)
    line = t.summary_line()
    assert "Сегодня" in line
    assert "$0.0012" in line
    assert "(1)" in line
