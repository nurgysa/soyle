"""History window — two-pane recover-and-reinject UI (Stage 2)."""
from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QCoreApplication


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
