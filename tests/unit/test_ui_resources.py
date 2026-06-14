"""Tests for resource paths."""
from __future__ import annotations

from soyle.ui.resources import asset_path, prompt_path


def test_asset_path_returns_file_under_package() -> None:
    p = asset_path("icon.ico")
    assert p.parent.name == "assets"


def test_prompt_path_returns_file_under_prompts() -> None:
    p = prompt_path("polish_v1.md")
    assert p.exists()
    assert p.parent.name == "prompts"


def test_i18n_path_returns_file_under_i18n() -> None:
    from soyle.ui.resources import i18n_path

    p = i18n_path("soyle_kk.qm")
    assert p.parent.name == "i18n"
    assert str(p).endswith("soyle_kk.qm")
