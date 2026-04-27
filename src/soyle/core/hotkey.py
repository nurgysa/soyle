"""Global hotkey listener with debounce."""
from __future__ import annotations

import time
from threading import Lock
from typing import Any

import keyboard

from soyle.core.bus import Event, EventBus

# All modifier families the `keyboard` library's is_pressed() recognises.
_MODIFIER_FAMILIES = ("ctrl", "alt", "shift", "windows")


def _ptt_modifier_family(ptt: str) -> str | None:
    """Return the modifier family name the PTT belongs to, or None.

    Examples: "right alt" → "alt", "left ctrl" → "ctrl", "f8" → None.
    Used so the interference check doesn't flag the PTT's own modifier.
    """
    low = ptt.lower()
    for fam in _MODIFIER_FAMILIES:
        if fam in low:
            return fam
    return None


def is_interfering_modifier_held(ptt: str) -> bool:
    """True if a modifier OTHER than the PTT's own family is currently held.

    Purpose: suppress accidental PTT activations when the user is in the
    middle of a keyboard-layout switch or another system shortcut
    (Alt+Shift, Ctrl+Shift, Ctrl+Alt, Win+Space, etc.). The PTT's own
    family is excluded — otherwise PTT="right ctrl" would block itself.
    """
    own = _ptt_modifier_family(ptt)
    for fam in _MODIFIER_FAMILIES:
        if fam == own:
            continue
        try:
            if keyboard.is_pressed(fam):
                return True
        except Exception:
            # keyboard.is_pressed can throw on some exotic platforms; we
            # fail open rather than soft-locking the hotkey out.
            pass
    return False


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
                    # Guard against accidental triggers during OS keyboard
                    # shortcuts like Alt+Shift / Ctrl+Shift (layout switch),
                    # Ctrl+Alt (various combos), Win+Space, etc. Release
                    # handler already early-returns when _is_pressed is
                    # False, so a matching KEY_UP later won't fire either.
                    if is_interfering_modifier_held(self._combination):
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
