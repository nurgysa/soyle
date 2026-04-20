"""Tests for Ctrl+V keystroke helper."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from whisperflow.platform import paste as paste_mod


def test_send_ctrl_v_uses_sendinput(mocker) -> None:
    mock_sendinput = mocker.patch.object(paste_mod, "SendInput")
    paste_mod.send_ctrl_v()
    # 4 INPUT structs: ctrl down, v down, v up, ctrl up
    args = mock_sendinput.call_args
    assert args[0][0] == 4  # nInputs


def test_send_ctrl_v_suppresses_errors(mocker) -> None:
    mocker.patch.object(paste_mod, "SendInput", side_effect=OSError("foo"))
    # Should NOT raise - caller will detect failure via clipboard state
    paste_mod.send_ctrl_v()
