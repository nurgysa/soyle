"""Manage HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run entry."""
from __future__ import annotations

import contextlib
import sys

if sys.platform == "win32":
    import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_APP_NAME = "WhisperFlow"


def enable_autostart(exe_path: str, app_name: str = DEFAULT_APP_NAME) -> None:
    if sys.platform != "win32":
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')


def disable_autostart(app_name: str = DEFAULT_APP_NAME) -> None:
    if sys.platform != "win32":
        return
    with contextlib.suppress(FileNotFoundError), winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.DeleteValue(key, app_name)


def is_autostart_enabled(app_name: str = DEFAULT_APP_NAME) -> bool:
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, app_name)
            return True
    except FileNotFoundError:
        return False
