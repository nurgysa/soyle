"""Tests for Config pydantic models."""
from __future__ import annotations

from pathlib import Path

import pytest

from soyle.core.config import (
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
    assert cfg.behavior.monthly_cost_limit_usd == 0.0  # disabled by default


def test_behavior_cost_limit_rejects_negative() -> None:
    with pytest.raises(ValueError):
        BehaviorConfig(monthly_cost_limit_usd=-1.0)


def test_config_store_is_first_run_when_file_missing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    assert not path.exists()
    store = ConfigStore(config_path=path)
    assert store.is_first_run is True
    # `load()` may create the file on first run — that must NOT flip the flag.
    store.load()
    assert store.is_first_run is True


def test_config_store_is_first_run_false_when_file_exists(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("version = 1\n", encoding="utf-8")
    store = ConfigStore(config_path=path)
    assert store.is_first_run is False


def test_hotkey_mode_validated() -> None:
    with pytest.raises(ValueError, match=r"push_to_talk|toggle"):
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


def test_audio_silence_threshold_default_and_validation() -> None:
    cfg = AudioConfig()
    assert cfg.silence_threshold_rms == 0.02

    # Reject below floor (would treat near-zero noise as speech)
    with pytest.raises(ValueError):
        AudioConfig(silence_threshold_rms=0.0)
    # Reject above ceiling (would drop normal speaking volume)
    with pytest.raises(ValueError):
        AudioConfig(silence_threshold_rms=0.5)
    # Accept realistic office-tightened value
    AudioConfig(silence_threshold_rms=0.05)


def test_audio_silence_threshold_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    store = ConfigStore(config_path=target)
    cfg = store.load()
    cfg.audio.silence_threshold_rms = 0.045
    store.save(cfg)

    reloaded = ConfigStore(config_path=target).load()
    assert reloaded.audio.silence_threshold_rms == 0.045


def test_postprocess_timeout_positive() -> None:
    with pytest.raises(ValueError):
        PostProcessConfig(timeout_seconds=0)


def test_postprocess_default_prompt_files() -> None:
    """Every supported mode must map to a default prompt-file name.

    Drift-guard: if a new mode is added without its prompt_file default,
    `app.py`'s `prompt_path(self._cfg.postprocess.<mode>_file)` lookup
    would crash at PostProcess construction.
    """
    cfg = PostProcessConfig()
    assert cfg.mode == "polish"
    assert cfg.prompt_file == "polish_v1.md"
    assert cfg.rewrite_prompt_file == "rewrite_v1.md"
    assert cfg.ai_prompt_file == "ai_prompt_v1.md"
    assert cfg.plain_text_file == "plain_text_v1.md"
    assert cfg.task_prompt_file == "task_v1.md"


def test_postprocess_mode_accepts_task() -> None:
    """`task` is a valid Literal value for the mode field."""
    cfg = PostProcessConfig(mode="task")
    assert cfg.mode == "task"


def test_postprocess_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        PostProcessConfig(mode="summarize")


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


def test_whisper_language_roundtrip_explicit_code(tmp_path: Path) -> None:
    """Forcing a language ('kk') must persist through save/reload."""
    target = tmp_path / "config.toml"
    store = ConfigStore(config_path=target)

    cfg = store.load()
    cfg.whisper.language = "kk"
    store.save(cfg)

    reloaded = ConfigStore(config_path=target).load()
    assert reloaded.whisper.language == "kk"


def test_whisper_language_roundtrip_auto_is_none(tmp_path: Path) -> None:
    """Auto-detect (None) round-trips through TOML (None values are omitted on
    write but reappear as None via the pydantic default)."""
    target = tmp_path / "config.toml"
    store = ConfigStore(config_path=target)

    cfg = store.load()
    cfg.whisper.language = None
    store.save(cfg)

    reloaded = ConfigStore(config_path=target).load()
    assert reloaded.whisper.language is None


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


def test_set_and_get_api_key(mocker) -> None:
    mock_keyring = mocker.patch("soyle.core.config.keyring")
    store = ConfigStore(config_path=Path("/tmp/doesnt_matter"))

    store.set_api_key("sk-or-v1-abcdef")
    mock_keyring.set_password.assert_called_once_with(
        "Söyle", "openrouter", "sk-or-v1-abcdef"
    )

    mock_keyring.get_password.return_value = "sk-or-v1-abcdef"
    assert store.get_api_key() == "sk-or-v1-abcdef"


def test_get_api_key_returns_none_when_missing(mocker) -> None:
    mock_keyring = mocker.patch("soyle.core.config.keyring")
    mock_keyring.get_password.return_value = None

    store = ConfigStore(config_path=Path("/tmp/doesnt_matter"))
    assert store.get_api_key() is None


def test_clear_api_key(mocker) -> None:
    mock_keyring = mocker.patch("soyle.core.config.keyring")
    store = ConfigStore(config_path=Path("/tmp/doesnt_matter"))

    store.clear_api_key()
    mock_keyring.delete_password.assert_called_once_with("Söyle", "openrouter")
