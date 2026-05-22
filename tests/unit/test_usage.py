"""Tests for UsageTracker — JSON-backed daily cost aggregation."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from soyle.core.usage import UsageTracker


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


# ---- Phase 2: per-device schema ----


def _stub_device_id(monkeypatch: pytest.MonkeyPatch, device: str) -> None:
    """Force usage._device_id() (re-exported from cloud_sync) to return `device`."""
    from soyle.core import usage as u
    monkeypatch.setattr(u, "_device_id", lambda: device)


def test_record_writes_only_to_own_device_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_device_id(monkeypatch, "dev-A")
    tracker = UsageTracker(tmp_path / "usage.json")
    tracker.record(0.01)

    raw = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    [date_key] = raw.keys()
    assert raw[date_key] == {"dev-A": {"cost_usd": 0.01, "requests": 1}}


def test_record_accumulates_within_own_bucket_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two calls on the same device sum into one bucket, not split per-call."""
    _stub_device_id(monkeypatch, "dev-A")
    tracker = UsageTracker(tmp_path / "usage.json")
    tracker.record(0.01)
    tracker.record(0.02)

    raw = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    [date_key] = raw.keys()
    bucket = raw[date_key]["dev-A"]
    assert bucket["cost_usd"] == pytest.approx(0.03)
    assert bucket["requests"] == 2


def test_record_does_not_touch_other_devices_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing 'dev-B' entry on disk survives when 'dev-A' records."""
    seed = {
        "2026-05-22": {"dev-B": {"cost_usd": 0.05, "requests": 3}},
    }
    (tmp_path / "usage.json").write_text(json.dumps(seed), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")
    from soyle.core import usage as u
    monkeypatch.setattr(u.UsageTracker, "_today_key", staticmethod(lambda: "2026-05-22"))

    tracker = UsageTracker(tmp_path / "usage.json")
    tracker.record(0.01)

    raw = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert raw["2026-05-22"]["dev-B"] == {"cost_usd": 0.05, "requests": 3}
    assert raw["2026-05-22"]["dev-A"] == {"cost_usd": 0.01, "requests": 1}


def test_load_migrates_v1_flat_schema_to_v2_per_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v1 file (flat {date: {cost, requests}}) is detected and rewritten to v2
    on first load, attributing all entries to current device."""
    v1_data = {
        "2026-05-20": {"cost_usd": 0.10, "requests": 5},
        "2026-05-21": {"cost_usd": 0.20, "requests": 8},
    }
    (tmp_path / "usage.json").write_text(json.dumps(v1_data), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    tracker = UsageTracker(tmp_path / "usage.json")
    serialized = tracker.serialize_for_sync()
    assert serialized == {
        "2026-05-20": {"dev-A": {"cost_usd": 0.10, "requests": 5}},
        "2026-05-21": {"dev-A": {"cost_usd": 0.20, "requests": 8}},
    }


def test_v2_schema_passes_through_load_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading a v2-format file does not corrupt or re-migrate it."""
    v2_data = {
        "2026-05-22": {
            "dev-A": {"cost_usd": 0.05, "requests": 2},
            "dev-B": {"cost_usd": 0.07, "requests": 4},
        },
    }
    (tmp_path / "usage.json").write_text(json.dumps(v2_data), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    tracker = UsageTracker(tmp_path / "usage.json")
    assert tracker.serialize_for_sync() == v2_data


# ---- Phase 2: cross-device sum tests ----------------------------------------


def test_today_sums_across_all_devices_for_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    today_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    seed = {
        today_key: {
            "dev-A": {"cost_usd": 0.05, "requests": 3},
            "dev-B": {"cost_usd": 0.07, "requests": 4},
        },
    }
    (tmp_path / "usage.json").write_text(json.dumps(seed), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    tracker = UsageTracker(tmp_path / "usage.json")
    cost, reqs = tracker.today()

    assert cost == pytest.approx(0.12)
    assert reqs == 7


def test_this_month_sums_across_all_devices_for_current_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = datetime.now(tz=UTC).strftime("%Y-%m-")
    seed = {
        f"{prefix}01": {"dev-A": {"cost_usd": 0.10, "requests": 5}},
        f"{prefix}15": {"dev-B": {"cost_usd": 0.20, "requests": 8}},
        # An entry from a previous month — must NOT count
        "2020-01-01": {"dev-A": {"cost_usd": 99.0, "requests": 999}},
    }
    (tmp_path / "usage.json").write_text(json.dumps(seed), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    tracker = UsageTracker(tmp_path / "usage.json")
    cost, reqs = tracker.this_month()

    assert cost == pytest.approx(0.30)
    assert reqs == 13


def test_summary_line_reflects_cross_device_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tray menu line shows totals summed across all devices, not just current."""
    today_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    seed = {
        today_key: {
            "dev-A": {"cost_usd": 0.01, "requests": 1},
            "dev-B": {"cost_usd": 0.02, "requests": 2},
        },
    }
    (tmp_path / "usage.json").write_text(json.dumps(seed), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    line = UsageTracker(tmp_path / "usage.json").summary_line()
    assert "$0.0300" in line
    assert "(3)" in line


def test_apply_merged_replaces_full_state_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_device_id(monkeypatch, "dev-A")
    tracker = UsageTracker(tmp_path / "usage.json")
    tracker.record(0.05)

    today_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    new_state = {
        today_key: {
            "dev-A": {"cost_usd": 0.05, "requests": 1},
            "dev-B": {"cost_usd": 0.10, "requests": 2},
        },
    }
    tracker.apply_merged(new_state)

    raw = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert raw == new_state
    cost, reqs = tracker.today()
    assert cost == pytest.approx(0.15)
    assert reqs == 3


def test_apply_merged_trims_entries_older_than_45_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_device_id(monkeypatch, "dev-A")
    tracker = UsageTracker(tmp_path / "usage.json")

    long_ago = (datetime.now(tz=UTC).date() - timedelta(days=60)).strftime("%Y-%m-%d")
    today_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    merged = {
        long_ago: {"dev-A": {"cost_usd": 99.0, "requests": 999}},
        today_key: {"dev-A": {"cost_usd": 0.05, "requests": 1}},
    }
    tracker.apply_merged(merged)

    raw = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert long_ago not in raw
    assert today_key in raw
