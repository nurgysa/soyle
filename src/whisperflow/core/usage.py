"""Lightweight daily usage tracker: accumulates LLM cost in a JSON file.

Stored at `%APPDATA%/WhisperFlow/usage.json` as a flat dict keyed by
ISO date (YYYY-MM-DD). Each entry carries the day's aggregate cost and
request count. Entries older than 45 days are trimmed on save so the
file stays bounded.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import structlog

log = structlog.get_logger()

_RETENTION_DAYS = 45


class UsageTracker:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, float]] = self._load()

    def record(self, cost_usd: float) -> None:
        """Add a single polished request to today's bucket."""
        today = self._today_key()
        entry = self._data.setdefault(today, {"cost_usd": 0.0, "requests": 0})
        entry["cost_usd"] = float(entry.get("cost_usd", 0.0)) + float(cost_usd)
        entry["requests"] = int(entry.get("requests", 0)) + 1
        self._trim_old()
        self._save()

    def today(self) -> tuple[float, int]:
        entry = self._data.get(self._today_key(), {"cost_usd": 0.0, "requests": 0})
        return float(entry["cost_usd"]), int(entry["requests"])

    def this_month(self) -> tuple[float, int]:
        prefix = datetime.now(tz=UTC).strftime("%Y-%m-")
        total_cost = 0.0
        total_req = 0
        for day, entry in self._data.items():
            if day.startswith(prefix):
                total_cost += float(entry.get("cost_usd", 0.0))
                total_req += int(entry.get("requests", 0))
        return total_cost, total_req

    def summary_line(self) -> str:
        """Human-readable single-line summary for the tray menu."""
        today_cost, today_n = self.today()
        month_cost, month_n = self.this_month()
        return (
            f"Сегодня: ${today_cost:.4f} ({today_n}) · "
            f"за месяц: ${month_cost:.4f} ({month_n})"
        )

    # --- internals ---

    @staticmethod
    def _today_key() -> str:
        return datetime.now(tz=UTC).strftime("%Y-%m-%d")

    def _trim_old(self) -> None:
        cutoff = (datetime.now(tz=UTC).date() - timedelta(days=_RETENTION_DAYS))
        stale = [
            day for day in self._data
            if self._parse_day(day) is not None and self._parse_day(day) < cutoff
        ]
        for day in stale:
            del self._data[day]

    @staticmethod
    def _parse_day(key: str) -> date | None:
        try:
            return datetime.strptime(key, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _load(self) -> dict[str, dict[str, float]]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("usage_load_failed", error=str(exc), path=str(self._path))
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("usage_save_failed", error=str(exc), path=str(self._path))
