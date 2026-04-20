"""Single-instance guarantee via Win32 named mutex."""
from __future__ import annotations

import sys
from typing import Any

if sys.platform == "win32":
    import win32api
    import win32event
    import winerror


class SingleInstance:
    """Named-mutex lock; call acquire() at startup to detect second launch."""

    def __init__(self, name: str = "WhisperFlow-SingleInstance-Mutex") -> None:
        self._name = name
        self._handle: Any = None

    def acquire(self) -> bool:
        """Return True if this is the first/only instance, False if another holds the mutex."""
        if sys.platform != "win32":
            return True  # non-Windows: treat as first
        self._handle = win32event.CreateMutex(None, False, self._name)
        last_error = win32api.GetLastError()
        if last_error == winerror.ERROR_ALREADY_EXISTS:
            self.release()
            return False
        return True

    def release(self) -> None:
        if self._handle is not None:
            win32api.CloseHandle(self._handle)
            self._handle = None
