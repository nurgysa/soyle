"""Tests for foreground window HWND tracking."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from whisperflow.platform.window import get_foreground_hwnd, is_same_window


def test_get_foreground_hwnd_returns_int() -> None:
    hwnd = get_foreground_hwnd()
    assert isinstance(hwnd, int)
    assert hwnd > 0


def test_is_same_window_identity() -> None:
    hwnd = get_foreground_hwnd()
    assert is_same_window(hwnd, hwnd) is True


def test_is_same_window_zero_never_matches() -> None:
    hwnd = get_foreground_hwnd()
    assert is_same_window(0, hwnd) is False
    assert is_same_window(hwnd, 0) is False
