"""Tests for Ctrl+V keystroke helper."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from whisperflow.platform import paste as paste_mod


def test_send_ctrl_v_calls_keybd_event_four_times(mocker) -> None:
    mock_keybd = mocker.patch.object(paste_mod.win32api, "keybd_event")
    paste_mod.send_ctrl_v()
    # 4 keybd_event calls: ctrl down, v down, v up, ctrl up
    assert mock_keybd.call_count == 4


def test_send_ctrl_v_sends_correct_sequence(mocker) -> None:
    mock_keybd = mocker.patch.object(paste_mod.win32api, "keybd_event")
    paste_mod.send_ctrl_v()
    calls = mock_keybd.call_args_list
    # ctrl down
    assert calls[0].args[0] == paste_mod.VK_CONTROL
    assert calls[0].args[2] == 0
    # v down
    assert calls[1].args[0] == paste_mod.VK_V
    assert calls[1].args[2] == 0
    # v up
    assert calls[2].args[0] == paste_mod.VK_V
    assert calls[2].args[2] == paste_mod.KEYEVENTF_KEYUP
    # ctrl up
    assert calls[3].args[0] == paste_mod.VK_CONTROL
    assert calls[3].args[2] == paste_mod.KEYEVENTF_KEYUP


def test_send_ctrl_v_suppresses_errors(mocker) -> None:
    mocker.patch.object(paste_mod.win32api, "keybd_event", side_effect=OSError("foo"))
    # Should NOT raise — caller will detect failure via clipboard state
    paste_mod.send_ctrl_v()
