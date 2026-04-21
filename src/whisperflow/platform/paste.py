"""Send Ctrl+V to the foreground window.

Uses win32api.keybd_event (from pywin32) which is simple and reliable on
Windows. The earlier ctypes+SendInput implementation silently failed on
some targets because the Python INPUT union did not include MOUSEINPUT /
HARDWAREINPUT members, so ctypes.sizeof(INPUT) was smaller than what
SendInput expects, and Windows rejected the call silently.
"""
from __future__ import annotations

import contextlib
import sys

if sys.platform == "win32":
    import win32api

VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002


def send_ctrl_v() -> None:
    """Send Ctrl+V as 4 synthetic key events. Errors are suppressed."""
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        win32api.keybd_event(VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(VK_V, 0, 0, 0)
        win32api.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
