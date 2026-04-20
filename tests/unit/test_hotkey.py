"""Tests for hotkey debounce logic."""
from __future__ import annotations

from whisperflow.core.hotkey import DebounceFilter


def test_debounce_first_press_allowed() -> None:
    f = DebounceFilter(min_hold_ms=150)
    assert f.accept_press(timestamp_ms=100) is True


def test_debounce_quick_release_rejected() -> None:
    f = DebounceFilter(min_hold_ms=150)
    f.accept_press(timestamp_ms=100)
    # Release at t=200, but press was at 100 → held 100ms < 150ms → reject
    assert f.accept_release(timestamp_ms=200) is False


def test_debounce_long_hold_accepted() -> None:
    f = DebounceFilter(min_hold_ms=150)
    f.accept_press(timestamp_ms=100)
    assert f.accept_release(timestamp_ms=400) is True  # 300ms hold


def test_debounce_second_press_without_release_ignored() -> None:
    f = DebounceFilter(min_hold_ms=150)
    f.accept_press(timestamp_ms=100)
    # Before release, another press fires → ignored
    assert f.accept_press(timestamp_ms=120) is False


def test_debounce_cycle_works() -> None:
    f = DebounceFilter(min_hold_ms=150)
    f.accept_press(100)
    f.accept_release(400)
    # Next press after release — should work
    assert f.accept_press(timestamp_ms=500) is True
