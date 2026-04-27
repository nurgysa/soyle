"""Tests for resource paths."""
from __future__ import annotations

from soyle.ui.resources import asset_path, prompt_path, qss_path


def test_asset_path_returns_file_under_package() -> None:
    p = asset_path("icon.ico")
    assert p.parent.name == "assets"


def test_prompt_path_returns_file_under_prompts() -> None:
    p = prompt_path("polish_v1.md")
    assert p.exists()
    assert p.parent.name == "prompts"


def test_qss_path_returns_theme_file() -> None:
    p = qss_path("dark")
    assert str(p).endswith("dark.qss")
