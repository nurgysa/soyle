"""Tray history entry wiring."""
from __future__ import annotations

from soyle.ui.tray import TrayIcon


def test_history_action_emits_signal(qtbot) -> None:
    tray = TrayIcon()
    received: list[bool] = []
    tray.history_requested.connect(lambda: received.append(True))

    tray._act_history.trigger()
    assert received == [True]
