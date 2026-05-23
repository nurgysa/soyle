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


def get_window_class_name(hwnd: int) -> str:
    """Return the Win32 class name of ``hwnd`` (e.g. 'ConsoleWindowClass').

    Returns an empty string on any failure or non-Windows platforms. The class
    name is used to apply per-app injection policies — see the terminal
    blocklist in core/injector.py.
    """
    if sys.platform != "win32" or hwnd == 0:
        return ""
    try:
        return str(win32gui.GetClassName(hwnd))
    except Exception:
        return ""
