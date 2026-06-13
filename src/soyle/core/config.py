"""Configuration models and persistence."""
from __future__ import annotations

import contextlib
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import keyring
import tomli_w
from platformdirs import user_config_path
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError


class HotkeyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    combination: str = "right alt"
    mode: Literal["push_to_talk", "toggle"] = "push_to_talk"
    debounce_ms: int = Field(default=150, ge=0, le=1000)


class AudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str = "default"
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    # When True, trim leading/trailing audio frames quieter than
    # silence_threshold_rms before sending to Whisper. Tightens the
    # "endpoints" of the recording — useful when colleagues speak nearby
    # while you start/end your push-to-talk press.
    vad_enabled: bool = True
    silence_threshold_rms: float = Field(default=0.02, ge=0.001, le=0.2)
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
    # Five LLM modes — each loads its own prompt file from prompts/:
    #   - 'polish'     : conservative — strip fillers, fix punctuation, keep structure.
    #   - 'rewrite'    : active — reformulate dictation into a well-formed sentence.
    #   - 'ai_prompt'  : turn dictation into a clean instruction for an LLM
    #                    (Claude / ChatGPT / Gemini). Imperative, structured,
    #                    preserves code/file paths verbatim.
    #   - 'plain_text' : turn dictation into clean prose for documents (Word,
    #                    email). Natural paragraphs, no instruction language.
    #   - 'task'       : turn dictation into a structured 4-field task
    #                    (Задача / Департамент / Приоритет / Описание) for
    #                    pasting into a tracker (Jira, Linear, Notion).
    mode: Literal["polish", "rewrite", "ai_prompt", "plain_text", "task"] = "polish"
    prompt_file: str = "polish_v1.md"
    rewrite_prompt_file: str = "rewrite_v1.md"
    ai_prompt_file: str = "ai_prompt_v1.md"
    plain_text_file: str = "plain_text_v1.md"
    task_prompt_file: str = "task_v1.md"


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_position: Literal["cursor", "tray_only"] = "cursor"
    indicator_follow_mouse: bool = True
    theme: Literal["dark", "light", "system"] = "dark"
    # UI language. "system" resolves to ru/kk/en from the OS locale at
    # startup. Stored locally (like `theme`); not synced via Cloud Sync.
    language: Literal["system", "ru", "kk", "en"] = "system"
    sound_enabled: bool = True
    # Phase A: always-visible floating mic pill in bottom-right corner.
    # Mouse press-and-hold = PTT alternative to Right Alt. Phase B will
    # repurpose this widget to anchor near focused text fields (Wispr-style).
    show_floating_button: bool = True


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


class CloudSyncConfig(BaseModel):
    """Per-device cloud sync state.

    Currently single-field: timestamp of the last successful sync. Used by
    CloudSync.should_run_scheduled() to determine whether the 24h interval
    has elapsed. Stored on disk so it survives Söyle restarts.

    Per-device by design — two devices syncing the same Drive folder run
    their 24h schedule independently, so each tracks its own clock locally.
    Schema enforces timezone-aware datetimes (`AwareDatetime`) so naive
    datetimes are rejected at validation time, not silently accepted to
    explode later in `now() - last_synced_at` arithmetic.
    """
    model_config = ConfigDict(extra="forbid")

    last_synced_at: AwareDatetime | None = None


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    postprocess: PostProcessConfig = Field(default_factory=PostProcessConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    cloud_sync: CloudSyncConfig = Field(default_factory=CloudSyncConfig)


# Two names because of the umlaut: APP_NAME is the user-facing brand,
# APP_SLUG is the ASCII filesystem-safe form used for paths and any place
# CLI tooling (cd, gpresult, dir) might trip on a non-ASCII path.
APP_NAME = "Söyle"
APP_SLUG = "Soyle"


def default_config_path() -> Path:
    """Return %APPDATA%\\Soyle\\config.toml on Windows."""
    return user_config_path(APP_SLUG, appauthor=False, roaming=True) / "config.toml"


class ConfigStore:
    """Load/save Config from TOML file with broken-file recovery."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = config_path or default_config_path()
        # Snapshot existence BEFORE any load() call can create the file —
        # used by the UI to trigger the first-run wizard. A second
        # ConfigStore constructed later will report is_first_run=False
        # because by then load() has written the default config.
        self._existed_at_init = self._path.exists()
        self._push_hook: Callable[[], None] | None = None

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

    def save(self, config: Config, *, _bypass_hook: bool = False) -> None:
        """Persist `config` to disk.

        If a push hook is registered, fire it after the write — unless
        `_bypass_hook=True` (used by internal sync metadata writes like
        `last_synced_at` updates to avoid an infinite debounced-push
        loop; see codex P1 fix on PR #30).
        """
        self._ensure_parent()
        self._write(config)
        if self._push_hook is not None and not _bypass_hook:
            self._push_hook()

    def mtime(self) -> datetime:
        """Config file's modified time as aware UTC datetime.

        Used by CloudSync to compare local vs Drive modifiedTime when
        deciding push-vs-pull direction. Raises FileNotFoundError if the
        config has never been written.
        """
        stat = self._path.stat()
        return datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    def apply_synced_overrides(self, remote: Config) -> None:
        """Replace on-disk config with `remote`, then trigger any push
        hook just like a normal save would.

        Called by CloudSync after a successful pull. `remote` already
        has deny-list paths overlaid from local by `_merge_config`, so
        writing it verbatim is safe — no further merging at this layer.
        """
        self.save(remote)

    def set_push_hook(self, hook: Callable[[], None] | None) -> None:
        """Register a callable invoked synchronously at the end of every
        save(). Used by CloudSync to schedule a debounced push after the
        user changes settings. Pass None to clear."""
        self._push_hook = hook

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
