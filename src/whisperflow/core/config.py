"""Configuration models and persistence."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
