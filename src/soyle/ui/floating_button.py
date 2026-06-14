"""Frameless circular mic button — mouse-triggered PTT alternative.

Mirrors Indicator's window-flag pattern but is INTERACTIVE: clicks are
captured by the widget, not passed through. Press-and-hold emits
HOTKEY_PRESSED/HOTKEY_RELEASED so the rest of Söyle (Recorder,
Transcriber, Injector) treats it identically to a Right Alt press.

State machine guards against double-trigger: if Right Alt has already
started recording, _on_hotkey_pressed in app.py early-returns on the
mouse-emitted HOTKEY_PRESSED via state.can_start_recording() check.
This widget therefore needs no coordination with HotkeyBox.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from soyle.core.bus import Event, EventBus
from soyle.ui.theme.tokens import STATE_POLISHING, STATE_RECORDING

_RING_COLOR_IDLE = QColor("#7f8c8d")          # gray
_RING_COLOR_RECORDING = QColor(STATE_RECORDING)
_RING_COLOR_PROCESSING = QColor(STATE_POLISHING)
_FILL_BG = QColor(44, 62, 80, 220)            # dark navy, slightly translucent
_DOT_COLOR_RECORDING = QColor(STATE_RECORDING)
_MIC_COLOR_IDLE = QColor("#ecf0f1")           # light gray-white


class FloatingButton(QWidget):
    """Mouse-triggered PTT pill, fixed bottom-right of primary screen.

    Public API:
      - set_recording(bool)  : reflects RECORDING state via fill color
      - set_processing(bool) : reflects TRANSCRIBING/POLISHING/INJECTING via ring color
      - _position_in_corner(): re-pins to primary screen's available bottom-right

    Click handling: only mouse presses inside the painted circle (radius =
    width/2 - 2) emit bus events. Corners outside the circle are ignored to
    prevent near-miss clicks from accidentally starting a recording.
    """

    SIZE = 56
    MARGIN = 24
    RING_WIDTH = 3

    def __init__(self, bus: EventBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._recording = False
        self._processing = False
        self._is_pressed = False  # tracks our own press lifecycle for paired release

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # Translucent background so the circle is the only visible region;
        # corners outside the circle are click-through-invisible.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(self.SIZE, self.SIZE)
        self.setToolTip(self.tr("Зажмите для записи"))
        self._position_in_corner()

    # ---- Public API ---------------------------------------------------------

    def set_recording(self, on: bool) -> None:
        self._recording = on
        self.update()

    def set_processing(self, on: bool) -> None:
        self._processing = on
        self.update()

    # ---- Mouse events -------------------------------------------------------

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if not self._point_inside_circle(ev.position().toPoint()):
            # Corner click — translucent dead-zone. Ignore, don't trigger PTT.
            return
        self._is_pressed = True
        self._bus.emit(Event.HOTKEY_PRESSED, {})

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if not self._is_pressed:
            # Release without a paired press (e.g. press in dead-zone followed
            # by release inside circle). Don't emit RELEASED with no PRESSED.
            return
        self._is_pressed = False
        self._bus.emit(Event.HOTKEY_RELEASED, {})

    # ---- Painting -----------------------------------------------------------

    def paintEvent(self, _ev: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer ring color reflects state; recording wins over processing.
        if self._recording:
            ring_color = _RING_COLOR_RECORDING
        elif self._processing:
            ring_color = _RING_COLOR_PROCESSING
        else:
            ring_color = _RING_COLOR_IDLE

        # Filled inner disk
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_FILL_BG)
        inset = self.RING_WIDTH
        p.drawEllipse(
            inset, inset, self.width() - 2 * inset, self.height() - 2 * inset
        )

        # State ring
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ring_color, self.RING_WIDTH))
        half = self.RING_WIDTH / 2
        p.drawEllipse(
            int(half),
            int(half),
            int(self.width() - self.RING_WIDTH),
            int(self.height() - self.RING_WIDTH),
        )

        # Center glyph: solid dot when recording (visual feedback), mic-shape otherwise
        if self._recording:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_DOT_COLOR_RECORDING)
            dot_size = self.width() // 3
            p.drawEllipse(
                (self.width() - dot_size) // 2,
                (self.height() - dot_size) // 2,
                dot_size,
                dot_size,
            )
        else:
            # Simple mic glyph: rounded vertical rect (body) + horizontal stand
            p.setPen(QPen(_MIC_COLOR_IDLE, 2))
            p.setBrush(_MIC_COLOR_IDLE)
            cx = self.width() // 2
            cy = self.height() // 2
            body_w = 10
            body_h = 16
            p.drawRoundedRect(cx - body_w // 2, cy - body_h // 2 - 2, body_w, body_h, 4, 4)
            # Stand: short vertical line + horizontal base
            p.drawLine(cx, cy + body_h // 2 - 2, cx, cy + body_h // 2 + 4)
            p.drawLine(cx - 6, cy + body_h // 2 + 4, cx + 6, cy + body_h // 2 + 4)

    # ---- Internals ----------------------------------------------------------

    def _point_inside_circle(self, pt: QPoint) -> bool:
        """True if pt is inside the painted circle (radius = SIZE/2 - 2px tolerance)."""
        cx = self.width() / 2
        cy = self.height() / 2
        dx = pt.x() - cx
        dy = pt.y() - cy
        # 2px tolerance under the visible radius — match the painted circle exactly.
        radius = (self.width() / 2) - 2
        return math.hypot(dx, dy) <= radius

    def _position_in_corner(self) -> None:
        """Pin to bottom-right of the primary screen's available geometry.

        Re-callable on screen geometry changes (DPI scale, primary monitor
        switch). For Phase A there's no signal subscription — caller can
        invoke manually if needed. Phase B will subscribe to screenChanged.
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = avail.right() - self.width() - self.MARGIN
        y = avail.bottom() - self.height() - self.MARGIN
        self.move(x, y)
