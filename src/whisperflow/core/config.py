"""Configuration models and persistence."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import tomli
import tomli_w
from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class HotkeyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    combination: str = "right alt"
    mode: Literal["push_to_talk", "toggle"] = "push_to_talk"
    debounce_ms: int = Field(default=150, ge=0, le=1000)


class AudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str = "default"
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    vad_enabled: bool = True
    vad_min_speech_ms: int = Field(default=300, ge=0)
    max_recording_seconds: int = Field(default=90, gt=0, le=600)


class WhisperConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "large-v3-turbo"
    device: Literal["auto", "cuda", "cpu"] = "auto"
    compute_type: Literal["int8", "float16", "float32"] = "int8"
    beam_size: int = Field(default=5, ge=1, le=10)
    language: str | None = None


class PostProcessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: Literal["openrouter"] = "openrouter"
    model: str = "google/gemini-2.5-flash-lite"
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    retries: int = Field(default=3, ge=0, le=10)
    temperature: float = Field(default=0.0, ge=0, le=2)
    prompt_file: str = "polish_v1.md"


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_position: Literal["cursor", "tray_only"] = "cursor"
    indicator_follow_mouse: bool = True
    theme: Literal["dark", "light", "system"] = "dark"
    sound_enabled: bool = True


class BehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autostart: bool = False
    check_updates: bool = True
    log_transcriptions: bool = False
    inject_method: Literal["clipboard", "keystroke"] = "clipboard"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    postprocess: PostProcessConfig = Field(default_factory=PostProcessConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)


APP_NAME = "WhisperFlow"


def default_config_path() -> Path:
    """Return %APPDATA%\\WhisperFlow\\config.toml on Windows."""
    return user_config_path(APP_NAME, appauthor=False, roaming=True) / "config.toml"


class ConfigStore:
    """Load/save Config from TOML file with broken-file recovery."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = config_path or default_config_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Config:
        if not self._path.exists():
            cfg = Config()
            self._ensure_parent()
            self._write(cfg)
            return cfg

        try:
            raw = tomli.loads(self._path.read_text(encoding="utf-8"))
            return Config.model_validate(raw)
        except (tomli.TOMLDecodeError, ValidationError):
            self._backup_broken()
            cfg = Config()
            self._write(cfg)
            return cfg

    def save(self, config: Config) -> None:
        self._ensure_parent()
        self._write(config)

    def reset_to_defaults(self) -> Config:
        if self._path.exists():
            self._backup_broken()
        cfg = Config()
        self._write(cfg)
        return cfg

    # --- internals ---

    def _ensure_parent(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _backup_broken(self) -> None:
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
        backup = self._path.with_suffix(f".toml.broken-{ts}")
        self._path.rename(backup)

    def _write(self, config: Config) -> None:
        # TOML has no null; omit None values so fields like whisper.language
        # (Optional[str]) round-trip cleanly when unset.
        data = config.model_dump(mode="json", exclude_none=True)
        with self._path.open("wb") as f:
            tomli_w.dump(data, f)
