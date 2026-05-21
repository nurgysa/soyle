"""QRunnable adapter that runs an async coroutine on a worker thread.

Generic helper used wherever Qt UI code needs to fire an asyncio
coroutine without blocking the main thread. The on_done / on_error
callbacks are typically wired to QObject Signals so the result is
marshalled back to the main thread via QueuedConnection — direct UI
mutation from inside `run()` would crash Qt.

Lives in `soyle.ui` (not `soyle.app`) so both SoyleApp (scheduled sync)
and SettingsWindow (Connect / Sync now / Disconnect buttons) can import
without creating a cycle between app.py and settings.py.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QRunnable


class AsyncRunnable(QRunnable):
    """Run an async coroutine on a worker thread; route the result back via callbacks.

    The coroutine is created inside `run()` (not passed in pre-built)
    because `asyncio.run` needs to drive a fresh coro on the same thread
    that owns the new event loop.
    """

    def __init__(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        on_done: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        super().__init__()
        self._coro_factory = coro_factory
        self._on_done = on_done
        self._on_error = on_error

    def run(self) -> None:
        try:
            result: Any = asyncio.run(self._coro_factory())
        except Exception as exc:
            self._on_error(exc)
            return
        self._on_done(result)
