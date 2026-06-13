"""Tests for design tokens."""
from __future__ import annotations

from soyle.ui.theme.tokens import (
    DARK,
    LIGHT,
    STATE_ERROR,
    STATE_POLISHING,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
    Tokens,
    active_tokens,
    resolve_theme,
)


def test_light_and_dark_are_tokens() -> None:
    assert isinstance(LIGHT, Tokens)
    assert isinstance(DARK, Tokens)


def test_accent_is_indigo() -> None:
    assert LIGHT.accent == "#5b5bd6"
    assert DARK.accent == "#6d6df0"


def test_state_colors_single_sourced() -> None:
    # Painter widgets and tokens must agree on the dictation palette.
    assert LIGHT.state_recording == STATE_RECORDING
    assert LIGHT.state_transcribing == STATE_TRANSCRIBING
    assert LIGHT.state_polishing == STATE_POLISHING
    assert LIGHT.state_error == STATE_ERROR
    # DARK reuses the same module constants — checking one confirms the link.
    assert DARK.state_recording == STATE_RECORDING


def test_resolve_theme_passthrough() -> None:
    assert resolve_theme("light") == "light"
    assert resolve_theme("dark") == "dark"


def test_resolve_theme_unknown_defaults_dark() -> None:
    # No running QApplication in a headless test run → safe dark default.
    assert resolve_theme("nonsense") == "dark"
    assert resolve_theme("system") == "dark"


def test_active_tokens_maps_concrete_themes() -> None:
    assert active_tokens("light") is LIGHT
    assert active_tokens("dark") is DARK
