"""Tests for Injector — clipboard save, paste, restore cycle."""
from __future__ import annotations

from whisperflow.core.bus import Event, EventBus
from whisperflow.core.injector import Injector


def test_inject_uses_wm_paste_when_edit_child_found(qtbot, mocker) -> None:
    """Classic Win32 path: child Edit control → WM_PASTE, no Ctrl+V."""
    clipboard_state = {"value": "old clipboard"}

    def fake_copy(text: str) -> None:
        clipboard_state["value"] = text

    def fake_paste() -> str:
        return clipboard_state["value"]

    mocker.patch("whisperflow.core.injector.pyperclip.copy", side_effect=fake_copy)
    mocker.patch("whisperflow.core.injector.pyperclip.paste", side_effect=fake_paste)
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("whisperflow.core.injector.send_wm_paste", return_value=True)
    mocker.patch("whisperflow.core.injector.find_edit_child", return_value=5678)
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)

    bus = EventBus()
    injector = Injector(bus=bus, restore_delay_ms=10)

    captured = injector.capture_target()
    result = injector.inject("hello world", target_hwnd=captured)

    assert result.success is True
    assert result.method == "paste"
    assert result.target_changed is False
    mock_wm.assert_called_once_with(1234)
    mock_sendv.assert_not_called()
    qtbot.wait(50)
    assert clipboard_state["value"] == "old clipboard"


def test_inject_falls_back_to_ctrl_v_without_edit_child(qtbot, mocker) -> None:
    """Modern apps (browsers, Electron) — no Edit child → synthetic Ctrl+V."""
    clipboard_state = {"value": "previous"}

    def fake_copy(text: str) -> None:
        clipboard_state["value"] = text

    def fake_paste() -> str:
        return clipboard_state["value"]

    mocker.patch("whisperflow.core.injector.pyperclip.copy", side_effect=fake_copy)
    mocker.patch("whisperflow.core.injector.pyperclip.paste", side_effect=fake_paste)
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("whisperflow.core.injector.send_wm_paste", return_value=False)
    mocker.patch("whisperflow.core.injector.find_edit_child", return_value=0)
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)

    bus = EventBus()
    injector = Injector(bus=bus, restore_delay_ms=10)
    result = injector.inject("hi", target_hwnd=injector.capture_target())

    assert result.success is True
    mock_sendv.assert_called_once()
    mock_wm.assert_not_called()
    qtbot.wait(50)
    assert clipboard_state["value"] == "previous"


def test_inject_does_not_paste_if_window_changed(qtbot, mocker) -> None:  # noqa: ARG001
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("whisperflow.core.injector.send_wm_paste")
    # capture returns 1111, but later foreground is 2222
    mocker.patch(
        "whisperflow.core.injector.get_foreground_hwnd",
        side_effect=[1111, 2222, 2222],
    )

    bus = EventBus()
    injector = Injector(bus=bus)
    captured = injector.capture_target()
    result = injector.inject("text", target_hwnd=captured)

    assert result.target_changed is True
    assert result.success is False
    mock_sendv.assert_not_called()
    mock_wm.assert_not_called()


def test_inject_emits_events(qtbot, mocker) -> None:  # noqa: ARG001
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mocker.patch("whisperflow.core.injector.send_wm_paste", return_value=False)
    mocker.patch("whisperflow.core.injector.find_edit_child", return_value=0)
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)

    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(Event.INJECTING, lambda _: seen.append("inject"))
    bus.subscribe(Event.INJECTED, lambda _: seen.append("done"))

    injector = Injector(bus=bus, restore_delay_ms=10)
    injector.inject("hi", target_hwnd=injector.capture_target())

    assert seen == ["inject", "done"]
