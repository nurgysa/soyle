"""Tests for HKCU\\...\\Run autostart management."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from soyle.platform.autostart import (
    disable_autostart,
    enable_autostart,
    is_autostart_enabled,
)

APP_KEY = "SöyleTest"


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    yield
    disable_autostart(app_name=APP_KEY)


def test_enable_autostart_roundtrip(tmp_path) -> None:
    exe = tmp_path / "fake_soyle.exe"
    exe.write_text("")
    enable_autostart(exe_path=str(exe), app_name=APP_KEY)
    assert is_autostart_enabled(app_name=APP_KEY) is True
    disable_autostart(app_name=APP_KEY)
    assert is_autostart_enabled(app_name=APP_KEY) is False


def test_disable_autostart_idempotent() -> None:
    disable_autostart(app_name=APP_KEY)
    disable_autostart(app_name=APP_KEY)
    assert is_autostart_enabled(app_name=APP_KEY) is False


def test_enable_autostart_rejects_quote_in_path() -> None:
    """Defence against registry-quoting injection if caller passes bad input."""
    with pytest.raises(ValueError):
        enable_autostart(exe_path=r'C:\evil"\app.exe', app_name=APP_KEY)


def test_enable_autostart_rejects_null_in_path() -> None:
    with pytest.raises(ValueError):
        enable_autostart(exe_path="C:\\evil\x00.exe", app_name=APP_KEY)
