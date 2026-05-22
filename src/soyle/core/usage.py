"""Lightweight daily usage tracker — per-device buckets (v2).

Stored at `%APPDATA%/Soyle/usage.json` as nested dict:
    {date: {device_id: {"cost_usd": float, "requests": int}}}

v1 files (flat `{date: {cost_usd, requests}}`) are auto-migrated on first
load by attributing existing entries to the current device's UUID. The
migration is self-describing — v1's value type is the inner dict directly,
v2's value type wraps inner dicts under device-id keys.

Per-device schema is required so cross-device sync via Drive can merge
without double-counting: each device only writes to its own bucket, so
LWW per `(date, device_id)` tuple has zero conflict opportunity.

Entries older than 45 days are trimmed on save so the file stays bounded.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import structlog

# Re-exported so tests can monkeypatch `usage._device_id` without reaching
# into cloud_sync. The runtime function lives in cloud_sync.py to keep
# the keyring-touching code in one place.
from soyle.core.cloud_sync import _device_id

log = structlog.get_logger()

_RETENTION_DAYS = 45

# Inner-bucket type: {"cost_usd": float, "requests": int}
_Bucket = dict[str, float]
# Per-device map for a single date
_DateEntry = dict[str, _Bucket]
# Whole-file v2 state
_V2State = dict[str, _DateEntry]


class UsageTracker:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: _V2State = self._load()

    def record(self, cost_usd: float) -> None:
        """Add a single polished request to today's bucket for THIS device."""
        today = self._today_key()
        device = _device_id()
        date_entry = self._data.setdefault(today, {})
        bucket = date_entry.setdefault(device, {"cost_usd": 0.0, "requests": 0})
        bucket["cost_usd"] = float(bucket.get("cost_usd", 0.0)) + float(cost_usd)
        bucket["requests"] = int(bucket.get("requests", 0)) + 1
        self._trim_old()
        self._save()

    def today(self) -> tuple[float, int]:
        """Sum across ALL devices for today — gives cross-device total."""
        return self._sum_for_dates({self._today_key()})

    def this_month(self) -> tuple[float, int]:
        """Sum across ALL devices for the current calendar month (UTC)."""
        prefix = datetime.now(tz=UTC).strftime("%Y-%m-")
        matching = {d for d in self._data if d.startswith(prefix)}
        return self._sum_for_dates(matching)

    def summary_line(self) -> str:
        """Human-readable single-line summary for the tray menu."""
        today_cost, today_n = self.today()
        month_cost, month_n = self.this_month()
        return (
            f"Сегодня: ${today_cost:.4f} ({today_n}) · "
            f"за месяц: ${month_cost:.4f} ({month_n})"
        )

    # -- Phase 2: cross-device sync API ---------------------------------------

    def serialize_for_sync(self) -> _V2State:
        """Return a deep-copy snapshot of the full v2 state for CloudSync.

        Returns the nested dict in the same shape that's persisted on disk.
        Cloud sync uses this to compute the merge against remote state.
        """
        return _deep_copy_state(self._data)

    def apply_merged(self, merged: _V2State) -> None:
        """Replace local state with a merged version from CloudSync.

        Called after `_merge_usage(local, remote)` produces the union of
        per-device buckets. Caller guarantees the format is v2.
        """
        self._data = _deep_copy_state(merged)
        self._trim_old()
        self._save()

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _today_key() -> str:
        return datetime.now(tz=UTC).strftime("%Y-%m-%d")

    def _sum_for_dates(self, dates: set[str]) -> tuple[float, int]:
        total_cost = 0.0
        total_req = 0
        for d in dates:
            date_entry = self._data.get(d, {})
            for bucket in date_entry.values():
                total_cost += float(bucket.get("cost_usd", 0.0))
                total_req += int(bucket.get("requests", 0))
        return total_cost, total_req

    def _trim_old(self) -> None:
        cutoff = datetime.now(tz=UTC).date() - timedelta(days=_RETENTION_DAYS)
        stale = [
            day for day in self._data
            if (parsed := self._parse_day(day)) is not None and parsed < cutoff
        ]
        for day in stale:
            del self._data[day]

    @staticmethod
    def _parse_day(key: str) -> date | None:
        try:
            return datetime.strptime(key, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _load(self) -> _V2State:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("usage_load_failed", error=str(exc), path=str(self._path))
            return {}
        if not isinstance(raw, dict):
            return {}
        if _looks_like_v1(raw):
            log.info("usage_migrating_v1_to_v2", path=str(self._path))
            migrated = _migrate_v1_to_v2(raw)
            self._data = migrated
            self._save()
            return migrated
        return raw

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("usage_save_failed", error=str(exc), path=str(self._path))


# ---- v1 → v2 migration -------------------------------------------------------

def _looks_like_v1(raw: dict) -> bool:  # type: ignore[type-arg]
    """v1 value is {"cost_usd": float, "requests": int};
    v2 value is {device_id: {"cost_usd": ..., "requests": ...}}.

    Detect v1 by checking whether the FIRST value at top level has cost_usd
    directly (v1) or wraps device-id keys whose values have cost_usd (v2).
    Empty dict is neither — treat as v2 (no migration needed).
    """
    if not raw:
        return False
    first_value = next(iter(raw.values()))
    if not isinstance(first_value, dict):
        return False
    return "cost_usd" in first_value


def _migrate_v1_to_v2(raw: dict) -> _V2State:  # type: ignore[type-arg]
    """Attribute every existing v1 entry to the current device's UUID."""
    device = _device_id()
    return {
        date_str: {device: dict(entry)}
        for date_str, entry in raw.items()
        if isinstance(entry, dict)
    }


def _deep_copy_state(state: _V2State) -> _V2State:
    """Independent copy preserving nested-dict independence (no shared mutable refs)."""
    return {
        date_str: {device: dict(bucket) for device, bucket in date_entry.items()}
        for date_str, date_entry in state.items()
    }
