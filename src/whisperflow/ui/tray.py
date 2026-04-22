"""System tray icon with context menu."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QObject):
    """Tray icon with menu: Mode submenu, Settings, Logs, Quit."""

    settings_requested = Signal()
    logs_requested = Signal()
    quit_requested = Signal()
    mode_changed = Signal(str)  # "polish" or "rewrite"

    def __init__(self) -> None:
        super().__init__()
        self._tray = QSystemTrayIcon(self._make_icon(recording=False))
        self._tray.setToolTip("WhisperFlow")

        menu = QMenu()

        # Mode submenu — quick toggle between polish / rewrite.
        mode_menu = menu.addMenu("Режим")
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        self._act_polish = QAction("Polish", self)
        self._act_polish.setCheckable(True)
        self._act_polish.setData("polish")
        self._act_polish.triggered.connect(lambda: self.mode_changed.emit("polish"))
        self._act_rewrite = QAction("Rewrite", self)
        self._act_rewrite.setCheckable(True)
        self._act_rewrite.setData("rewrite")
        self._act_rewrite.triggered.connect(lambda: self.mode_changed.emit("rewrite"))
        self._mode_group.addAction(self._act_polish)
        self._mode_group.addAction(self._act_rewrite)
        mode_menu.addAction(self._act_polish)
        mode_menu.addAction(self._act_rewrite)

        menu.addSeparator()

        # Usage summary — non-interactive, shows today's and monthly cost.
        self._act_usage = QAction("Расход: $0.0000 (0)", self)
        self._act_usage.setEnabled(False)
        menu.addAction(self._act_usage)

        menu.addSeparator()

        act_settings = QAction("Настройки…", self)
        act_settings.triggered.connect(self.settings_requested.emit)
        act_logs = QAction("Показать логи", self)
        act_logs.triggered.connect(self.logs_requested.emit)
        act_quit = QAction("Выход", self)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_settings)
        menu.addAction(act_logs)
        menu.addSeparator()
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)
        self._menu = menu

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def set_recording(self, recording: bool) -> None:
        self._tray.setIcon(self._make_icon(recording=recording))

    def set_mode(self, mode: str) -> None:
        """Reflect current LLM mode in the submenu checkmark and tooltip."""
        self._act_polish.setChecked(mode == "polish")
        self._act_rewrite.setChecked(mode == "rewrite")
        label = "Rewrite" if mode == "rewrite" else "Polish"
        self._tray.setToolTip(f"WhisperFlow — режим {label}")

    def toast(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    def set_usage_text(self, text: str) -> None:
        """Update the non-interactive usage label in the tray menu."""
        self._act_usage.setText(text)

    @staticmethod
    def _make_icon(recording: bool) -> QIcon:
        pix = QPixmap(32, 32)
        pix.fill()
        painter = QPainter(pix)
        color = "#e74c3c" if recording else "#2d2d30"
        painter.fillRect(pix.rect(), color)
        painter.end()
        return QIcon(pix)
