"""Event bus built on Qt signals for thread-safe in-process messaging."""
from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QObject, Signal


class Event(StrEnum):
    HOTKEY_PRESSED = "hotkey.pressed"
    HOTKEY_RELEASED = "hotkey.released"
    RECORDING_STARTED = "recording.started"
    AUDIO_LEVEL = "audio.level"
    RECORDING_STOPPED = "recording.stopped"
    TRANSCRIBING = "transcribing"
    TRANSCRIPT_READY = "transcript.ready"
    POLISHING = "polishing"
    POLISH_READY = "polish.ready"
    INJECTING = "injecting"
    INJECTED = "injected"
    ERROR = "error"
    STATE_CHANGED = "state.changed"


Handler = Callable[[dict[str, Any]], None]


class EventBus(QObject):
    """
    Pub/sub over Qt's signal-slot machinery.

    Signals are thread-safe: emissions from background threads are marshalled
    to the receiver's thread automatically by Qt.
    """

    _signal = Signal(str, dict)

    def __init__(self) -> None:
        super().__init__()
        self._subscribers: dict[Event, list[Handler]] = {}
        self._signal.connect(self._dispatch)

    def subscribe(self, event: Event, handler: Handler) -> None:
        self._subscribers.setdefault(event, []).append(handler)

    def unsubscribe(self, event: Event, handler: Handler) -> None:
        handlers = self._subscribers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event: Event, payload: dict[str, Any]) -> None:
        self._signal.emit(str(event), payload)

    def _dispatch(self, event_str: str, payload: dict[str, Any]) -> None:
        event = Event(event_str)
        for handler in list(self._subscribers.get(event, [])):
            handler(payload)
