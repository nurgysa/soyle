"""Tests for hotkey debounce logic and modifier-interference guard."""
from __future__ import annotations

from whisperflow.core.hotkey import (
    DebounceFilter,
    _ptt_modifier_family,
    is_interfering_modifier_held,
)


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


# ---- _ptt_modifier_family ----


def test_ptt_family_right_alt() -> None:
    assert _ptt_modifier_family("right alt") == "alt"


def test_ptt_family_left_ctrl() -> None:
    assert _ptt_modifier_family("left ctrl") == "ctrl"


def test_ptt_family_shift() -> None:
    assert _ptt_modifier_family("right shift") == "shift"


def test_ptt_family_windows() -> None:
    assert _ptt_modifier_family("right windows") == "windows"


def test_ptt_family_function_key_is_none() -> None:
    assert _ptt_modifier_family("f8") is None


def test_ptt_family_caps_lock_is_none() -> None:
    assert _ptt_modifier_family("caps lock") is None


# ---- is_interfering_modifier_held ----


def test_interference_skip_own_family(mocker) -> None:
    """PTT='right alt' — pressing alt alone shouldn't flag alt as interference."""
    # Simulate: only Alt is held (the PTT itself), nothing else.
    def fake_is_pressed(fam: str) -> bool:
        return fam == "alt"

    mocker.patch("whisperflow.core.hotkey.keyboard.is_pressed", side_effect=fake_is_pressed)
    assert is_interfering_modifier_held("right alt") is False


def test_interference_ctrl_while_alt_is_ptt(mocker) -> None:
    """Ctrl+Alt layout switch: PTT='right alt' and ctrl held → interference."""
    def fake_is_pressed(fam: str) -> bool:
        return fam == "ctrl"

    mocker.patch("whisperflow.core.hotkey.keyboard.is_pressed", side_effect=fake_is_pressed)
    assert is_interfering_modifier_held("right alt") is True


def test_interference_shift_while_alt_is_ptt(mocker) -> None:
    """Alt+Shift layout switch: PTT='right alt' and shift held → interference."""
    def fake_is_pressed(fam: str) -> bool:
        return fam == "shift"

    mocker.patch("whisperflow.core.hotkey.keyboard.is_pressed", side_effect=fake_is_pressed)
    assert is_interfering_modifier_held("right alt") is True


def test_interference_alt_while_ctrl_is_ptt(mocker) -> None:
    """PTT='right ctrl'; alt is not ptt-family → interference."""
    def fake_is_pressed(fam: str) -> bool:
        return fam == "alt"

    mocker.patch("whisperflow.core.hotkey.keyboard.is_pressed", side_effect=fake_is_pressed)
    assert is_interfering_modifier_held("right ctrl") is True


def test_interference_f8_with_shift(mocker) -> None:
    """PTT='f8' (no family) with shift held → interference, because
    Shift+F8 is a common chord the user probably didn't mean as PTT."""
    def fake_is_pressed(fam: str) -> bool:
        return fam == "shift"

    mocker.patch("whisperflow.core.hotkey.keyboard.is_pressed", side_effect=fake_is_pressed)
    assert is_interfering_modifier_held("f8") is True


def test_interference_fail_open_on_exception(mocker) -> None:
    """keyboard.is_pressed can throw on exotic setups — don't soft-lock the hotkey."""
    mocker.patch(
        "whisperflow.core.hotkey.keyboard.is_pressed",
        side_effect=RuntimeError("backend glitch"),
    )
    assert is_interfering_modifier_held("right alt") is False


def test_interference_all_clear(mocker) -> None:
    mocker.patch(
        "whisperflow.core.hotkey.keyboard.is_pressed",
        return_value=False,
    )
    assert is_interfering_modifier_held("right alt") is False
