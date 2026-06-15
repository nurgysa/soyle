"""Frameless pill overlay fixed at bottom-center that shows recording state."""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QRect, Qt, QTimer
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

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.hide_indicator)

    # ---- Public API ----

    def show_recording(self) -> None:
        self._stage = "recording"
        self._text = self.tr("Запись")
        self._position_fixed()
        self.show()
        self.update()

    def show_transcribing(self) -> None:
        self._stage = "transcribing"
        self._text = self.tr("Распознавание…")
        self.update()

    def show_polishing(self) -> None:
        self._stage = "polishing"
        self._text = self.tr("Обработка…")
        self.update()

    def show_done(self) -> None:
        self._stage = "done"
        self._text = self.tr("Готово")
        self.show()
        self.update()
        self._auto_hide_timer.start(600)

    def flash_error(self, message: str, duration_ms: int = 1500) -> None:
        self._stage = "error"
        self._text = message
        self.show()
        self._auto_hide_timer.start(duration_ms)
        self.update()

    def hide_indicator(self) -> None:
        self._stage = "hidden"
        self.hide()

    def set_level(self, rms: float) -> None:
        """Feed a raw RMS sample; stored as an EMA-smoothed 0..1 level."""
        target = normalize_level(rms)
        self._level = self._level_smooth * target + (1 - self._level_smooth) * self._level
        self.update()

    # ---- Internals ----

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

        bg = QColor(0, 0, 0, 180)
        p.setBrush(bg)
        p.setPen(QPen(STAGE_COLORS[self._stage], 2))
        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        p.drawRoundedRect(rect, 18, 18)

        # Status dot on the left — fills the gap the old +90px offset left empty.
        dot_d = 10
        dot_x = 16
        dot_y = (self.height() - dot_d) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(STAGE_COLORS[self._stage])
        p.drawEllipse(dot_x, dot_y, dot_d, dot_d)

        # Text sits just right of the dot, vertically centered.
        p.setPen(QColor("#ffffff"))
        p.drawText(
            rect.adjusted(36, 0, -12, 0),
            Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )
