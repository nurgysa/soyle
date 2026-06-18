"""Tests for Config pydantic models."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from soyle.core.config import (
    AudioConfig,
    BehaviorConfig,
    CloudSyncConfig,
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


def test_ui_show_floating_button_default_true() -> None:
    """Phase A default — pill is visible on first launch so users discover it."""
    cfg = Config()
    assert cfg.ui.show_floating_button is True


def test_ui_show_floating_button_roundtrips_via_toml(tmp_path: Path) -> None:
    """User-disabled state survives save/reload."""
    target = tmp_path / "config.toml"
    store = ConfigStore(config_path=target)
    cfg = store.load()
    cfg.ui.show_floating_button = False
    store.save(cfg)

    reloaded = ConfigStore(config_path=target).load()
    assert reloaded.ui.show_floating_button is False


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


def test_cloud_sync_config_defaults() -> None:
    cfg = CloudSyncConfig()
    assert cfg.last_synced_at is None


def test_config_has_cloud_sync_section() -> None:
    cfg = Config()
    assert cfg.cloud_sync is not None
    assert cfg.cloud_sync.last_synced_at is None


def test_cloud_sync_last_synced_at_roundtrips_via_toml(tmp_path: Path) -> None:
    """Datetime survives TOML save/load round-trip."""
    path = tmp_path / "config.toml"
    store = ConfigStore(config_path=path)
    cfg = store.load()
    when = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
    cfg.cloud_sync.last_synced_at = when
    store.save(cfg)

    reloaded = ConfigStore(config_path=path).load()
    assert reloaded.cloud_sync.last_synced_at == when
    assert reloaded.cloud_sync.last_synced_at.tzinfo is not None  # NEW


def test_cloud_sync_config_rejects_unknown_field() -> None:
    """extra='forbid' contract per other config sections."""
    with pytest.raises(ValueError):
        CloudSyncConfig(unknown_field=42)


def test_cloud_sync_config_rejects_naive_datetime() -> None:
    """Naive datetimes (no tzinfo) must fail validation, not silently propagate."""
    naive = datetime(2026, 4, 30, 12, 0, 0)  # no tzinfo
    with pytest.raises(ValueError):
        CloudSyncConfig(last_synced_at=naive)


# ---- Phase 2: Cloud sync push-hook + apply_synced_overrides ----


def test_mtime_returns_timezone_aware_utc_datetime(tmp_path: Path) -> None:
    """mtime() reads file's modified time as aware UTC datetime."""
    path = tmp_path / "config.toml"
    path.write_text("version = 1\n", encoding="utf-8")
    store = ConfigStore(config_path=path)

    result = store.mtime()
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)


def test_mtime_raises_when_file_does_not_exist(tmp_path: Path) -> None:
    """Calling mtime() before any save() raises FileNotFoundError."""
    store = ConfigStore(config_path=tmp_path / "missing.toml")
    with pytest.raises(FileNotFoundError):
        store.mtime()


def test_apply_synced_overrides_writes_remote_config(tmp_path: Path) -> None:
    """apply_synced_overrides persists the remote Config verbatim."""
    path = tmp_path / "config.toml"
    store = ConfigStore(config_path=path)
    _ = store.load()

    remote = Config()
    remote.hotkey.combination = "ctrl+shift"
    remote.postprocess.mode = "rewrite"

    store.apply_synced_overrides(remote)

    reloaded = ConfigStore(config_path=path).load()
    assert reloaded.hotkey.combination == "ctrl+shift"
    assert reloaded.postprocess.mode == "rewrite"


def test_save_invokes_push_hook_when_registered(tmp_path: Path) -> None:
    """set_push_hook + save → hook called once."""
    store = ConfigStore(config_path=tmp_path / "config.toml")
    calls: list[int] = []
    store.set_push_hook(lambda: calls.append(1))

    cfg = store.load()
    cfg.hotkey.combination = "ctrl+alt"
    store.save(cfg)

    assert calls == [1]


def test_save_does_not_invoke_push_hook_when_not_registered(
    tmp_path: Path,
) -> None:
    """save() without a push hook works as before (no AttributeError)."""
    store = ConfigStore(config_path=tmp_path / "config.toml")
    cfg = store.load()
    cfg.hotkey.combination = "ctrl+alt"
    store.save(cfg)

    reloaded = ConfigStore(config_path=tmp_path / "config.toml").load()
    assert reloaded.hotkey.combination == "ctrl+alt"


def test_save_bypass_hook_skips_registered_hook(tmp_path: Path) -> None:
    """Codex P1 fix on PR #30: internal sync-metadata writes pass
    _bypass_hook=True so they don't re-arm the debounced push timer."""
    store = ConfigStore(config_path=tmp_path / "config.toml")
    calls: list[int] = []
    store.set_push_hook(lambda: calls.append(1))

    cfg = store.load()
    cfg.hotkey.combination = "ctrl+alt"
    store.save(cfg, _bypass_hook=True)

    assert calls == []  # hook NOT fired
    # On-disk write still happened
    reloaded = ConfigStore(config_path=tmp_path / "config.toml").load()
    assert reloaded.hotkey.combination == "ctrl+alt"


def test_save_bypass_hook_is_per_call_not_sticky(tmp_path: Path) -> None:
    """The bypass is per-call, not a global mode — a subsequent regular
    save() still fires the hook."""
    store = ConfigStore(config_path=tmp_path / "config.toml")
    calls: list[int] = []
    store.set_push_hook(lambda: calls.append(1))

    cfg = store.load()
    store.save(cfg, _bypass_hook=True)   # bypassed
    store.save(cfg)                       # not bypassed
    store.save(cfg, _bypass_hook=True)   # bypassed again

    assert calls == [1]  # exactly one regular save fired the hook


def test_ui_language_default_is_system() -> None:
    assert UIConfig().language == "system"


def test_ui_language_accepts_supported() -> None:
    for lang in ("system", "ru", "kk", "en"):
        assert UIConfig(language=lang).language == lang


def test_ui_language_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        UIConfig(language="fr")


def test_history_enabled_defaults_true_and_round_trips(tmp_path: Path) -> None:
    store = ConfigStore(config_path=tmp_path / "config.toml")
    cfg = store.load()
    assert cfg.ui.history_enabled is True

    cfg.ui.history_enabled = False
    store.save(cfg)
    assert store.load().ui.history_enabled is False
