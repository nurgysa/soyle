# Changelog

All notable changes to Söyle are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] — 2026-07-10

### Changed
- Signed Windows installer via SignPath Foundation (Authenticode). No more
  "Unknown publisher" / SmartScreen warning on clean machines.
- `resolve_theme("system")` falls back to **light** (not dark) when the
  OS color scheme is unknown.

### Fixed
- UI i18n: Settings tab labels (Whisper / LLM / Cloud Sync) now translate
  in Kazakh and English (were hardcoded Russian).
- Dark-theme accent button text contrast: `#0c0c1a` → `#ffffff`
  (was ~3.5:1, below WCAG AA; now ~9:1).
- Indicator: long status text (e.g. Kazakh) is elided instead of overflowing.
- Floating button: re-pins to the primary screen on monitor add/remove
  (multi-monitor / laptop+dock).
- Startup pre-flight toast when the OpenRouter API key is missing (non-first
  run) so LLM-polish outage isn't a silent surprise.

## [Unreleased]

### Planned

- OpenRouter login via OAuth 2.0 PKCE — no more manual API key copy-paste.
- Cross-device sync via Google Drive AppDataFolder.

## [1.1.0] — 2026-07-10

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
- Kazakh + Russian + English UI localization (settings language switcher,
  restart to apply).
- Dictation history: per-entry raw + polished text, persisted locally,
  toggleable in Settings.
- Redesigned HUD + floating button with design-token theming (light/dark).
- Cloud sync (Phase 1–2) via Google Drive AppDataFolder: config + usage,
  cross-device LWW merge, OAuth 2.0 PKCE.

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

[Unreleased]: https://github.com/nurgysa/soyle/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/nurgysa/soyle/releases/tag/v1.0.0
