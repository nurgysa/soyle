"""Settings language switcher."""
from __future__ import annotations

from pathlib import Path

from soyle.core.config import ConfigStore
from soyle.ui.settings import SettingsWindow


def test_language_combo_saves_choice(qtbot, tmp_path: Path) -> None:
    store = ConfigStore(config_path=tmp_path / "config.toml")
    win = SettingsWindow(store)
    qtbot.addWidget(win)

    idx = win._ui_language.findData("kk")
    assert idx >= 0
    win._ui_language.setCurrentIndex(idx)
    win._save()

    assert store.load().ui.language == "kk"
