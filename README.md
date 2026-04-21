# WhisperFlow

Local Windows push-to-talk dictation with Whisper + OpenRouter polish.

## Features

- Hold RightAlt, speak, release — text appears in the active window.
- Local Whisper transcription (`faster-whisper` `small` / `large-v3-turbo`, CPU or CUDA).
- Optional cloud LLM polish via OpenRouter (default: Gemini 2.5 Flash Lite).
- Russian, English, and code-switching supported.
- Works in any Windows app that accepts `Ctrl+V`: browsers, IDEs, Telegram, Word, Claude, chat clients.

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
uv sync --extra dev --extra gpu   # drop --extra gpu for CPU-only
uv run python scripts/download_model.py --model small
uv run python -c "from whisperflow.core.config import ConfigStore; ConfigStore().set_api_key('sk-or-v1-YOUR_KEY_HERE')"
uv run whisperflow
```

The app runs in the system tray — right-click the icon for Settings / Logs / Quit.

## Configuration

- Config file: `%APPDATA%\WhisperFlow\config.toml`
- API key: stored in Windows Credential Manager (service `WhisperFlow`)
- Logs: `%APPDATA%\WhisperFlow\logs\whisperflow.log`

Default hotkey is right Alt; change it in the Settings window.

## Known limitations

- Classic Windows Notepad (legacy Win32 edit control) sometimes ignores synthetic `Ctrl+V`. Works fine in browsers, IDEs, Word, Telegram, Claude, etc.
- Transcription of large-v3-turbo on GPUs without tensor cores (GTX 16-series) can hang at segment iteration; we default to `small` with `int8_float16` on CUDA or `int8` on CPU.

## License

MIT
