"""Tests for FloatingButton — mouse-triggered PTT widget."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication

from soyle.core.bus import Event, EventBus
from soyle.ui.floating_button import FloatingButton


def _collected_events(bus: EventBus) -> list[tuple[Event, dict]]:
    """Subscribe to both HOTKEY events; return a mutable list of received tuples."""
    seen: list[tuple[Event, dict]] = []
    bus.subscribe(Event.HOTKEY_PRESSED, lambda payload: seen.append((Event.HOTKEY_PRESSED, payload)))
    bus.subscribe(Event.HOTKEY_RELEASED, lambda payload: seen.append((Event.HOTKEY_RELEASED, payload)))
    return seen


def test_press_inside_circle_emits_hotkey_pressed(qtbot) -> None:
    """Click on the painted-circle center → HOTKEY_PRESSED on the bus."""
    bus = EventBus()
    seen = _collected_events(bus)
    btn = FloatingButton(bus=bus)
    qtbot.addWidget(btn)
    btn.show()

    center = btn.rect().center()
    qtbot.mousePress(btn, Qt.MouseButton.LeftButton, pos=center)
    qtbot.wait(20)  # let queued Qt signals dispatch

    pressed = [evt for evt, _ in seen if evt == Event.HOTKEY_PRESSED]
    assert len(pressed) == 1, f"expected exactly 1 HOTKEY_PRESSED, got {seen}"


def test_release_emits_hotkey_released(qtbot) -> None:
    """Press then release → both HOTKEY_PRESSED and HOTKEY_RELEASED in order."""
    bus = EventBus()
    seen = _collected_events(bus)
    btn = FloatingButton(bus=bus)
    qtbot.addWidget(btn)
    btn.show()

    center = btn.rect().center()
    qtbot.mousePress(btn, Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseRelease(btn, Qt.MouseButton.LeftButton, pos=center)
    qtbot.wait(20)

    event_names = [evt for evt, _ in seen]
    assert event_names == [Event.HOTKEY_PRESSED, Event.HOTKEY_RELEASED]


def test_press_in_corner_outside_circle_is_ignored(qtbot) -> None:
    """Click at widget corner (outside the painted circle) is a no-op.

    The painted circle is centered with radius ≈ width/2 - 2. A click at
    QPoint(3, 3) is in the transparent corner; it shouldn't trigger PTT.
    Without this guard, near-misses on the visible button would silently
    start recording — bad UX. (Note: QPoint(0,0) is a QTest sentinel
    meaning "use widget center" — we use (3,3) to disambiguate.)
    """
    bus = EventBus()
    seen = _collected_events(bus)
    btn = FloatingButton(bus=bus)
    qtbot.addWidget(btn)
    btn.show()

    qtbot.mousePress(btn, Qt.MouseButton.LeftButton, pos=QPoint(3, 3))
    qtbot.wait(20)

    assert seen == [], f"expected no events for corner click, got {seen}"


def test_set_recording_changes_visual_state(qtbot) -> None:
    """set_recording(True/False) toggles the internal flag the painter reads.

    We avoid pixel-level assertions (pixmap rendering on Windows test runners
    is finicky with translucent-background widgets — the alpha channel can
    swallow color samples). The behavioral contract is: paintEvent reads
    `_recording`, so flipping the flag is what shapes downstream visual state.
    """
    bus = EventBus()
    btn = FloatingButton(bus=bus)
    qtbot.addWidget(btn)
    btn.show()

    btn.set_recording(True)
    assert btn._recording is True

    btn.set_recording(False)
    assert btn._recording is False


def test_window_flags_include_stays_on_top_and_frameless(qtbot) -> None:
    """The pill must stay above all other windows and have no chrome."""
    bus = EventBus()
    btn = FloatingButton(bus=bus)
    qtbot.addWidget(btn)

    flags = btn.windowFlags()
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.FramelessWindowHint
    # NOT WindowTransparentForInput — clicks must reach this widget,
    # unlike the visual-only Indicator which sets that flag.
    assert not (flags & Qt.WindowType.WindowTransparentForInput)


def test_position_in_corner_pins_to_primary_bottom_right(qtbot) -> None:
    """After _position_in_corner(), bottom-right is within margin of screen edge."""
    bus = EventBus()
    btn = FloatingButton(bus=bus)
    qtbot.addWidget(btn)
    btn.show()

    btn._position_in_corner()
    qtbot.wait(20)

    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    geom = btn.geometry()

    # FloatingButton's MARGIN constant is 24 px; assert the gap matches.
    expected_x = avail.right() - btn.width() - FloatingButton.MARGIN
    expected_y = avail.bottom() - btn.height() - FloatingButton.MARGIN
    assert geom.x() == expected_x
    assert geom.y() == expected_y


def test_set_level_rises_then_decays(qtbot) -> None:
    btn = FloatingButton(bus=EventBus())
    qtbot.addWidget(btn)
    for _ in range(20):
        btn.set_level(0.15)
    assert btn._level > 0.8
    for _ in range(40):
        btn.set_level(0.0)
    assert btn._level < 0.1


def test_set_stage_updates_field(qtbot) -> None:
    from soyle.core.bus import EventBus

    btn = FloatingButton(bus=EventBus())
    qtbot.addWidget(btn)

    btn.set_stage("transcribing")
    assert btn._stage == "transcribing"
    assert btn._anim_timer.isActive()  # processing stages breathe

    btn.set_stage("recording")
    assert btn._stage == "recording"
    assert btn._anim_timer.isActive()  # recording pulses

    btn.set_stage("hidden")
    assert btn._stage == "hidden"
    assert not btn._anim_timer.isActive()  # idle: no animation
