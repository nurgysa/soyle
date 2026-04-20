"""System tray icon with context menu."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QObject):
    """Minimal tray icon with 3 actions: Settings, Logs, Quit."""

    settings_requested = Signal()
    logs_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._tray = QSystemTrayIcon(self._make_icon(recording=False))
        self._tray.setToolTip("WhisperFlow")

        menu = QMenu()
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

    def toast(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    @staticmethod
    def _make_icon(recording: bool) -> QIcon:
        pix = QPixmap(32, 32)
        pix.fill()
        painter = QPainter(pix)
        color = "#e74c3c" if recording else "#2d2d30"
        painter.fillRect(pix.rect(), color)
        painter.end()
        return QIcon(pix)
