# WhisperFlow v1 — Design Specification

| Field | Value |
|-------|-------|
| Project | WhisperFlow (Windows дом-Wispr Flow) |
| Version | 1.0.0 (MVP) |
| Date | 2026-04-19 |
| Status | Approved for implementation |
| Target platform | Windows 10/11 x64 |
| Target hardware | ASUS ROG Strix G512LI (i7-10750H, 16 GB RAM, GTX 1650 Ti 4 GB VRAM) |
| Primary languages | Russian + English (code-switching) |

---

## 1. Problem statement

Wispr Flow (wisprflow.ai) — это популярное macOS-приложение для голосовой диктовки, которое позволяет пользователю зажать клавишу, наговорить текст, и получить этот текст, вставленный в любое активное окно. На Windows нет качественного локального аналога: существующие решения либо целиком облачные (Nerdio, Dragon NaturallySpeaking за $500+), либо примитивные обёртки над Windows Speech Recognition, либо тяжёлые Electron-приложения, не влезающие на среднее железо.

Цель: построить **лёгкое локальное Windows-приложение для push-to-talk голосового ввода**, которое:

1. Работает с локальной моделью Whisper (приватность голоса, низкая задержка).
2. Использует облачный LLM (OpenRouter) для косметической постобработки текста.
3. Вставляет результат в активное окно любого приложения.
4. Помещается в ресурсы среднего игрового ноутбука (≤1.2 GB RAM, ≤2 GB VRAM в работе).

## 2. Goals

- Задержка от отпускания клавиши до появления текста ≤ 1 секунда для 5-секундной фразы.
- Качество распознавания русского + английского + code-switching выше, чем у Windows встроенного Speech Recognition.
- Отсутствие интернет-зависимости для core-функции (транскрипции); LLM-постобработка gracefully падает в fallback.
- Один exe, установленный в папку пользователя; без админ-прав; без .NET / иных рантаймов на стороне пользователя.
- Приватность: аудио никогда не покидает машину; только нормализованный текст уходит в OpenRouter при включённой постобработке.

## 3. Non-goals (v1)

- Кастомный пользовательский словарь (v2).
- Голосовые команды ("новая строка", "удалить это" — v2).
- История транскрипций с поиском (v2).
- Кроссплатформенность (только Windows 10/11 x64).
- Voice activation / always-on mode (только push-to-talk).
- Офлайн-LLM fallback (сырой Whisper-текст без постобработки — этого достаточно).
- Реальный watchdog / crash-reporter (локальные логи достаточны для v1).
- Shumopodavlenie до Whisper (сам Whisper справляется).

## 4. Constraints

### 4.1 Hardware

- **GPU:** NVIDIA GTX 1650 Ti (Turing, 4 GB VRAM, **без Tensor Cores**). Это означает: fp16-ускорение доступно, но медленнее RTX-карт; оптимально — int8-квантизация.
- **CPU:** Intel Core i7-10750H (6 cores / 12 threads, AVX2). Достаточно для CPU-fallback на `medium` или `small`.
- **RAM:** 16 GB физически, в обычной работе свободно ~2.7 GB. Приложение должно жить в пределах 1.2 GB RSS в пиковой нагрузке.
- **Storage:** Intel NVMe SSD 512 GB. Первоначальная загрузка модели (~800 MB) допустима.

### 4.2 Software

- Python 3.12.x (не 3.13 — некоторые зависимости ещё не обновились).
- Windows 10 build 19042+ (у пользователя — 19042, тестируем от этой планки).
- NVIDIA driver ≥ 530 + CUDA 12 + cuDNN 8.x для GPU-режима.

### 4.3 Runtime policy

- Никогда не блокировать Qt main thread на I/O или инференсе.
- Никогда не логировать содержимое транскрипций по умолчанию (только metadata).
- Никогда не логировать API-ключ, даже в tracebacks.
- Ни один core-модуль не импортирует Qt напрямую — только через EventBus.

---

## 5. Architecture

### 5.1 High-level component diagram

```
┌──────────────────────── WhisperFlow (Qt main thread) ────────────────────────┐
│                                                                               │
│                          ┌────────────┐                                       │
│                          │  EventBus  │  ◄──── Qt Signals (thread-safe)       │
│                          └──────┬─────┘                                       │
│                                 │                                             │
│   ┌──────────────┐       ┌──────▼───────┐       ┌─────────────────┐           │
│   │  HotkeyBox   │──────►│   Recorder   │──────►│   Transcriber   │           │
│   │ (bg thread)  │ start/│  (bg thread) │ wav   │  (bg thread)    │           │
│   └──────────────┘ stop  │ sounddevice  │ bytes │ faster-whisper  │           │
│                          │  + VAD trim  │       │    CUDA/int8    │           │
│                          └──────┬───────┘       └────────┬────────┘           │
│                                 │                        │ raw text           │
│                                 │                        ▼                    │
│                                 │                ┌───────────────┐            │
│                                 │                │  PostProcess  │            │
│                                 │                │  (async/httpx)│──► OpenRouter
│                                 │                └───────┬───────┘            │
│                                 │                        │ polished text      │
│                                 │                        ▼                    │
│                                 │                ┌───────────────┐            │
│                                 │                │   Injector    │──► active window
│                                 │                │  clipboard+V  │    (Win32 SendInput)
│                                 │                └───────────────┘            │
│                                 ▼                                             │
│                          ┌──────────────┐       ┌─────────────────┐           │
│                          │   Indicator  │       │   SettingsUI    │           │
│                          │  (Qt widget) │       │  (Qt window +   │           │
│                          │  pill+wave   │       │    tray menu)   │           │
│                          └──────────────┘       └────────┬────────┘           │
│                                                          │                    │
│                                                  ┌───────▼───────┐            │
│                                                  │  ConfigStore  │            │
│                                                  │  TOML+keyring │            │
│                                                  └───────────────┘            │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Module inventory

| Модуль | Файл | Ответственность | Ключевые зависимости |
|--------|------|-----------------|----------------------|
| EventBus | `core/bus.py` | Qt-based шина событий | `PySide6` |
| HotkeyBox | `core/hotkey.py` | Глобальный хоткей listener | `keyboard` |
| Recorder | `core/recorder.py` | Захват аудио + VAD-обрезка | `sounddevice`, `numpy`, `silero-vad` |
| Transcriber | `core/transcriber.py` | Whisper инференс (singleton) | `faster-whisper` |
| PostProcess | `core/postprocess.py` | OpenRouter HTTP-клиент | `httpx` |
| Injector | `core/injector.py` | Clipboard+Ctrl+V с save/restore | `pywin32`, `pyperclip` |
| ConfigStore | `core/config.py` | TOML + Credential Manager | `tomli`, `tomli_w`, `keyring`, `pydantic` |
| StateMachine | `core/state.py` | State transitions | — |
| Indicator | `ui/indicator.py` | Frameless pill overlay | `PySide6` |
| SettingsUI | `ui/settings.py` | Главное окно настроек | `PySide6` |
| Tray | `ui/tray.py` | QSystemTrayIcon + menu | `PySide6` |
| Platform adapters | `platform/*.py` | Win32-specifics | `pywin32` |
| App | `app.py` | Entry point, lifecycle | всё выше |

### 5.3 Isolation principle

Каждый core-модуль — чистый Python-класс без UI-зависимостей. Общение только через EventBus (Qt signals, thread-safe). Это обеспечивает:

- UI можно менять без трогать ML.
- ML-ядро unit-тестируется без GUI.
- Подмена Qt на CLI-прототип возможна без изменения ядра.

## 6. Data flow

### 6.1 Golden path: hotkey press → text injected

```
t=0мс      │ RightAlt press
           │ HotkeyBox.on_press() → EventBus.emit(HOTKEY_PRESSED)
           ▼
t=1мс      │ Recorder создаёт sounddevice.InputStream (16 kHz, mono, float32)
           │ Indicator показывает pill: "● Recording 0:00" + live waveform
           │ Beep (80мс, 440 Hz), если sound_enabled
           ▼
t=1..TALK  │ Recorder накапливает frames в queue; RMS уровень → AUDIO_LEVEL каждые 100мс
           ▼
t=TALK     │ RightAlt release
           │ HotkeyBox.on_release() → EventBus.emit(HOTKEY_RELEASED)
           │ Beep (60мс, 660 Hz)
           │ Recorder закрывает stream, склеивает frames в np.ndarray
           ▼
t=+1мс     │ Silero VAD trim: обрезка тишины в начале/конце
           │ Если speech_ms < 300 → RECORDING_STOPPED (duration_ms=0), STOP pipeline
           │ Indicator показывает "⏳ Transcribing..."
           ▼
t=+50мс    │ Transcriber.transcribe(audio) — на QThreadPool worker
           │ faster-whisper large-v3-turbo int8, beam_size=5, language=None, vad_filter=True
           │ Expected: 150–400мс для 3.5 сек на GTX 1650 Ti
           ▼
t=+400мс   │ TRANSCRIPT_READY (raw_text, language)
           │ Indicator "✨ Polishing..."
           │ PostProcess.polish(raw, lang) — async httpx POST → OpenRouter
           ▼
t=+600мс   │ POLISH_READY (text, fallback=False)
           ▼
t=+601мс   │ Injector.inject(text, target_hwnd=captured_at_record_start):
           │   1. backup = pyperclip.paste()
           │   2. pyperclip.copy(text)
           │   3. sleep(20ms)  # дать clipboard зарегистрироваться
           │   4. Win32.SendInput(Ctrl+V)
           │   5. QTimer.singleShot(200ms, lambda: pyperclip.copy(backup))
           ▼
t=+800мс   │ INJECTED (success=True)
           │ Indicator fade-out 150мс
           │ StateMachine → IDLE
```

### 6.2 Target latency budget

| Этап | Budget | Notes |
|------|--------|-------|
| Recording → stop | пользовательский | 2–10 сек типично |
| VAD trim | 30мс | CPU-bound |
| Whisper transcription | 150–400мс | GPU int8 |
| OpenRouter polish | 200–400мс | Gemini 2.5 Flash Lite |
| Clipboard + paste | 50мс | включая 20мс sleep |
| **Dead air после release** | **≤ 900мс** | цель |

### 6.3 Threading model

| Поток | Кто создаёт | Что делает |
|-------|------------|-----------|
| Main (Qt) | Python start | Event loop, UI updates, EventBus dispatch |
| Hotkey listener | `keyboard.start_listening` | Блокирующий listen на глобальный хоткей |
| sounddevice callback | драйвер PortAudio | Пишет frames в `queue.Queue` |
| Inference worker | `QThreadPool.globalInstance()` | Whisper + OpenRouter для одной записи (последовательно) |
| Clipboard restore | `QTimer.singleShot` | Восстановление через 200мс (в main thread) |

**Правило:** core-модули никогда не трогают Qt-виджеты напрямую. Только EventBus.

### 6.4 State machine

```
          ┌────────┐   hotkey press   ┌───────────┐
          │  IDLE  │─────────────────►│ RECORDING │
          └────────┘                  └─────┬─────┘
              ▲                             │ hotkey release
              │                             ▼
              │                       ┌──────────────┐
              │                       │ TRANSCRIBING │
              │                       └──────┬───────┘
              │                              │ whisper done
              │                              ▼
              │                       ┌───────────┐
              │  polish done +        │ POLISHING │
              │  paste done           └─────┬─────┘
              │                             │
              │                             ▼
              │                       ┌───────────┐
              └───────────────────────│ INJECTING │
                                      └───────────┘
```

Hotkey в любом state ≠ IDLE игнорируется. Любая ошибка → возврат в IDLE + ERROR event.

## 7. Module contracts

### 7.1 Event catalog

```python
class Event(StrEnum):
    HOTKEY_PRESSED = "hotkey.pressed"       # {}
    HOTKEY_RELEASED = "hotkey.released"     # {}
    RECORDING_STARTED = "recording.started" # {sample_rate: int}
    AUDIO_LEVEL = "audio.level"             # {rms: float}            (каждые 100мс)
    RECORDING_STOPPED = "recording.stopped" # {audio: ndarray, duration_ms: int}
    TRANSCRIBING = "transcribing"           # {}
    TRANSCRIPT_READY = "transcript.ready"   # {raw: str, lang: str, duration_ms: int}
    POLISHING = "polishing"                 # {}
    POLISH_READY = "polish.ready"           # {text: str, fallback: bool, cost_usd: float}
    INJECTING = "injecting"                 # {target_hwnd: int}
    INJECTED = "injected"                   # {success: bool}
    ERROR = "error"                         # {code: str, message: str, module: str, recoverable: bool}
    STATE_CHANGED = "state.changed"         # {from: State, to: State}
```

### 7.2 Public module interfaces

**Recorder**
```python
class Recorder:
    def start(self, sample_rate: int = 16000, device: str = "default") -> None: ...
    def stop(self) -> RecordingResult: ...
    # RecordingResult: {audio: np.ndarray, duration_ms: int, rms_peak: float}
    # emits: RECORDING_STARTED, AUDIO_LEVEL, RECORDING_STOPPED, ERROR
    # throws: AudioDeviceError, PermissionDeniedError
```

**Transcriber** (singleton, модель грузится при старте)
```python
class Transcriber:
    def __init__(self, model: str, device: str, compute_type: str) -> None: ...
    def warm_up(self) -> None: ...
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> TranscriptResult: ...
    # TranscriptResult: {raw_text: str, language: str, segments: list, duration_ms: int}
    # emits: TRANSCRIBING, TRANSCRIPT_READY, ERROR
    # throws: ModelNotLoadedError, CudaUnavailableError, CudaOOMError
```

**PostProcess**
```python
class PostProcess:
    async def polish(self, raw_text: str, language: str) -> PolishResult: ...
    # PolishResult: {text: str, fallback: bool, tokens_in: int, tokens_out: int,
    #                cost_usd: float, latency_ms: int}
    # fallback=True: OpenRouter упал → text == raw_text
    # emits: POLISHING, POLISH_READY, ERROR (recoverable=True)
    # DOES NOT throw — всегда возвращает результат
```

**Injector**
```python
class Injector:
    def capture_target(self) -> int: ...  # сохраняет HWND активного окна
    def inject(self, text: str, target_hwnd: int) -> InjectResult: ...
    # InjectResult: {success: bool, method: Literal["paste","keystroke"], target_changed: bool}
    # target_changed=True → текст в буфере, Ctrl+V НЕ нажат
    # emits: INJECTING, INJECTED, ERROR
```

**ConfigStore**
```python
class ConfigStore:
    def load(self) -> Config: ...          # pydantic model
    def save(self, config: Config) -> None: ...
    def get_api_key(self) -> str | None: ...  # Windows Credential Manager
    def set_api_key(self, key: str) -> None: ...
    def reset_to_defaults(self) -> None: ... # backup старого в config.toml.broken-{ts}
```

**StateMachine**
```python
class StateMachine:
    current: State  # IDLE | RECORDING | TRANSCRIBING | POLISHING | INJECTING
    def can_start_recording(self) -> bool: ...
    def transition(self, to: State) -> None: ...
```

## 8. Error handling

### 8.1 Input errors (before recording)

| Ситуация | Обработка |
|----------|-----------|
| Хоткей занят | Tray notification + форсированное открытие SettingsUI |
| Нет микрофона | Фатальный диалог на старте |
| Windows отозвал разрешение мика | Ссылка на `ms-settings:privacy-microphone` |
| Устройство мика исчезло | Fallback на system default + тост |

### 8.2 Recording errors

| Ситуация | Обработка |
|----------|-----------|
| Release <300мс после press | VAD → пусто → `flash_error("Слишком коротко")`, Whisper НЕ вызывается |
| Только тишина | Аналогично |
| Запись >60 сек | Soft-limit: до 90 сек, затем принудительный stop |
| Hotkey debounce (<50мс) | Игнорируем release если press был <150мс назад |

### 8.3 Whisper / GPU errors

| Ситуация | Обработка |
|----------|-----------|
| CUDA недоступна | Fallback на `device="cpu"` + `compute_type="int8"` + тост |
| VRAM exhausted | Retry на CPU; если и CPU не тянет — ошибка в трее |
| Модель не скачана / corrupted | Auto-download с progress dialog; SHA256 верификация; ≤3 retry |
| Галлюцинации ("Subscribe!") | VAD pre-filter + post-filter: >3 повторов одной фразы → пустота |
| Empty output | `flash_error("Ничего не распознано")`, OpenRouter НЕ вызывается |

### 8.4 OpenRouter errors

| Ситуация | Обработка |
|----------|-----------|
| Нет интернета | Вставляем raw Whisper-текст + `⚠ offline` 3 сек |
| 401 Unauthorized | Тост + SettingsUI, fallback на raw text |
| 429 Rate limit | Exponential backoff 500мс/1с/2с, затем raw text |
| 5xx | 2 retry × 500мс, затем raw text |
| Timeout >5s | Отмена, raw text |
| LLM отказ ("I can't help") | Heuristic: output *3 длиннее или содержит отказные фразы → raw text |
| LLM переписала смысл | Защита через системный промпт + temperature=0 + unit-тесты регресса |

### 8.5 Injection errors

| Ситуация | Обработка |
|----------|-----------|
| Target window изменился | HWND проверка: текст в буфер, Ctrl+V НЕ нажимается + тост |
| Read-only поле | Текст остаётся в буфере для ручной вставки |
| Clipboard locked | 3 retry × 50мс, fallback на keystroke simulation |
| Ctrl+V перехвачен IDE | Через 500мс если текст не появился — тост |

### 8.6 Config / persistence

| Ситуация | Обработка |
|----------|-----------|
| Битый config.toml | Backup `*.broken-{ts}` + реинициализация + тост |
| Credential Manager недоступен | Fallback на Fernet + DPAPI machine-guid |
| Несколько экземпляров | Named mutex; второй открывает SettingsUI первого и выходит |

### 8.7 Lifecycle

| Ситуация | Обработка |
|----------|-----------|
| Сон Windows во время записи | `WM_POWERBROADCAST` → принудительный stop |
| USB-мик выдернут | sounddevice error → stop + тост |
| Процесс крэш | Tray пропадает, молча умирает; пользователь перезапускает |

## 9. Testing strategy

### 9.1 Coverage targets

- Pure logic (bus, config, postprocess, state, injector helpers): **≥90%** через pytest + TDD.
- Whisper integration: фиксированные WAV → `SequenceMatcher.ratio() > 0.85` от эталона.
- UI, global hotkey, OS integration: **manual smoke checklist** перед релизом.

### 9.2 Automated tests

| Модуль | Тип | Проверяем |
|--------|-----|-----------|
| ConfigStore | unit | Дефолты, миграция, битый TOML, keyring mock |
| PostProcess | unit + `respx` | Корректность промпта, retry-логика, 401/429/5xx fallback, timeout, детекция галлюцинаций |
| Transcriber (filters) | unit | Повторы, нормализация, empty handling |
| Transcriber (model) | integration `@pytest.mark.gpu` | WAV fixtures → ratio >0.85 |
| EventBus | unit + pytest-qt | Subscribe, thread-safety, order |
| Recorder (VAD trim) | unit | Обрезка, short→empty, long→full |
| Injector (clipboard) | unit + mock | Save/paste/restore через 200мс |

### 9.3 Fixtures

```
tests/fixtures/audio/
├── short_ru.wav          # "Привет, как дела", 2 сек, 16 kHz mono
├── short_en.wav          # "Hello world how are you", 2 сек
├── mixed.wav             # "Сегодня я deploy'ил новый feature", 3.5 сек
├── silence.wav           # 2 сек тишины
├── hallucination.wav     # тихий фон → тест защиты от "Subscribe!"
└── expected.json         # эталонный текст + допустимая погрешность
```

### 9.4 Manual smoke checklist

Полный список в `docs/MANUAL_TESTS.md`; обязательный минимум перед релизом:

```
[ ] Свежий билд на чистой Windows VM
[ ] Первый запуск: модель скачалась с progress
[ ] RightAlt hold → pill у курсора → waveform
[ ] Release → текст в Notepad за <1с
[ ] RU speech → правильная пунктуация
[ ] EN speech → правильная капитализация
[ ] Code-switching → смесь сохраняется
[ ] Offline → raw text + тост
[ ] Bad API key → тост + raw text
[ ] Смена хоткея → старый не работает, новый работает
[ ] Закрытие окна → живёт в трее
[ ] Tray меню: Open/Settings/Quit
[ ] Quit → процесс завершается, exe удаляемый
```

### 9.5 Logging

**Путь:** `%APPDATA%\WhisperFlow\logs\whisperflow.log` (rotating, 5 файлов × 5 MB).

**Формат:** structlog JSON renderer:
```json
{"ts":"2026-04-19T10:23:45Z","lvl":"info","mod":"transcriber","event":"done","dur_ms":284,"lang":"ru","chars":42}
```

**Логируем:** старт/стоп записи, Whisper метаданные (model, device, duration, lang, tokens), OpenRouter (model, latency, tokens, cost), все ошибки с traceback, critical события (GPU fallback, hotkey conflict).

**НЕ логируем:** полные тексты транскрипций (только hash + length), API-ключ.

**Опционально:** `transcriptions.jsonl` — полные тексты, toggle в настройках, off by default.

**Tray menu → "Показать логи"** открывает текущий log-файл в Блокноте.

### 9.6 Runtime stats (vкладка "Статистика")

- Транскрипций за сегодня / всё время.
- Средняя латентность инференса.
- % fallback-ов OpenRouter.
- Примерная стоимость за месяц.

## 10. Repository structure

```
Windows Whisper Flow/
├── pyproject.toml
├── README.md
├── LICENSE                           # MIT
├── .python-version                   # 3.12.7
├── .gitignore
├── .env.example
│
├── src/whisperflow/
│   ├── __init__.py                   # __version__
│   ├── __main__.py                   # python -m whisperflow
│   ├── app.py                        # Qt entry point
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── bus.py                    # EventBus
│   │   ├── config.py                 # ConfigStore
│   │   ├── hotkey.py                 # HotkeyBox
│   │   ├── recorder.py               # Recorder
│   │   ├── transcriber.py            # Transcriber
│   │   ├── postprocess.py            # PostProcess
│   │   ├── injector.py               # Injector
│   │   ├── state.py                  # StateMachine
│   │   └── errors.py                 # Домен-exceptions
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── indicator.py              # Pill overlay
│   │   ├── settings.py               # Главное окно
│   │   ├── tray.py                   # QSystemTrayIcon
│   │   ├── resources.py              # Загрузчик assets
│   │   └── qss/
│   │       ├── dark.qss
│   │       └── light.qss
│   │
│   ├── platform/
│   │   ├── __init__.py
│   │   ├── autostart.py              # HKCU\...\Run registry
│   │   ├── window.py                 # GetForegroundWindow
│   │   ├── paste.py                  # SendInput(Ctrl+V)
│   │   └── single_instance.py        # named mutex
│   │
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── polish_v1.md
│   │   └── README.md
│   │
│   └── assets/
│       ├── icon.ico
│       ├── icon_recording.ico
│       ├── beep_start.wav
│       └── beep_stop.wav
│
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── audio/
│   │   │   ├── short_ru.wav
│   │   │   ├── short_en.wav
│   │   │   ├── mixed.wav
│   │   │   ├── silence.wav
│   │   │   ├── hallucination.wav
│   │   │   └── expected.json
│   │   └── config/
│   │       ├── valid.toml
│   │       └── broken.toml
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_bus.py
│   │   ├── test_postprocess.py
│   │   ├── test_state.py
│   │   └── test_injector.py
│   └── integration/
│       ├── test_transcriber_gpu.py
│       └── test_transcriber_cpu.py
│
├── scripts/
│   ├── download_model.py
│   ├── download_cudnn.py
│   ├── build_exe.py
│   └── bump_version.py
│
├── docs/
│   ├── superpowers/specs/2026-04-19-whisperflow-design.md
│   ├── MANUAL_TESTS.md
│   ├── ARCHITECTURE.md
│   ├── TROUBLESHOOTING.md
│   └── PROMPT_ITERATION.md
│
└── .github/workflows/
    ├── test.yml
    └── release.yml
```

## 11. Dependencies

### 11.1 Runtime

| Package | Version | Reason |
|---------|---------|--------|
| `pyside6` | `>=6.8.0` | Qt GUI, tray, signals |
| `faster-whisper` | `>=1.1.0` | Whisper через CTranslate2 |
| `sounddevice` | `>=0.5.0` | Микрофон через PortAudio |
| `numpy` | `>=2.1.0` | Аудио-буферы |
| `silero-vad` | `>=5.1.0` | VAD trim |
| `keyboard` | `>=0.13.5` | Глобальный хоткей |
| `pywin32` | `>=308` | Win32 API |
| `pyperclip` | `>=1.9.0` | Clipboard |
| `keyring` | `>=25.5.0` | Credential Manager |
| `httpx` | `>=0.28.0` | OpenRouter клиент |
| `pydantic` | `>=2.10.0` | Валидация config |
| `tomli` / `tomli-w` | `>=2.2.0` / `>=1.1.0` | TOML |
| `structlog` | `>=24.4.0` | Логирование |
| `platformdirs` | `>=4.3.0` | %APPDATA% путь |

### 11.2 Dev

| Package | Version | Reason |
|---------|---------|--------|
| `pytest` | `>=8.3.0` | Test runner |
| `pytest-qt` | `>=4.4.0` | Qt signals тестирование |
| `pytest-asyncio` | `>=0.24.0` | Async tests |
| `pytest-xdist` | `>=3.6.0` | Параллельный запуск |
| `pytest-mock` | `>=3.14.0` | Mocks |
| `respx` | `>=0.22.0` | httpx mocking |
| `ruff` | `>=0.8.0` | Linter + formatter |
| `mypy` | `>=1.13.0` | Static types |
| `pre-commit` | `>=4.0.0` | Git hooks |

### 11.3 Build

| Package | Version | Reason |
|---------|---------|--------|
| `pyinstaller` | `>=6.11.0` | Exe-сборка |

### 11.4 External requirements

- **Python 3.12.x** (≥3.12.0, <3.13 — часть deps не поддерживает 3.13 на момент написания).
- **NVIDIA driver ≥530** (для CUDA 12 runtime).
- **cuDNN 8.x** — скачивается отдельно через `scripts/download_cudnn.py`; для билда включается в exe через PyInstaller `--add-binary`.

## 12. Configuration

### 12.1 Location

- Config TOML: `%APPDATA%\WhisperFlow\config.toml` (через `platformdirs.user_config_dir`).
- API key: Windows Credential Manager (`service="WhisperFlow", username="openrouter"`).
- Logs: `%APPDATA%\WhisperFlow\logs\`.
- Model cache: `%APPDATA%\WhisperFlow\models\` (faster-whisper default override).

### 12.2 Default config

```toml
version = 1

[hotkey]
combination = "right alt"           # keyboard-lib synтаксис
mode = "push_to_talk"               # или "toggle"
debounce_ms = 150

[audio]
device = "default"
sample_rate = 16000
vad_enabled = true
vad_min_speech_ms = 300
max_recording_seconds = 90

[whisper]
model = "large-v3-turbo"
device = "auto"                     # "auto" | "cuda" | "cpu"
compute_type = "int8"               # int8 | float16 | float32
beam_size = 5
language = null                     # null = auto-detect

[postprocess]
enabled = true
provider = "openrouter"
model = "google/gemini-2.5-flash-lite"
timeout_seconds = 5
retries = 3
temperature = 0.0
prompt_file = "polish_v1.md"

[ui]
indicator_position = "cursor"       # "cursor" | "tray_only"
indicator_follow_mouse = true
theme = "dark"                      # "dark" | "light" | "system"
sound_enabled = true

[behavior]
autostart = false
check_updates = true
log_transcriptions = false
inject_method = "clipboard"         # "clipboard" | "keystroke"
```

## 13. LLM prompt

Файл: `src/whisperflow/prompts/polish_v1.md`. Промпт — артефакт кода: версионируется, тестируется, итерируется через A/B в отдельной ветке.

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

**Вызов OpenRouter:**
```python
{
  "model": "google/gemini-2.5-flash-lite",
  "messages": [
    {"role": "system", "content": <polish_v1.md>},
    {"role": "user", "content": json.dumps({"language": lang, "text": raw})}
  ],
  "temperature": 0.0,
  "max_tokens": min(len(raw_tokens) * 2, 1024),
}
```

## 14. Build order

Зависимости идут снизу вверх. TDD: для каждого core-слоя сначала тесты, потом реализация. UI — без автотестов, только manual.

| Слой | Модули |
|------|--------|
| 0 — foundation | `errors.py`, `state.py`, `bus.py`, `config.py` |
| 1 — OS adapters | `platform/autostart.py`, `platform/window.py`, `platform/paste.py`, `platform/single_instance.py` |
| 2 — core | `recorder.py`, `injector.py` |
| 3 — ML | `transcriber.py`, `postprocess.py` |
| 4 — input | `hotkey.py` |
| 5 — UI | `ui/indicator.py`, `ui/settings.py`, `ui/tray.py`, `ui/resources.py` |
| 6 — app | `app.py` |
| 7 — dist | `scripts/download_model.py`, `scripts/download_cudnn.py`, `scripts/build_exe.py` |

## 15. Build & distribution

`scripts/build_exe.py` использует PyInstaller:

```
pyinstaller --onedir
            --windowed
            --icon=src/whisperflow/assets/icon.ico
            --name WhisperFlow
            --add-data "src/whisperflow/assets;assets"
            --add-data "src/whisperflow/prompts;prompts"
            --add-data "src/whisperflow/ui/qss;qss"
            --add-binary "vendor/cudnn/*.dll;."
            --collect-all faster_whisper
            --collect-all silero_vad
            src/whisperflow/app.py
```

Результат: `dist/WhisperFlow/` — папка ~400 MB без модели. Модель (800 MB) скачивается при первом запуске. Размер установщика ≤500 MB (цель).

На v1 — не делаем Inno Setup / MSI инсталлер: пользователь запускает exe из папки.

## 16. Acceptance criteria

### Functional

- [ ] End-to-end: hotkey hold → speech → text injected в активное окно за ≤1 сек.
- [ ] 30 последовательных транскрипций без крэша, без роста RSS >100 MB.
- [ ] Изменение настроек вступает в силу без перезапуска (кроме смены модели Whisper).
- [ ] Offline: raw Whisper-текст вставляется, тост появляется.
- [ ] Manual smoke checklist (§9.4) пройден полностью.

### Non-functional

- [ ] Mean latency от release до inject ≤ 900мс для 5-сек речи.
- [ ] RSS idle ≤ 500 MB, peak ≤ 1.2 GB.
- [ ] VRAM ≤ 2 GB с `large-v3-turbo` int8.
- [ ] Размер установки ≤ 500 MB (без модели).

### Quality

- [ ] `ruff check .` + `mypy src/` зелёные.
- [ ] Coverage pure-logic ≥ 90%.
- [ ] Integration tests проходят на GPU и CPU targets.

## 17. Future work (v2+)

- Кастомный словарь: dynamic initial_prompt для Whisper + post-dictionary замены в LLM.
- Голосовые команды: LLM распознавание intent-ов ("новая строка", "удали это", "новый абзац").
- История транскрипций: SQLite, поиск full-text, экспорт в Markdown.
- Персонализация: fine-tune промпта под стиль пользователя (retrieval из последних N транскрипций).
- Мульти-профили: разные хоткеи/модели/промпты для разных контекстов (email / code / заметки).
- Installer: Inno Setup / MSIX.
- Опциональный Sentry для crash-reports (opt-in).

---

## Appendix A — Risks and mitigations

| Риск | Вероятность | Impact | Mitigation |
|------|------------|--------|-----------|
| `keyboard` lib требует админ-прав на некоторых конфигурациях | Средняя | High | Документируем; готовим fallback на `pynput` за второй итерацией |
| cuDNN DLL не включились в PyInstaller build | Средняя | High | Явный `--add-binary`; smoke-тест на чистой Windows VM перед релизом |
| Gemini 2.5 Flash Lite цензурит безобидный ввод | Низкая | Medium | Fallback на raw text + heuristic detection в PostProcess |
| GTX 1650 Ti OOM при параллельном использовании GPU (игра) | Средняя | Medium | Try/except CudaOOMError → fallback на CPU runtime |
| Пользователь обновил Windows и сбросил Credential Manager | Низкая | Medium | Диалог повторного ввода API-ключа при 401 |
| faster-whisper ломает совместимость между minor-версиями | Низкая | Medium | Pin точной minor-версии в pyproject, обновление через dedicated PR |

## Appendix B — Open questions (не блокирующие v1)

1. **Горячая замена модели** без перезапуска — нужна ли в v1? (Сейчас требует рестарт. Решение: документировать, обсудить в v2.)
2. **Multi-monitor behaviour для Indicator:** pill появляется у курсора — корректно ли на HiDPI-экранах и нескольких мониторах? Проверяем в manual smoke.
3. **Локализация UI** — ru/en или только ru? Решение: v1 — только ru (пользователь русскоязычный), v2 — i18n через Qt Linguist.
