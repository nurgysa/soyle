"""Tests for the monthly-spend-limit warning logic in WhisperFlowApp.

We don't boot the full Qt app here — just exercise the pure policy by
faking the pieces `_check_monthly_limit` touches (config, usage tracker,
tray toast).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from whisperflow.core.usage import UsageTracker


@dataclass
class _FakeBehavior:
    monthly_cost_limit_usd: float


@dataclass
class _FakeCfg:
    behavior: _FakeBehavior


class _FakeTray:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def toast(self, title: str, message: str, level: str = "info") -> None:
        self.calls.append((title, message, level))


def _make_checker(cfg: _FakeCfg, usage: UsageTracker, tray: _FakeTray) -> Any:
    """Build a minimal callable mirroring WhisperFlowApp._check_monthly_limit.

    Done this way so the policy is exercised as a pure function rather than
    requiring Qt boot. If the real method ever grows, mirror it here too.
    """

    def _check(new_cost: float) -> None:
        limit = cfg.behavior.monthly_cost_limit_usd
        if limit <= 0:
            return
        current, _ = usage.this_month()
        previous = current - new_cost
        if previous < limit <= current:
            tray.toast(
                "WhisperFlow",
                f"Месячный лимит превышен: ${current:.4f} из ${limit:.2f}",
                level="warning",
            )

    return _check


def test_no_warning_when_limit_disabled(tmp_path: Path) -> None:
    usage = UsageTracker(tmp_path / "usage.json")
    tray = _FakeTray()
    check = _make_checker(_FakeCfg(_FakeBehavior(0.0)), usage, tray)

    usage.record(5.0)
    check(5.0)

    assert tray.calls == []  # disabled → silent


def test_no_warning_while_under_limit(tmp_path: Path) -> None:
    usage = UsageTracker(tmp_path / "usage.json")
    tray = _FakeTray()
    check = _make_checker(_FakeCfg(_FakeBehavior(10.0)), usage, tray)

    usage.record(3.0)
    check(3.0)

    assert tray.calls == []


def test_toast_on_first_crossing(tmp_path: Path) -> None:
    usage = UsageTracker(tmp_path / "usage.json")
    tray = _FakeTray()
    check = _make_checker(_FakeCfg(_FakeBehavior(1.0)), usage, tray)

    usage.record(0.80)
    check(0.80)   # still under → silent
    usage.record(0.30)
    check(0.30)   # 0.80 → 1.10: crosses 1.0 → warn once

    assert len(tray.calls) == 1
    _, message, level = tray.calls[0]
    assert level == "warning"
    assert "$1." in message and "$1.00" in message


def test_silent_after_already_over(tmp_path: Path) -> None:
    """Second crossing-checker invocation after we're already over: no repeat."""
    usage = UsageTracker(tmp_path / "usage.json")
    tray = _FakeTray()
    check = _make_checker(_FakeCfg(_FakeBehavior(1.0)), usage, tray)

    usage.record(1.20)
    check(1.20)    # crosses 1.0 → toast
    usage.record(0.50)
    check(0.50)    # already over; no new toast

    assert len(tray.calls) == 1
