"""Tests for language resolution and translator installation."""
from __future__ import annotations

from PySide6.QtCore import QLocale

from soyle.ui.i18n import SUPPORTED, resolve_language


def test_explicit_values_pass_through() -> None:
    for lang in ("ru", "kk", "en"):
        assert resolve_language(lang) == lang


def test_system_maps_russian_locale() -> None:
    loc = QLocale(QLocale.Language.Russian)
    assert resolve_language("system", loc) == "ru"


def test_system_maps_kazakh_locale() -> None:
    loc = QLocale(QLocale.Language.Kazakh)
    assert resolve_language("system", loc) == "kk"


def test_system_unknown_locale_falls_back_to_en() -> None:
    loc = QLocale(QLocale.Language.French)
    assert resolve_language("system", loc) == "en"


def test_supported_languages() -> None:
    assert SUPPORTED == ("ru", "kk", "en")
