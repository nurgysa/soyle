"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixture_dir() -> Path:
    """Path to tests/fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def audio_fixture_dir(fixture_dir: Path) -> Path:
    return fixture_dir / "audio"


@pytest.fixture
def config_fixture_dir(fixture_dir: Path) -> Path:
    return fixture_dir / "config"
