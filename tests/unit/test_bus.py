"""Tests for EventBus (Qt signal-based)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject

from whisperflow.core.bus import Event, EventBus


def test_event_values_are_strings() -> None:
    assert Event.HOTKEY_PRESSED == "hotkey.pressed"
    assert Event.RECORDING_STARTED == "recording.started"
    assert Event.ERROR == "error"


def test_subscribe_and_emit(qtbot) -> None:  # noqa: ARG001
    bus = EventBus()
    received: list[dict] = []

    bus.subscribe(Event.HOTKEY_PRESSED, lambda payload: received.append(payload))
    bus.emit(Event.HOTKEY_PRESSED, {"source": "test"})

    assert received == [{"source": "test"}]


def test_unsubscribe(qtbot) -> None:  # noqa: ARG001
    bus = EventBus()
    received: list[dict] = []

    handler = lambda p: received.append(p)  # noqa: E731
    bus.subscribe(Event.HOTKEY_PRESSED, handler)
    bus.unsubscribe(Event.HOTKEY_PRESSED, handler)
    bus.emit(Event.HOTKEY_PRESSED, {})

    assert received == []


def test_multiple_subscribers_all_called(qtbot) -> None:  # noqa: ARG001
    bus = EventBus()
    calls: list[str] = []

    bus.subscribe(Event.TRANSCRIBING, lambda _: calls.append("a"))
    bus.subscribe(Event.TRANSCRIBING, lambda _: calls.append("b"))
    bus.emit(Event.TRANSCRIBING, {})

    assert set(calls) == {"a", "b"}


def test_unrelated_events_not_delivered(qtbot) -> None:  # noqa: ARG001
    bus = EventBus()
    received: list[str] = []

    bus.subscribe(Event.HOTKEY_PRESSED, lambda _: received.append("hotkey"))
    bus.emit(Event.ERROR, {"message": "boom"})

    assert received == []


def test_bus_is_qobject() -> None:
    bus = EventBus()
    assert isinstance(bus, QObject)
