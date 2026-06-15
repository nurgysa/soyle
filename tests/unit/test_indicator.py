"""Tests for the cursor-following Indicator pill."""
from __future__ import annotations

from PySide6.QtGui import QColor

from soyle.ui.indicator import STAGE_COLORS, Indicator
from soyle.ui.theme.tokens import (
    STATE_DONE,
    STATE_ERROR,
    STATE_POLISHING,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
)


def test_stage_colors_sourced_from_tokens() -> None:
    assert STAGE_COLORS["recording"] == QColor(STATE_RECORDING)
    assert STAGE_COLORS["transcribing"] == QColor(STATE_TRANSCRIBING)
    assert STAGE_COLORS["polishing"] == QColor(STATE_POLISHING)
    assert STAGE_COLORS["error"] == QColor(STATE_ERROR)


def test_show_recording_sets_stage_and_text(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    ind.show_recording()
    assert ind._stage == "recording"
    assert ind._text == "Запись"


def test_set_level_rises_toward_loud_input(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    for _ in range(20):
        ind.set_level(0.15)  # sustained "full" input
    assert ind._level > 0.8


def test_set_level_decays_toward_silence(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    for _ in range(20):
        ind.set_level(0.15)
    for _ in range(40):
        ind.set_level(0.0)
    assert ind._level < 0.1


def test_show_done_sets_done_stage(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    ind.show_done()
    assert ind._stage == "done"


def test_done_color_from_token(qtbot) -> None:
    assert STAGE_COLORS["done"] == QColor(STATE_DONE)


def test_fixed_position_is_bottom_center(qtbot) -> None:
    from PySide6.QtGui import QGuiApplication

    ind = Indicator()
    qtbot.addWidget(ind)
    ind.show_recording()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    geom = ind.geometry()
    assert abs(geom.center().x() - avail.center().x()) <= 2
    assert geom.bottom() <= avail.bottom() - 120 + ind.height()
