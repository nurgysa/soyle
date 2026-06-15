"""Frameless pill overlay fixed at bottom-center that shows recording state."""
from __future__ import annotations

import math
from collections import deque
from typing import Literal

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from soyle.core.recorder import normalize_level
from soyle.ui.theme.tokens import (
    STATE_DONE,
    STATE_ERROR,
    STATE_POLISHING,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
)

Stage = Literal["recording", "transcribing", "polishing", "done", "hidden", "error"]

STAGE_COLORS: dict[Stage, QColor] = {
    "recording": QColor(STATE_RECORDING),
    "transcribing": QColor(STATE_TRANSCRIBING),
    "polishing": QColor(STATE_POLISHING),
    "done": QColor(STATE_DONE),
    "error": QColor(STATE_ERROR),
    "hidden": QColor("#000000"),
}


class Indicator(QWidget):
    """Small frameless always-on-top pill widget fixed at bottom-center."""

    MARGIN_BOTTOM = 120

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(180, 40)

        self._stage: Stage = "hidden"
        self._text: str = ""
        self._level: float = 0.0  # EMA-smoothed 0..1 display level
        self._level_smooth = 0.35  # EMA alpha

        self._levels: deque[float] = deque(maxlen=24)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(120)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_hides: bool = False
        self._breath_phase = 0.0
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(33)
        self._breath_timer.timeout.connect(self._tick_breath)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.hide_indicator)

        self._done_fade_timer = QTimer(self)
        self._done_fade_timer.setSingleShot(True)
        self._done_fade_timer.setInterval(600)
        self._done_fade_timer.timeout.connect(self._on_done_timeout)

    # ---- Public API ----

    def show_recording(self) -> None:
        self._stage = "recording"
        self._text = self.tr("Запись")
        self._breath_timer.stop()
        self._position_fixed()
        self.setWindowOpacity(0.0)
        self.show()
        self._fade_to(1.0)
        self.update()

    def show_transcribing(self) -> None:
        self._stage = "transcribing"
        self._text = self.tr("Распознавание…")
        self._breath_timer.start()
        self.update()

    def show_polishing(self) -> None:
        self._stage = "polishing"
        self._text = self.tr("Обработка…")
        self._breath_timer.start()
        self.update()

    def show_done(self) -> None:
        self._stage = "done"
        self._text = self.tr("Готово")
        self._breath_timer.stop()
        self.show()
        self.update()
        self._done_fade_timer.start(600)

    def flash_error(self, message: str, duration_ms: int = 1500) -> None:
        self._breath_timer.stop()
        self._stage = "error"
        self._text = message
        self.show()
        self._auto_hide_timer.start(duration_ms)
        self.update()

    def hide_indicator(self) -> None:
        self._stage = "hidden"
        self._breath_timer.stop()
        self.hide()

    def set_level(self, rms: float) -> None:
        """Feed a raw RMS sample; stored as an EMA-smoothed 0..1 level."""
        target = normalize_level(rms)
        self._level = self._level_smooth * target + (1 - self._level_smooth) * self._level
        self._levels.append(self._level)
        self.update()

    # ---- Internals ----

    def _tick_breath(self) -> None:
        self._breath_phase += 0.12
        self.update()

    def _on_done_timeout(self) -> None:
        self._fade_to(0.0, then_hide=True)

    def _fade_to(self, end: float, *, then_hide: bool = False) -> None:
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(end)
        if self._fade_hides:
            self._fade.finished.disconnect(self.hide)
            self._fade_hides = False
        if then_hide:
            self._fade.finished.connect(self.hide)
            self._fade_hides = True
        self._fade.start()

    def _position_fixed(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = avail.center().x() - self.width() // 2
        y = avail.bottom() - self.height() - self.MARGIN_BOTTOM
        self.move(x, y)

    def paintEvent(self, _ev: QPaintEvent | None) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = STAGE_COLORS[self._stage]
        bg = QColor(0, 0, 0, 200)
        p.setBrush(bg)
        p.setPen(QPen(color, 2))
        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        p.drawRoundedRect(rect, 18, 18)

        icon_box = QRect(12, (self.height() - 18) // 2, 18, 18)
        if self._stage in ("transcribing", "polishing"):
            opacity = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._breath_phase))
            p.setOpacity(opacity)
        self._paint_glyph(p, icon_box, color)
        p.setOpacity(1.0)

        if self._stage == "recording":
            self._paint_waveform(p, color)

        if self._stage != "recording":
            p.setPen(QColor("#ffffff"))
            p.drawText(rect.adjusted(40, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter, self._text)

    def _paint_glyph(self, p: QPainter, box: QRect, color: QColor) -> None:
        p.save()
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = box.center().x(), box.center().y()
        if self._stage == "recording":
            p.setBrush(color)
            p.drawRoundedRect(cx - 3, box.top() + 1, 6, 9, 3, 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(cx - 5, cy - 3, 10, 10, 200 * 16, 140 * 16)
            p.drawLine(cx, box.bottom() - 4, cx, box.bottom())
        elif self._stage == "transcribing":
            p.drawRect(box.left() + 3, box.top() + 1, 10, 14)
            for i in range(3):
                yy = box.top() + 5 + i * 3
                p.drawLine(box.left() + 5, yy, box.left() + 11, yy)
        elif self._stage == "polishing":
            p.setBrush(color)
            star = [
                QPoint(cx, cy - 7), QPoint(cx + 2, cy - 2),
                QPoint(cx + 7, cy), QPoint(cx + 2, cy + 2),
                QPoint(cx, cy + 7), QPoint(cx - 2, cy + 2),
                QPoint(cx - 7, cy), QPoint(cx - 2, cy - 2),
            ]
            p.drawPolygon(star)
        elif self._stage == "done":
            p.drawPolyline([QPoint(cx - 6, cy), QPoint(cx - 2, cy + 4), QPoint(cx + 6, cy - 5)])
        elif self._stage == "error":
            p.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
            p.drawLine(cx + 5, cy - 5, cx - 5, cy + 5)
        p.restore()

    def _paint_waveform(self, p: QPainter, color: QColor) -> None:
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        bar_w, gap = 3, 2
        x0 = 40
        max_h = self.height() - 16
        cy = self.height() // 2
        levels = list(self._levels)
        for i in range(len(levels)):
            h = max(2, int(levels[i] * max_h))
            x = x0 + i * (bar_w + gap)
            if x > self.width() - 14:
                break
            p.drawRoundedRect(x, cy - h // 2, bar_w, h, 1, 1)
        p.restore()
