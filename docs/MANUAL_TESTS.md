# Manual Smoke Tests

Run this checklist before each release. Do NOT release if anything fails.

## Prerequisites

- [ ] Fresh Windows 10/11 x64 VM or test machine
- [ ] Valid OpenRouter API key installed (`ConfigStore().set_api_key(...)`)
- [ ] Working microphone (RMS > 0.03 when speaking — check with `scripts/diag_e2e.py`)

## Install & launch

- [ ] `uv sync --extra dev --extra gpu` completes without errors
- [ ] `uv run python scripts/download_model.py --model small` completes
- [ ] `uv run whisperflow` launches; console blocks (event loop running)
- [ ] Tray icon appears in system tray within 10 seconds of launch

## Core flow

- [ ] Right-click tray → menu: Settings, Logs, Quit all visible
- [ ] Click "Settings" → window opens
- [ ] Close settings — app keeps running
- [ ] Open a text editor (Claude chat input, VS Code, or browser form)
- [ ] Click into the text area
- [ ] Hold RightAlt → pill "● Recording" appears near cursor
- [ ] Pill shows live waveform during speech
- [ ] Release after ~3 sec → pill cycles "Transcribing…" → "Polishing…" → hidden
- [ ] Dictated text appears in the target field
- [ ] Total dead air after release ≤ 1 second on GPU, ≤ 4 seconds on CPU

## Language quality

- [ ] Pure Russian: "Привет это тестовая фраза" → correctly capitalized with period
- [ ] Pure English: "Hello world how are you" → capitalised first letter, punctuation added
- [ ] Code-switching: "Нужно задеплоить на staging" → both languages preserved

## Edge cases

- [ ] Hotkey release under 300 ms → pill shows "Слишком коротко", no paste
- [ ] Speaking into muted mic → pill shows "Ничего не распознано", no paste
- [ ] Disconnect internet → raw Whisper text pasted anyway; tray toast "LLM недоступна"
- [ ] Bad API key → tray toast "ключ невалиден", fallback to raw text
- [ ] Switch focus to a different window between recording and paste end →
      text appears in the ORIGINAL target (HWND guard); if target changed, text
      is copied to clipboard for manual Ctrl+V

## Settings

- [ ] Change hotkey combination, save → new hotkey works, old one does not
- [ ] Enter API key in Settings → saved, placeholder shows "••••••• (ключ сохранён)"
- [ ] Enable autostart → reboot → app starts with Windows
- [ ] Disable autostart → reboot → app does not autostart

## Stability

- [ ] 30 consecutive transcriptions without crash
- [ ] RAM growth under 100 MB over 30 cycles (check Task Manager)
- [ ] VRAM ≤ 2 GB with `small` + `int8_float16` on CUDA

## Shutdown

- [ ] Tray → Quit → process terminates cleanly
- [ ] exe / pycache / venv can be deleted after quit (no locks held)

## Known quirks (not blockers)

- Classic Notepad can ignore synthetic Ctrl+V. Verified: works in Claude, Chrome,
  Firefox, VS Code, Telegram, Word, Cursor, PyCharm.
- `large-v3-turbo` on GTX 1650 Ti hangs during segment iteration. Use `small`.
