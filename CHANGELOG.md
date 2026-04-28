# Changelog

All notable changes to Söyle are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Whisper language selector in Settings → Whisper (Auto / Қазақша / Русский /
  English). "Auto" lets Whisper detect per utterance; an explicit choice
  forces the language and avoids cross-language mis-detection (e.g. short
  Kazakh phrase mis-tagged as Turkish). Hot-swappable — applies on the next
  recording without restarting the app.
- LLM polish and rewrite prompts now declare Kazakh as a first-class
  language alongside Russian and English. Both prompts have an explicit
  KZ+RU+EN code-switching rule, KZ-specific filler-word list, and three
  draft Kazakh examples to anchor model behavior.

### Planned

- OpenRouter login via OAuth 2.0 PKCE — no more manual API key copy-paste.
- UI localization scaffold (Kazakh / Russian / English).
- Cross-device sync via Google Drive AppDataFolder.

## [1.0.0] — 2026-04-XX

First public release of Söyle (formerly **WhisperFlow** during private development).

### Added

- Push-to-talk dictation via Right Alt — hold to record, release to
  transcribe and paste.
- Local Whisper transcription with `faster-whisper` (`large-v3-turbo`
  default; `small` fallback for older GPUs).
- Optional cloud LLM polish via OpenRouter (Gemini 2.5 Flash Lite by
  default) for cleanup and punctuation.
- User-defined dictionary of custom terms (names, jargon) injected into
  Whisper's `initial_prompt` and the LLM polish prompt.
- System tray icon with quick mode switching (Polish / Rewrite),
  settings, logs, monthly cost summary.
- Settings window: hotkey customization, audio device, model picker,
  dictionary editor, themes (dark / light / system).
- First-run wizard that opens Settings with the API-key field focused.
- Crash handler — unhandled exceptions write a timestamped report to
  `%APPDATA%\Soyle\logs\crash-*.log` and show a user dialog.
- Per-user Windows installer (Inno Setup) — no admin required, lands in
  `%LocalAppData%\Programs\Söyle`.
- Chrome-style minimal install wizard: progress bar + Launch checkbox
  only.
- CI auto-build on tag push: pushing `vX.Y.Z` produces a signed-ready
  `.exe` on the GitHub Releases page (`.github/workflows/release.yml`).
- Comprehensive docs: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `docs/signing.md` (SignPath Foundation walkthrough),
  `docs/MANUAL_TESTS.md`.

### Platform support

- Windows 10 build 17763 (October 2018) or newer.
- Windows 11 — all versions.
- x64 native, ARM64 via x64 emulation.

### Known limitations

- Classic Windows Notepad sometimes ignores synthetic `Ctrl+V` (legacy
  Win32 edit control). All modern apps work fine.
- `large-v3-turbo` on tensor-core-less GPUs (GTX 16-series) can hang;
  app defaults to `small` with `int8_float16` on such hardware.
- Installer is currently **unsigned** — Windows SmartScreen warns on
  first download. SignPath Foundation application is in flight; future
  releases will be signed automatically.

[Unreleased]: https://github.com/nurgisa/soyle/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/nurgisa/soyle/releases/tag/v1.0.0
