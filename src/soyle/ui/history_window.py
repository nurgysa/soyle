"""History window — two-pane recover-and-reinject UI (Stage 2)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from soyle.core.history import HistoryEntry, HistoryStore


def _tr(text: str) -> str:
    return QCoreApplication.translate("HistoryWindow", text)


def format_relative(timestamp: str, *, now: datetime | None = None) -> str:
    """Human relative time for a HistoryEntry.timestamp.

    Russian source strings (identity locale); kk/en come from .qm. Returns
    the raw input unchanged if it cannot be parsed, so a corrupt row never
    crashes the list.
    """
    now = now or datetime.now(tz=UTC)
    try:
        then = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return timestamp
    secs = (now - then).total_seconds()
    if secs < 60:
        return _tr("только что")
    if secs < 3600:
        return _tr("{n} мин назад").format(n=int(secs // 60))
    if secs < 86400:
        return _tr("{n} ч назад").format(n=int(secs // 3600))
    if secs < 172800:
        return _tr("вчера")
    return then.strftime("%d.%m.%Y")


class _HistoryRow(QWidget):
    """List row: relative time + mode/lang badges + a one-line preview."""

    def __init__(self, entry: HistoryEntry) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(6)
        time_lbl = QLabel(format_relative(entry.timestamp))
        time_lbl.setObjectName("historyRowTime")
        badge = QLabel(f"{entry.mode} · {entry.language}")
        badge.setObjectName("historyRowBadge")
        top.addWidget(time_lbl)
        top.addStretch(1)
        top.addWidget(badge)
        layout.addLayout(top)

        preview = QLabel(entry.processed_text)
        preview.setObjectName("historyRowPreview")
        preview.setWordWrap(False)
        preview.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(preview)


class HistoryWindow(QWidget):
    """Two-pane history: list left, detail right. Recover & re-inject."""

    def __init__(
        self,
        store: HistoryStore,
        on_inject: Callable[[str], None],
        *,
        clipboard: Any = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._on_inject = on_inject
        # Injected for tests; defaults to the app clipboard at runtime.
        from PySide6.QtWidgets import QApplication

        self._clipboard: Any = clipboard or QApplication.clipboard()
        self._current: HistoryEntry | None = None

        self.setWindowTitle(_tr("История"))
        self.resize(720, 460)

        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(_tr("Поиск…"))
        self._search.textChanged.connect(self._populate)
        self._btn_clear = QPushButton(_tr("Очистить"))
        self._btn_clear.clicked.connect(self._on_clear)
        toolbar.addWidget(self._search, 1)
        toolbar.addWidget(self._btn_clear)
        root.addLayout(toolbar)

        panes = QHBoxLayout()

        self._list = QListWidget()
        self._list.setObjectName("historyList")
        self._list.setFixedWidth(260)
        self._list.currentItemChanged.connect(self._on_select)
        panes.addWidget(self._list)

        detail = QVBoxLayout()
        self._detail_processed = QLabel()
        self._detail_processed.setObjectName("historyProcessed")
        self._detail_processed.setWordWrap(True)
        self._detail_processed.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail.addWidget(self._detail_processed)

        self._raw_toggle = QPushButton(_tr("Показать сырой текст"))
        self._raw_toggle.setObjectName("historyRawToggle")
        self._raw_toggle.setFlat(True)
        self._raw_toggle.clicked.connect(self._toggle_raw)
        detail.addWidget(self._raw_toggle)

        self._detail_raw = QLabel()
        self._detail_raw.setObjectName("historyRaw")
        self._detail_raw.setWordWrap(True)
        self._detail_raw.setVisible(False)
        self._detail_raw.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail.addWidget(self._detail_raw)

        detail.addStretch(1)

        actions = QHBoxLayout()
        self._btn_inject = QPushButton(_tr("Вставить"))
        self._btn_inject.setObjectName("primary")  # reuse the existing accent-button QSS
        self._btn_inject.clicked.connect(self._on_inject_clicked)
        self._btn_copy = QPushButton(_tr("Копировать"))
        self._btn_copy.clicked.connect(self._on_copy)
        self._btn_delete = QPushButton(_tr("Удалить"))
        self._btn_delete.clicked.connect(self._on_delete)
        actions.addWidget(self._btn_inject)
        actions.addWidget(self._btn_copy)
        actions.addStretch(1)
        actions.addWidget(self._btn_delete)
        detail.addLayout(actions)

        panes.addLayout(detail, 1)
        root.addLayout(panes)

        self._populate()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt override)
        # Re-read the store every time the window is shown so it reflects
        # dictations made while it was closed.
        self._populate()
        super().showEvent(event)

    def _populate(self, _filter: str = "") -> None:
        needle = self._search.text().strip().lower()
        self._list.clear()
        for entry in self._store.all():
            if needle and needle not in entry.processed_text.lower() \
                    and needle not in entry.raw_text.lower():
                continue
            item = QListWidgetItem(self._list)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            row = _HistoryRow(entry)
            item.setSizeHint(row.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._current = None
            self._detail_processed.clear()
            self._detail_raw.clear()

    def _on_select(
        self, current: QListWidgetItem | None, _prev: object = None
    ) -> None:
        if current is None:
            return
        entry: HistoryEntry = current.data(Qt.ItemDataRole.UserRole)
        self._current = entry
        self._detail_processed.setText(entry.processed_text)
        self._detail_raw.setText(entry.raw_text)
        self._detail_raw.setVisible(False)
        self._raw_toggle.setText(_tr("Показать сырой текст"))

    def _toggle_raw(self) -> None:
        shown = not self._detail_raw.isVisible()
        self._detail_raw.setVisible(shown)
        self._raw_toggle.setText(
            _tr("Скрыть сырой текст") if shown else _tr("Показать сырой текст")
        )

    def _on_inject_clicked(self) -> None:
        if self._current is not None:
            self._on_inject(self._current.processed_text)

    def _on_copy(self) -> None:
        if self._current is not None:
            self._clipboard.setText(self._current.processed_text)

    def _on_delete(self) -> None:
        if self._current is not None:
            self._store.delete(self._current.timestamp)
            self._populate()

    def _on_clear(self) -> None:
        if self._list.count() == 0:
            return
        confirm = QMessageBox.question(
            self,
            _tr("Очистить историю"),
            _tr("Удалить все записи истории? Это действие необратимо."),
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._store.clear()
            self._populate()
