"""Tests for QSS rendering from tokens."""
from __future__ import annotations

from soyle.ui.theme.qss import render_qss
from soyle.ui.theme.tokens import DARK, LIGHT


def test_render_contains_accent_hex() -> None:
    assert LIGHT.accent in render_qss(LIGHT)


def test_render_has_core_selectors() -> None:
    css = render_qss(LIGHT)
    assert "QPushButton" in css
    assert "QTabBar::tab" in css
    assert "QLineEdit" in css


def test_primary_button_uses_accent_fill() -> None:
    css = render_qss(DARK)
    assert "QPushButton#primary" in css
    assert DARK.accent in css


def test_light_and_dark_differ() -> None:
    assert render_qss(LIGHT) != render_qss(DARK)
