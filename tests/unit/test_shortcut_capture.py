"""Tests for qt_event_to_hotkey_string — the Qt→`keyboard` translator."""
from __future__ import annotations

from PySide6.QtCore import Qt

from whisperflow.ui.shortcut_capture import qt_event_to_hotkey_string


# Win32 VK codes used when the user presses a side-distinguished modifier.
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5


def _no_mod() -> int:
    return Qt.KeyboardModifier.NoModifier.value


def _ctrl_mod() -> int:
    return Qt.KeyboardModifier.ControlModifier.value


def test_right_alt_alone_accepted() -> None:
    name, err = qt_event_to_hotkey_string(
        int(Qt.Key.Key_Alt),
        Qt.KeyboardModifier.AltModifier.value,  # Alt is held (itself)
        VK_RMENU,
    )
    assert err is None
    assert name == "right alt"


def test_left_ctrl_alone_accepted() -> None:
    name, err = qt_event_to_hotkey_string(
        int(Qt.Key.Key_Control),
        Qt.KeyboardModifier.ControlModifier.value,
        VK_LCONTROL,
    )
    assert err is None
    assert name == "left ctrl"


def test_caps_lock_accepted() -> None:
    name, err = qt_event_to_hotkey_string(
        int(Qt.Key.Key_CapsLock),
        _no_mod(),
        0,
    )
    assert err is None
    assert name == "caps lock"


def test_f8_accepted() -> None:
    name, err = qt_event_to_hotkey_string(int(Qt.Key.Key_F8), _no_mod(), 0)
    assert err is None
    assert name == "f8"


def test_f12_accepted() -> None:
    name, err = qt_event_to_hotkey_string(int(Qt.Key.Key_F12), _no_mod(), 0)
    assert err is None
    assert name == "f12"


def test_modifier_plus_key_rejected() -> None:
    # Ctrl+P — combo not allowed for push-to-talk.
    name, err = qt_event_to_hotkey_string(
        int(Qt.Key.Key_P), _ctrl_mod(), 0
    )
    assert name is None
    assert err is not None
    assert "комбинация" in err.lower() or "одн" in err.lower()


def test_letter_alone_accepted() -> None:
    # A user could realistically bind "a" — weird UX but valid.
    name, err = qt_event_to_hotkey_string(int(Qt.Key.Key_A), _no_mod(), 0)
    assert err is None
    assert name == "a"


def test_digit_alone_accepted() -> None:
    name, err = qt_event_to_hotkey_string(int(Qt.Key.Key_5), _no_mod(), 0)
    assert err is None
    assert name == "5"


def test_unknown_key_rejected() -> None:
    # A random Qt key we don't map — e.g., Unknown itself.
    name, err = qt_event_to_hotkey_string(int(Qt.Key.Key_unknown), _no_mod(), 0)
    assert name is None
    assert err is not None


def test_modifier_without_native_vk_rejected() -> None:
    # Alt pressed but nativeVirtualKey doesn't match any known side code.
    name, err = qt_event_to_hotkey_string(
        int(Qt.Key.Key_Alt),
        Qt.KeyboardModifier.AltModifier.value,
        0x00,  # nonsense VK
    )
    assert name is None
    assert err is not None
    assert "модификатор" in err.lower()


def test_scroll_lock_accepted() -> None:
    name, err = qt_event_to_hotkey_string(int(Qt.Key.Key_ScrollLock), _no_mod(), 0)
    assert err is None
    assert name == "scroll lock"


def test_right_shift_accepted() -> None:
    name, err = qt_event_to_hotkey_string(
        int(Qt.Key.Key_Shift),
        Qt.KeyboardModifier.ShiftModifier.value,
        VK_RSHIFT,
    )
    assert err is None
    assert name == "right shift"
