"""Inject text into the foreground window.

Two methods, selected via ``BehaviorConfig.inject_method``:

- ``clipboard`` (default) — put text in the clipboard, synthesise Ctrl+V
  (or WM_PASTE for legacy Win32 edit children), restore the prior
  clipboard content after a short delay. Works everywhere but briefly
  exposes the polished text to any running clipboard manager.
- ``keystroke`` — synthesise Unicode keystrokes directly via the
  ``keyboard`` library. Slower on long strings, may misbehave if the
  user touches the keyboard mid-injection, but never touches the
  clipboard.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal

import keyboard
import pyperclip
import structlog
from PySide6.QtCore import QTimer

from whisperflow.core.bus import Event, EventBus
from whisperflow.platform.paste import find_edit_child, send_ctrl_v, send_wm_paste
from whisperflow.platform.window import (
    get_foreground_hwnd,
    get_window_class_name,
    is_same_window,
)

_log = structlog.get_logger(__name__)

# Strip non-printable control characters that could exploit a terminal or
# renderer. Preserves \t (0x09), \n (0x0a), \r (0x0d). An LLM can otherwise
# emit ESC-sequences, DEL (0x7f), or bell (0x07) which downstream apps
# interpret unexpectedly.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Win32 class names of foreground windows where auto-pasting is dangerous
# (a newline in the polished text would execute a command). For these we
# keep the text in the clipboard but do NOT hit Ctrl+V — user pastes
# manually if they want.
_TERMINAL_CLASSES = frozenset({
    "ConsoleWindowClass",              # cmd.exe, legacy PowerShell
    "CASCADIA_HOSTING_WINDOW_CLASS",   # Windows Terminal
    "mintty",                          # Git Bash, Cygwin
    "PuTTY",
    "ConEmu",
    "WezTermWindow",
})


def _sanitize_for_injection(text: str) -> str:
    """Remove non-printable control characters from text before injection.

    Kept as module-level so the tests can exercise it without constructing
    an Injector + window fixtures.
    """
    return _CONTROL_CHARS.sub("", text)


@dataclass
class InjectResult:
    success: bool
    method: Literal["paste", "keystroke"]
    target_changed: bool
    blocked: bool = False  # True if target was on the terminal blocklist


InjectMethod = Literal["clipboard", "keystroke"]


class Injector:
    """Inject text into the captured HWND.

    Default is ``clipboard`` — save the existing clipboard, copy text,
    trigger paste, restore the clipboard after ``restore_delay_ms``. The
    ``keystroke`` mode skips the clipboard entirely by synthesising
    Unicode keystrokes via the ``keyboard`` library.
    """

    def __init__(
        self,
        bus: EventBus,
        restore_delay_ms: int = 500,
        method: InjectMethod = "clipboard",
    ) -> None:
        self._bus = bus
        self._restore_delay_ms = restore_delay_ms
        self._method: InjectMethod = method

    def set_method(self, method: str) -> None:
        """Switch the injection strategy at runtime. Invalid values raise."""
        if method not in ("clipboard", "keystroke"):
            raise ValueError(f"unknown inject method: {method!r}")
        self._method = method  # type: ignore[assignment]

    def capture_target(self) -> int:
        hwnd = get_foreground_hwnd()
        _log.info("capture_target", hwnd=hwnd)
        return hwnd

    def inject(self, text: str, target_hwnd: int) -> InjectResult:
        # Strip non-printable control characters before anything touches
        # the clipboard — a malicious or glitchy LLM reply could otherwise
        # carry ANSI escapes, NUL, DEL, etc.
        text = _sanitize_for_injection(text)

        self._bus.emit(Event.INJECTING, {"target_hwnd": target_hwnd})
        current = get_foreground_hwnd()
        target_class = get_window_class_name(current)
        _log.info(
            "inject_attempt",
            text_len=len(text),
            target=target_hwnd,
            current=current,
            target_class=target_class,
            same_window=is_same_window(target_hwnd, current),
        )

        if not is_same_window(target_hwnd, current):
            # Keep text in clipboard for manual paste; do NOT hit Ctrl+V.
            pyperclip.copy(text)
            _log.warning("inject_skipped_target_changed", text_len=len(text))
            self._bus.emit(Event.INJECTED, {"success": False, "target_changed": True})
            return InjectResult(success=False, method="paste", target_changed=True)

        # Terminal blocklist: dropping polished LLM text (which may contain
        # newlines) straight into a shell would auto-execute commands. Keep
        # the text in the clipboard for a manual Ctrl+V instead. Applies
        # regardless of inject method — a stray \n via keystroke would
        # execute just the same.
        if target_class in _TERMINAL_CLASSES:
            pyperclip.copy(text)
            _log.warning(
                "inject_blocked_terminal",
                target_class=target_class,
                text_len=len(text),
            )
            self._bus.emit(
                Event.INJECTED,
                {"success": False, "target_changed": False, "blocked": True},
            )
            return InjectResult(
                success=False, method="paste", target_changed=False, blocked=True
            )

        # Opt-in: type each character directly, never touching the clipboard.
        # Trade-off — slower on long strings and sensitive to user's own
        # keystrokes landing in the middle.
        if self._method == "keystroke":
            try:
                keyboard.write(text, delay=0)
            except Exception as exc:
                _log.warning("keystroke_inject_failed", error=str(exc))
                self._bus.emit(
                    Event.INJECTED, {"success": False, "target_changed": False}
                )
                return InjectResult(
                    success=False, method="keystroke", target_changed=False
                )
            _log.info("inject_keystroke", text_len=len(text))
            self._bus.emit(
                Event.INJECTED, {"success": True, "target_changed": False}
            )
            return InjectResult(
                success=True, method="keystroke", target_changed=False
            )

        backup = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.02)  # give clipboard manager a moment

        # Prefer WM_PASTE to a child Edit/RichEdit (reliable on Notepad and
        # other classic Win32 apps). Fall back to synthetic Ctrl+V for
        # modern apps (browsers, Electron, Qt) that have no such child.
        edit_hwnd = find_edit_child(target_hwnd)
        if edit_hwnd and send_wm_paste(target_hwnd):
            _log.info(
                "inject_wm_paste",
                edit_hwnd=edit_hwnd,
                restore_delay_ms=self._restore_delay_ms,
            )
        else:
            send_ctrl_v()
            _log.info("inject_send_ctrl_v", restore_delay_ms=self._restore_delay_ms)

        QTimer.singleShot(self._restore_delay_ms, lambda: pyperclip.copy(backup))

        self._bus.emit(Event.INJECTED, {"success": True, "target_changed": False})
        return InjectResult(success=True, method="paste", target_changed=False)
