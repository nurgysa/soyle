"""Tests for Injector — clipboard save, paste, restore cycle."""
from __future__ import annotations

from soyle.core.bus import Event, EventBus
from soyle.core.injector import Injector, _sanitize_for_injection


def test_inject_uses_wm_paste_when_edit_child_found(qtbot, mocker) -> None:
    """Classic Win32 path: child Edit control → WM_PASTE, no Ctrl+V."""
    clipboard_state = {"value": "old clipboard"}

    def fake_copy(text: str) -> None:
        clipboard_state["value"] = text

    def fake_paste() -> str:
        return clipboard_state["value"]

    mocker.patch("soyle.core.injector.pyperclip.copy", side_effect=fake_copy)
    mocker.patch("soyle.core.injector.pyperclip.paste", side_effect=fake_paste)
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("soyle.core.injector.send_wm_paste", return_value=True)
    mocker.patch("soyle.core.injector.find_edit_child", return_value=5678)
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch("soyle.core.injector.get_window_class_name", return_value="Chrome_WidgetWin_1")

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

    mocker.patch("soyle.core.injector.pyperclip.copy", side_effect=fake_copy)
    mocker.patch("soyle.core.injector.pyperclip.paste", side_effect=fake_paste)
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("soyle.core.injector.send_wm_paste", return_value=False)
    mocker.patch("soyle.core.injector.find_edit_child", return_value=0)
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch("soyle.core.injector.get_window_class_name", return_value="Chrome_WidgetWin_1")

    bus = EventBus()
    injector = Injector(bus=bus, restore_delay_ms=10)
    result = injector.inject("hi", target_hwnd=injector.capture_target())

    assert result.success is True
    mock_sendv.assert_called_once()
    mock_wm.assert_not_called()
    qtbot.wait(50)
    assert clipboard_state["value"] == "previous"


def test_inject_does_not_paste_if_window_changed(qtbot, mocker) -> None:
    mocker.patch("soyle.core.injector.pyperclip.copy")
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("soyle.core.injector.send_wm_paste")
    # capture returns 1111, but later foreground is 2222
    mocker.patch(
        "soyle.core.injector.get_foreground_hwnd",
        side_effect=[1111, 2222, 2222],
    )
    mocker.patch("soyle.core.injector.get_window_class_name", return_value="Chrome_WidgetWin_1")

    bus = EventBus()
    injector = Injector(bus=bus)
    captured = injector.capture_target()
    result = injector.inject("text", target_hwnd=captured)

    assert result.target_changed is True
    assert result.success is False
    mock_sendv.assert_not_called()
    mock_wm.assert_not_called()


def test_inject_emits_events(qtbot, mocker) -> None:
    mocker.patch("soyle.core.injector.pyperclip.copy")
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="")
    mocker.patch("soyle.core.injector.send_ctrl_v")
    mocker.patch("soyle.core.injector.send_wm_paste", return_value=False)
    mocker.patch("soyle.core.injector.find_edit_child", return_value=0)
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch("soyle.core.injector.get_window_class_name", return_value="Chrome_WidgetWin_1")

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
        "soyle.core.injector.pyperclip.copy",
        side_effect=lambda s: captured_copy.append(s),
    )
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="")
    mocker.patch("soyle.core.injector.send_ctrl_v")
    mocker.patch("soyle.core.injector.send_wm_paste", return_value=False)
    mocker.patch("soyle.core.injector.find_edit_child", return_value=0)
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch("soyle.core.injector.get_window_class_name", return_value="Notepad")

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
        "soyle.core.injector.pyperclip.copy",
        side_effect=lambda s: captured_copy.append(s),
    )
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("soyle.core.injector.send_wm_paste", return_value=True)
    mocker.patch("soyle.core.injector.find_edit_child", return_value=0)
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "soyle.core.injector.get_window_class_name",
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
    mocker.patch("soyle.core.injector.pyperclip.copy")
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mocker.patch("soyle.core.injector.send_wm_paste", return_value=False)
    mocker.patch("soyle.core.injector.find_edit_child", return_value=0)
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "soyle.core.injector.get_window_class_name",
        return_value="CASCADIA_HOSTING_WINDOW_CLASS",
    )

    injector = Injector(bus=EventBus(), restore_delay_ms=10)
    result = injector.inject("whoami", target_hwnd=injector.capture_target())

    assert result.blocked is True
    mock_sendv.assert_not_called()


# ---- M1: keystroke method doesn't touch the clipboard ----

def test_keystroke_method_writes_text_without_clipboard(qtbot, mocker) -> None:
    mock_copy = mocker.patch("soyle.core.injector.pyperclip.copy")
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="secret")
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("soyle.core.injector.send_wm_paste")
    mock_write = mocker.patch("soyle.core.injector.keyboard.write")
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "soyle.core.injector.get_window_class_name",
        return_value="Chrome_WidgetWin_1",
    )

    injector = Injector(bus=EventBus(), method="keystroke")
    result = injector.inject("hello", target_hwnd=injector.capture_target())

    assert result.success is True
    assert result.method == "keystroke"
    mock_write.assert_called_once_with("hello", delay=0)
    mock_copy.assert_not_called()          # clipboard untouched
    mock_sendv.assert_not_called()
    mock_wm.assert_not_called()


def test_keystroke_method_still_honours_terminal_blocklist(qtbot, mocker) -> None:
    """Newlines typed into a terminal auto-execute just like a paste would."""
    mock_copy = mocker.patch("soyle.core.injector.pyperclip.copy")
    mock_write = mocker.patch("soyle.core.injector.keyboard.write")
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "soyle.core.injector.get_window_class_name",
        return_value="ConsoleWindowClass",
    )

    injector = Injector(bus=EventBus(), method="keystroke")
    result = injector.inject("rm -rf /\n", target_hwnd=injector.capture_target())

    assert result.blocked is True
    mock_write.assert_not_called()
    # Clipboard still receives the text (user can Ctrl+V manually if they
    # want) — blocklist is the same across both methods.
    mock_copy.assert_called_once()


def test_set_method_rejects_invalid_value() -> None:
    import pytest

    injector = Injector(bus=EventBus())
    with pytest.raises(ValueError):
        injector.set_method("telepathy")


# ---- M2: Tk auto-fallback — clipboard method auto-routes to keystroke
#         for widgets that ignore synthetic Ctrl+V (tkinter, customtkinter).

def test_clipboard_mode_auto_falls_back_to_keystroke_for_tk(qtbot, mocker) -> None:
    """`TkTopLevel` target → keystroke override fires; clipboard untouched.

    Regression — without this routing, customtkinter `CTkTextbox` widgets
    silently swallow synthetic Ctrl+V because `tkinter.Text` has no default
    `<Control-v>` binding. The user sees the textbox stay empty after a
    successful transcribe + polish, with no signal what went wrong.
    """
    mock_copy = mocker.patch("soyle.core.injector.pyperclip.copy")
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="prev")
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mock_wm = mocker.patch("soyle.core.injector.send_wm_paste")
    mock_write = mocker.patch("soyle.core.injector.keyboard.write")
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "soyle.core.injector.get_window_class_name", return_value="TkTopLevel"
    )

    injector = Injector(bus=EventBus(), method="clipboard")
    result = injector.inject("задача срочная", target_hwnd=injector.capture_target())

    # Routed through keystroke despite clipboard config:
    assert result.success is True
    assert result.method == "keystroke"
    mock_write.assert_called_once_with("задача срочная", delay=0)
    # Clipboard path never touched — the whole point of the auto-route:
    mock_copy.assert_not_called()
    mock_sendv.assert_not_called()
    mock_wm.assert_not_called()
    # User's persisted preference was NOT mutated — Settings UI still shows
    # "clipboard" correctly. The override is per-call routing only.
    assert injector._method == "clipboard"


def test_clipboard_mode_does_not_auto_route_for_normal_targets(qtbot, mocker) -> None:
    """Non-Tk target with clipboard mode → existing clipboard path still runs.

    Guards against a refactor that would turn the auto-route into a blanket
    "always keystroke" behavior.
    """
    mocker.patch("soyle.core.injector.pyperclip.copy")
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="prev")
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mocker.patch("soyle.core.injector.send_wm_paste", return_value=False)
    mocker.patch("soyle.core.injector.find_edit_child", return_value=0)
    mock_write = mocker.patch("soyle.core.injector.keyboard.write")
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "soyle.core.injector.get_window_class_name",
        return_value="Chrome_WidgetWin_1",
    )

    injector = Injector(bus=EventBus(), method="clipboard", restore_delay_ms=10)
    result = injector.inject("hello", target_hwnd=injector.capture_target())

    # Existing Ctrl+V path runs:
    assert result.success is True
    assert result.method == "paste"
    mock_sendv.assert_called_once()
    # No keystroke override:
    mock_write.assert_not_called()


def test_keystroke_mode_for_tk_target_runs_normally(qtbot, mocker) -> None:
    """Already-keystroke mode + Tk target → just keystroke, no override path.

    The auto-route code path is irrelevant when the user already chose
    keystroke globally — they'd just get keystroke twice if we weren't
    careful. Ensures the override only fires for `clipboard` callers.
    """
    mock_copy = mocker.patch("soyle.core.injector.pyperclip.copy")
    mock_write = mocker.patch("soyle.core.injector.keyboard.write")
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "soyle.core.injector.get_window_class_name", return_value="TkTopLevel"
    )

    injector = Injector(bus=EventBus(), method="keystroke")
    result = injector.inject("hi", target_hwnd=injector.capture_target())

    assert result.success is True
    assert result.method == "keystroke"
    mock_write.assert_called_once_with("hi", delay=0)
    mock_copy.assert_not_called()


def test_terminal_blocklist_priority_over_keystroke_auto_route(qtbot, mocker) -> None:
    """If a target somehow matches both lists, terminal block wins.

    Practically impossible (the lists don't overlap today) but guards
    against a future entry being added to both — terminal blocking exists
    because newlines auto-execute commands, which is strictly worse than a
    silent Tk paste failure. Order in `inject()` must keep terminal first.
    """
    mocker.patch("soyle.core.injector.pyperclip.copy")
    mocker.patch("soyle.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("soyle.core.injector.send_ctrl_v")
    mock_write = mocker.patch("soyle.core.injector.keyboard.write")
    mocker.patch("soyle.core.injector.get_foreground_hwnd", return_value=1234)
    mocker.patch(
        "soyle.core.injector.get_window_class_name",
        return_value="ConsoleWindowClass",
    )

    injector = Injector(bus=EventBus(), method="clipboard")
    result = injector.inject("echo hi\n", target_hwnd=injector.capture_target())

    # Terminal block wins — neither paste nor keystroke fires.
    assert result.blocked is True
    mock_sendv.assert_not_called()
    mock_write.assert_not_called()
