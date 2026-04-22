"""Tests for Injector — clipboard save, paste, restore cycle."""
from __future__ import annotations

from whisperflow.core.bus import Event, EventBus
from whisperflow.core.injector import Injector, _sanitize_for_injection


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
    mocker.patch("whisperflow.core.injector.get_window_class_name", return_value="Chrome_WidgetWin_1")

    bus = EventBus()
    injector = Injector(bus=bus, restore_delay_ms=10)

    captured = injector.capture_target()
    result = injector.inject("hello world", target_hwnd=captured)

    assert result.success is True
    assert result.method == "paste"
    assert result.target_changed is False
    assert result.blocked is False
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
    mocker.patch("whisperflow.core.injector.get_window_class_name", return_value="Chrome_WidgetWin_1")

    bus = EventBus()
    injector = Injector(bus=bus, restore_delay_ms=10)
    result = injector.inject("hi", target_hwnd=injector.capture_target())

    assert result.success is True
    mock_sendv.assert_called_once()
    mock_wm.assert_not_called()
    qtbot.wait(50)
    assert clipboard_state["value"] == "previous"


def test_inject_does_not_paste_if_window_changed(qtbot, mocker) -> None:
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("whisperflow.core.injector.send_wm_paste")
    # capture returns 1111, but later foreground is 2222
    mocker.patch(
        "whisperflow.core.injector.get_foreground_hwnd",
        side_effect=[1111, 2222, 2222],
    )
    mocker.patch("whisperflow.core.injector.get_window_class_name", return_value="Chrome_WidgetWin_1")

    bus = EventBus()
    injector = Injector(bus=bus)
    captured = injector.capture_target()
    result = injector.inject("text", target_hwnd=captured)

    assert result.target_changed is True
    assert result.success is False
    mock_sendv.assert_not_called()
    mock_wm.assert_not_called()


def test_inject_emits_events(qtbot, mocker) -> None:
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mocker.patch("whisperflow.core.injector.send_wm_paste", return_value=False)
    mocker.patch("whisperflow.core.injector.find_edit_child", return_value=0)
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch("whisperflow.core.injector.get_window_class_name", return_value="Chrome_WidgetWin_1")

    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(Event.INJECTING, lambda _: seen.append("inject"))
    bus.subscribe(Event.INJECTED, lambda _: seen.append("done"))

    injector = Injector(bus=bus, restore_delay_ms=10)
    injector.inject("hi", target_hwnd=injector.capture_target())

    assert seen == ["inject", "done"]


# ---- H1: sanitization and terminal blocklist ----

def test_sanitize_strips_control_chars_but_keeps_whitespace() -> None:
    # \x00 NUL, \x07 bell, \x1b ESC, \x7f DEL — all stripped.
    # \t \n \r preserved (0x09, 0x0a, 0x0d).
    dirty = "safe\x00text\x07\x1b[2Jmore\x7f\nline2\tcol"
    assert _sanitize_for_injection(dirty) == "safetext[2Jmore\nline2\tcol"


def test_inject_sanitizes_control_chars_before_clipboard(qtbot, mocker) -> None:
    """A malicious LLM reply with NUL / ESC must not reach the clipboard verbatim."""
    captured_copy: list[str] = []
    mocker.patch(
        "whisperflow.core.injector.pyperclip.copy",
        side_effect=lambda s: captured_copy.append(s),
    )
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mocker.patch("whisperflow.core.injector.send_wm_paste", return_value=False)
    mocker.patch("whisperflow.core.injector.find_edit_child", return_value=0)
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch("whisperflow.core.injector.get_window_class_name", return_value="Notepad")

    injector = Injector(bus=EventBus(), restore_delay_ms=10)
    injector.inject("hello\x00\x07\x1bworld", target_hwnd=injector.capture_target())

    assert captured_copy, "clipboard was never written"
    assert "\x00" not in captured_copy[0]
    assert "\x07" not in captured_copy[0]
    assert "\x1b" not in captured_copy[0]
    assert "hello" in captured_copy[0]
    assert "world" in captured_copy[0]


def test_inject_blocks_terminal_class_keeps_clipboard(qtbot, mocker) -> None:
    """Terminal blocklist: text in clipboard but NO auto-paste."""
    captured_copy: list[str] = []
    mocker.patch(
        "whisperflow.core.injector.pyperclip.copy",
        side_effect=lambda s: captured_copy.append(s),
    )
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("whisperflow.core.injector.send_wm_paste", return_value=True)
    mocker.patch("whisperflow.core.injector.find_edit_child", return_value=0)
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "whisperflow.core.injector.get_window_class_name",
        return_value="ConsoleWindowClass",
    )

    injector = Injector(bus=EventBus(), restore_delay_ms=10)
    result = injector.inject("echo hi\n", target_hwnd=injector.capture_target())

    assert result.blocked is True
    assert result.success is False
    mock_sendv.assert_not_called()
    mock_wm.assert_not_called()
    # Clipboard still received the text (for manual Ctrl+V by the user).
    assert captured_copy == ["echo hi\n"]


def test_inject_blocks_windows_terminal_class(qtbot, mocker) -> None:
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mocker.patch("whisperflow.core.injector.send_wm_paste", return_value=False)
    mocker.patch("whisperflow.core.injector.find_edit_child", return_value=0)
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "whisperflow.core.injector.get_window_class_name",
        return_value="CASCADIA_HOSTING_WINDOW_CLASS",
    )

    injector = Injector(bus=EventBus(), restore_delay_ms=10)
    result = injector.inject("whoami", target_hwnd=injector.capture_target())

    assert result.blocked is True
    mock_sendv.assert_not_called()
