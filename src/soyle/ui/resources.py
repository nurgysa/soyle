"""Resource-path helpers; works in both dev and PyInstaller bundles."""
from __future__ import annotations

import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Package root; PyInstaller overrides via sys._MEIPASS."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def asset_path(name: str) -> Path:
    return _bundle_root() / "assets" / name


def prompt_path(name: str) -> Path:
    return _bundle_root() / "prompts" / name


def qss_path(theme: str) -> Path:
    return _bundle_root() / "ui" / "qss" / f"{theme}.qss"
