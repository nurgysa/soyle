"""Foreground-window tracking helpers."""
from __future__ import annotations

import sys

if sys.platform == "win32":
    import win32gui


def get_foreground_hwnd() -> int:
    """Return the HWND of the currently focused window, 0 if no foreground."""
    if sys.platform != "win32":
        return 0
    return int(win32gui.GetForegroundWindow())


def is_same_window(expected: int, current: int) -> bool:
    """True iff both HWNDs are non-zero and equal."""
    if expected == 0 or current == 0:
        return False
    return expected == current


def refocus(hwnd: int) -> bool:
    """Attempt to bring the given HWND back to the foreground. Returns True on success."""
    if sys.platform != "win32" or hwnd == 0:
        return False
    try:
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
