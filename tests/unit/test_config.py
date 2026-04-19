"""Tests for Config pydantic models."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from whisperflow.core.config import (
    AudioConfig,
    BehaviorConfig,
    Config,
    ConfigStore,
    HotkeyConfig,
    PostProcessConfig,
    UIConfig,
    WhisperConfig,
)


def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.version == 1
    assert cfg.hotkey.combination == "right alt"
    assert cfg.hotkey.mode == "push_to_talk"
    assert cfg.audio.sample_rate == 16000
    assert cfg.whisper.model == "large-v3-turbo"
    assert cfg.whisper.compute_type == "int8"
    assert cfg.postprocess.model == "google/gemini-2.5-flash-lite"
    assert cfg.postprocess.enabled is True
    assert cfg.ui.theme == "dark"
    assert cfg.behavior.autostart is False
    assert cfg.behavior.log_transcriptions is False


def test_hotkey_mode_validated() -> None:
    with pytest.raises(ValueError, match="push_to_talk|toggle"):
        HotkeyConfig(mode="invalid")


def test_whisper_device_validated() -> None:
    with pytest.raises(ValueError):
        WhisperConfig(device="tpu")


def test_whisper_compute_type_validated() -> None:
    with pytest.raises(ValueError):
        WhisperConfig(compute_type="fp64")


def test_ui_theme_validated() -> None:
    with pytest.raises(ValueError):
        UIConfig(theme="rainbow")


def test_inject_method_validated() -> None:
    with pytest.raises(ValueError):
        BehaviorConfig(inject_method="telepathy")


def test_audio_max_recording_positive() -> None:
    with pytest.raises(ValueError):
        AudioConfig(max_recording_seconds=-1)


def test_postprocess_timeout_positive() -> None:
    with pytest.raises(ValueError):
        PostProcessConfig(timeout_seconds=0)


def test_configstore_loads_valid_toml(tmp_path: Path, config_fixture_dir: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_bytes((config_fixture_dir / "valid.toml").read_bytes())

    store = ConfigStore(config_path=target)
    cfg = store.load()

    assert cfg.hotkey.mode == "toggle"
    assert cfg.hotkey.combination == "ctrl+alt+space"
    assert cfg.whisper.device == "cuda"
    assert cfg.ui.sound_enabled is False


def test_configstore_creates_default_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    store = ConfigStore(config_path=target)

    cfg = store.load()

    assert target.exists()
    assert cfg.version == 1
    assert cfg.hotkey.combination == "right alt"


def test_configstore_recovers_from_broken(tmp_path: Path, config_fixture_dir: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_bytes((config_fixture_dir / "broken.toml").read_bytes())

    store = ConfigStore(config_path=target)
    cfg = store.load()

    assert cfg.version == 1  # defaults
    # broken file backed up
    backups = list(tmp_path.glob("config.toml.broken-*"))
    assert len(backups) == 1


def test_configstore_save_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    store = ConfigStore(config_path=target)

    cfg = store.load()
    cfg.hotkey.combination = "f12"
    cfg.whisper.beam_size = 7
    store.save(cfg)

    reloaded = ConfigStore(config_path=target).load()
    assert reloaded.hotkey.combination == "f12"
    assert reloaded.whisper.beam_size == 7


def test_configstore_rejects_unknown_field(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text(
        "version = 1\n[hotkey]\nweird_field = 42\ncombination = 'right alt'\n",
        encoding="utf-8",
    )
    store = ConfigStore(config_path=target)
    cfg = store.load()
    # extra=forbid causes validation error → fallback to defaults + backup
    assert cfg.hotkey.combination == "right alt"
    backups = list(tmp_path.glob("config.toml.broken-*"))
    assert len(backups) == 1
