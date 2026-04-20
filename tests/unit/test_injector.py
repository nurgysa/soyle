"""Tests for Injector — clipboard save, paste, restore cycle."""
from __future__ import annotations

from whisperflow.core.bus import Event, EventBus
from whisperflow.core.injector import Injector


def test_inject_replaces_clipboard_then_restores(qtbot, mocker) -> None:
    clipboard_state = {"value": "old clipboard"}

    def fake_copy(text: str) -> None:
        clipboard_state["value"] = text

    def fake_paste() -> str:
        return clipboard_state["value"]

    mocker.patch("whisperflow.core.injector.pyperclip.copy", side_effect=fake_copy)
    mocker.patch("whisperflow.core.injector.pyperclip.paste", side_effect=fake_paste)
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mocker.patch(
        "whisperflow.core.injector.get_foreground_hwnd", return_value=1234
    )

    bus = EventBus()
    injector = Injector(bus=bus, restore_delay_ms=10)

    captured = injector.capture_target()
    result = injector.inject("hello world", target_hwnd=captured)

    assert result.success is True
    assert result.method == "paste"
    assert result.target_changed is False
    assert mock_sendv.call_count == 1
    # After restore delay, clipboard should be back to "old clipboard"
    qtbot.wait(50)
    assert clipboard_state["value"] == "old clipboard"


def test_inject_does_not_paste_if_window_changed(qtbot, mocker) -> None:
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
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


def test_inject_emits_events(qtbot, mocker) -> None:
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)

    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(Event.INJECTING, lambda _: seen.append("inject"))
    bus.subscribe(Event.INJECTED, lambda _: seen.append("done"))

    injector = Injector(bus=bus, restore_delay_ms=10)
    injector.inject("hi", target_hwnd=injector.capture_target())

    assert seen == ["inject", "done"]
