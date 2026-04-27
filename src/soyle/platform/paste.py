"""Paste-to-foreground-window primitives.

Two paths, chosen per-target:

1. ``send_wm_paste(hwnd)`` — sends ``WM_PASTE`` directly to a child Edit /
   RichEdit control under the given window. This is the classic Win32 way
   and works reliably with legacy controls like Notepad, notepad replacements,
   and plain dialogs where synthetic keyboard input is sometimes ignored.

2. ``send_ctrl_v()`` — synthesizes Ctrl+V via the ``keyboard`` package. Works
   for browsers, Electron apps (VS Code, Claude), Qt apps, modern Office,
   and anything that listens to raw keyboard events.

The Injector calls WM_PASTE first and falls back to Ctrl+V when no edit
child is found.
"""
from __future__ import annotations

import contextlib
import sys

if sys.platform == "win32":
    import keyboard
    import win32con
    import win32gui

# Edit-control class names to probe, in order of specificity.
EDIT_CLASSES = ("Edit", "RichEdit20W", "RichEdit20A", "RichEdit50W", "RichEdit")


def send_ctrl_v() -> None:
    """Press Ctrl+V synthetically. Errors are suppressed."""
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):
        keyboard.press_and_release("ctrl+v")


def find_edit_child(hwnd: int) -> int:
    """Return HWND of the first Edit/RichEdit child under ``hwnd``, or 0."""
    if sys.platform != "win32" or hwnd == 0:
        return 0
    for cls in EDIT_CLASSES:
        try:
            child = win32gui.FindWindowEx(hwnd, 0, cls, None)
        except Exception:
            child = 0
        if child:
            return int(child)
    return 0


def send_wm_paste(hwnd: int) -> bool:
    """Send ``WM_PASTE`` to a child edit control under ``hwnd``.

    Returns True if a suitable child was found and the message was posted.
    """
    if sys.platform != "win32":
        return False
    child = find_edit_child(hwnd)
    if child == 0:
        return False
    try:
        win32gui.SendMessage(child, win32con.WM_PASTE, 0, 0)
        return True
    except Exception:
        return False
