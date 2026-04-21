"""Tests for Ctrl+V keystroke helper."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from whisperflow.platform import paste as paste_mod


def test_send_ctrl_v_calls_keyboard(mocker) -> None:
    mock_kb = mocker.patch.object(paste_mod.keyboard, "press_and_release")
    paste_mod.send_ctrl_v()
    mock_kb.assert_called_once_with("ctrl+v")


def test_send_ctrl_v_suppresses_errors(mocker) -> None:
    mocker.patch.object(paste_mod.keyboard, "press_and_release", side_effect=OSError("foo"))
    # Should NOT raise — caller detects failure via clipboard state.
    paste_mod.send_ctrl_v()
