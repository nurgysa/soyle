"""Configuration models and persistence."""
from __future__ import annotations

import contextlib
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import keyring
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
    # CTranslate2-supported compute types; see
    # https://opennmt.net/CTranslate2/quantization.html
    compute_type: Literal[
        "default",
        "auto",
        "int8",
        "int8_float32",
        "int8_float16",
        "int8_bfloat16",
        "int16",
        "float16",
        "bfloat16",
        "float32",
    ] = "int8"
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
    # Two LLM modes:
    #   - 'polish'  : conservative — strip fillers, fix punctuation, keep structure
    #   - 'rewrite' : active       — reformulate into a well-formed sentence
    # Each mode loads its own prompt file from prompts/.
    mode: Literal["polish", "rewrite"] = "polish"
    rewrite_prompt_file: str = "rewrite_v1.md"


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
    # Monthly spend cap in USD. 0 disables the warning. When a polished
    # request pushes the month total over this value, a warning toast is
    # shown once — subsequent requests in the same month are silent.
    monthly_cost_limit_usd: float = Field(default=0.0, ge=0.0)


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
        # Snapshot existence BEFORE any load() call can create the file —
        # used by the UI to trigger the first-run wizard. A second
        # ConfigStore constructed later will report is_first_run=False
        # because by then load() has written the default config.
        self._existed_at_init = self._path.exists()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_first_run(self) -> bool:
        """True if config.toml did not exist when this store was constructed."""
        return not self._existed_at_init

    def load(self) -> Config:
        if not self._path.exists():
            cfg = Config()
            self._ensure_parent()
            self._write(cfg)
            return cfg

        try:
            raw = tomllib.loads(self._path.read_text(encoding="utf-8"))
            return Config.model_validate(raw)
        except (tomllib.TOMLDecodeError, ValidationError):
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
        # Defend against symlink attack: a local attacker who can write in
        # the parent dir could plant a symlink pointing elsewhere and
        # trick us into renaming an unrelated file. We own this directory,
        # so a symlink here is always unexpected — unlink and move on.
        if self._path.is_symlink():
            self._path.unlink()
            return
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
        backup = self._path.with_suffix(f".toml.broken-{ts}")
        self._path.rename(backup)

    def _write(self, config: Config) -> None:
        # TOML has no null; omit None values so fields like whisper.language
        # (Optional[str]) round-trip cleanly when unset.
        data = config.model_dump(mode="json", exclude_none=True)
        with self._path.open("wb") as f:
            tomli_w.dump(data, f)

    # --- API key management ---

    KEYRING_SERVICE = APP_NAME
    KEYRING_USERNAME = "openrouter"

    def get_api_key(self) -> str | None:
        return keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)

    def set_api_key(self, key: str) -> None:
        keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME, key)

    def clear_api_key(self) -> None:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)
