"""Design tokens — the single source of visual constants.

Qt QSS has no variables, so tokens live here in Python and are rendered
into a stylesheet by ``soyle.ui.theme.qss.render_qss``. The dictation-state
colors are module constants so the painter widgets (indicator, floating
button) and the rendered QSS reference one palette.
"""
from __future__ import annotations

from dataclasses import dataclass

# Canonical dictation-state palette (same in light and dark for now).
STATE_RECORDING = "#e74c3c"
STATE_TRANSCRIBING = "#f39c12"
STATE_POLISHING = "#3498db"
STATE_ERROR = "#95a5a6"
STATE_DONE = "#1d9e75"  # teal-green success, readable on both themes


@dataclass(frozen=True)
class Tokens:
    bg_base: str
    bg_surface: str
    bg_elevated: str
    text_primary: str
    text_secondary: str
    text_tertiary: str
    border_default: str
    border_strong: str
    accent: str
    accent_hover: str
    accent_text: str
    state_recording: str
    state_transcribing: str
    state_polishing: str
    state_error: str
    radius_sm: int
    radius_md: int
    radius_lg: int
    space_sm: int
    space_md: int
    font_family: str
    font_size_base: int
    font_size_small: int


LIGHT = Tokens(
    bg_base="#fafafa",
    bg_surface="#ffffff",
    bg_elevated="#ffffff",  # same as bg_surface; light theme stays flat for now
    text_primary="#1a1a1a",
    text_secondary="#555555",
    text_tertiary="#8a8a8a",
    border_default="#e2e2e6",
    border_strong="#c8c8cc",
    accent="#5b5bd6",
    accent_hover="#4a4ac4",
    accent_text="#ffffff",
    state_recording=STATE_RECORDING,
    state_transcribing=STATE_TRANSCRIBING,
    state_polishing=STATE_POLISHING,
    state_error=STATE_ERROR,
    radius_sm=4,
    radius_md=6,
    radius_lg=10,
    space_sm=6,
    space_md=12,
    font_family="Segoe UI",
    font_size_base=13,
    font_size_small=11,
)

DARK = Tokens(
    bg_base="#1a1a1e",
    bg_surface="#202027",
    bg_elevated="#26262d",
    text_primary="#e8e8ee",
    text_secondary="#b0b0b8",
    text_tertiary="#8a8a94",
    border_default="#2c2c33",
    border_strong="#3a3a42",
    accent="#6d6df0",
    accent_hover="#7f7ff5",
    accent_text="#ffffff",
    state_recording=STATE_RECORDING,
    state_transcribing=STATE_TRANSCRIBING,
    state_polishing=STATE_POLISHING,
    state_error=STATE_ERROR,
    radius_sm=4,
    radius_md=6,
    radius_lg=10,
    space_sm=6,
    space_md=12,
    font_family="Segoe UI",
    font_size_base=13,
    font_size_small=11,
)


def resolve_theme(theme: str) -> str:
    """Map a config theme value to a concrete ``"light"`` or ``"dark"``.

    ``"system"`` (or any unexpected value) queries the OS color scheme via
    Qt; with no running app or an unknown scheme, defaults to ``"dark"``.
    """
    if theme in ("light", "dark"):
        return theme
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if isinstance(app, QGuiApplication):
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
    return "dark"


def active_tokens(theme: str) -> Tokens:
    """Return the token set for the (possibly ``"system"``) theme value."""
    return DARK if resolve_theme(theme) == "dark" else LIGHT
