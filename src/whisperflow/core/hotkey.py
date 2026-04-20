"""Global hotkey listener with debounce."""
from __future__ import annotations

import time
from threading import Lock
from typing import Any

import keyboard

from whisperflow.core.bus import Event, EventBus


class DebounceFilter:
    """Decides whether a press/release should be accepted based on timing."""

    def __init__(self, min_hold_ms: int = 150) -> None:
        self._min_hold_ms = min_hold_ms
        self._pressed_at_ms: int | None = None

    def accept_press(self, timestamp_ms: int | None = None) -> bool:
        ts = timestamp_ms if timestamp_ms is not None else int(time.monotonic() * 1000)
        if self._pressed_at_ms is not None:
            # Still holding; ignore repeat / echo
            return False
        self._pressed_at_ms = ts
        return True

    def accept_release(self, timestamp_ms: int | None = None) -> bool:
        ts = timestamp_ms if timestamp_ms is not None else int(time.monotonic() * 1000)
        if self._pressed_at_ms is None:
            return False
        hold_ms = ts - self._pressed_at_ms
        self._pressed_at_ms = None
        return hold_ms >= self._min_hold_ms


class HotkeyBox:
    """
    Listens globally for a hotkey; emits HOTKEY_PRESSED / HOTKEY_RELEASED via EventBus.

    Built on the `keyboard` package, which spawns its own listener thread.
    """

    def __init__(self, bus: EventBus, combination: str = "right alt", min_hold_ms: int = 150) -> None:
        self._bus = bus
        self._combination = combination
        self._filter = DebounceFilter(min_hold_ms=min_hold_ms)
        self._lock = Lock()
        self._registered: Any = None
        self._is_pressed = False

    def start(self) -> None:
        def on_event(event: keyboard.KeyboardEvent) -> None:
            with self._lock:
                if event.event_type == keyboard.KEY_DOWN:
                    if self._is_pressed:
                        return
                    if self._filter.accept_press():
                        self._is_pressed = True
                        self._bus.emit(Event.HOTKEY_PRESSED, {})
                elif event.event_type == keyboard.KEY_UP:
                    if not self._is_pressed:
                        return
                    if self._filter.accept_release():
                        self._is_pressed = False
                        self._bus.emit(Event.HOTKEY_RELEASED, {})
                    else:
                        # Too short; still reset so we don't desync
                        self._is_pressed = False

        self._registered = keyboard.hook_key(self._combination, on_event, suppress=False)

    def stop(self) -> None:
        if self._registered is not None:
            keyboard.unhook(self._registered)
            self._registered = None

    def rebind(self, new_combination: str) -> None:
        self.stop()
        self._combination = new_combination
        self.start()
