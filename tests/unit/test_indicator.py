"""Tests for the cursor-following Indicator pill."""
from __future__ import annotations

from PySide6.QtGui import QColor

from soyle.ui.indicator import STAGE_COLORS, Indicator
from soyle.ui.theme.tokens import (
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
