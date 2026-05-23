# Manual Smoke Tests

Run this checklist before each release. Do NOT release if anything fails.

## Prerequisites

- [ ] Fresh Windows 10/11 x64 VM or test machine
- [ ] Valid OpenRouter API key installed (`ConfigStore().set_api_key(...)`)
- [ ] Working microphone (RMS > 0.03 when speaking — check with `scripts/diag_e2e.py`)

## Install & launch

- [ ] `uv sync --extra dev --extra gpu` completes without errors
- [ ] `uv run python scripts/download_model.py --model small` completes
- [ ] `uv run soyle` launches; console blocks (event loop running)
- [ ] Tray icon appears in system tray within 10 seconds of launch

## Core flow

- [ ] Right-click tray → menu: Settings, Logs, Quit all visible
- [ ] Click "Settings" → window opens
- [ ] Close settings — app keeps running
- [ ] Open a text editor (Claude chat input, VS Code, or browser form)
- [ ] Click into the text area
- [ ] Hold RightAlt → pill "● Recording" appears near cursor
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

## Code-switching и казахский

Сценарии проверяют, что KZ-распознавание и KZ-сохранение работают
во всём пайплайне Whisper → LLM. Используйте реальный микрофон —
audio-первый pipeline единственный способ протестировать Whisper-слой.
Без аудио можно тестировать только LLM-слой (например, через REPL:
`asyncio.run(PostProcess(...).polish(text=..., language='kk'))`).

### A. Pure KZ recognition (Whisper layer)

- [ ] Произнесите: "Бүгін кешке үйде боламын".
      Распознать должен: букву **Қ/Ң/Ө/Ү/Ұ/Һ/І** не теряя; никаких подстановок RU-фонетики.
- [ ] Произнесите: "Қазақстанда қаншама уақыт өмір сүрдің?"
      Должен сохранить вопросительную интонацию + KZ-буквы.
- [ ] Произнесите: "Алматыдан Астанаға поездбен жүрдім."
      Должен сохранить KZ-падежи (-дан ablative, -ға dative).

### B. KZ + English code-switching

- [ ] Произнесите: "Бұл feature-ды staging-ке push етеміз."
      Должен сохранить английские слова латиницей + KZ-суффиксы (-ды accusative, -ке dative).
- [ ] Произнесите: "Pull request жасадым, code review керек."
      Должен сохранить EN-имена существительные + KZ-глаголы.
- [ ] Произнесите: "GitHub-қа commit-ті push етіп жатырмын."
      Множественные EN-сущ + KZ-глаголы.

### C. KZ + Russian code-switching

- [ ] Произнесите: "Документке тапсырманы жазып қойдым."
      Должен сохранить RU-stem "документ" + KZ-падеж (-ке dative), не транскрибировать в KZ-фонетику.
- [ ] Произнесите: "Сосын совещаниеге барамын."
      RU-сущ "совещание" + KZ-падеж (-ге dative).

### D. LLM polish сохраняет KZ во всех 5 modes

Прогоните ОДИН и тот же KZ-доминантный input через каждый mode и проверьте,
что ни один не "нормализует" KZ → RU:

Прогоните этот input через каждый из 5 LLM modes по очереди и проверьте output:

> Input: "анау мынау бұл функцияда баг бар сонымен fix қылу керек ертеңге дейін"

- [ ] **polish** → "Бұл функцияда баг бар, fix қылу керек ертеңге дейін." (filler-stripping, KZ stays KZ)
- [ ] **rewrite** → реорганизация остаётся KZ. Например: "Бұл функцияда баг бар — fix қылу керек ертеңге дейін."
- [ ] **ai_prompt** → должен превратить в KZ-инструкцию ("Fix қыл мына функцияны…")
- [ ] **plain_text** → KZ prose, не RU translation
- [ ] **task** → input без priority/department cues, поэтому output может быть неполным; главное — "Задача"/"Описание" остаются KZ, не транслируются в RU.

### E. Regression: pure-RU остался прежним

- [ ] Произнесите старую тестовую фразу: "Привет это тестовая фраза"
      Распознавание и polish должны быть так же хороши, как до изменений.
      (Это страховка от R1 — добавление KZ в initial_prompt не должно ухудшать pure-RU recognition.)

### F. Regression: pure-EN остался прежним

- [ ] Произнесите: "Hello world how are you doing today"
      Pure-EN recognition + polish без регрессий.
      (Если этот чек проседает — initial_prompt смещает auto-detect, нужно откатить
      `as_whisper_prompt()` к старому формату или поменять порядок Languages-списка.)

## Cloud Sync (Phase 1)

These checks supplement `tests/unit/test_cloud_sync.py` (≥50 unit tests).
They cover behaviors that depend on real OAuth, real Drive, real Windows,
or real PyInstaller bundles — none of which are practical to automate.

### Pre-conditions

> **⚠ Gate:** If `_GOOGLE_CLIENT_ID` in `src/soyle/app.py` is still the
> placeholder `"REPLACE_WITH_REAL_CLIENT_ID..."`, **skip all of section
> A–E and F.1/F.2/F.4/F.5 below — they require a real OAuth client**.
> The single check that works with the placeholder is **F.3
> (Placeholder client_id)** — it asserts the expected `RuntimeError`
> + `cloud_sync_client_id_not_configured` warning fail-fast path.

- [ ] Real Google account with Drive enabled and quota < 100% used
- [ ] `_GOOGLE_CLIENT_ID` in `src/soyle/app.py` replaced with a real Desktop-app
      OAuth client (Drive API enabled, `drive.appdata` scope registered)
- [ ] Test machine: Windows 10/11 x64

### A. Fresh OAuth flow

- [ ] Wipe state: delete `%APPDATA%\Soyle\config.toml`, `dictionary.toml`,
      and any "Söyle Cloud" entry in Credential Manager
- [ ] Launch Söyle (`uv run soyle`)
- [ ] First-run wizard fires: API-key toast, then ~2 seconds later the
      Cloud Sync toast ("Подключите Google Drive в Settings → Cloud Sync…")
- [ ] Open Settings → Cloud Sync tab. Status shows "Не подключено",
      only the "Подключить Google Drive" button is visible
- [ ] Click **Подключить Google Drive**. Toast appears: "Открыл браузер
      для авторизации в Google. Подтвердите и вернитесь."
- [ ] Browser opens to `accounts.google.com/o/oauth2/v2/auth?…`. Verify:
  - App name shown is "Söyle" (from Google Cloud project config)
  - Scope shown is "View and manage its own configuration data in your
    Google Drive" (the `drive.appdata` scope's user-visible label)
- [ ] Authorize. Browser shows the confirmation page "Söyle подключён к
      Google Drive ✓"
- [ ] Settings tab updates: status flips to "✓ Подключено к Google Drive",
      buttons change to "Синхронизировать сейчас" + "Отключить"

### B. First-ever upload (no remote backup yet)

- [ ] Add a few terms via Settings → Словарь tab (e.g. "Söyle", "Astana",
      "OpenRouter"). Save settings.
- [ ] Click **Синхронизировать сейчас**
- [ ] Watch `%APPDATA%\Soyle\logs\soyle.log` for `cloud_sync_ok` event
      with `added_remote=3, added_local=0`
- [ ] In Google Drive web UI, confirm the App Data folder is NOT visible
      in "My Drive" (it shouldn't be — that's the whole point of `drive.appdata`).
      To verify it exists: drive.google.com → Settings → "Manage apps" → "Söyle"
      should show storage usage
- [ ] Click **Отключить**. Status flips back to "Не подключено"
- [ ] Click **Подключить Google Drive** again, complete OAuth.
      Restore prompt appears: "В Google Drive найден backup словаря: 3 терминов…"

### C. Cross-device restore (merge semantics)

- [ ] On a SECOND Windows machine (or VM, or after wiping `%APPDATA%\Soyle`):
- [ ] Launch Söyle; first-run wizard fires
- [ ] Settings → Cloud Sync → Connect with the SAME Google account
- [ ] Restore prompt appears: "В Google Drive найден backup словаря: N
      терминов (обновлён YYYY-MM-DD). Объединить с локальным словарём сейчас?"
- [ ] Click **Yes**. Toast confirms: "Sync OK. Локально +N, в Drive +0."
- [ ] Settings → Словарь tab shows the restored terms
- [ ] Dictate a phrase containing one of the restored terms — verify
      Whisper picks up the new vocabulary WITHOUT restarting (this exercises
      the on_dictionary_changed callback wired in PR #20)

### D. Daily-cadence trigger

- [ ] With `cloud_sync.last_synced_at` < 24h ago in `config.toml`: launch Söyle.
      No auto-sync (nothing in logs about `cloud_sync_*` after warm-up).
- [ ] Manually edit `config.toml` to set `last_synced_at` to 30 hours ago.
- [ ] Re-launch Söyle. Log shows `cloud_sync_ok` automatically after warm-up
      (no user action needed)

### E. Auth revoked

- [ ] Go to https://myaccount.google.com/permissions
- [ ] Find "Söyle". Click "Remove access"
- [ ] Wait ~1 minute. In Söyle, click **Синхронизировать сейчас** (or wait
      for scheduled sync at next launch)
- [ ] Toast appears: "Google Drive отключён. Подключите заново в Settings."
      (level: warning — yellow triangle on Windows)
- [ ] Log shows `cloud_sync_auth_revoked` event
- [ ] Settings tab status flips to "Не подключено", buttons change back
      to single "Подключить Google Drive"

### F. Edge cases

- [ ] **Browser closed without authorizing:** click Connect, close the
      browser tab without clicking Authorize. After ~120s the action-failed
      toast appears: "Söyle — Cloud Sync: Не удалось подключить Drive:
      TimeoutError" (level: warning). Söyle stays usable.
- [ ] **Network down at sync time:** disable network, click Sync now.
      No user-facing toast (silent — `_handle_sync_outcome` skips NETWORK).
      `soyle.log` shows `cloud_sync_network_error` with the relevant phase.
      Re-enable network, click Sync now → succeeds.
- [ ] **Placeholder client_id (dev build before swap):** start Söyle with
      the placeholder still in `_GOOGLE_CLIENT_ID`. Click Connect. Action-failed
      toast: "Не удалось подключить Drive: RuntimeError". Log warning
      `cloud_sync_client_id_not_configured` was emitted at startup.
- [ ] **Corrupted Drive backup:** manually replace dictionary.toml's content
      via drive.google.com → Manage apps → Söyle → some custom tooling (or
      by hex-editing the local copy of the file before its next sync).
      Click Sync now. Log shows `cloud_sync_corrupted_remote`; remote file
      gets renamed to `dictionary.toml.broken-<UTC>`; fresh upload replaces it.
- [ ] **PyInstaller-built binary** (after `scripts/build_installer.py`):
      verify Windows firewall doesn't pop a warning when the localhost
      listener starts on `begin_oauth_flow()`.

### Out of scope (Phase 1)

- Multi-account switching (planned Phase 4)
- Real-time propagation between devices (planned Phase 3)
- Encryption beyond Google's defaults (planned Phase 3+)

## Cloud Sync (Phase 2)

Сценарии проверяют, что синхронизация config.toml и usage.json
работает корректно в реальном Drive. Требует двух машин (или одной
машины + временно очищенного `%APPDATA%\Soyle\` для имитации второй).

### A. Settings sync — push на одном устройстве, pull на другом

- [ ] На устройстве 1: подключи Drive, сохрани какую-то синкаемую
      настройку (Settings → Hotkey → измени combination → Save).
- [ ] Подожди 10 секунд (8с debounce + 2с overhead).
- [ ] Открой Settings → Cloud Sync — "Последняя синхронизация: только
      что".
- [ ] На устройстве 2: Söyle уже запущен → закрой и перезапусти, чтобы
      сработал startup sync_now. Открой Settings → Hotkey: значение
      должно совпадать с устройством 1.

### B. Deny-list соблюдён — device-local поля НЕ синкаются

- [ ] На устройстве 1: измени Whisper → Model на large-v3, сохрани.
- [ ] Жди 10 секунд.
- [ ] На устройстве 2 после перезапуска: Whisper → Model должен
      остаться твоим прежним значением (например, large-v3-turbo).

### C. Cross-device cost tracking

- [ ] На устройстве 1: сделай 1-2 диктовки с post-process включенным
      (накапливает usage.json).
- [ ] Подожди ежедневный sync_now (или жми Settings → Cloud Sync →
      "Sync now").
- [ ] На устройстве 2 после перезапуска: tray меню → "Сегодня: $X" —
      сумма должна включать стоимость с устройства 1.
- [ ] Если установлен `behavior.monthly_cost_limit_usd`, проверь, что
      warning срабатывает на cross-device суммы, а не только локальные.

### D. First-run wizard — settings restore prompt

- [ ] Очисти `%APPDATA%\Soyle\` полностью (бэкап сначала!).
- [ ] Запусти Söyle → wizard → подключи Drive.
- [ ] Появится prompt "Найдены настройки с другого устройства. Применить?"
- [ ] Нажми "Да" → проверь, что synced поля восстановились (hotkey,
      postprocess.mode, prompts), а device-local поля — defaults.

### E. Disconnect → reconnect не теряет данные

- [ ] Подключи Drive, синкни, отключи (Settings → Disconnect).
- [ ] Поменяй настройки локально.
- [ ] Подключи Drive обратно.
- [ ] Локальные изменения должны попасть в Drive после первого
      sync_now (как обычно через mtime LWW).

### F. Schema mismatch (forward-compat)

Этот сценарий требует двух версий Söyle: одной с дополнительным полем
в Pydantic Config (вручную добавить временно), другой без.

- [ ] Старая Söyle → подключи Drive → синкни (создаёт config.toml в Drive).
- [ ] Новая Söyle → подключи тот же Drive → измени любое поле → push.
- [ ] Старая Söyle → запусти → daily sync_now должен НЕ упасть, НЕ
      переименовать .broken, НЕ перезаписать. Логи покажут
      `cloud_sync_config_schema_mismatch`. Локальный config.toml
      остаётся прежним.

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
