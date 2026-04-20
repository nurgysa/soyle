"""Send Ctrl+V via Win32 SendInput."""
from __future__ import annotations

import contextlib
import ctypes
import sys
from ctypes import wintypes

# ---- Win32 structures for SendInput ----

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):  # noqa: N801  (Win32 naming convention)
    _fields_ = [("ki", KEYBDINPUT)]  # noqa: RUF012  (ctypes requires class-level _fields_)


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


if sys.platform == "win32":
    SendInput = ctypes.windll.user32.SendInput
    SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    SendInput.restype = wintypes.UINT
else:
    def SendInput(*args: object, **kwargs: object) -> int:  # noqa: N802  # pragma: no cover
        return 0


def _make_input(vk: int, up: bool) -> INPUT:
    ki = KEYBDINPUT(
        wVk=vk,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if up else 0,
        time=0,
        dwExtraInfo=ctypes.pointer(ctypes.c_ulong(0)),
    )
    return INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=ki))


def send_ctrl_v() -> None:
    """Send Ctrl+V as 4 synthetic key events. Errors are suppressed."""
    with contextlib.suppress(OSError):
        inputs = (INPUT * 4)(
            _make_input(VK_CONTROL, up=False),
            _make_input(VK_V, up=False),
            _make_input(VK_V, up=True),
            _make_input(VK_CONTROL, up=True),
        )
        SendInput(4, inputs, ctypes.sizeof(INPUT))
