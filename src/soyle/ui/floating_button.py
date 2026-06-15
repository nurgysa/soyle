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

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from soyle.core.bus import Event, EventBus
from soyle.core.recorder import normalize_level
from soyle.ui.indicator import STAGE_COLORS, Stage
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
        self._level: float = 0.0
        self._level_smooth = 0.35

        self._stage: Stage = "hidden"
        self._breath_phase = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._tick_anim)

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

    def set_stage(self, stage: Stage) -> None:
        self._stage = stage
        if stage in ("recording", "transcribing", "polishing"):
            self._anim_timer.start()
        else:
            self._anim_timer.stop()
        self.update()

    def _tick_anim(self) -> None:
        self._breath_phase += 0.12
        self.update()

    def set_recording(self, on: bool) -> None:
        self._recording = on
        self.set_stage("recording" if on else "hidden")

    def set_processing(self, on: bool) -> None:
        self._processing = on
        if on:
            self.set_stage("polishing")
        elif not self._recording:
            self.set_stage("hidden")

    def set_level(self, rms: float) -> None:
        """Feed a raw RMS sample; stored as an EMA-smoothed 0..1 level."""
        target = normalize_level(rms)
        self._level = self._level_smooth * target + (1 - self._level_smooth) * self._level
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

        # Stage-aware overlays (level pulse for recording; breathing ring for processing)
        stage_color = STAGE_COLORS.get(self._stage)
        if self._stage == "recording" and stage_color is not None:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            pulse = QColor(stage_color)
            pulse.setAlpha(int(90 * self._level))
            grow = int(6 * self._level)
            p.setBrush(pulse)
            p.drawEllipse(self.rect().center(), self.SIZE // 2 - 2 + grow, self.SIZE // 2 - 2 + grow)
            p.restore()
        elif self._stage in ("transcribing", "polishing") and stage_color is not None:
            opacity = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._breath_phase))
            p.save()
            p.setOpacity(opacity)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(stage_color, self.RING_WIDTH))
            half = self.RING_WIDTH / 2
            p.drawEllipse(int(half), int(half), int(self.width() - self.RING_WIDTH), int(self.height() - self.RING_WIDTH))
            p.restore()

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
