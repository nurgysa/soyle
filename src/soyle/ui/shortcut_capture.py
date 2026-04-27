"""Shortcut capture — dialog that lets the user press their desired
push-to-talk key instead of typing its name.

The translator `qt_event_to_hotkey_string()` is the testable core: it
maps a Qt keyPressEvent (virtual key + modifiers + native Win32 VK)
to the string format the `keyboard` library understands for
`keyboard.hook_key()`.

Push-to-talk requires a SINGLE key — combinations like Ctrl+P are
rejected because `keyboard.hook_key` doesn't support them and the
hold-to-record semantics are undefined for multi-key presses.
"""
from __future__ import annotations

from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# Win32 VK codes that distinguish left/right-side modifier keys.
# Qt's `event.key()` collapses both sides to the same Qt.Key_*, so
# these native codes are the only way to tell them apart on Windows.
_VK_LSHIFT: Final = 0xA0
_VK_RSHIFT: Final = 0xA1
_VK_LCONTROL: Final = 0xA2
_VK_RCONTROL: Final = 0xA3
_VK_LMENU: Final = 0xA4
_VK_RMENU: Final = 0xA5
_VK_LWIN: Final = 0x5B
_VK_RWIN: Final = 0x5C

_VK_TO_NAME: Final = {
    _VK_LSHIFT: "left shift",
    _VK_RSHIFT: "right shift",
    _VK_LCONTROL: "left ctrl",
    _VK_RCONTROL: "right ctrl",
    _VK_LMENU: "left alt",
    _VK_RMENU: "right alt",
    _VK_LWIN: "left windows",
    _VK_RWIN: "right windows",
}

# Standalone (non-modifier) keys that make sense as PTT triggers.
_QT_KEY_TO_NAME: Final = {
    Qt.Key.Key_CapsLock: "caps lock",
    Qt.Key.Key_ScrollLock: "scroll lock",
    Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "page up",
    Qt.Key.Key_PageDown: "page down",
    Qt.Key.Key_Print: "print screen",
    Qt.Key.Key_Menu: "menu",
}

_MODIFIER_KEYS: Final = frozenset({
    Qt.Key.Key_Shift,
    Qt.Key.Key_Control,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
})


def qt_event_to_hotkey_string(
    qt_key: int,
    modifiers: int,
    native_vkey: int,
) -> tuple[str | None, str | None]:
    """Translate a Qt keyPressEvent into a `keyboard` library hotkey name.

    Returns ``(name, error)``. On success, ``name`` is the string passed
    verbatim to ``keyboard.hook_key``. On failure, ``error`` holds a
    user-facing message explaining why the key wasn't accepted.
    """
    # In PySide6 the Qt.KeyboardModifier enum doesn't int-coerce
    # directly — use `.value` to stay in the int domain.
    mod_mask = (
        Qt.KeyboardModifier.ControlModifier.value
        | Qt.KeyboardModifier.AltModifier.value
        | Qt.KeyboardModifier.ShiftModifier.value
        | Qt.KeyboardModifier.MetaModifier.value
    )
    any_modifier_held = bool(modifiers & mod_mask)

    # Case 1: the user pressed ONLY a modifier — "right alt" style PTT.
    if qt_key in _MODIFIER_KEYS:
        name = _VK_TO_NAME.get(native_vkey)
        if name is None:
            return None, "Не удалось определить сторону клавиши-модификатора"
        return name, None

    # Case 2: modifier(s) + regular key — reject. hook_key is single-key only.
    if any_modifier_held:
        return None, (
            "Нужна одна клавиша, не комбинация. "
            "Например: Right Alt, Caps Lock, F8"
        )

    # Case 3: function keys F1–F24
    if Qt.Key.Key_F1 <= qt_key <= Qt.Key.Key_F35:
        fn_num = int(qt_key) - int(Qt.Key.Key_F1) + 1
        if 1 <= fn_num <= 24:
            return f"f{fn_num}", None

    # Case 4: curated list of standalone special keys
    if qt_key in _QT_KEY_TO_NAME:
        return _QT_KEY_TO_NAME[qt_key], None

    # Case 5: regular letter/digit keys — allowed but unusual (they'd
    # eat normal typing). Let the user set them if they want.
    if Qt.Key.Key_A <= qt_key <= Qt.Key.Key_Z:
        return chr(qt_key).lower(), None
    if Qt.Key.Key_0 <= qt_key <= Qt.Key.Key_9:
        return chr(qt_key), None

    return None, "Эта клавиша не поддерживается как хоткей"


class ShortcutCaptureDialog(QDialog):
    """Modal dialog: 'Нажмите клавишу…' → captured hotkey string."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Запись хоткея")
        self.setModal(True)
        self.setMinimumWidth(360)

        self._label = QLabel(
            "Нажмите одну клавишу для push-to-talk\n"
            "(например, Right Alt, Caps Lock, F8)"
        )
        self._error = QLabel("")
        self._error.setStyleSheet("color: #e74c3c;")
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._error)
        layout.addWidget(self._buttons)

        self._captured: str = ""

    @property
    def captured(self) -> str:
        return self._captured

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        # Intercept everything except Escape (close) so that pressing a
        # modifier doesn't get consumed by Qt's default focus handling.
        if event.key() == Qt.Key.Key_Escape:
            super().keyPressEvent(event)
            return

        # `event.modifiers()` in PySide6 returns a QFlags wrapper; `.value`
        # unwraps to a plain int matching the translator's expectations.
        name, error = qt_event_to_hotkey_string(
            int(event.key()),
            event.modifiers().value,
            int(event.nativeVirtualKey()),
        )
        if error:
            self._captured = ""
            self._error.setText(f"⚠ {error}")
            self._label.setText("Попробуйте снова…")
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        else:
            assert name is not None
            self._captured = name
            self._error.setText("")
            self._label.setText(f"Записано: {name}\nЕсли верно — нажмите OK.")
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

        event.accept()
