"""Send Ctrl+V to the foreground window via the `keyboard` package.

We previously tried ctypes+SendInput (wrong INPUT union size) and
win32api.keybd_event (still no paste in real Notepad). The `keyboard`
package wraps the Win32 Raw Input interface and handles the timing,
layout, and scan-code quirks that defeat the lower-level approaches.
"""
from __future__ import annotations

import contextlib
import sys

if sys.platform == "win32":
    import keyboard


def send_ctrl_v() -> None:
    """Press Ctrl+V synthetically. Errors are suppressed."""
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        keyboard.press_and_release("ctrl+v")
