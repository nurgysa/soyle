"""Inject text into the foreground window via clipboard + Ctrl+V."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

import pyperclip
from PySide6.QtCore import QTimer

from whisperflow.core.bus import Event, EventBus
from whisperflow.platform.paste import send_ctrl_v
from whisperflow.platform.window import get_foreground_hwnd, is_same_window

_log = logging.getLogger(__name__)


@dataclass
class InjectResult:
    success: bool
    method: Literal["paste", "keystroke"]
    target_changed: bool


class Injector:
    """Paste text into the captured HWND; restore clipboard after a short delay."""

    def __init__(self, bus: EventBus, restore_delay_ms: int = 200) -> None:
        self._bus = bus
        self._restore_delay_ms = restore_delay_ms

    def capture_target(self) -> int:
        hwnd = get_foreground_hwnd()
        _log.info("capture_target hwnd=%s", hwnd)
        return hwnd

    def inject(self, text: str, target_hwnd: int) -> InjectResult:
        self._bus.emit(Event.INJECTING, {"target_hwnd": target_hwnd})
        current = get_foreground_hwnd()
        _log.info(
            "inject text_len=%d target=%s current=%s same=%s",
            len(text),
            target_hwnd,
            current,
            is_same_window(target_hwnd, current),
        )

        if not is_same_window(target_hwnd, current):
            # Keep text in clipboard for manual paste; do NOT hit Ctrl+V.
            pyperclip.copy(text)
            _log.warning("inject skipped: target window changed; text copied to clipboard")
            self._bus.emit(Event.INJECTED, {"success": False, "target_changed": True})
            return InjectResult(success=False, method="paste", target_changed=True)

        backup = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.02)  # give clipboard manager a moment
        send_ctrl_v()
        _log.info("inject send_ctrl_v fired; restore in %dms", self._restore_delay_ms)

        QTimer.singleShot(self._restore_delay_ms, lambda: pyperclip.copy(backup))

        self._bus.emit(Event.INJECTED, {"success": True, "target_changed": False})
        return InjectResult(success=True, method="paste", target_changed=False)
