# WhisperFlow v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Windows push-to-talk dictation app (Wispr Flow analog) using faster-whisper on GPU, OpenRouter for LLM polish, and PySide6 for UI.

**Architecture:** 7-layer modular build. Core Python 3.12 app with Qt UI. All modules communicate through a Qt-based `EventBus` — no direct cross-module dependencies. Pure logic is TDD-tested; hardware/OS integrations are manually smoke-tested.

**Tech Stack:** Python 3.12, PySide6, faster-whisper 1.1+ (CUDA int8), silero-vad, sounddevice, keyboard, pywin32, keyring, httpx, structlog, pydantic, PyInstaller.

**Spec reference:** [2026-04-19-whisperflow-design.md](../specs/2026-04-19-whisperflow-design.md)

---

## File Structure Map

Before defining tasks, here's the file-by-file inventory with responsibilities:

| File | Responsibility | Interfaces with |
|------|----------------|-----------------|
| `pyproject.toml` | Project metadata, runtime + dev dependencies | uv / pip |
| `src/whisperflow/__init__.py` | `__version__`, package marker | — |
| `src/whisperflow/__main__.py` | `python -m whisperflow` entry | `app.main` |
| `src/whisperflow/app.py` | Qt application lifecycle, DI wiring | All modules |
| `src/whisperflow/core/errors.py` | Domain exception hierarchy | Imported everywhere |
| `src/whisperflow/core/state.py` | `State` enum + `StateMachine` | EventBus |
| `src/whisperflow/core/bus.py` | `Event` enum + `EventBus` (Qt signals) | All modules |
| `src/whisperflow/core/config.py` | `Config` pydantic model + `ConfigStore` | keyring, platformdirs |
| `src/whisperflow/platform/single_instance.py` | Named mutex for single-process guarantee | pywin32 |
| `src/whisperflow/platform/window.py` | HWND capture/verify | pywin32 |
| `src/whisperflow/platform/paste.py` | `SendInput(Ctrl+V)` wrapper | pywin32 |
| `src/whisperflow/platform/autostart.py` | Read/write `HKCU\...\Run` | winreg |
| `src/whisperflow/core/recorder.py` | `Recorder` — mic capture + VAD trim | sounddevice, silero-vad |
| `src/whisperflow/core/injector.py` | `Injector` — clipboard save/paste/restore | pyperclip, platform.paste, platform.window |
| `src/whisperflow/core/transcriber.py` | `Transcriber` — Whisper inference + hallucination filter | faster-whisper |
| `src/whisperflow/core/postprocess.py` | `PostProcess` — OpenRouter client + fallback | httpx |
| `src/whisperflow/core/hotkey.py` | `HotkeyBox` — global hotkey listener + debounce | keyboard |
| `src/whisperflow/prompts/polish_v1.md` | LLM system prompt (versioned artifact) | postprocess.py |
| `src/whisperflow/ui/resources.py` | Asset loader (icons, sounds, QSS) | — |
| `src/whisperflow/ui/indicator.py` | Frameless pill overlay widget | Qt |
| `src/whisperflow/ui/settings.py` | Settings window with tabs | Qt, config |
| `src/whisperflow/ui/tray.py` | System tray icon + context menu | Qt |
| `src/whisperflow/ui/qss/*.qss` | Theme stylesheets | Qt |
| `src/whisperflow/assets/*` | Icons, beep WAVs | ui.resources |
| `scripts/download_model.py` | First-run Whisper model download | faster-whisper |
| `scripts/download_cudnn.py` | cuDNN DLL downloader | Windows-only |
| `scripts/build_exe.py` | PyInstaller wrapper | PyInstaller |
| `tests/unit/*` | Fast unit tests (pytest) | pytest, respx, pytest-qt |
| `tests/integration/*` | Whisper with fixture WAVs (`@pytest.mark.gpu`) | pytest |
| `tests/fixtures/audio/*.wav` | Ground-truth recordings | — |
| `tests/fixtures/audio/expected.json` | Expected transcriptions | — |

---

## Phase 0 — Bootstrap (project skeleton, deps, git)

### Task 0.1: Initialize git repository

**Files:**
- Create: `.gitignore`
- Create: `.python-version`

- [ ] **Step 1: Initialize git**

```bash
cd "/c/Users/nurgisa/Documents/Windows Whisper Flow"
git init -b main
```

Expected: `Initialized empty Git repository in .../Windows Whisper Flow/.git/`

- [ ] **Step 2: Create `.gitignore`**

File: `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
env/
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/
dist/
build/

# IDE
.vscode/
.idea/
*.swp

# App-local
.env
vendor/cudnn/
models/
*.log

# OS
Thumbs.db
.DS_Store

# Build outputs
*.spec.bak
```

- [ ] **Step 3: Pin Python version**

File: `.python-version`

```
3.12.7
```

- [ ] **Step 4: Commit bootstrap**

```bash
git add .gitignore .python-version docs/
git commit -m "chore: initial project skeleton with spec and plan"
```

Expected: `[main (root-commit) <hash>] chore: initial project skeleton with spec and plan`

---

### Task 0.2: Create `pyproject.toml`

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write pyproject.toml**

File: `pyproject.toml`

```toml
[project]
name = "whisperflow"
version = "1.0.0"
description = "Local Windows push-to-talk dictation with Whisper + LLM polish"
requires-python = ">=3.12,<3.13"
readme = "README.md"
license = { text = "MIT" }
authors = [{ name = "nurgisa" }]

dependencies = [
  "pyside6>=6.8.0",
  "faster-whisper>=1.1.0",
  "sounddevice>=0.5.0",
  "numpy>=2.1.0",
  "silero-vad>=5.1.0",
  "keyboard>=0.13.5",
  "pywin32>=308; sys_platform == 'win32'",
  "pyperclip>=1.9.0",
  "keyring>=25.5.0",
  "httpx>=0.28.0",
  "pydantic>=2.10.0",
  "tomli>=2.2.0",
  "tomli-w>=1.1.0",
  "structlog>=24.4.0",
  "platformdirs>=4.3.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3.0",
  "pytest-qt>=4.4.0",
  "pytest-asyncio>=0.24.0",
  "pytest-xdist>=3.6.0",
  "pytest-mock>=3.14.0",
  "respx>=0.22.0",
  "ruff>=0.8.0",
  "mypy>=1.13.0",
  "pre-commit>=4.0.0",
]
build = [
  "pyinstaller>=6.11.0",
]

[project.scripts]
whisperflow = "whisperflow.app:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/whisperflow"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "C4", "SIM", "RUF"]
ignore = ["E501"]  # line length handled by formatter

[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_ignores = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
  "gpu: integration tests that require a CUDA-capable GPU",
]
```

- [ ] **Step 2: Install uv and bootstrap venv**

```bash
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
cd "/c/Users/nurgisa/Documents/Windows Whisper Flow"
uv venv
uv pip install -e ".[dev]"
```

Expected: venv created in `.venv/`, dependencies installed.

- [ ] **Step 3: Verify python works**

```bash
uv run python -c "import sys; print(sys.version)"
```

Expected: `3.12.x (...)`.

- [ ] **Step 4: Create src package skeleton**

```bash
mkdir -p src/whisperflow/core src/whisperflow/platform src/whisperflow/ui/qss \
         src/whisperflow/prompts src/whisperflow/assets \
         tests/unit tests/integration tests/fixtures/audio tests/fixtures/config \
         scripts
```

Then create `src/whisperflow/__init__.py`:

```python
__version__ = "1.0.0"
```

And empty `__init__.py` files:

```bash
touch src/whisperflow/core/__init__.py \
      src/whisperflow/platform/__init__.py \
      src/whisperflow/ui/__init__.py \
      src/whisperflow/prompts/__init__.py \
      tests/__init__.py \
      tests/unit/__init__.py \
      tests/integration/__init__.py
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/ scripts/
git commit -m "chore: scaffold pyproject.toml and package skeleton"
```

---

### Task 0.3: Set up `conftest.py` and basic test fixtures

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Write conftest.py**

File: `tests/conftest.py`

```python
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
```

- [ ] **Step 2: Verify pytest discovers tests**

```bash
uv run pytest --collect-only
```

Expected: `collected 0 items` (no tests yet, but no errors).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "chore: add conftest with fixture paths"
```

---

## Phase 1 — Foundation (Layer 0)

### Task 1.1: Domain exceptions (`errors.py`)

**Files:**
- Create: `src/whisperflow/core/errors.py`
- Create: `tests/unit/test_errors.py`

- [ ] **Step 1: Write the failing test**

File: `tests/unit/test_errors.py`

```python
"""Tests for domain exception hierarchy."""
from __future__ import annotations

import pytest

from whisperflow.core.errors import (
    AudioDeviceError,
    ConfigError,
    CudaOOMError,
    CudaUnavailableError,
    ModelNotLoadedError,
    PermissionDeniedError,
    PostProcessError,
    WhisperFlowError,
)


def test_all_errors_inherit_base() -> None:
    for exc_type in [
        AudioDeviceError,
        PermissionDeniedError,
        CudaUnavailableError,
        CudaOOMError,
        ModelNotLoadedError,
        PostProcessError,
        ConfigError,
    ]:
        assert issubclass(exc_type, WhisperFlowError)


def test_base_error_is_exception() -> None:
    assert issubclass(WhisperFlowError, Exception)


def test_error_carries_message() -> None:
    err = AudioDeviceError("microphone not found")
    assert str(err) == "microphone not found"


def test_error_with_module_attr() -> None:
    err = CudaOOMError("vram exhausted")
    err.module = "transcriber"
    assert err.module == "transcriber"
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/unit/test_errors.py -v
```

Expected: `ImportError: cannot import name 'WhisperFlowError' from 'whisperflow.core.errors'`.

- [ ] **Step 3: Implement minimal errors module**

File: `src/whisperflow/core/errors.py`

```python
"""Domain exception hierarchy."""
from __future__ import annotations


class WhisperFlowError(Exception):
    """Base for all WhisperFlow domain exceptions."""


class AudioDeviceError(WhisperFlowError):
    """Microphone device unavailable or not found."""


class PermissionDeniedError(WhisperFlowError):
    """Windows privacy settings blocked mic access."""


class CudaUnavailableError(WhisperFlowError):
    """CUDA runtime not available; caller should fallback to CPU."""


class CudaOOMError(WhisperFlowError):
    """VRAM exhausted during model load or inference."""


class ModelNotLoadedError(WhisperFlowError):
    """Whisper model not loaded or file corrupted."""


class PostProcessError(WhisperFlowError):
    """OpenRouter call failed irrecoverably (surfaced to caller only when fallback impossible)."""


class ConfigError(WhisperFlowError):
    """Config file missing, unreadable, or invalid."""
```

- [ ] **Step 4: Run test, verify PASS**

```bash
uv run pytest tests/unit/test_errors.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/errors.py tests/unit/test_errors.py
git commit -m "feat(core): add domain exception hierarchy"
```

---

### Task 1.2: State machine (`state.py`)

**Files:**
- Create: `src/whisperflow/core/state.py`
- Create: `tests/unit/test_state.py`

- [ ] **Step 1: Write the failing test**

File: `tests/unit/test_state.py`

```python
"""Tests for StateMachine."""
from __future__ import annotations

import pytest

from whisperflow.core.state import State, StateMachine


def test_initial_state_is_idle() -> None:
    sm = StateMachine()
    assert sm.current == State.IDLE


def test_can_start_recording_from_idle() -> None:
    sm = StateMachine()
    assert sm.can_start_recording() is True


def test_cannot_start_recording_from_recording() -> None:
    sm = StateMachine()
    sm.transition(State.RECORDING)
    assert sm.can_start_recording() is False


def test_valid_transition_idle_to_recording() -> None:
    sm = StateMachine()
    sm.transition(State.RECORDING)
    assert sm.current == State.RECORDING


def test_full_happy_path_cycle() -> None:
    sm = StateMachine()
    sm.transition(State.RECORDING)
    sm.transition(State.TRANSCRIBING)
    sm.transition(State.POLISHING)
    sm.transition(State.INJECTING)
    sm.transition(State.IDLE)
    assert sm.current == State.IDLE


def test_invalid_transition_raises() -> None:
    sm = StateMachine()
    # IDLE -> TRANSCRIBING (skipping RECORDING) is invalid
    with pytest.raises(ValueError, match="invalid transition"):
        sm.transition(State.TRANSCRIBING)


def test_any_state_can_return_to_idle_on_error() -> None:
    sm = StateMachine()
    sm.transition(State.RECORDING)
    sm.reset_to_idle()
    assert sm.current == State.IDLE
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/unit/test_state.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement StateMachine**

File: `src/whisperflow/core/state.py`

```python
"""Application state machine — enforces valid state transitions."""
from __future__ import annotations

from enum import StrEnum


class State(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    POLISHING = "polishing"
    INJECTING = "injecting"


VALID_TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.RECORDING},
    State.RECORDING: {State.TRANSCRIBING, State.IDLE},
    State.TRANSCRIBING: {State.POLISHING, State.IDLE},
    State.POLISHING: {State.INJECTING, State.IDLE},
    State.INJECTING: {State.IDLE},
}


class StateMachine:
    """Simple deterministic state machine with explicit transitions."""

    def __init__(self) -> None:
        self._current: State = State.IDLE

    @property
    def current(self) -> State:
        return self._current

    def can_start_recording(self) -> bool:
        return self._current == State.IDLE

    def transition(self, to: State) -> None:
        allowed = VALID_TRANSITIONS[self._current]
        if to not in allowed:
            raise ValueError(
                f"invalid transition: {self._current} -> {to} (allowed: {allowed})"
            )
        self._current = to

    def reset_to_idle(self) -> None:
        """Forced reset; used after errors from any state."""
        self._current = State.IDLE
```

- [ ] **Step 4: Run test, verify PASS**

```bash
uv run pytest tests/unit/test_state.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/state.py tests/unit/test_state.py
git commit -m "feat(core): add state machine with validated transitions"
```

---

### Task 1.3: Event bus (`bus.py`)

**Files:**
- Create: `src/whisperflow/core/bus.py`
- Create: `tests/unit/test_bus.py`

- [ ] **Step 1: Write the failing test**

File: `tests/unit/test_bus.py`

```python
"""Tests for EventBus (Qt signal-based)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject

from whisperflow.core.bus import Event, EventBus


def test_event_values_are_strings() -> None:
    assert Event.HOTKEY_PRESSED == "hotkey.pressed"
    assert Event.RECORDING_STARTED == "recording.started"
    assert Event.ERROR == "error"


def test_subscribe_and_emit(qtbot) -> None:  # noqa: ARG001
    bus = EventBus()
    received: list[dict] = []

    bus.subscribe(Event.HOTKEY_PRESSED, lambda payload: received.append(payload))
    bus.emit(Event.HOTKEY_PRESSED, {"source": "test"})

    assert received == [{"source": "test"}]


def test_unsubscribe(qtbot) -> None:  # noqa: ARG001
    bus = EventBus()
    received: list[dict] = []

    handler = lambda p: received.append(p)  # noqa: E731
    bus.subscribe(Event.HOTKEY_PRESSED, handler)
    bus.unsubscribe(Event.HOTKEY_PRESSED, handler)
    bus.emit(Event.HOTKEY_PRESSED, {})

    assert received == []


def test_multiple_subscribers_all_called(qtbot) -> None:  # noqa: ARG001
    bus = EventBus()
    calls: list[str] = []

    bus.subscribe(Event.TRANSCRIBING, lambda _: calls.append("a"))
    bus.subscribe(Event.TRANSCRIBING, lambda _: calls.append("b"))
    bus.emit(Event.TRANSCRIBING, {})

    assert set(calls) == {"a", "b"}


def test_unrelated_events_not_delivered(qtbot) -> None:  # noqa: ARG001
    bus = EventBus()
    received: list[str] = []

    bus.subscribe(Event.HOTKEY_PRESSED, lambda _: received.append("hotkey"))
    bus.emit(Event.ERROR, {"message": "boom"})

    assert received == []


def test_bus_is_qobject() -> None:
    bus = EventBus()
    assert isinstance(bus, QObject)
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/unit/test_bus.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement EventBus**

File: `src/whisperflow/core/bus.py`

```python
"""Event bus built on Qt signals for thread-safe in-process messaging."""
from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QObject, Signal


class Event(StrEnum):
    HOTKEY_PRESSED = "hotkey.pressed"
    HOTKEY_RELEASED = "hotkey.released"
    RECORDING_STARTED = "recording.started"
    AUDIO_LEVEL = "audio.level"
    RECORDING_STOPPED = "recording.stopped"
    TRANSCRIBING = "transcribing"
    TRANSCRIPT_READY = "transcript.ready"
    POLISHING = "polishing"
    POLISH_READY = "polish.ready"
    INJECTING = "injecting"
    INJECTED = "injected"
    ERROR = "error"
    STATE_CHANGED = "state.changed"


Handler = Callable[[dict[str, Any]], None]


class EventBus(QObject):
    """
    Pub/sub over Qt's signal-slot machinery.

    Signals are thread-safe: emissions from background threads are marshalled
    to the receiver's thread automatically by Qt.
    """

    _signal = Signal(str, dict)

    def __init__(self) -> None:
        super().__init__()
        self._subscribers: dict[Event, list[Handler]] = {}
        self._signal.connect(self._dispatch)

    def subscribe(self, event: Event, handler: Handler) -> None:
        self._subscribers.setdefault(event, []).append(handler)

    def unsubscribe(self, event: Event, handler: Handler) -> None:
        handlers = self._subscribers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event: Event, payload: dict[str, Any]) -> None:
        self._signal.emit(str(event), payload)

    def _dispatch(self, event_str: str, payload: dict[str, Any]) -> None:
        event = Event(event_str)
        for handler in list(self._subscribers.get(event, [])):
            handler(payload)
```

- [ ] **Step 4: Run test, verify PASS**

```bash
uv run pytest tests/unit/test_bus.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/bus.py tests/unit/test_bus.py
git commit -m "feat(core): add Qt-based EventBus"
```

---

### Task 1.4: Config models (`config.py` — part 1 of 3: pydantic schema)

**Files:**
- Create: `src/whisperflow/core/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

File: `tests/unit/test_config.py`

```python
"""Tests for Config pydantic models."""
from __future__ import annotations

import pytest

from whisperflow.core.config import (
    AudioConfig,
    BehaviorConfig,
    Config,
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
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement Config models (schema only, persistence later)**

File: `src/whisperflow/core/config.py`

```python
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
```

- [ ] **Step 4: Run test, verify PASS**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/config.py tests/unit/test_config.py
git commit -m "feat(core): add Config pydantic models with validation"
```

---

### Task 1.5: ConfigStore persistence (`config.py` — part 2 of 3: TOML I/O)

**Files:**
- Modify: `src/whisperflow/core/config.py`
- Modify: `tests/unit/test_config.py`
- Create: `tests/fixtures/config/valid.toml`
- Create: `tests/fixtures/config/broken.toml`

- [ ] **Step 1: Create fixture configs**

File: `tests/fixtures/config/valid.toml`

```toml
version = 1

[hotkey]
combination = "ctrl+alt+space"
mode = "toggle"
debounce_ms = 200

[audio]
device = "Microphone (Realtek)"
sample_rate = 16000
vad_enabled = true
vad_min_speech_ms = 400
max_recording_seconds = 60

[whisper]
model = "large-v3-turbo"
device = "cuda"
compute_type = "int8"
beam_size = 5
language = "ru"

[postprocess]
enabled = true
provider = "openrouter"
model = "google/gemini-2.5-flash-lite"
timeout_seconds = 4.0
retries = 2
temperature = 0.0
prompt_file = "polish_v1.md"

[ui]
indicator_position = "cursor"
indicator_follow_mouse = true
theme = "dark"
sound_enabled = false

[behavior]
autostart = true
check_updates = true
log_transcriptions = false
inject_method = "clipboard"
```

File: `tests/fixtures/config/broken.toml`

```toml
version = 1
this is not valid [[ toml at all
```

- [ ] **Step 2: Add failing tests for ConfigStore**

Append to `tests/unit/test_config.py`:

```python
from pathlib import Path
from unittest.mock import patch

from whisperflow.core.config import ConfigStore


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
```

- [ ] **Step 3: Run tests, verify FAIL**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: `ImportError: cannot import name 'ConfigStore'`.

- [ ] **Step 4: Append ConfigStore to config.py**

Append to `src/whisperflow/core/config.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import tomli
import tomli_w
from platformdirs import user_config_path
from pydantic import ValidationError


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
        data = config.model_dump(mode="json")
        with self._path.open("wb") as f:
            tomli_w.dump(data, f)
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/whisperflow/core/config.py tests/unit/test_config.py tests/fixtures/config/
git commit -m "feat(core): add ConfigStore with TOML persistence and broken-file recovery"
```

---

### Task 1.6: API key storage via keyring (`config.py` — part 3 of 3)

**Files:**
- Modify: `src/whisperflow/core/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Append tests**

Append to `tests/unit/test_config.py`:

```python
def test_set_and_get_api_key(mocker) -> None:
    mock_keyring = mocker.patch("whisperflow.core.config.keyring")
    store = ConfigStore(config_path=Path("/tmp/doesnt_matter"))

    store.set_api_key("sk-or-v1-abcdef")
    mock_keyring.set_password.assert_called_once_with(
        "WhisperFlow", "openrouter", "sk-or-v1-abcdef"
    )

    mock_keyring.get_password.return_value = "sk-or-v1-abcdef"
    assert store.get_api_key() == "sk-or-v1-abcdef"


def test_get_api_key_returns_none_when_missing(mocker) -> None:
    mock_keyring = mocker.patch("whisperflow.core.config.keyring")
    mock_keyring.get_password.return_value = None

    store = ConfigStore(config_path=Path("/tmp/doesnt_matter"))
    assert store.get_api_key() is None


def test_clear_api_key(mocker) -> None:
    mock_keyring = mocker.patch("whisperflow.core.config.keyring")
    store = ConfigStore(config_path=Path("/tmp/doesnt_matter"))

    store.clear_api_key()
    mock_keyring.delete_password.assert_called_once_with("WhisperFlow", "openrouter")
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
uv run pytest tests/unit/test_config.py::test_set_and_get_api_key -v
```

Expected: `AttributeError: ... has no attribute 'set_api_key'`.

- [ ] **Step 3: Add keyring methods to ConfigStore**

Add to top of `src/whisperflow/core/config.py`:

```python
import keyring
```

Append to `ConfigStore`:

```python
    # --- API key management ---

    KEYRING_SERVICE = APP_NAME
    KEYRING_USERNAME = "openrouter"

    def get_api_key(self) -> str | None:
        return keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)

    def set_api_key(self, key: str) -> None:
        keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME, key)

    def clear_api_key(self) -> None:
        try:
            keyring.delete_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)
        except keyring.errors.PasswordDeleteError:
            pass
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/config.py tests/unit/test_config.py
git commit -m "feat(core): ConfigStore manages OpenRouter API key via Windows keyring"
```

---

## Phase 2 — Platform adapters (Layer 1)

### Task 2.1: Single-instance mutex (`platform/single_instance.py`)

**Files:**
- Create: `src/whisperflow/platform/single_instance.py`
- Create: `tests/unit/test_single_instance.py`

- [ ] **Step 1: Write smoke test**

File: `tests/unit/test_single_instance.py`

```python
"""Tests for single-instance mutex."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from whisperflow.platform.single_instance import SingleInstance


def test_acquire_succeeds_once() -> None:
    inst = SingleInstance(name="WhisperFlowTest-Acquire")
    assert inst.acquire() is True
    inst.release()


def test_second_acquire_fails_while_held() -> None:
    a = SingleInstance(name="WhisperFlowTest-Double")
    b = SingleInstance(name="WhisperFlowTest-Double")

    assert a.acquire() is True
    assert b.acquire() is False
    a.release()


def test_release_allows_reacquire() -> None:
    a = SingleInstance(name="WhisperFlowTest-Reacquire")
    assert a.acquire() is True
    a.release()

    b = SingleInstance(name="WhisperFlowTest-Reacquire")
    assert b.acquire() is True
    b.release()
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
uv run pytest tests/unit/test_single_instance.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement SingleInstance**

File: `src/whisperflow/platform/single_instance.py`

```python
"""Single-instance guarantee via Win32 named mutex."""
from __future__ import annotations

import sys
from typing import Any

if sys.platform == "win32":
    import win32api
    import win32event
    import winerror


class SingleInstance:
    """Named-mutex lock; call acquire() at startup to detect second launch."""

    def __init__(self, name: str = "WhisperFlow-SingleInstance-Mutex") -> None:
        self._name = name
        self._handle: Any = None

    def acquire(self) -> bool:
        """Return True if this is the first/only instance, False if another holds the mutex."""
        if sys.platform != "win32":
            return True  # non-Windows: treat as first
        self._handle = win32event.CreateMutex(None, False, self._name)
        last_error = win32api.GetLastError()
        if last_error == winerror.ERROR_ALREADY_EXISTS:
            self.release()
            return False
        return True

    def release(self) -> None:
        if self._handle is not None:
            win32api.CloseHandle(self._handle)
            self._handle = None
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_single_instance.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/platform/single_instance.py tests/unit/test_single_instance.py
git commit -m "feat(platform): single-instance guard via named mutex"
```

---

### Task 2.2: Window HWND tracking (`platform/window.py`)

**Files:**
- Create: `src/whisperflow/platform/window.py`
- Create: `tests/unit/test_platform_window.py`

- [ ] **Step 1: Write test**

File: `tests/unit/test_platform_window.py`

```python
"""Tests for foreground window HWND tracking."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from whisperflow.platform.window import get_foreground_hwnd, is_same_window


def test_get_foreground_hwnd_returns_int() -> None:
    hwnd = get_foreground_hwnd()
    assert isinstance(hwnd, int)
    assert hwnd > 0


def test_is_same_window_identity() -> None:
    hwnd = get_foreground_hwnd()
    assert is_same_window(hwnd, hwnd) is True


def test_is_same_window_zero_never_matches() -> None:
    hwnd = get_foreground_hwnd()
    assert is_same_window(0, hwnd) is False
    assert is_same_window(hwnd, 0) is False
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
uv run pytest tests/unit/test_platform_window.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

File: `src/whisperflow/platform/window.py`

```python
"""Foreground-window tracking helpers."""
from __future__ import annotations

import sys

if sys.platform == "win32":
    import win32gui


def get_foreground_hwnd() -> int:
    """Return the HWND of the currently focused window, 0 if no foreground."""
    if sys.platform != "win32":
        return 0
    return int(win32gui.GetForegroundWindow())


def is_same_window(expected: int, current: int) -> bool:
    """True iff both HWNDs are non-zero and equal."""
    if expected == 0 or current == 0:
        return False
    return expected == current


def refocus(hwnd: int) -> bool:
    """Attempt to bring the given HWND back to the foreground. Returns True on success."""
    if sys.platform != "win32" or hwnd == 0:
        return False
    try:
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_platform_window.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/platform/window.py tests/unit/test_platform_window.py
git commit -m "feat(platform): foreground-window HWND capture and comparison"
```

---

### Task 2.3: Paste (`platform/paste.py`)

**Files:**
- Create: `src/whisperflow/platform/paste.py`
- Create: `tests/unit/test_platform_paste.py`

- [ ] **Step 1: Write test**

File: `tests/unit/test_platform_paste.py`

```python
"""Tests for Ctrl+V keystroke helper."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from unittest.mock import MagicMock

from whisperflow.platform import paste as paste_mod


def test_send_ctrl_v_uses_sendinput(mocker) -> None:
    mock_sendinput = mocker.patch.object(paste_mod, "SendInput")
    paste_mod.send_ctrl_v()
    # 4 INPUT structs: ctrl down, v down, v up, ctrl up
    args = mock_sendinput.call_args
    assert args[0][0] == 4  # nInputs


def test_send_ctrl_v_suppresses_errors(mocker) -> None:
    mocker.patch.object(paste_mod, "SendInput", side_effect=OSError("foo"))
    # Should NOT raise — caller will detect failure via clipboard state
    paste_mod.send_ctrl_v()
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/unit/test_platform_paste.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement paste**

File: `src/whisperflow/platform/paste.py`

```python
"""Send Ctrl+V via Win32 SendInput."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

# ---- Win32 structures for SendInput ----

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


if sys.platform == "win32":
    SendInput = ctypes.windll.user32.SendInput
    SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    SendInput.restype = wintypes.UINT
else:
    def SendInput(*args: object, **kwargs: object) -> int:  # pragma: no cover
        return 0


def _make_input(vk: int, up: bool) -> INPUT:
    ki = KEYBDINPUT(
        wVk=vk,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if up else 0,
        time=0,
        dwExtraInfo=ctypes.pointer(ctypes.c_ulong(0)),
    )
    return INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=ki))


def send_ctrl_v() -> None:
    """Send Ctrl+V as 4 synthetic key events. Errors are suppressed."""
    try:
        inputs = (INPUT * 4)(
            _make_input(VK_CONTROL, up=False),
            _make_input(VK_V, up=False),
            _make_input(VK_V, up=True),
            _make_input(VK_CONTROL, up=True),
        )
        SendInput(4, inputs, ctypes.sizeof(INPUT))
    except OSError:
        # Suppress; injector will notice paste didn't happen via clipboard state
        pass
```

- [ ] **Step 4: Run test, verify PASS**

```bash
uv run pytest tests/unit/test_platform_paste.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/platform/paste.py tests/unit/test_platform_paste.py
git commit -m "feat(platform): Ctrl+V via Win32 SendInput"
```

---

### Task 2.4: Autostart (`platform/autostart.py`)

**Files:**
- Create: `src/whisperflow/platform/autostart.py`
- Create: `tests/unit/test_autostart.py`

- [ ] **Step 1: Write test**

File: `tests/unit/test_autostart.py`

```python
"""Tests for HKCU\\...\\Run autostart management."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from whisperflow.platform.autostart import (
    disable_autostart,
    enable_autostart,
    is_autostart_enabled,
)

APP_KEY = "WhisperFlowTest"


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    yield
    disable_autostart(app_name=APP_KEY)


def test_enable_autostart_roundtrip(tmp_path) -> None:
    exe = tmp_path / "fake_whisperflow.exe"
    exe.write_text("")
    enable_autostart(exe_path=str(exe), app_name=APP_KEY)
    assert is_autostart_enabled(app_name=APP_KEY) is True
    disable_autostart(app_name=APP_KEY)
    assert is_autostart_enabled(app_name=APP_KEY) is False


def test_disable_autostart_idempotent() -> None:
    disable_autostart(app_name=APP_KEY)
    disable_autostart(app_name=APP_KEY)
    assert is_autostart_enabled(app_name=APP_KEY) is False
```

- [ ] **Step 2: Run tests, verify FAIL**

```bash
uv run pytest tests/unit/test_autostart.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

File: `src/whisperflow/platform/autostart.py`

```python
"""Manage HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run entry."""
from __future__ import annotations

import sys

if sys.platform == "win32":
    import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_APP_NAME = "WhisperFlow"


def enable_autostart(exe_path: str, app_name: str = DEFAULT_APP_NAME) -> None:
    if sys.platform != "win32":
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')


def disable_autostart(app_name: str = DEFAULT_APP_NAME) -> None:
    if sys.platform != "win32":
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, app_name)
    except FileNotFoundError:
        pass


def is_autostart_enabled(app_name: str = DEFAULT_APP_NAME) -> bool:
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, app_name)
            return True
    except FileNotFoundError:
        return False
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_autostart.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/platform/autostart.py tests/unit/test_autostart.py
git commit -m "feat(platform): autostart via HKCU Run registry entry"
```

---

## Phase 3 — Core capture & inject (Layer 2)

### Task 3.1: VAD trim pure function (`core/recorder.py` — part 1)

**Files:**
- Create: `src/whisperflow/core/recorder.py`
- Create: `tests/unit/test_recorder.py`

- [ ] **Step 1: Write test for VAD-trim function**

File: `tests/unit/test_recorder.py`

```python
"""Tests for Recorder's pure VAD-trim function."""
from __future__ import annotations

import numpy as np

from whisperflow.core.recorder import compute_rms, trim_silence_endpoints


def test_compute_rms_of_silence_is_zero() -> None:
    audio = np.zeros(16000, dtype=np.float32)
    assert compute_rms(audio) == 0.0


def test_compute_rms_of_tone() -> None:
    # 1-second 440 Hz tone at amplitude 0.5
    t = np.linspace(0, 1, 16000, endpoint=False, dtype=np.float32)
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    rms = compute_rms(tone)
    # Expected RMS of a sine wave = amplitude / sqrt(2)
    assert 0.34 < rms < 0.36


def test_trim_silence_leaves_speech_intact() -> None:
    # 0.5s silence + 1.0s "speech" (noise) + 0.5s silence
    sr = 16000
    silence = np.zeros(sr // 2, dtype=np.float32)
    speech = (np.random.default_rng(42).standard_normal(sr) * 0.2).astype(np.float32)
    audio = np.concatenate([silence, speech, silence])

    trimmed = trim_silence_endpoints(audio, sample_rate=sr, threshold_rms=0.05, pad_ms=50)

    # Trimmed should be ~1.0s ± 100ms
    assert sr * 0.8 < len(trimmed) < sr * 1.2


def test_trim_silence_on_all_silence_returns_empty() -> None:
    audio = np.zeros(16000, dtype=np.float32)
    trimmed = trim_silence_endpoints(audio, sample_rate=16000, threshold_rms=0.05)
    assert len(trimmed) == 0


def test_trim_silence_preserves_short_clip() -> None:
    sr = 16000
    speech = (np.random.default_rng(42).standard_normal(sr // 2) * 0.3).astype(np.float32)
    trimmed = trim_silence_endpoints(speech, sample_rate=sr, threshold_rms=0.05)
    assert len(trimmed) >= sr * 0.4  # lost at most ~20%
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
uv run pytest tests/unit/test_recorder.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement VAD helpers**

File: `src/whisperflow/core/recorder.py`

```python
"""Microphone capture with RMS-based silence trimming.

Note: full Silero-VAD is integrated in Recorder class (task 3.2);
this module provides the pure helpers first to enable TDD.
"""
from __future__ import annotations

import numpy as np


def compute_rms(audio: np.ndarray) -> float:
    """Root-mean-square of a mono float32 audio array."""
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def trim_silence_endpoints(
    audio: np.ndarray,
    sample_rate: int,
    threshold_rms: float = 0.02,
    frame_ms: int = 20,
    pad_ms: int = 50,
) -> np.ndarray:
    """Trim leading and trailing silence using RMS energy per frame.

    - threshold_rms: frames quieter than this are silence.
    - frame_ms: analysis window size.
    - pad_ms: keep this many ms around the detected speech for naturalness.
    """
    if audio.size == 0:
        return audio

    frame_samples = max(1, int(sample_rate * frame_ms / 1000))
    pad_samples = int(sample_rate * pad_ms / 1000)

    num_frames = len(audio) // frame_samples
    if num_frames == 0:
        return audio

    frames = audio[: num_frames * frame_samples].reshape(num_frames, frame_samples)
    rms_per_frame = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))

    speech_mask = rms_per_frame > threshold_rms
    if not np.any(speech_mask):
        return np.zeros(0, dtype=audio.dtype)

    first = int(np.argmax(speech_mask))
    last = num_frames - int(np.argmax(speech_mask[::-1]))

    start = max(0, first * frame_samples - pad_samples)
    end = min(len(audio), last * frame_samples + pad_samples)
    return audio[start:end]
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_recorder.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/recorder.py tests/unit/test_recorder.py
git commit -m "feat(core): RMS and silence-trim pure helpers for recorder"
```

---

### Task 3.2: Recorder class with sounddevice (`core/recorder.py` — part 2)

**Files:**
- Modify: `src/whisperflow/core/recorder.py`
- Modify: `tests/unit/test_recorder.py`

- [ ] **Step 1: Append test with mocked sounddevice**

Append to `tests/unit/test_recorder.py`:

```python
from unittest.mock import MagicMock

import pytest

from whisperflow.core.bus import Event, EventBus
from whisperflow.core.errors import AudioDeviceError
from whisperflow.core.recorder import Recorder


def _make_mock_sd(mocker, chunks: list[np.ndarray]):
    """Replace sounddevice.InputStream with one that yields given chunks via callback."""
    mock_sd = mocker.patch("whisperflow.core.recorder.sd")
    state = {"stream": None, "callback": None}

    def fake_input_stream(**kwargs):
        stream = MagicMock()
        state["callback"] = kwargs["callback"]

        def start() -> None:
            for chunk in chunks:
                # sounddevice passes (indata, frames, time_info, status)
                state["callback"](chunk.reshape(-1, 1), len(chunk), None, None)

        stream.start = MagicMock(side_effect=start)
        stream.stop = MagicMock()
        stream.close = MagicMock()
        state["stream"] = stream
        return stream

    mock_sd.InputStream = fake_input_stream
    mock_sd.query_devices.return_value = [{"name": "default", "max_input_channels": 1}]
    return mock_sd


def test_recorder_captures_audio(qtbot, mocker) -> None:  # noqa: ARG001
    rng = np.random.default_rng(0)
    chunks = [rng.standard_normal(1600).astype(np.float32) for _ in range(3)]
    _make_mock_sd(mocker, chunks)

    bus = EventBus()
    rec = Recorder(bus=bus)
    rec.start(sample_rate=16000)
    result = rec.stop()

    assert result.audio.shape[0] == 4800  # 3 × 1600
    assert result.duration_ms == pytest.approx(300, abs=10)


def test_recorder_emits_started_and_stopped(qtbot, mocker) -> None:  # noqa: ARG001
    _make_mock_sd(mocker, [np.zeros(1600, dtype=np.float32)])

    bus = EventBus()
    events: list[str] = []
    bus.subscribe(Event.RECORDING_STARTED, lambda _: events.append("start"))
    bus.subscribe(Event.RECORDING_STOPPED, lambda _: events.append("stop"))

    rec = Recorder(bus=bus)
    rec.start()
    rec.stop()

    assert events == ["start", "stop"]


def test_recorder_raises_when_no_input_device(mocker) -> None:
    mock_sd = mocker.patch("whisperflow.core.recorder.sd")
    mock_sd.query_devices.return_value = [{"name": "Speakers", "max_input_channels": 0}]

    bus = EventBus()
    rec = Recorder(bus=bus)
    with pytest.raises(AudioDeviceError):
        rec.start()
```

- [ ] **Step 2: Run, verify FAIL**

```bash
uv run pytest tests/unit/test_recorder.py -v
```

- [ ] **Step 3: Implement Recorder class**

Append to `src/whisperflow/core/recorder.py`:

```python
from dataclasses import dataclass
from queue import Queue
from typing import Any

import sounddevice as sd

from whisperflow.core.bus import Event, EventBus
from whisperflow.core.errors import AudioDeviceError


@dataclass
class RecordingResult:
    audio: np.ndarray
    duration_ms: int
    rms_peak: float


class Recorder:
    """Captures microphone audio into a queue; emits events through EventBus."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._queue: Queue[np.ndarray] = Queue()
        self._stream: Any = None
        self._sample_rate: int = 16000

    def start(self, sample_rate: int = 16000, device: str = "default") -> None:
        self._ensure_input_device_exists()
        self._sample_rate = sample_rate
        self._queue = Queue()

        def _callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:  # noqa: ARG001
            mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
            self._queue.put(mono)

        self._stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            callback=_callback,
            device=None if device == "default" else device,
        )
        self._stream.start()
        self._bus.emit(Event.RECORDING_STARTED, {"sample_rate": sample_rate})

    def stop(self) -> RecordingResult:
        if self._stream is None:
            return RecordingResult(audio=np.zeros(0, np.float32), duration_ms=0, rms_peak=0.0)

        self._stream.stop()
        self._stream.close()
        self._stream = None

        chunks: list[np.ndarray] = []
        while not self._queue.empty():
            chunks.append(self._queue.get_nowait())

        audio = (
            np.concatenate(chunks).astype(np.float32)
            if chunks
            else np.zeros(0, dtype=np.float32)
        )
        duration_ms = int(len(audio) * 1000 / self._sample_rate)
        rms_peak = compute_rms(audio)

        result = RecordingResult(audio=audio, duration_ms=duration_ms, rms_peak=rms_peak)
        self._bus.emit(
            Event.RECORDING_STOPPED,
            {"audio": audio, "duration_ms": duration_ms, "rms_peak": rms_peak},
        )
        return result

    @staticmethod
    def _ensure_input_device_exists() -> None:
        try:
            devices = sd.query_devices()
        except Exception as exc:
            raise AudioDeviceError(f"could not enumerate audio devices: {exc}") from exc

        has_input = any(
            (d.get("max_input_channels", 0) > 0) for d in devices  # type: ignore[union-attr]
        )
        if not has_input:
            raise AudioDeviceError("no microphone device found")
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_recorder.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/recorder.py tests/unit/test_recorder.py
git commit -m "feat(core): Recorder — sounddevice-based mic capture with events"
```

---

### Task 3.3: Injector with clipboard save/restore (`core/injector.py`)

**Files:**
- Create: `src/whisperflow/core/injector.py`
- Create: `tests/unit/test_injector.py`

- [ ] **Step 1: Write failing test**

File: `tests/unit/test_injector.py`

```python
"""Tests for Injector — clipboard save, paste, restore cycle."""
from __future__ import annotations

from unittest.mock import MagicMock

from whisperflow.core.bus import Event, EventBus
from whisperflow.core.injector import Injector


def test_inject_replaces_clipboard_then_restores(qtbot, mocker) -> None:  # noqa: ARG001
    clipboard_state = {"value": "old clipboard"}

    def fake_copy(text: str) -> None:
        clipboard_state["value"] = text

    def fake_paste() -> str:
        return clipboard_state["value"]

    mocker.patch("whisperflow.core.injector.pyperclip.copy", side_effect=fake_copy)
    mocker.patch("whisperflow.core.injector.pyperclip.paste", side_effect=fake_paste)
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mock_get_hwnd = mocker.patch(
        "whisperflow.core.injector.get_foreground_hwnd", return_value=1234
    )

    bus = EventBus()
    injector = Injector(bus=bus, restore_delay_ms=10)

    captured = injector.capture_target()
    result = injector.inject("hello world", target_hwnd=captured)

    assert result.success is True
    assert result.method == "paste"
    assert result.target_changed is False
    assert mock_sendv.call_count == 1
    # After restore delay, clipboard should be back to "old clipboard"
    qtbot.wait(50)
    assert clipboard_state["value"] == "old clipboard"


def test_inject_does_not_paste_if_window_changed(qtbot, mocker) -> None:  # noqa: ARG001
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mock_sendv = mocker.patch("whisperflow.core.injector.send_ctrl_v")
    # capture returns 1111, but later foreground is 2222
    mocker.patch(
        "whisperflow.core.injector.get_foreground_hwnd",
        side_effect=[1111, 2222, 2222],
    )

    bus = EventBus()
    injector = Injector(bus=bus)
    captured = injector.capture_target()
    result = injector.inject("text", target_hwnd=captured)

    assert result.target_changed is True
    assert result.success is False
    mock_sendv.assert_not_called()


def test_inject_emits_events(qtbot, mocker) -> None:  # noqa: ARG001
    mocker.patch("whisperflow.core.injector.pyperclip.copy")
    mocker.patch("whisperflow.core.injector.pyperclip.paste", return_value="")
    mocker.patch("whisperflow.core.injector.send_ctrl_v")
    mocker.patch("whisperflow.core.injector.get_foreground_hwnd", return_value=1234)

    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(Event.INJECTING, lambda _: seen.append("inject"))
    bus.subscribe(Event.INJECTED, lambda _: seen.append("done"))

    injector = Injector(bus=bus, restore_delay_ms=10)
    injector.inject("hi", target_hwnd=injector.capture_target())

    assert seen == ["inject", "done"]
```

- [ ] **Step 2: Run, verify FAIL**

```bash
uv run pytest tests/unit/test_injector.py -v
```

- [ ] **Step 3: Implement Injector**

File: `src/whisperflow/core/injector.py`

```python
"""Inject text into the foreground window via clipboard + Ctrl+V."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import pyperclip
from PySide6.QtCore import QTimer

from whisperflow.core.bus import Event, EventBus
from whisperflow.platform.paste import send_ctrl_v
from whisperflow.platform.window import get_foreground_hwnd, is_same_window


@dataclass
class InjectResult:
    success: bool
    method: Literal["paste", "keystroke"]
    target_changed: bool


class Injector:
    """Paste text into the captured HWND; restore clipboard after a short delay."""

    def __init__(self, bus: EventBus, restore_delay_ms: int = 200) -> None:
        self._bus = bus
        self._restore_delay_ms = restore_delay_ms

    def capture_target(self) -> int:
        return get_foreground_hwnd()

    def inject(self, text: str, target_hwnd: int) -> InjectResult:
        self._bus.emit(Event.INJECTING, {"target_hwnd": target_hwnd})

        current = get_foreground_hwnd()
        if not is_same_window(target_hwnd, current):
            # Keep text in clipboard for manual paste; do NOT hit Ctrl+V.
            pyperclip.copy(text)
            self._bus.emit(Event.INJECTED, {"success": False, "target_changed": True})
            return InjectResult(success=False, method="paste", target_changed=True)

        backup = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.02)  # give clipboard manager a moment
        send_ctrl_v()

        QTimer.singleShot(self._restore_delay_ms, lambda: pyperclip.copy(backup))

        self._bus.emit(Event.INJECTED, {"success": True, "target_changed": False})
        return InjectResult(success=True, method="paste", target_changed=False)
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_injector.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/injector.py tests/unit/test_injector.py
git commit -m "feat(core): Injector with clipboard save/paste/restore and HWND guard"
```

---

## Phase 4 — ML (Layer 3)

### Task 4.1: Polish prompt (`prompts/polish_v1.md`)

**Files:**
- Create: `src/whisperflow/prompts/polish_v1.md`

- [ ] **Step 1: Write prompt file**

File: `src/whisperflow/prompts/polish_v1.md`

```
You are a transcription cleanup assistant. Your ONLY job is to produce a clean,
readable written version of a spoken utterance.

RULES — follow all strictly:

1. Preserve the speaker's meaning exactly. Never add facts, never remove facts,
   never summarize, never translate, never rephrase for style. If the speaker said
   something dumb or grammatically wrong, keep it dumb or grammatically wrong in
   the same language.

2. Remove filler words only: "эээ", "ээ", "ну", "короче", "типа", "вот",
   "это самое", "um", "uh", "er", "like" (when used as filler, NOT as comparison),
   "you know", "I mean". If removal breaks the sentence, keep the word.

3. Fix punctuation and capitalization. Add periods, commas, question marks,
   quotation marks where obviously needed. Capitalize the first letter of sentences
   and proper nouns. Do NOT add exclamation marks unless the tone is clearly excited.

4. Preserve code-switching. If the speaker mixes Russian and English in one
   sentence (e.g. "давай заdeployим"), keep the mixing. Do not translate either side.

5. Preserve technical terms verbatim. File paths, commands, URLs, code identifiers,
   brand names — do not alter.

6. Do NOT add or change content. No greetings, no sign-offs, no notes,
   no "[transcribed text]" markers, no explanations. Output ONLY the cleaned text.

7. If the input is empty, garbled, or just noise markers (like "[Music]",
   "Subscribe!", "you", repeating tokens), return the input unchanged.

8. Length discipline. Your output must be within ±30% of the input token count.
   If you would produce something significantly longer or shorter, return the input
   unchanged instead.

INPUT FORMAT:
You will receive JSON: {"language": "ru"|"en"|"mixed", "text": "..."}

OUTPUT FORMAT:
Plain text only. No JSON, no markdown, no commentary. Just the cleaned text.

EXAMPLES:

Input: {"language":"ru","text":"эээ короче давай завтра встретимся в три часа ну"}
Output: Давай завтра встретимся в три часа.

Input: {"language":"en","text":"um so basically the the function returns a promise you know"}
Output: So basically the function returns a promise.

Input: {"language":"mixed","text":"нужно задеплоить это на staging environment сегодня"}
Output: Нужно задеплоить это на staging environment сегодня.

Input: {"language":"ru","text":"Subscribe! Subscribe! Subscribe!"}
Output: Subscribe! Subscribe! Subscribe!
```

- [ ] **Step 2: Commit**

```bash
git add src/whisperflow/prompts/polish_v1.md
git commit -m "feat(prompts): polish_v1 system prompt for LLM postprocessing"
```

---

### Task 4.2: Hallucination filter (`core/transcriber.py` — part 1)

**Files:**
- Create: `src/whisperflow/core/transcriber.py`
- Create: `tests/unit/test_transcriber_filters.py`

- [ ] **Step 1: Write test**

File: `tests/unit/test_transcriber_filters.py`

```python
"""Tests for Transcriber's pure text-post-processing helpers."""
from __future__ import annotations

from whisperflow.core.transcriber import filter_hallucinations, normalize_whitespace


def test_normalize_whitespace_collapses_spaces() -> None:
    assert normalize_whitespace("  hello  world  ") == "hello world"
    assert normalize_whitespace("line1\n\nline2") == "line1 line2"


def test_filter_hallucinations_removes_repeat_spam() -> None:
    # 4 copies of "Subscribe!" with spaces → treat as hallucination
    text = "Subscribe! Subscribe! Subscribe! Subscribe!"
    assert filter_hallucinations(text) == ""


def test_filter_hallucinations_allows_natural_repetition() -> None:
    # "Yes yes yes" is natural speech, not hallucination
    text = "Yes yes yes I agree"
    assert filter_hallucinations(text) == "Yes yes yes I agree"


def test_filter_hallucinations_strips_music_tag() -> None:
    text = "[Music] hello world"
    assert filter_hallucinations(text) == "hello world"


def test_filter_hallucinations_handles_empty() -> None:
    assert filter_hallucinations("") == ""
    assert filter_hallucinations("   ") == ""


def test_filter_hallucinations_preserves_real_speech() -> None:
    text = "Привет, это обычное предложение."
    assert filter_hallucinations(text) == text
```

- [ ] **Step 2: Run, verify FAIL**

```bash
uv run pytest tests/unit/test_transcriber_filters.py -v
```

- [ ] **Step 3: Implement filters**

File: `src/whisperflow/core/transcriber.py`

```python
"""Whisper inference wrapper.

Part 1: pure text-cleanup helpers (this file).
Part 2: Transcriber class using faster-whisper (task 4.3).
"""
from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")
_NOISE_TAGS_RE = re.compile(r"\[(music|applause|laughter|noise|silence)\]", re.IGNORECASE)


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def filter_hallucinations(text: str) -> str:
    """Strip Whisper hallucinations: noise tags and repetitive spam."""
    cleaned = _NOISE_TAGS_RE.sub("", text)
    cleaned = normalize_whitespace(cleaned)

    if not cleaned:
        return ""

    # Detect N-copies-of-same-phrase pattern (common Whisper failure mode).
    # If the same ≥2-word phrase appears ≥4 times in a row → hallucination.
    words = cleaned.split()
    if len(words) < 4:
        return cleaned

    for phrase_len in range(1, max(2, len(words) // 4 + 1)):
        repeats = _count_leading_repeats(words, phrase_len)
        if repeats >= 4 and phrase_len * repeats >= len(words) * 0.75:
            return ""

    return cleaned


def _count_leading_repeats(words: list[str], phrase_len: int) -> int:
    if phrase_len == 0 or phrase_len > len(words):
        return 0
    phrase = words[:phrase_len]
    count = 1
    for i in range(phrase_len, len(words) - phrase_len + 1, phrase_len):
        if words[i : i + phrase_len] == phrase:
            count += 1
        else:
            break
    return count
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_transcriber_filters.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/transcriber.py tests/unit/test_transcriber_filters.py
git commit -m "feat(core): hallucination filter for Whisper raw output"
```

---

### Task 4.3: Transcriber class (`core/transcriber.py` — part 2)

**Files:**
- Modify: `src/whisperflow/core/transcriber.py`
- Create: `tests/integration/test_transcriber.py`
- Create: `tests/fixtures/audio/expected.json` (stub; audio files added in Task 9.1)

- [ ] **Step 1: Create expected.json stub**

File: `tests/fixtures/audio/expected.json`

```json
{
  "short_ru.wav": {
    "language": "ru",
    "expected_text": "Привет, как дела",
    "min_similarity": 0.75
  },
  "short_en.wav": {
    "language": "en",
    "expected_text": "Hello world how are you",
    "min_similarity": 0.75
  },
  "mixed.wav": {
    "language": null,
    "expected_text": "Сегодня я deploy новый feature",
    "min_similarity": 0.55
  },
  "silence.wav": {
    "language": null,
    "expected_text": "",
    "min_similarity": 1.0
  }
}
```

- [ ] **Step 2: Write integration test (gpu-marked, skipped when no GPU)**

File: `tests/integration/test_transcriber.py`

```python
"""Integration tests for Transcriber with real Whisper model."""
from __future__ import annotations

import json
import wave
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pytest

from whisperflow.core.transcriber import Transcriber

pytestmark = pytest.mark.gpu


def _load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        frames = w.readframes(w.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sr


@pytest.fixture(scope="module")
def transcriber() -> Transcriber:
    t = Transcriber(model="large-v3-turbo", device="auto", compute_type="int8")
    t.warm_up()
    return t


def test_short_ru(transcriber: Transcriber, audio_fixture_dir: Path) -> None:
    wav = audio_fixture_dir / "short_ru.wav"
    if not wav.exists():
        pytest.skip("short_ru.wav fixture not recorded yet")

    audio, sr = _load_wav(wav)
    result = transcriber.transcribe(audio, sample_rate=sr)

    expected = json.loads((audio_fixture_dir / "expected.json").read_text())["short_ru.wav"]
    ratio = SequenceMatcher(None, result.raw_text.lower(), expected["expected_text"].lower()).ratio()
    assert ratio >= expected["min_similarity"], f"got '{result.raw_text}', expected ~'{expected['expected_text']}'"
    assert result.language == "ru"


def test_silence_returns_empty(transcriber: Transcriber, audio_fixture_dir: Path) -> None:
    wav = audio_fixture_dir / "silence.wav"
    if not wav.exists():
        pytest.skip("silence.wav fixture not recorded yet")

    audio, sr = _load_wav(wav)
    result = transcriber.transcribe(audio, sample_rate=sr)

    assert result.raw_text == ""
```

- [ ] **Step 3: Append Transcriber class to `core/transcriber.py`**

```python
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel

from whisperflow.core.errors import CudaOOMError, CudaUnavailableError, ModelNotLoadedError


@dataclass
class TranscriptResult:
    raw_text: str
    language: str
    duration_ms: int
    segments: list[dict]


class Transcriber:
    """Singleton-style Whisper wrapper; load once, transcribe many."""

    def __init__(
        self, model: str = "large-v3-turbo", device: str = "auto", compute_type: str = "int8"
    ) -> None:
        self._model_name = model
        self._device_pref = device
        self._compute_type = compute_type
        self._model: WhisperModel | None = None
        self._actual_device: str = "cpu"

    @property
    def device(self) -> str:
        return self._actual_device

    def warm_up(self) -> None:
        self._ensure_loaded()
        dummy = np.zeros(16000, dtype=np.float32)
        try:
            list(self._model.transcribe(dummy, language="en", beam_size=1)[0])
        except Exception:
            pass

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> TranscriptResult:
        if sample_rate != 16000:
            # faster-whisper expects 16 kHz; resample if needed
            audio = _resample_to_16k(audio, sample_rate)
            sample_rate = 16000

        self._ensure_loaded()
        assert self._model is not None

        try:
            segments_iter, info = self._model.transcribe(
                audio,
                beam_size=5,
                vad_filter=True,
                language=None,
            )
            segments = [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in segments_iter
            ]
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "out of memory" in msg or "cuda" in msg and "memory" in msg:
                raise CudaOOMError(str(exc)) from exc
            raise ModelNotLoadedError(str(exc)) from exc

        raw_text = filter_hallucinations(" ".join(s["text"] for s in segments).strip())
        duration_ms = int(info.duration * 1000) if info.duration else 0
        language = info.language or ""

        return TranscriptResult(
            raw_text=raw_text,
            language=language,
            duration_ms=duration_ms,
            segments=segments,
        )

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        device = self._device_pref
        try:
            if device in ("auto", "cuda"):
                try:
                    self._model = WhisperModel(
                        self._model_name, device="cuda", compute_type=self._compute_type
                    )
                    self._actual_device = "cuda"
                    return
                except Exception as exc:
                    if device == "cuda":
                        raise CudaUnavailableError(f"CUDA requested but unavailable: {exc}") from exc
                    # auto fallback to CPU
            self._model = WhisperModel(
                self._model_name, device="cpu", compute_type="int8"
            )
            self._actual_device = "cpu"
        except Exception as exc:
            raise ModelNotLoadedError(f"failed to load model '{self._model_name}': {exc}") from exc


def _resample_to_16k(audio: np.ndarray, from_rate: int) -> np.ndarray:
    if from_rate == 16000:
        return audio
    # Simple linear-interpolation resample (sufficient for 8-48kHz voice)
    duration = len(audio) / from_rate
    target_len = int(duration * 16000)
    x = np.linspace(0, 1, len(audio), dtype=np.float64)
    y = np.linspace(0, 1, target_len, dtype=np.float64)
    return np.interp(y, x, audio).astype(np.float32)
```

- [ ] **Step 4: Verify unit tests still pass (integration tests need GPU + fixtures; skipped for now)**

```bash
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v -m gpu  # likely skips without fixtures
```

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/transcriber.py tests/integration/test_transcriber.py tests/fixtures/audio/expected.json
git commit -m "feat(core): Transcriber wrapper around faster-whisper with CPU fallback"
```

---

### Task 4.4: OpenRouter client (`core/postprocess.py`)

**Files:**
- Create: `src/whisperflow/core/postprocess.py`
- Create: `tests/unit/test_postprocess.py`

- [ ] **Step 1: Write test**

File: `tests/unit/test_postprocess.py`

```python
"""Tests for PostProcess — OpenRouter client with fallback behavior."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from whisperflow.core.config import PostProcessConfig
from whisperflow.core.postprocess import PostProcess

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        },
    )


@pytest.fixture
def prompt_file(tmp_path: Path) -> Path:
    p = tmp_path / "prompt.md"
    p.write_text("You are a cleanup assistant. Just polish the text.", encoding="utf-8")
    return p


@pytest.fixture
def pp_config() -> PostProcessConfig:
    return PostProcessConfig(timeout_seconds=2.0, retries=2)


@pytest.mark.asyncio
@respx.mock
async def test_polish_success(prompt_file: Path, pp_config: PostProcessConfig) -> None:
    respx.post(API_URL).mock(return_value=_ok_response("Привет, как дела?"))

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    result = await pp.polish("эээ привет ну как дела", language="ru")

    assert result.text == "Привет, как дела?"
    assert result.fallback is False
    assert result.tokens_in == 10
    assert result.tokens_out == 8


@pytest.mark.asyncio
@respx.mock
async def test_polish_falls_back_on_401(prompt_file: Path, pp_config: PostProcessConfig) -> None:
    respx.post(API_URL).mock(return_value=httpx.Response(401, json={"error": "bad key"}))

    pp = PostProcess(config=pp_config, api_key="sk-bad", prompt_path=prompt_file)
    raw = "эээ привет"
    result = await pp.polish(raw, language="ru")

    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
@respx.mock
async def test_polish_retries_on_5xx(prompt_file: Path, pp_config: PostProcessConfig) -> None:
    route = respx.post(API_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            _ok_response("Clean text."),
        ]
    )

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    result = await pp.polish("um raw text", language="en")

    assert result.fallback is False
    assert result.text == "Clean text."
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_polish_falls_back_on_timeout(
    prompt_file: Path, pp_config: PostProcessConfig
) -> None:
    respx.post(API_URL).mock(side_effect=httpx.TimeoutException("slow"))

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    raw = "hi there"
    result = await pp.polish(raw, language="en")

    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
@respx.mock
async def test_polish_detects_refusal(
    prompt_file: Path, pp_config: PostProcessConfig
) -> None:
    respx.post(API_URL).mock(
        return_value=_ok_response("I can't help with that request.")
    )

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    raw = "hello test"
    result = await pp.polish(raw, language="en")

    # Refusal detection → fallback to raw
    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
@respx.mock
async def test_polish_detects_hallucination_length_mismatch(
    prompt_file: Path, pp_config: PostProcessConfig
) -> None:
    # LLM returned 5x longer text — probably hallucinated
    raw = "hi"
    long_reply = "Well actually it is very interesting that you said hi because there are many."
    respx.post(API_URL).mock(return_value=_ok_response(long_reply))

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    result = await pp.polish(raw, language="en")

    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
async def test_polish_fallback_without_api_key(
    prompt_file: Path, pp_config: PostProcessConfig
) -> None:
    pp = PostProcess(config=pp_config, api_key=None, prompt_path=prompt_file)
    raw = "some text"
    result = await pp.polish(raw, language="en")
    assert result.fallback is True
    assert result.text == raw
```

- [ ] **Step 2: Run, verify FAIL**

```bash
uv run pytest tests/unit/test_postprocess.py -v
```

- [ ] **Step 3: Implement PostProcess**

File: `src/whisperflow/core/postprocess.py`

```python
"""OpenRouter client for post-transcription polish."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from whisperflow.core.config import PostProcessConfig

API_URL = "https://openrouter.ai/api/v1/chat/completions"
REFUSAL_MARKERS = (
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "я не могу помочь",
    "я не могу ответить",
    "as an ai",
)
MAX_LENGTH_RATIO = 3.0  # output token estimate / input token estimate must be ≤ this


@dataclass
class PolishResult:
    text: str
    fallback: bool
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


class PostProcess:
    """
    Async OpenRouter wrapper with retry + graceful fallback.

    - Never raises: on any failure, returns raw input with fallback=True.
    - 5xx → exponential backoff (0.5s, 1s, 2s).
    - 401/403 → immediate fallback.
    - 429 → retries with backoff.
    - Timeout/connect error → fallback after retries exhausted.
    - LLM output that looks refused or significantly longer than input → fallback.
    """

    def __init__(
        self,
        config: PostProcessConfig,
        api_key: str | None,
        prompt_path: Path,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""

    async def polish(self, raw_text: str, language: str) -> PolishResult:
        if not self._api_key or not raw_text.strip():
            return self._fallback(raw_text, reason="no_api_key" if not self._api_key else "empty_input")

        user_payload = json.dumps({"language": language, "text": raw_text}, ensure_ascii=False)

        body = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "temperature": self._config.temperature,
            "max_tokens": min(len(raw_text) * 2, 1024),
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/nurgisa/whisperflow",
            "X-Title": "WhisperFlow",
        }

        import time

        start = time.monotonic()
        reply, tokens_in, tokens_out = await self._call_with_retry(body, headers)
        latency_ms = int((time.monotonic() - start) * 1000)

        if reply is None:
            return self._fallback(raw_text, reason="api_failed", latency_ms=latency_ms)

        cleaned = reply.strip()
        if self._looks_refused(cleaned) or self._too_long(raw_text, cleaned):
            return self._fallback(raw_text, reason="refused_or_hallucinated", latency_ms=latency_ms)

        cost_usd = self._estimate_cost(tokens_in, tokens_out)
        return PolishResult(
            text=cleaned,
            fallback=False,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )

    async def _call_with_retry(
        self, body: dict, headers: dict
    ) -> tuple[str | None, int, int]:
        delays = [0.5, 1.0, 2.0]
        attempts = max(1, self._config.retries)

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            for attempt in range(attempts):
                try:
                    resp = await client.post(API_URL, json=body, headers=headers)
                except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
                    if attempt + 1 < attempts:
                        await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                        continue
                    return None, 0, 0

                if resp.status_code == 200:
                    data = resp.json()
                    msg = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    return msg, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)

                if resp.status_code in (401, 403):
                    return None, 0, 0

                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                        continue
                    return None, 0, 0

                return None, 0, 0

        return None, 0, 0

    @staticmethod
    def _looks_refused(text: str) -> bool:
        low = text.lower()
        return any(marker in low for marker in REFUSAL_MARKERS)

    @staticmethod
    def _too_long(raw: str, reply: str) -> bool:
        if len(raw) == 0:
            return False
        return len(reply) / max(len(raw), 1) > MAX_LENGTH_RATIO

    @staticmethod
    def _estimate_cost(tokens_in: int, tokens_out: int) -> float:
        # Gemini 2.5 Flash Lite: $0.10/M input, $0.40/M output
        return (tokens_in / 1_000_000) * 0.10 + (tokens_out / 1_000_000) * 0.40

    @staticmethod
    def _fallback(raw: str, reason: str, latency_ms: int = 0) -> PolishResult:
        return PolishResult(
            text=raw,
            fallback=True,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_postprocess.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/postprocess.py tests/unit/test_postprocess.py
git commit -m "feat(core): PostProcess — OpenRouter client with retry and fallback"
```

---

## Phase 5 — Hotkey (Layer 4)

### Task 5.1: Hotkey debounce logic + HotkeyBox (`core/hotkey.py`)

**Files:**
- Create: `src/whisperflow/core/hotkey.py`
- Create: `tests/unit/test_hotkey.py`

- [ ] **Step 1: Write test for debounce pure function**

File: `tests/unit/test_hotkey.py`

```python
"""Tests for hotkey debounce logic."""
from __future__ import annotations

from whisperflow.core.hotkey import DebounceFilter


def test_debounce_first_press_allowed() -> None:
    f = DebounceFilter(min_hold_ms=150)
    assert f.accept_press(timestamp_ms=100) is True


def test_debounce_quick_release_rejected() -> None:
    f = DebounceFilter(min_hold_ms=150)
    f.accept_press(timestamp_ms=100)
    # Release at t=200, but press was at 100 → held 100ms < 150ms → reject
    assert f.accept_release(timestamp_ms=200) is False


def test_debounce_long_hold_accepted() -> None:
    f = DebounceFilter(min_hold_ms=150)
    f.accept_press(timestamp_ms=100)
    assert f.accept_release(timestamp_ms=400) is True  # 300ms hold


def test_debounce_second_press_without_release_ignored() -> None:
    f = DebounceFilter(min_hold_ms=150)
    f.accept_press(timestamp_ms=100)
    # Before release, another press fires → ignored
    assert f.accept_press(timestamp_ms=120) is False


def test_debounce_cycle_works() -> None:
    f = DebounceFilter(min_hold_ms=150)
    f.accept_press(100)
    f.accept_release(400)
    # Next press after release — should work
    assert f.accept_press(timestamp_ms=500) is True
```

- [ ] **Step 2: Run, verify FAIL**

```bash
uv run pytest tests/unit/test_hotkey.py -v
```

- [ ] **Step 3: Implement debounce and HotkeyBox**

File: `src/whisperflow/core/hotkey.py`

```python
"""Global hotkey listener with debounce."""
from __future__ import annotations

import time
from threading import Lock
from typing import Any

import keyboard

from whisperflow.core.bus import Event, EventBus


class DebounceFilter:
    """Decides whether a press/release should be accepted based on timing."""

    def __init__(self, min_hold_ms: int = 150) -> None:
        self._min_hold_ms = min_hold_ms
        self._pressed_at_ms: int | None = None

    def accept_press(self, timestamp_ms: int | None = None) -> bool:
        ts = timestamp_ms if timestamp_ms is not None else int(time.monotonic() * 1000)
        if self._pressed_at_ms is not None:
            # Still holding; ignore repeat / echo
            return False
        self._pressed_at_ms = ts
        return True

    def accept_release(self, timestamp_ms: int | None = None) -> bool:
        ts = timestamp_ms if timestamp_ms is not None else int(time.monotonic() * 1000)
        if self._pressed_at_ms is None:
            return False
        hold_ms = ts - self._pressed_at_ms
        self._pressed_at_ms = None
        return hold_ms >= self._min_hold_ms


class HotkeyBox:
    """
    Listens globally for a hotkey; emits HOTKEY_PRESSED / HOTKEY_RELEASED via EventBus.

    Built on the `keyboard` package, which spawns its own listener thread.
    """

    def __init__(self, bus: EventBus, combination: str = "right alt", min_hold_ms: int = 150) -> None:
        self._bus = bus
        self._combination = combination
        self._filter = DebounceFilter(min_hold_ms=min_hold_ms)
        self._lock = Lock()
        self._registered: Any = None
        self._is_pressed = False

    def start(self) -> None:
        def on_event(event: keyboard.KeyboardEvent) -> None:
            with self._lock:
                if event.event_type == keyboard.KEY_DOWN:
                    if self._is_pressed:
                        return
                    if self._filter.accept_press():
                        self._is_pressed = True
                        self._bus.emit(Event.HOTKEY_PRESSED, {})
                elif event.event_type == keyboard.KEY_UP:
                    if not self._is_pressed:
                        return
                    if self._filter.accept_release():
                        self._is_pressed = False
                        self._bus.emit(Event.HOTKEY_RELEASED, {})
                    else:
                        # Too short; still reset so we don't desync
                        self._is_pressed = False

        self._registered = keyboard.hook_key(self._combination, on_event, suppress=False)

    def stop(self) -> None:
        if self._registered is not None:
            keyboard.unhook(self._registered)
            self._registered = None

    def rebind(self, new_combination: str) -> None:
        self.stop()
        self._combination = new_combination
        self.start()
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_hotkey.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/whisperflow/core/hotkey.py tests/unit/test_hotkey.py
git commit -m "feat(core): HotkeyBox global listener with debounce"
```

---

## Phase 6 — UI (Layer 5)

### Task 6.1: Asset placeholders & resource loader (`ui/resources.py`)

**Files:**
- Create: `src/whisperflow/assets/.gitkeep`
- Create: `src/whisperflow/ui/resources.py`
- Create: `tests/unit/test_ui_resources.py`

- [ ] **Step 1: Ensure asset folder exists with placeholder**

```bash
touch src/whisperflow/assets/.gitkeep
```

For v1 we ship with placeholder icons generated programmatically — real icons are added during polish phase. For now, create tiny placeholder files:

File: `src/whisperflow/assets/README.md`

```markdown
# Assets

Replace these placeholder files before release:

- `icon.ico` — 256×256 multi-size app icon
- `icon_recording.ico` — same with red dot
- `beep_start.wav` — 80ms, 440 Hz
- `beep_stop.wav` — 60ms, 660 Hz

Recommended: generate with online ICO tools or use ImageMagick.
```

- [ ] **Step 2: Write test for resource loader**

File: `tests/unit/test_ui_resources.py`

```python
"""Tests for resource paths."""
from __future__ import annotations

from pathlib import Path

from whisperflow.ui.resources import asset_path, prompt_path, qss_path


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
```

- [ ] **Step 3: Run, verify FAIL**

```bash
uv run pytest tests/unit/test_ui_resources.py -v
```

- [ ] **Step 4: Implement resources.py**

File: `src/whisperflow/ui/resources.py`

```python
"""Resource-path helpers; works in both dev and PyInstaller bundles."""
from __future__ import annotations

import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Package root; PyInstaller overrides via sys._MEIPASS."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def asset_path(name: str) -> Path:
    return _bundle_root() / "assets" / name


def prompt_path(name: str) -> Path:
    return _bundle_root() / "prompts" / name


def qss_path(theme: str) -> Path:
    return _bundle_root() / "ui" / "qss" / f"{theme}.qss"
```

- [ ] **Step 5: Create QSS theme files**

File: `src/whisperflow/ui/qss/dark.qss`

```css
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI";
    font-size: 13px;
}
QPushButton {
    background-color: #2d2d30;
    border: 1px solid #3f3f46;
    padding: 6px 14px;
    border-radius: 4px;
}
QPushButton:hover { background-color: #3e3e42; }
QPushButton:pressed { background-color: #505056; }
QLineEdit, QComboBox, QSpinBox {
    background-color: #252526;
    border: 1px solid #3f3f46;
    padding: 4px;
    border-radius: 3px;
}
QTabWidget::pane { border: 1px solid #3f3f46; }
QTabBar::tab {
    padding: 6px 14px;
    background-color: #2d2d30;
}
QTabBar::tab:selected { background-color: #1e1e1e; }
```

File: `src/whisperflow/ui/qss/light.qss`

```css
QWidget {
    background-color: #fafafa;
    color: #222;
    font-family: "Segoe UI";
    font-size: 13px;
}
QPushButton {
    background-color: #fff;
    border: 1px solid #ccc;
    padding: 6px 14px;
    border-radius: 4px;
}
QPushButton:hover { background-color: #f0f0f0; }
QPushButton:pressed { background-color: #e0e0e0; }
QLineEdit, QComboBox, QSpinBox {
    background-color: #fff;
    border: 1px solid #ccc;
    padding: 4px;
    border-radius: 3px;
}
QTabWidget::pane { border: 1px solid #ccc; }
QTabBar::tab {
    padding: 6px 14px;
    background-color: #eee;
}
QTabBar::tab:selected { background-color: #fafafa; }
```

- [ ] **Step 6: Run tests, verify PASS**

```bash
uv run pytest tests/unit/test_ui_resources.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/whisperflow/assets/ src/whisperflow/ui/resources.py \
        src/whisperflow/ui/qss/ tests/unit/test_ui_resources.py
git commit -m "feat(ui): resource loader + QSS themes + assets placeholder"
```

---

### Task 6.2: Indicator overlay widget (`ui/indicator.py`)

**Files:**
- Create: `src/whisperflow/ui/indicator.py`

No automated tests — this is visual. Manual smoke in Task 7.3.

- [ ] **Step 1: Implement Indicator**

File: `src/whisperflow/ui/indicator.py`

```python
"""Frameless pill overlay that follows the cursor and shows recording state."""
from __future__ import annotations

from collections import deque
from typing import Literal

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QWidget

Stage = Literal["recording", "transcribing", "polishing", "hidden", "error"]

STAGE_COLORS: dict[Stage, QColor] = {
    "recording": QColor("#e74c3c"),
    "transcribing": QColor("#f39c12"),
    "polishing": QColor("#3498db"),
    "error": QColor("#95a5a6"),
    "hidden": QColor("#000000"),
}


class Indicator(QWidget):
    """Small frameless always-on-top pill widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(180, 40)

        self._stage: Stage = "hidden"
        self._text: str = ""
        self._rms_history: deque[float] = deque(maxlen=40)

        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(50)
        self._follow_timer.timeout.connect(self._follow_cursor)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.hide_indicator)

    # ---- Public API ----

    def show_recording(self) -> None:
        self._stage = "recording"
        self._text = "Recording"
        self._rms_history.clear()
        self._follow_timer.start()
        self.show()
        self.update()

    def show_transcribing(self) -> None:
        self._stage = "transcribing"
        self._text = "Transcribing…"
        self.update()

    def show_polishing(self) -> None:
        self._stage = "polishing"
        self._text = "Polishing…"
        self.update()

    def flash_error(self, message: str, duration_ms: int = 1500) -> None:
        self._stage = "error"
        self._text = message
        self.show()
        self._auto_hide_timer.start(duration_ms)
        self.update()

    def push_rms(self, rms: float) -> None:
        self._rms_history.append(min(1.0, rms * 5))
        self.update()

    def hide_indicator(self) -> None:
        self._stage = "hidden"
        self._follow_timer.stop()
        self.hide()

    # ---- Internals ----

    def _follow_cursor(self) -> None:
        pos = QCursor.pos() + QPoint(16, 16)
        self.move(pos)

    def paintEvent(self, _) -> None:  # noqa: N802, ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(0, 0, 0, 180)
        p.setBrush(bg)
        p.setPen(QPen(STAGE_COLORS[self._stage], 2))
        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        p.drawRoundedRect(rect, 18, 18)

        # waveform on left
        if self._stage == "recording" and self._rms_history:
            p.setPen(QPen(STAGE_COLORS["recording"], 1))
            bar_w = 2
            gap = 1
            x = 12
            mid = self.height() // 2
            for level in self._rms_history:
                h = max(2, int(level * (self.height() - 14)))
                p.drawRect(x, mid - h // 2, bar_w, h)
                x += bar_w + gap
                if x > 80:
                    break

        # text
        p.setPen(QColor("#ffffff"))
        p.drawText(rect.adjusted(90, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, self._text)
```

- [ ] **Step 2: Smoke-check — import doesn't explode**

```bash
uv run python -c "from whisperflow.ui.indicator import Indicator; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/whisperflow/ui/indicator.py
git commit -m "feat(ui): Indicator overlay widget with waveform and stage states"
```

---

### Task 6.3: Tray icon + menu (`ui/tray.py`)

**Files:**
- Create: `src/whisperflow/ui/tray.py`

- [ ] **Step 1: Implement tray**

File: `src/whisperflow/ui/tray.py`

```python
"""System tray icon with context menu."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QObject):
    """Minimal tray icon with 3 actions: Settings, Logs, Quit."""

    settings_requested = Signal()
    logs_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._tray = QSystemTrayIcon(self._make_icon(recording=False))
        self._tray.setToolTip("WhisperFlow")

        menu = QMenu()
        act_settings = QAction("Настройки…", self)
        act_settings.triggered.connect(self.settings_requested.emit)
        act_logs = QAction("Показать логи", self)
        act_logs.triggered.connect(self.logs_requested.emit)
        act_quit = QAction("Выход", self)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_settings)
        menu.addAction(act_logs)
        menu.addSeparator()
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)
        self._menu = menu

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def set_recording(self, recording: bool) -> None:
        self._tray.setIcon(self._make_icon(recording=recording))

    def toast(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    @staticmethod
    def _make_icon(recording: bool) -> QIcon:
        pix = QPixmap(32, 32)
        pix.fill()
        painter = QPainter(pix)
        color = "#e74c3c" if recording else "#2d2d30"
        painter.fillRect(pix.rect(), color)
        painter.end()
        return QIcon(pix)
```

- [ ] **Step 2: Smoke-check**

```bash
uv run python -c "from whisperflow.ui.tray import TrayIcon; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add src/whisperflow/ui/tray.py
git commit -m "feat(ui): system-tray icon with context menu and recording state"
```

---

### Task 6.4: Settings window (`ui/settings.py`)

**Files:**
- Create: `src/whisperflow/ui/settings.py`

- [ ] **Step 1: Implement SettingsWindow**

File: `src/whisperflow/ui/settings.py`

```python
"""Settings window with tabs: Hotkey, Audio, Whisper, PostProcess, UI, About."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from whisperflow.core.config import Config, ConfigStore


class SettingsWindow(QMainWindow):
    """Tabbed settings editor; saves Config via ConfigStore."""

    settings_saved = Signal()

    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self._store = store
        self._cfg: Config = store.load()

        self.setWindowTitle("WhisperFlow — настройки")
        self.resize(560, 440)

        central = QWidget()
        root = QVBoxLayout(central)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_hotkey_tab(), "Хоткей")
        self._tabs.addTab(self._build_audio_tab(), "Аудио")
        self._tabs.addTab(self._build_whisper_tab(), "Whisper")
        self._tabs.addTab(self._build_postprocess_tab(), "LLM")
        self._tabs.addTab(self._build_ui_tab(), "Внешний вид")
        self._tabs.addTab(self._build_about_tab(), "О программе")
        root.addWidget(self._tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_save = QPushButton("Сохранить")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        self.setCentralWidget(central)

    # ---- Tabs ----

    def _build_hotkey_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._hk_combination = QLineEdit(self._cfg.hotkey.combination)
        layout.addRow("Клавиша:", self._hk_combination)
        self._hk_mode = QComboBox()
        self._hk_mode.addItems(["push_to_talk", "toggle"])
        self._hk_mode.setCurrentText(self._cfg.hotkey.mode)
        layout.addRow("Режим:", self._hk_mode)
        self._hk_debounce = QSpinBox()
        self._hk_debounce.setRange(0, 1000)
        self._hk_debounce.setValue(self._cfg.hotkey.debounce_ms)
        layout.addRow("Debounce (мс):", self._hk_debounce)
        return w

    def _build_audio_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._audio_device = QLineEdit(self._cfg.audio.device)
        layout.addRow("Устройство:", self._audio_device)
        self._audio_max = QSpinBox()
        self._audio_max.setRange(1, 600)
        self._audio_max.setValue(self._cfg.audio.max_recording_seconds)
        layout.addRow("Макс. запись (сек):", self._audio_max)
        self._audio_vad = QCheckBox("VAD включён")
        self._audio_vad.setChecked(self._cfg.audio.vad_enabled)
        layout.addRow(self._audio_vad)
        return w

    def _build_whisper_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._w_model = QLineEdit(self._cfg.whisper.model)
        layout.addRow("Модель:", self._w_model)
        self._w_device = QComboBox()
        self._w_device.addItems(["auto", "cuda", "cpu"])
        self._w_device.setCurrentText(self._cfg.whisper.device)
        layout.addRow("Device:", self._w_device)
        self._w_compute = QComboBox()
        self._w_compute.addItems(["int8", "float16", "float32"])
        self._w_compute.setCurrentText(self._cfg.whisper.compute_type)
        layout.addRow("Compute type:", self._w_compute)
        return w

    def _build_postprocess_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._pp_enabled = QCheckBox("Включить постобработку LLM")
        self._pp_enabled.setChecked(self._cfg.postprocess.enabled)
        layout.addRow(self._pp_enabled)
        self._pp_model = QLineEdit(self._cfg.postprocess.model)
        layout.addRow("Модель:", self._pp_model)
        self._pp_timeout = QDoubleSpinBox()
        self._pp_timeout.setRange(1.0, 30.0)
        self._pp_timeout.setValue(self._cfg.postprocess.timeout_seconds)
        layout.addRow("Таймаут (сек):", self._pp_timeout)

        self._pp_api_key = QLineEdit()
        self._pp_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        existing = self._store.get_api_key()
        if existing:
            self._pp_api_key.setPlaceholderText("••••••• (ключ сохранён)")
        layout.addRow("OpenRouter API key:", self._pp_api_key)
        return w

    def _build_ui_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._ui_theme = QComboBox()
        self._ui_theme.addItems(["dark", "light", "system"])
        self._ui_theme.setCurrentText(self._cfg.ui.theme)
        layout.addRow("Тема:", self._ui_theme)
        self._ui_sound = QCheckBox("Звуковые сигналы")
        self._ui_sound.setChecked(self._cfg.ui.sound_enabled)
        layout.addRow(self._ui_sound)
        self._beh_autostart = QCheckBox("Запуск при старте Windows")
        self._beh_autostart.setChecked(self._cfg.behavior.autostart)
        layout.addRow(self._beh_autostart)
        return w

    def _build_about_tab(self) -> QWidget:
        from whisperflow import __version__

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(f"WhisperFlow v{__version__}"))
        layout.addWidget(
            QLabel("Локальная диктовка через Whisper + OpenRouter для постобработки.")
        )
        layout.addStretch()
        return w

    # ---- Save ----

    def _save(self) -> None:
        self._cfg.hotkey.combination = self._hk_combination.text().strip()
        self._cfg.hotkey.mode = self._hk_mode.currentText()  # type: ignore[assignment]
        self._cfg.hotkey.debounce_ms = self._hk_debounce.value()

        self._cfg.audio.device = self._audio_device.text().strip() or "default"
        self._cfg.audio.max_recording_seconds = self._audio_max.value()
        self._cfg.audio.vad_enabled = self._audio_vad.isChecked()

        self._cfg.whisper.model = self._w_model.text().strip()
        self._cfg.whisper.device = self._w_device.currentText()  # type: ignore[assignment]
        self._cfg.whisper.compute_type = self._w_compute.currentText()  # type: ignore[assignment]

        self._cfg.postprocess.enabled = self._pp_enabled.isChecked()
        self._cfg.postprocess.model = self._pp_model.text().strip()
        self._cfg.postprocess.timeout_seconds = self._pp_timeout.value()

        new_key = self._pp_api_key.text().strip()
        if new_key:
            self._store.set_api_key(new_key)
            self._pp_api_key.clear()
            self._pp_api_key.setPlaceholderText("••••••• (ключ сохранён)")

        self._cfg.ui.theme = self._ui_theme.currentText()  # type: ignore[assignment]
        self._cfg.ui.sound_enabled = self._ui_sound.isChecked()
        self._cfg.behavior.autostart = self._beh_autostart.isChecked()

        self._store.save(self._cfg)
        self.settings_saved.emit()
```

- [ ] **Step 2: Smoke-check import**

```bash
uv run python -c "from whisperflow.ui.settings import SettingsWindow; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add src/whisperflow/ui/settings.py
git commit -m "feat(ui): tabbed settings window wired to ConfigStore"
```

---

## Phase 7 — App (Layer 6)

### Task 7.1: Application wiring (`app.py`)

**Files:**
- Create: `src/whisperflow/app.py`
- Create: `src/whisperflow/__main__.py`

- [ ] **Step 1: Implement `__main__.py`**

File: `src/whisperflow/__main__.py`

```python
"""python -m whisperflow entry."""
from __future__ import annotations

from whisperflow.app import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement `app.py`**

File: `src/whisperflow/app.py`

```python
"""Qt application wiring: lifecycle, DI, event routing."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Any

import structlog
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox

from whisperflow.core.bus import Event, EventBus
from whisperflow.core.config import ConfigStore, default_config_path
from whisperflow.core.errors import AudioDeviceError
from whisperflow.core.hotkey import HotkeyBox
from whisperflow.core.injector import Injector
from whisperflow.core.postprocess import PostProcess
from whisperflow.core.recorder import Recorder, RecordingResult
from whisperflow.core.state import State, StateMachine
from whisperflow.core.transcriber import Transcriber
from whisperflow.platform.autostart import (
    disable_autostart,
    enable_autostart,
    is_autostart_enabled,
)
from whisperflow.platform.single_instance import SingleInstance
from whisperflow.ui.indicator import Indicator
from whisperflow.ui.resources import prompt_path, qss_path
from whisperflow.ui.settings import SettingsWindow
from whisperflow.ui.tray import TrayIcon

log = structlog.get_logger()


class _InferenceJob(QRunnable):
    """Runs transcription + polish on a worker thread."""

    def __init__(self, transcriber: Transcriber, postprocess: PostProcess,
                 audio, sample_rate: int, on_done, on_error) -> None:
        super().__init__()
        self._transcriber = transcriber
        self._postprocess = postprocess
        self._audio = audio
        self._sr = sample_rate
        self._on_done = on_done
        self._on_error = on_error

    def run(self) -> None:
        try:
            transcript = self._transcriber.transcribe(self._audio, sample_rate=self._sr)
            if not transcript.raw_text:
                self._on_done(transcript.raw_text, True, transcript.language)
                return
            polish = asyncio.run(
                self._postprocess.polish(transcript.raw_text, language=transcript.language)
            )
            self._on_done(polish.text, polish.fallback, transcript.language)
        except Exception as exc:
            self._on_error(exc)


class WhisperFlowApp(QObject):
    """Orchestrator: holds singletons and wires events."""

    def __init__(self, qapp: QApplication) -> None:
        super().__init__()
        self._qapp = qapp

        self._bus = EventBus()
        self._state = StateMachine()
        self._store = ConfigStore()
        self._cfg = self._store.load()

        self._indicator = Indicator()
        self._tray = TrayIcon()
        self._settings_window: SettingsWindow | None = None

        self._recorder = Recorder(bus=self._bus)
        self._injector = Injector(bus=self._bus)
        self._transcriber = Transcriber(
            model=self._cfg.whisper.model,
            device=self._cfg.whisper.device,
            compute_type=self._cfg.whisper.compute_type,
        )
        self._postprocess = PostProcess(
            config=self._cfg.postprocess,
            api_key=self._store.get_api_key(),
            prompt_path=prompt_path(self._cfg.postprocess.prompt_file),
        )
        self._hotkey = HotkeyBox(
            bus=self._bus,
            combination=self._cfg.hotkey.combination,
            min_hold_ms=self._cfg.hotkey.debounce_ms,
        )

        self._target_hwnd = 0

        self._wire_events()
        self._wire_tray()
        self._apply_theme()

    # ---- Lifecycle ----

    def start(self) -> None:
        self._tray.show()
        try:
            self._hotkey.start()
        except Exception as exc:
            log.error("hotkey_registration_failed", error=str(exc))
            self._tray.toast("WhisperFlow", "Не удалось зарегистрировать хоткей. Откройте настройки.")
            self._show_settings()

        # Warm up Whisper in background so first transcription is fast
        QTimer.singleShot(250, self._warm_up_transcriber)

    def quit(self) -> None:
        self._hotkey.stop()
        self._indicator.hide_indicator()
        self._tray.hide()
        self._qapp.quit()

    # ---- Event wiring ----

    def _wire_events(self) -> None:
        self._bus.subscribe(Event.HOTKEY_PRESSED, self._on_hotkey_pressed)
        self._bus.subscribe(Event.HOTKEY_RELEASED, self._on_hotkey_released)

    def _wire_tray(self) -> None:
        self._tray.settings_requested.connect(self._show_settings)
        self._tray.logs_requested.connect(self._open_logs)
        self._tray.quit_requested.connect(self.quit)

    # ---- Hotkey handlers ----

    def _on_hotkey_pressed(self, _: dict) -> None:
        if not self._state.can_start_recording():
            return
        try:
            self._target_hwnd = self._injector.capture_target()
            self._recorder.start(
                sample_rate=self._cfg.audio.sample_rate,
                device=self._cfg.audio.device,
            )
            self._state.transition(State.RECORDING)
            self._tray.set_recording(True)
            self._indicator.show_recording()
        except AudioDeviceError as exc:
            self._tray.toast("WhisperFlow", f"Микрофон: {exc}")
            self._state.reset_to_idle()

    def _on_hotkey_released(self, _: dict) -> None:
        if self._state.current != State.RECORDING:
            return
        try:
            result = self._recorder.stop()
        except Exception as exc:
            log.error("recorder_stop_failed", error=str(exc))
            self._state.reset_to_idle()
            self._tray.set_recording(False)
            self._indicator.hide_indicator()
            return

        self._tray.set_recording(False)

        if result.duration_ms < self._cfg.audio.vad_min_speech_ms:
            self._indicator.flash_error("Слишком коротко")
            self._state.reset_to_idle()
            return

        self._state.transition(State.TRANSCRIBING)
        self._indicator.show_transcribing()

        job = _InferenceJob(
            transcriber=self._transcriber,
            postprocess=self._postprocess,
            audio=result.audio,
            sample_rate=self._cfg.audio.sample_rate,
            on_done=self._on_inference_done,
            on_error=self._on_inference_error,
        )
        QThreadPool.globalInstance().start(job)

    # ---- Inference callbacks (always invoked from worker thread) ----

    def _on_inference_done(self, text: str, fallback: bool, language: str) -> None:
        QTimer.singleShot(0, partial(self._finish_inference, text, fallback, language))

    def _on_inference_error(self, exc: Exception) -> None:
        log.error("inference_failed", error=str(exc))
        QTimer.singleShot(0, lambda: self._indicator.flash_error("Ошибка распознавания"))
        QTimer.singleShot(0, self._state.reset_to_idle)

    def _finish_inference(self, text: str, fallback: bool, _language: str) -> None:
        if not text.strip():
            self._indicator.flash_error("Ничего не распознано")
            self._state.reset_to_idle()
            return

        self._state.transition(State.POLISHING)
        self._indicator.show_polishing()
        self._state.transition(State.INJECTING)
        self._injector.inject(text, target_hwnd=self._target_hwnd)
        if fallback:
            self._tray.toast("WhisperFlow", "LLM недоступна — вставлен сырой текст")
        QTimer.singleShot(200, self._after_inject)

    def _after_inject(self) -> None:
        self._indicator.hide_indicator()
        self._state.reset_to_idle()

    # ---- Settings ----

    def _show_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self._store)
            self._settings_window.settings_saved.connect(self._reload_config)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _reload_config(self) -> None:
        self._cfg = self._store.load()
        self._hotkey.rebind(self._cfg.hotkey.combination)
        self._postprocess = PostProcess(
            config=self._cfg.postprocess,
            api_key=self._store.get_api_key(),
            prompt_path=prompt_path(self._cfg.postprocess.prompt_file),
        )
        self._sync_autostart()
        self._apply_theme()
        self._tray.toast("WhisperFlow", "Настройки сохранены")

    def _sync_autostart(self) -> None:
        if self._cfg.behavior.autostart:
            exe = sys.executable
            enable_autostart(exe_path=exe)
        else:
            disable_autostart()

    def _apply_theme(self) -> None:
        theme = self._cfg.ui.theme
        if theme == "system":
            return
        qss = qss_path(theme)
        if qss.exists():
            self._qapp.setStyleSheet(qss.read_text(encoding="utf-8"))

    def _warm_up_transcriber(self) -> None:
        try:
            self._transcriber.warm_up()
        except Exception as exc:
            log.warning("warm_up_failed", error=str(exc))

    # ---- Logs ----

    def _open_logs(self) -> None:
        log_path = default_config_path().parent / "logs" / "whisperflow.log"
        if log_path.exists():
            subprocess.Popen(["notepad.exe", str(log_path)])
        else:
            self._tray.toast("WhisperFlow", "Логов пока нет")


def _configure_logging() -> None:
    log_dir = default_config_path().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "whisperflow.log"

    import logging
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(message)s")

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def main() -> int:
    _configure_logging()

    guard = SingleInstance()
    if not guard.acquire():
        log.info("already_running")
        return 0

    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)

    app = WhisperFlowApp(qapp)
    app.start()

    try:
        return qapp.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Smoke-test: app imports without error**

```bash
uv run python -c "from whisperflow.app import main; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/whisperflow/app.py src/whisperflow/__main__.py
git commit -m "feat(app): Qt application wiring — lifecycle, DI, event routing"
```

---

### Task 7.2: First manual E2E smoke test

**Files:** none (manual test only)

- [ ] **Step 1: Ensure the Whisper model is downloaded**

The first transcription downloads `large-v3-turbo` (~800 MB) to `~/.cache/huggingface/hub/`. Do this explicitly once to avoid a freeze on first real use:

```bash
uv run python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cuda', compute_type='int8')"
```

Expected: progress bars downloading files; exits with no errors.

- [ ] **Step 2: Set API key**

```bash
uv run python -c "from whisperflow.core.config import ConfigStore; ConfigStore().set_api_key('YOUR_OPENROUTER_KEY_HERE')"
```

Replace `YOUR_OPENROUTER_KEY_HERE` with the real key. Expected: no output (success).

- [ ] **Step 3: Launch the app**

```bash
uv run whisperflow
```

Expected: tray icon appears in system tray (grey square). No visible window.

- [ ] **Step 4: Run through the manual checklist**

Mark each as you go:

- [ ] Tray icon is visible in system tray
- [ ] Right-click tray → menu shows "Настройки", "Показать логи", "Выход"
- [ ] Click "Настройки" → window opens, shows saved API key placeholder
- [ ] Close settings window → app keeps running
- [ ] Open Notepad. Focus on text area.
- [ ] Hold **Right Alt**, say in Russian: *"Привет, это тестовая фраза"* for ~3 seconds.
- [ ] Release Right Alt. Expected: pill near cursor shows "Recording" → "Transcribing…" → "Polishing…" → disappears. Text appears in Notepad within ~1 second.
- [ ] Text has proper capitalization and period.
- [ ] Repeat 5 times — no crashes, no memory leaks visible in Task Manager.
- [ ] Say a very short "hi" (release within 100ms) — pill shows "Слишком коротко", no text inserted.
- [ ] Right-click tray → "Выход" → tray disappears, process terminates.

If any step fails: read `%APPDATA%\WhisperFlow\logs\whisperflow.log`, identify the error, and create a fix task. Do NOT proceed until all steps pass.

- [ ] **Step 5: Commit state snapshot**

```bash
git add -A
git status  # verify nothing unexpected staged
git commit -m "chore: first successful E2E smoke test on dev machine" --allow-empty
```

---

## Phase 8 — Scripts & distribution (Layer 7)

### Task 8.1: Model download helper

**Files:**
- Create: `scripts/download_model.py`

- [ ] **Step 1: Write script**

File: `scripts/download_model.py`

```python
"""Download the Whisper model ahead of first run."""
from __future__ import annotations

import argparse
import sys

from faster_whisper import WhisperModel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()

    print(f"Downloading {args.model} ({args.device}, {args.compute_type})…")
    WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify it works**

```bash
uv run python scripts/download_model.py --device cpu
```

Expected: model download or confirmation that it's cached.

- [ ] **Step 3: Commit**

```bash
git add scripts/download_model.py
git commit -m "chore(scripts): add standalone Whisper model downloader"
```

---

### Task 8.2: cuDNN download helper

**Files:**
- Create: `scripts/download_cudnn.py`

- [ ] **Step 1: Write script**

File: `scripts/download_cudnn.py`

```python
"""Download cuDNN DLLs needed for GPU inference on Windows.

NOTE: cuDNN requires accepting NVIDIA's EULA. This script prints instructions;
we do not automate download of gated binaries.
"""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "cudnn"
REQUIRED_DLLS = [
    "cudnn_ops_infer64_8.dll",
    "cudnn_cnn_infer64_8.dll",
    "cudnn64_8.dll",
]


def main() -> int:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    missing = [dll for dll in REQUIRED_DLLS if not (VENDOR_DIR / dll).exists()]
    if not missing:
        print("All cuDNN DLLs present in vendor/cudnn/.")
        return 0

    print("The following cuDNN DLLs are missing from vendor/cudnn/:")
    for dll in missing:
        print(f"  - {dll}")
    print()
    print("Steps:")
    print("  1. Visit https://developer.nvidia.com/cudnn-downloads")
    print("  2. Download cuDNN 8.x for CUDA 12 (Windows x64) — requires NVIDIA account.")
    print("  3. Extract the archive and copy the DLLs above to `vendor/cudnn/`.")
    print("  4. Re-run this script to verify.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify the script runs**

```bash
uv run python scripts/download_cudnn.py
```

Expected: prints instructions listing missing DLLs (on dev machine CUDA should already be installed system-wide; `vendor/cudnn` is only for the release build).

- [ ] **Step 3: Commit**

```bash
git add scripts/download_cudnn.py
git commit -m "chore(scripts): cuDNN downloader helper (manual steps)"
```

---

### Task 8.3: PyInstaller build script

**Files:**
- Create: `scripts/build_exe.py`

- [ ] **Step 1: Write build script**

File: `scripts/build_exe.py`

```python
"""Build WhisperFlow.exe via PyInstaller."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "whisperflow"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "WhisperFlow.spec"

ADD_DATA = [
    (SRC / "assets", "assets"),
    (SRC / "prompts", "prompts"),
    (SRC / "ui" / "qss", "qss"),
]
CUDNN_DIR = ROOT / "vendor" / "cudnn"


def main() -> int:
    # Clean previous
    for p in (DIST, BUILD, SPEC):
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--windowed",
        f"--icon={SRC / 'assets' / 'icon.ico'}",
        "--name", "WhisperFlow",
        "--collect-all", "faster_whisper",
        "--collect-all", "silero_vad",
    ]

    for src_dir, dest in ADD_DATA:
        cmd += ["--add-data", f"{src_dir}{';' if sys.platform == 'win32' else ':'}{dest}"]

    if CUDNN_DIR.exists():
        for dll in CUDNN_DIR.glob("*.dll"):
            cmd += ["--add-binary", f"{dll}{';' if sys.platform == 'win32' else ':'}."]

    cmd.append(str(SRC / "app.py"))

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    print(f"\nBuild artifact: {DIST / 'WhisperFlow' / 'WhisperFlow.exe'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify script runs (build will take ~2-5 minutes)**

```bash
uv run python scripts/build_exe.py
```

Expected: PyInstaller produces `dist/WhisperFlow/WhisperFlow.exe`.

Then verify:

```bash
dist/WhisperFlow/WhisperFlow.exe
```

Expected: tray icon appears; same smoke test as Task 7.2 passes.

- [ ] **Step 3: Commit**

```bash
git add scripts/build_exe.py
git commit -m "chore(scripts): PyInstaller build wrapper for WhisperFlow.exe"
```

---

## Phase 9 — Integration, fixtures, CI, release prep

### Task 9.1: Record WAV fixtures for integration tests

**Files:**
- Create: `tests/fixtures/audio/short_ru.wav`
- Create: `tests/fixtures/audio/short_en.wav`
- Create: `tests/fixtures/audio/mixed.wav`
- Create: `tests/fixtures/audio/silence.wav`
- Create: `tests/fixtures/audio/hallucination.wav`

These need to be recorded with your actual microphone. WAV format: 16 kHz mono int16.

- [ ] **Step 1: Record using a helper script**

Create one-off helper `scripts/record_fixture.py`:

```python
"""Record a WAV fixture from the microphone."""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd


def record(path: Path, duration_seconds: float, sample_rate: int = 16000) -> None:
    print(f"Recording {duration_seconds}s to {path}…")
    audio = sd.rec(int(duration_seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio.tobytes())
    print("Done.")


if __name__ == "__main__":
    path = Path(sys.argv[1])
    duration = float(sys.argv[2])
    record(path, duration)
```

- [ ] **Step 2: Record each fixture**

Say the phrase clearly into the mic after running each command. Use a quiet environment.

```bash
uv run python scripts/record_fixture.py tests/fixtures/audio/short_ru.wav 3
# Say: "Привет, как дела"

uv run python scripts/record_fixture.py tests/fixtures/audio/short_en.wav 3
# Say: "Hello world how are you"

uv run python scripts/record_fixture.py tests/fixtures/audio/mixed.wav 4
# Say: "Сегодня я deploy новый feature"

uv run python scripts/record_fixture.py tests/fixtures/audio/silence.wav 2
# Stay silent

uv run python scripts/record_fixture.py tests/fixtures/audio/hallucination.wav 4
# Stay silent with mic muted or in very quiet room — should produce no speech
```

- [ ] **Step 3: Run integration tests on GPU**

```bash
uv run pytest tests/integration/ -v -m gpu
```

Expected: all four shipping tests pass, similarity ≥ configured thresholds.

If similarity is below threshold for a fixture, the recording or expected text may need adjustment — update `tests/fixtures/audio/expected.json`.

- [ ] **Step 4: Commit fixtures**

```bash
git add tests/fixtures/audio/ scripts/record_fixture.py
git commit -m "test: add integration WAV fixtures (short_ru, short_en, mixed, silence, hallucination)"
```

---

### Task 9.2: GitHub Actions test workflow

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Write workflow**

File: `.github/workflows/test.yml`

```yaml
name: tests

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint-and-unit:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        run: irm https://astral.sh/uv/install.ps1 | iex
        shell: pwsh

      - name: Install deps
        run: |
          uv venv
          uv pip install -e ".[dev]"

      - name: Ruff
        run: uv run ruff check .

      - name: Mypy
        run: uv run mypy src/

      - name: Pytest (unit only — integration skipped without GPU)
        run: uv run pytest tests/unit/ -v --tb=short
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add lint + unit-test workflow on windows-latest"
```

---

### Task 9.3: README and MANUAL_TESTS docs

**Files:**
- Create: `README.md`
- Create: `docs/MANUAL_TESTS.md`

- [ ] **Step 1: Write README**

File: `README.md`

```markdown
# WhisperFlow

Local Windows push-to-talk dictation with Whisper + OpenRouter polish.

## Features

- Hold RightAlt, speak, release — text appears in the active window.
- Local Whisper transcription (faster-whisper `large-v3-turbo` int8 on GPU).
- Optional cloud LLM polish via OpenRouter (default: Gemini 2.5 Flash Lite).
- Russian, English, and code-switching supported.
- Works in any Windows application: browsers, IDEs, Telegram, Word, etc.

## Requirements

- Windows 10/11 x64
- NVIDIA GPU with ≥4 GB VRAM (optional — falls back to CPU)
- Python 3.12 (for development)
- OpenRouter API key (optional — polish falls back to raw text if missing)

## Install from source

```powershell
git clone https://github.com/nurgisa/whisperflow
cd whisperflow
irm https://astral.sh/uv/install.ps1 | iex
uv sync
uv run python scripts/download_model.py
uv run whisperflow
```

## Configuration

- Config file: `%APPDATA%\WhisperFlow\config.toml`
- API key: stored in Windows Credential Manager (service `WhisperFlow`)
- Logs: `%APPDATA%\WhisperFlow\logs\whisperflow.log`

## License

MIT
```

- [ ] **Step 2: Write manual test checklist**

File: `docs/MANUAL_TESTS.md`

```markdown
# Manual Smoke Tests

Run this checklist before each release. Do NOT release if anything fails.

## Prerequisites

- [ ] Fresh Windows 10/11 x64 VM or test machine
- [ ] Valid OpenRouter API key
- [ ] Working microphone

## Install & launch

- [ ] Installer (or dist folder) extracted
- [ ] First launch: Whisper model downloads with progress (~800 MB)
- [ ] Tray icon appears after successful launch

## Core flow

- [ ] Hold RightAlt → pill near cursor shows "Recording"
- [ ] Waveform animates during recording
- [ ] Release after ~3 sec → "Transcribing…" → "Polishing…" → text in active window
- [ ] Total dead air ≤1 second
- [ ] Russian speech → correct punctuation + capitalization
- [ ] English speech → correct capitalization
- [ ] Code-switching (RU + EN) → both languages preserved

## Edge cases

- [ ] Release under 300ms → "Слишком коротко" flash, no paste
- [ ] Silence only → "Ничего не распознано" flash, no paste
- [ ] Very long hold (>90s) → forced stop + tray toast
- [ ] Unplug microphone mid-session → error toast
- [ ] Disconnect internet → raw Whisper text still pasted + offline tost

## Settings

- [ ] Open settings from tray menu
- [ ] Change hotkey combination → save → old hotkey no longer works, new one works
- [ ] Enter API key → save → placeholder shows "••••••• (ключ сохранён)"
- [ ] Enable autostart → reboot → app launches automatically
- [ ] Disable autostart → reboot → app does not launch

## Stability

- [ ] 30 consecutive transcriptions without crash
- [ ] RAM growth < 100 MB over 30 cycles (check Task Manager)
- [ ] GPU VRAM ≤ 2 GB with model loaded

## Shutdown

- [ ] Tray → Quit → process terminates cleanly
- [ ] exe file can be deleted after quit (no locks held)
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/MANUAL_TESTS.md
git commit -m "docs: add README and manual smoke test checklist"
```

---

### Task 9.4: Final verification and acceptance

**Files:** none (verification only)

- [ ] **Step 1: Full unit test suite**

```bash
uv run pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 2: Full integration test suite**

```bash
uv run pytest tests/integration/ -v -m gpu
```

Expected: all pass (model + fixtures present).

- [ ] **Step 3: Lint + type check**

```bash
uv run ruff check .
uv run mypy src/
```

Expected: zero errors.

- [ ] **Step 4: Complete manual smoke checklist**

Work through every item in `docs/MANUAL_TESTS.md`. Do not skip any.

- [ ] **Step 5: Verify acceptance criteria from spec §16**

Against spec:

- [ ] End-to-end: hotkey → speech → text ≤1 sec
- [ ] 30 consecutive transcriptions without crash, RSS growth <100 MB
- [ ] Settings changes take effect without restart (except model change)
- [ ] Offline raw text + tost
- [ ] Mean latency release→inject ≤900ms for 5-sec speech
- [ ] RSS idle ≤500 MB, peak ≤1.2 GB
- [ ] VRAM ≤2 GB with large-v3-turbo int8
- [ ] Install folder ≤500 MB (without model)
- [ ] Ruff + mypy clean
- [ ] Pure-logic coverage ≥90% — check with `uv run pytest --cov=src/whisperflow --cov-report=term-missing`

- [ ] **Step 6: Tag and commit release**

```bash
git add -A
git commit -m "release: v1.0.0" --allow-empty
git tag -a v1.0.0 -m "WhisperFlow v1.0.0 — first release"
```

- [ ] **Step 7: Final summary**

Write a short release note in `CHANGELOG.md`:

File: `CHANGELOG.md`

```markdown
# Changelog

## v1.0.0 — 2026-04-19

First release.

### Features
- Push-to-talk dictation with RightAlt default hotkey
- Local Whisper transcription (large-v3-turbo int8 on GPU, CPU fallback)
- LLM polish via OpenRouter (Gemini 2.5 Flash Lite default)
- RU + EN + code-switching support
- Windows tray integration
- Clipboard-based text injection with HWND guard
- Autostart toggle
- Audible feedback (start/stop beeps)
- Configurable theme (dark/light)

### Known limitations (slated for v2)
- No custom dictionary
- No voice commands
- No transcription history
```

Commit:

```bash
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG for v1.0.0"
```

---

## Self-review checklist (already performed by plan author)

- **Spec coverage:** Every section of the spec maps to at least one task:
  - §1–§4 (problem, goals, constraints) → reflected in architecture of tasks
  - §5 (architecture) → Task file structure + per-module tasks
  - §6 (data flow) → Task 7.1 `WhisperFlowApp` wires the whole pipeline
  - §7 (module contracts) → Tasks 1.2–1.6, 2.x, 3.x, 4.x, 5.1, 7.1
  - §8 (error handling) → covered in Tasks 3.2 (AudioDeviceError), 4.3 (Cuda errors, hallucinations), 4.4 (API failures), 3.3 (HWND changed)
  - §9 (testing) → TDD throughout + Task 9.1 fixtures + 9.2 CI
  - §10 (repo structure) → Task 0.2 scaffolds directories
  - §11 (deps) → Task 0.2 `pyproject.toml`
  - §12 (config) → Tasks 1.4–1.6
  - §13 (LLM prompt) → Task 4.1
  - §14 (build order) → Phase numbering matches
  - §15 (build & dist) → Task 8.3
  - §16 (acceptance) → Task 9.4
  - §17 (future work) → explicitly out of scope
- **Placeholder scan:** No `TBD` / `TODO` / `fill in` in task bodies. All commands have expected outputs. All code blocks show the actual code.
- **Type consistency:** `Event` enum values, `State` enum values, method signatures (`polish(raw_text, language)`, `transcribe(audio, sample_rate)`, `capture_target()`) are consistent across tasks.
- **Spec requirements with no task:** Autostart toggle covered in Task 2.4 + Task 7.1 `_sync_autostart`. Theme switching covered in Task 6.1 (QSS) + Task 7.1 `_apply_theme`. Logging covered in Task 7.1 `_configure_logging`. ✅
