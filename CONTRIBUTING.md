# Contributing to Söyle

Thanks for your interest in improving Söyle. This guide explains how to
set up the project, make changes, and submit them upstream.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be
kind, be respectful, assume good faith.

## Quick start

```powershell
git clone https://github.com/nurgisa/soyle
cd soyle
irm https://astral.sh/uv/install.ps1 | iex   # install uv if you don't have it
uv sync --extra dev                          # install dev dependencies
uv run pytest tests/unit -v                  # run the test suite
uv run soyle                                 # launch the app
```

The minimum supported Python is 3.12 (managed automatically by `uv` via
`.python-version`).

## Project layout

```
src/soyle/
├── app.py                  Qt application wiring (lifecycle, DI, events)
├── core/                   Pure-Python domain logic (no Qt imports here)
│   ├── config.py           Pydantic settings + TOML persistence
│   ├── transcriber.py      faster-whisper wrapper
│   ├── postprocess.py      OpenRouter LLM polish client
│   └── ...
├── platform/               Win32-specific helpers (paste, autostart, hooks)
├── ui/                     PySide6 widgets, tray, indicator, settings
├── prompts/                LLM prompt templates (.md)
└── assets/                 Icons, QSS themes
installer/installer.iss     Inno Setup script (Win10/11 installer)
scripts/                    Build / diagnostic helpers
tests/                      pytest suites (unit + integration)
docs/                       Long-form docs (signing, manual tests, ...)
```

## Architecture rules of thumb

- **`core/` modules must not import Qt.** They're pure Python so unit
  tests don't need a Qt event loop. Cross-thread communication goes
  through `core/bus.py` (`EventBus`) — UI subscribes, core publishes.
- **`platform/` is Windows-only.** Each module guards `if sys.platform
  == "win32"` so static analysis doesn't break on macOS/Linux dev
  machines.
- **Constants for the brand:**
  - `APP_NAME = "Söyle"` — user-visible (tray title, toasts, window
    titles, keyring service name).
  - `APP_SLUG = "Soyle"` — filesystem paths (`%APPDATA%\Soyle\…`,
    install folder, executable).
  - Module name: `soyle` (lowercase, ASCII — Python convention).
- **No hardcoded user-visible strings outside the UI layer.** Eventually
  every user-facing string will go through `self.tr("…")` for i18n
  (Phase 3 of the roadmap). New strings should already use that pattern.

## Coding standards

- **Formatter / linter:** [`ruff`](https://docs.astral.sh/ruff/) with the
  config in `pyproject.toml`. Run `uv run ruff check .` and `uv run
  ruff format .` before pushing.
- **Type checker:** `mypy --strict` against `src/soyle/`. Run `uv run
  mypy src/`.
- **Style:** prefer explicit over clever. Comment the *why*, not the
  *what*. Existing files have a comment style worth matching.
- **Tests:** unit tests in `tests/unit/` should not require a real
  microphone, GPU, or network. Mock external boundaries with
  `pytest-mock` or `respx` (already in dev deps).

## Commit messages

Conventional Commits style:

```
feat(core): add Whisper language selector to Settings
fix(installer): correct ARM64 architecture flag for Win11
docs: clarify SignPath application steps
chore: bump faster-whisper to 1.2.2
```

Common types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`.

## Pull requests

1. Fork, branch off `main` with a descriptive name (`feature/oauth-openrouter`).
2. Make your changes in small, reviewable commits.
3. Run the full check: `uv run ruff check . && uv run mypy src/ && uv run pytest tests/unit -v`.
4. Open a PR. Fill out the template; link any related issue.
5. CI runs on every push (`.github/workflows/test.yml`). If it's red, fix it.
6. A maintainer reviews; iterate; merge.

## Filing issues

Use the issue templates in `.github/ISSUE_TEMPLATE/` — they prompt for
the info we need to reproduce. For security issues, **don't open a
public issue**; see [SECURITY.md](SECURITY.md).

## Translation contributions

Söyle ships in Kazakh, Russian, and English. Translations live under
`src/soyle/i18n/` (Phase 3, in progress). If your native language is
Kazakh and you'd like to review the kk strings for naturalness, please
open an issue with the `translation` label — it's enormously helpful.

## License

By contributing, you agree your contributions are licensed under the
project's [MIT License](LICENSE).
