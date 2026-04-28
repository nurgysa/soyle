# Söyle

> *Kazakh: «сөйле» — «speak!»*

Local Windows + Android push-to-talk dictation with Whisper + LLM polish,
designed for **Kazakh, Russian, English, and the code-switching mix that
Kazakhstanis speak every day**.

- Hold **Right Alt**, speak, release — text appears in the active window.
- Local Whisper transcription (CPU or NVIDIA GPU).
- Optional cloud LLM polish via OpenRouter (default: Gemini 2.5 Flash Lite).
- Native support for **Kazakh + Russian + English code-switching** — no need to choose one language at a time.
- Works in any Windows app that accepts `Ctrl+V`: browsers, IDEs, Telegram, Word, Claude, chat clients.

---

## Download and install

1. **Download** the latest installer from the
   [Releases page](https://github.com/nurgysa/soyle/releases/latest) —
   it's a single file called `Soyle-Setup-<version>.exe` (~300 MB).
2. **Double-click** the downloaded file.
3. If Windows shows a blue *"Windows protected your PC"* screen, click
   **More info → Run anyway**. This is normal for new apps without a
   paid code-signing certificate.
4. A small progress bar appears. When it finishes, Söyle launches
   automatically and a microphone icon appears in the system tray (near
   the clock, bottom-right of the screen).

No admin rights, no command line, no Python install required. The
installer works the same on personal PCs, work laptops, and school
computers — even when the user has no administrator password.

### First use

- Right-click the tray icon → **Settings** to paste your OpenRouter API
  key (optional — without a key the app still works, it just pastes raw
  Whisper output without polish). Get a key at
  [openrouter.ai](https://openrouter.ai/).
- Open any text field (browser, Word, Telegram, anywhere).
- Hold **Right Alt**, speak a sentence, release.
- The text appears where the cursor is.

### System requirements

- **Windows 10** (build 17763 / version 1809 or newer) or **Windows 11**,
  both x64 and ARM64.
- ~600 MB of free disk space.
- A microphone.
- Optional: an NVIDIA GPU with ≥4 GB VRAM for faster transcription.
  Without one, Söyle automatically uses the CPU.
- Optional: internet connection on first use (downloads the speech
  recognition model once, ~500 MB) and for the OpenRouter polish step.

### Configuration files

- Config: `%APPDATA%\Soyle\config.toml`
- API key: Windows Credential Manager (service `Söyle`)
- Logs: `%APPDATA%\Soyle\logs\soyle.log`

### Uninstall

Standard Windows flow: **Settings → Apps → Installed apps → Söyle
→ Uninstall**. User data (config, API key, logs) is intentionally left
behind so a re-install picks up where you left off. To wipe it too,
delete `%APPDATA%\Soyle` manually.

### Known limitations

- Classic Windows Notepad (the legacy Win32 edit control) sometimes
  ignores synthetic `Ctrl+V`. Works fine in browsers, IDEs, Word,
  Telegram, Claude, etc.
- Whisper's `large-v3-turbo` model on GPUs without tensor cores
  (GTX 16-series) can hang; default is `small` with `int8_float16`
  on CUDA, `int8` on CPU.

---

## For developers

### Install from source

```powershell
git clone https://github.com/nurgysa/soyle
cd soyle
irm https://astral.sh/uv/install.ps1 | iex
uv sync --extra dev --extra gpu   # drop --extra gpu for CPU-only
uv run python scripts/download_model.py --model small
uv run python -c "from soyle.core.config import ConfigStore; ConfigStore().set_api_key('sk-or-v1-YOUR_KEY_HERE')"
uv run soyle
```

### Build the Windows installer locally

One-time setup:

1. Install Inno Setup 6 from <https://jrsoftware.org/isdl.php> (default options).
2. `uv sync --extra dev --extra build`

Each release:

```powershell
uv run python scripts/build_installer.py
```

This runs PyInstaller (~302 MB `dist\Soyle\`), then Inno Setup's
`iscc` to produce `release\Soyle-Setup-<version>.exe`. Pass
`--rebuild` to force a fresh PyInstaller run.

### Automated releases (CI)

Pushing a git tag of the form `v*` (e.g. `v1.0.1`) triggers
[`release.yml`](.github/workflows/release.yml), which builds the
installer on a `windows-latest` runner and attaches it to the matching
GitHub Release. End users download from the Releases page — this is the
same file the local build would produce, no manual upload step.

To cut a release:

```powershell
# bump version in pyproject.toml, commit, then:
git tag v1.0.1
git push origin v1.0.1
```

The workflow finishes in ~6–10 minutes; the new `.exe` appears under
[Releases](https://github.com/nurgysa/soyle/releases).

### Installer internals

- **Per-user by default** (`PrivilegesRequired=lowest`) — installs to
  `%LocalAppData%\Programs\Söyle`, no UAC prompt. Users with
  admin can still flip to system-wide via the standard Inno Setup UAC
  dropdown or `/ALLUSERS` on the CLI (for MDM / Intune).
- **Chrome-style minimal wizard** — no welcome screen, no directory
  picker, no Tasks page, no language dialog (auto-detected). The user
  sees a progress bar and a single "Installation complete, Launch
  Söyle" checkbox.
- **Win10 1809+ / Win11, x64 + ARM64** — `MinVersion=10.0.17763`,
  `ArchitecturesAllowed=x64compatible`. No VC++ redistributable needed;
  PyInstaller bundles VCRUNTIME/MSVCP alongside the Python runtime.
- **Graceful GPU fallback** — CUDA/cuDNN are *not* bundled (would
  double the installer size). GPU acceleration requires a working
  NVIDIA driver on the target machine. If CUDA init fails,
  [`transcriber.py`](src/soyle/core/transcriber.py) falls back to
  CPU `int8` automatically.
- **`runasoriginaluser` on post-install launch** — if the user
  escalated to system-wide install, the launched app drops the admin
  token so low-level keyboard hooks can still inject into normal
  foreground apps.

### Code signing

Current installers are **unsigned** — Windows SmartScreen warns on
first download, users click *More info → Run anyway*.

To remove the warning for free (open-source projects qualify), apply
to [SignPath Foundation](https://signpath.org/apply) and follow the
step-by-step integration in [docs/signing.md](docs/signing.md). The
doc covers the application process, creating the SignPath
organization/policy, wiring four repo secrets, and the updated
`release.yml` that produces signed `.exe` artifacts.

Approval typically takes 1–2 weeks; cost is **$0/year**.

## License

MIT
