"""System tray icon with context menu."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from soyle.ui.resources import asset_path


class TrayIcon(QObject):
    """Tray icon with menu: Mode submenu, Settings, Logs, Quit."""

    settings_requested = Signal()
    logs_requested = Signal()
    quit_requested = Signal()
    mode_changed = Signal(str)  # "polish" or "rewrite"

    def __init__(self) -> None:
        super().__init__()
        self._tray = QSystemTrayIcon(self._make_icon(recording=False))
        self._tray.setToolTip("Söyle")

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
        self._tray.setToolTip(f"Söyle — режим {label}")

    def toast(self, title: str, message: str, level: str = "info") -> None:
        """Show a balloon notification. ``level`` picks the icon shape:
        "info" (default), "warning" (yellow triangle), "critical" (red X)."""
        icons = {
            "info": QSystemTrayIcon.MessageIcon.Information,
            "warning": QSystemTrayIcon.MessageIcon.Warning,
            "critical": QSystemTrayIcon.MessageIcon.Critical,
        }
        icon = icons.get(level, QSystemTrayIcon.MessageIcon.Information)
        self._tray.showMessage(title, message, icon, 3000)

    def set_usage_text(self, text: str) -> None:
        """Update the non-interactive usage label in the tray menu."""
        self._act_usage.setText(text)

    @staticmethod
    def _make_icon(recording: bool) -> QIcon:
        """Load the bundled .ico; for the recording state, overlay a red
        circle in the top-right corner so the user sees the change at
        16-20px sizes where the main icon's colour isn't very distinct.

        Falls back to a solid coloured square if the asset is missing —
        that path only matters during `pytest` without assets/ present.
        """
        ico_path = asset_path("icon.ico")
        if not ico_path.exists():
            pix = QPixmap(32, 32)
            pix.fill(QColor("#e74c3c" if recording else "#2d2d30"))
            return QIcon(pix)

        base = QIcon(str(ico_path))
        if not recording:
            return base

        # Build an overlay-stamped pixmap. Render at 64px so the red dot
        # stays crisp after Qt downsamples for the tray.
        pix = base.pixmap(64, 64)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#e74c3c"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(40, 4, 20, 20))
        painter.end()
        return QIcon(pix)
