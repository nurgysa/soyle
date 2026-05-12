"""Frameless pill overlay that follows the cursor and shows recording state."""
from __future__ import annotations

from collections import deque
from typing import Literal

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

Stage = Literal["recording", "transcribing", "polishing", "hidden", "error"]

STAGE_COLORS: dict[Stage, QColor] = {
    "recording": QColor("#e74c3c"),
    "transcribing": QColor("#f39c12"),
    "polishing": QColor("#3498db"),
    "error": QColor("#95a5a6"),
    "hidden": QColor("#000000"),
}


class Indicator(QWidget):
    """Small frameless always-on-top pill widget."""

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
        self._rms_history: deque[float] = deque(maxlen=40)

        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(50)
        self._follow_timer.timeout.connect(self._follow_cursor)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.hide_indicator)

    # ---- Public API ----

    def show_recording(self) -> None:
        self._stage = "recording"
        self._text = "Recording"
        self._rms_history.clear()
        self._follow_timer.start()
        self.show()
        self.update()

    def show_transcribing(self) -> None:
        self._stage = "transcribing"
        self._text = "Transcribing\u2026"
        self.update()

    def show_polishing(self) -> None:
        self._stage = "polishing"
        self._text = "Polishing\u2026"
        self.update()

    def flash_error(self, message: str, duration_ms: int = 1500) -> None:
        self._stage = "error"
        self._text = message
        self.show()
        self._auto_hide_timer.start(duration_ms)
        self.update()

    def push_rms(self, rms: float) -> None:
        self._rms_history.append(min(1.0, rms * 5))
        self.update()

    def hide_indicator(self) -> None:
        self._stage = "hidden"
        self._follow_timer.stop()
        self.hide()

    # ---- Internals ----

    def _follow_cursor(self) -> None:
        pos = QCursor.pos() + QPoint(16, 16)
        self.move(pos)

    def paintEvent(self, _ev: QPaintEvent | None) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(0, 0, 0, 180)
        p.setBrush(bg)
        p.setPen(QPen(STAGE_COLORS[self._stage], 2))
        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        p.drawRoundedRect(rect, 18, 18)

        # waveform on left
        if self._stage == "recording" and self._rms_history:
            p.setPen(QPen(STAGE_COLORS["recording"], 1))
            bar_w = 2
            gap = 1
            x = 12
            mid = self.height() // 2
            for level in self._rms_history:
                h = max(2, int(level * (self.height() - 14)))
                p.drawRect(x, mid - h // 2, bar_w, h)
                x += bar_w + gap
                if x > 80:
                    break

        # text
        p.setPen(QColor("#ffffff"))
        p.drawText(rect.adjusted(90, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, self._text)
