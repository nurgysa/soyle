"""Tests for paste primitives."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from soyle.platform import paste as paste_mod


def test_send_ctrl_v_calls_keyboard(mocker) -> None:
    mock_kb = mocker.patch.object(paste_mod.keyboard, "press_and_release")
    paste_mod.send_ctrl_v()
    mock_kb.assert_called_once_with("ctrl+v")


def test_send_ctrl_v_suppresses_errors(mocker) -> None:
    mocker.patch.object(paste_mod.keyboard, "press_and_release", side_effect=OSError("foo"))
    paste_mod.send_ctrl_v()


def test_find_edit_child_returns_zero_for_zero_hwnd() -> None:
    assert paste_mod.find_edit_child(0) == 0


def test_find_edit_child_tries_each_class_until_hit(mocker) -> None:
    mock_find = mocker.patch.object(paste_mod.win32gui, "FindWindowEx", side_effect=[0, 0, 9999])
    result = paste_mod.find_edit_child(1234)
    assert result == 9999
    assert mock_find.call_count == 3


def test_find_edit_child_returns_zero_when_all_fail(mocker) -> None:
    mocker.patch.object(paste_mod.win32gui, "FindWindowEx", return_value=0)
    assert paste_mod.find_edit_child(1234) == 0


def test_send_wm_paste_posts_when_edit_found(mocker) -> None:
    mocker.patch.object(paste_mod, "find_edit_child", return_value=5678)
    mock_send = mocker.patch.object(paste_mod.win32gui, "SendMessage")

    ok = paste_mod.send_wm_paste(1234)

    assert ok is True
    mock_send.assert_called_once()
    args = mock_send.call_args.args
    assert args[0] == 5678
    assert args[1] == paste_mod.win32con.WM_PASTE


def test_send_wm_paste_returns_false_when_no_edit(mocker) -> None:
    mocker.patch.object(paste_mod, "find_edit_child", return_value=0)
    mock_send = mocker.patch.object(paste_mod.win32gui, "SendMessage")

    ok = paste_mod.send_wm_paste(1234)

    assert ok is False
    mock_send.assert_not_called()


def test_send_wm_paste_suppresses_send_errors(mocker) -> None:
    mocker.patch.object(paste_mod, "find_edit_child", return_value=5678)
    mocker.patch.object(paste_mod.win32gui, "SendMessage", side_effect=OSError("denied"))
    ok = paste_mod.send_wm_paste(1234)
    assert ok is False
