# Cloud Sync (Phase 1) — Design Specification

| Field | Value |
|-------|-------|
| Feature | Google Drive sync of `dictionary.toml` |
| Phase | 1 of N (dictionary-only; future phases extend scope) |
| Date | 2026-04-30 |
| Status | Approved for implementation |
| Target platform | Windows 10/11 x64 (Söyle's existing scope) |
| Roadmap reference | "Drive sync remain" item in user roadmap |

---

## 1. Problem statement

Söyle stores user state in `%APPDATA%\Soyle\` — `config.toml`, `dictionary.toml`, `usage.json`. None of it is backed up. Two real failure modes have already happened:

1. **Dictionary loss (2026-04-30 morning).** During development, the user deleted `%APPDATA%\Soyle\` to test a clean install. The Inno Setup uninstaller [intentionally preserves user data](../../../installer/installer.iss) (`[UninstallDelete]` is empty), but a manual `rd /s /q` doesn't. The `dictionary.toml` was never recoverable — no backup existed anywhere, neither in git nor on disk. User had to start the glossary over.

2. **Multi-device frustration.** User has both a laptop and a desktop. Every term added on one machine must be re-typed on the other. There is no current mechanism for two Söyle installs to share state.

Both problems share the same root cause: **no cloud-side persistence of user state.** This spec proposes Phase 1 of a Google Drive-backed sync to address the dictionary case specifically (the highest-pain item), with architecture that extends naturally to `config.toml` and `usage.json` in later phases.

## 2. Goals

- **Restore dictionary on a new/wiped machine** with a single OAuth click — no manual file copying, no terminal commands.
- **Bidirectional sync between two devices** — terms added on either side eventually appear on the other.
- **Zero data loss** in any normal failure scenario — disconnect, network drop, concurrent writes, corrupted Drive content, etc., must never delete a term that was on either device.
- **WhatsApp-style first-run UX** — on a fresh install, the wizard offers "Restore from Drive" if a backup exists, otherwise silently enables ongoing sync.
- **No new pip dependencies.** Implementation lives in stdlib + already-shipped libraries (`httpx`, `keyring`, `pydantic`, `tomli-w`).
- **No background services or daemons.** Sync runs piggybacked on existing Söyle process lifecycle.

## 3. Non-goals (Phase 1)

- **`config.toml` and `usage.json` sync** — deferred to Phase 2. Settings re-entry on a new device is annoying but not data-losing in the way dictionary loss is.
- **Real-time sync** (changes propagate in seconds) — Phase 1 is daily-cadence only. Real-time requires file watchers, push API listeners, debouncing, and conflict resolution within seconds. Out of scope for the smallest valuable cut.
- **Delete propagation.** Pure-union merge means removing a term on one device does NOT remove it on the other. Justification: today's pain is data loss, not data accumulation; pure union is the only merge semantic that physically cannot lose data.
- **Visible Drive folder** that user can manage manually. Phase 1 uses `drive.appdata` (hidden App Data folder, WhatsApp-style). Visible-folder UX is a Phase 2+ option.
- **Multi-account support.** Single Google account at a time. Switching accounts means disconnect-then-reconnect.
- **Encryption beyond Google's at-rest defaults.** Drive's transport (HTTPS) and at-rest encryption are good enough for proper-noun glossary content. End-to-end encryption is a Phase 3+ consideration if user demand warrants.
- **Selective sync** ("sync just this device's terms"). All connected devices share one canonical dictionary. Per-device subsets are not supported.

## 4. Design decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Sync model | Daily two-way sync (not just backup) | User wants "WhatsApp feel": work on laptop, see on desktop tomorrow. |
| Sync latency | Daily — startup-check `if last_synced_at > 24h ago` + manual button | Söyle is a per-user tray app, not a daemon. Most users start it daily. Time-of-day scheduling adds complexity (sleep-during-scheduled-time, missed runs) without commensurate value. |
| Drive scope | `drive.appdata` (hidden App Data folder) | Minimum scope; user can't accidentally delete the file from Drive web UI; Google's app verification is easier; matches WhatsApp's actual technical pattern. |
| Merge semantics | Pure union (additive) | Deletes don't propagate, but no data can ever be lost. Bug in merge logic = "extra term hangs around" instead of "term disappears". Cost-of-getting-wrong is asymmetric in user's favor. |
| Discovery | First-run wizard step + restore prompt | Existing wizard ([app.py:415-424](../../../src/soyle/app.py)) currently just opens Settings; this gives it real content. Restore-on-new-machine UX is the highest-value cloud sync moment. |
| Schedule | Startup check + manual "Sync now" button | Söyle's `autostart=false` default means user manually starts each day → startup check is equivalent to "sync at first session of the day" without needing a clock. |

## 5. Architecture & components

### 5.1 New module: `src/soyle/core/cloud_sync.py`

A single class `CloudSync` is the central coordinator for all Drive operations.

```python
class CloudSync:
    """Google Drive sync coordinator. Owns OAuth tokens, sync state, and
    Drive REST calls. Delegates merge logic to DictionaryStore.

    Design: this class is the ONLY module that talks to Google. Everywhere
    else in Söyle (app.py, settings.py, wizard) interacts with it through
    a small async API. Keeping the surface narrow makes mocking trivial
    in tests and isolates the network/auth logic for review.
    """

    def __init__(
        self,
        dict_store: DictionaryStore,
        config_store: ConfigStore,
        client_id: str,  # baked-in Google Cloud project ID
    ) -> None: ...

    # -- State --
    @property
    def is_connected(self) -> bool: ...        # has refresh token in keyring
    @property
    def last_synced_at(self) -> datetime | None: ...
    @property
    def account_email(self) -> str | None: ... # from token introspection

    # -- OAuth lifecycle --
    async def begin_oauth_flow(self) -> str:
        """Generate PKCE pair, start localhost listener, return auth URL."""
    async def complete_oauth_flow(self, callback_data: dict) -> None:
        """Exchange auth code for refresh token, persist via keyring."""
    async def disconnect(self) -> None:
        """Revoke tokens, clear keyring, reset last_synced_at to None."""

    # -- Sync ops --
    async def sync_now(self) -> SyncResult:
        """Idempotent merge cycle: download remote → union with local →
        upload merged → update last_synced_at. Safe to call repeatedly."""
    def should_run_scheduled(self) -> bool:
        """True when is_connected AND last_synced_at > 24h ago."""

    # -- Restore flow (called from wizard) --
    async def detect_existing_backup(self) -> RestoreOption | None:
        """Probe Drive App Data; return metadata if dictionary.toml exists."""
```

`SyncResult` is a small `@dataclass` carrying outcome (`OK`, `NETWORK`, `AUTH_REVOKED`, `QUOTA`, `CORRUPTED_REMOTE`, `RATE_LIMITED`), counts (`added_local: int`, `added_remote: int`), and timing.

### 5.2 Extensions to existing modules

| File | Change | Rationale |
|---|---|---|
| `src/soyle/core/dictionary.py` | Add `merge_with(other_terms: list[str]) -> list[str]` using existing `_dedupe_preserving_order` helper. Pure function, no I/O. | Keeps merge logic in DictionaryStore where the data lives; CloudSync calls it. |
| `src/soyle/core/config.py` | New Pydantic section `CloudSyncConfig` with `last_synced_at: datetime \| None = None` field. Add to `Config` model. | Persists per-device sync state alongside other config; survives Söyle restarts. |
| `src/soyle/app.py` | Instantiate `CloudSync` in `SoyleApp.__init__`; in `start()`, after `warm_up()`, call `if cloud_sync.should_run_scheduled(): asyncio.run(cloud_sync.sync_now())`. | Minimal wiring; uses existing async-runner pattern from `_InferenceJob`. |
| `src/soyle/app.py` (`_show_first_run_wizard`) | Extend with optional Drive step after API-key prompt. | Currently wizard just opens Settings — adding a meaningful second step that solves a real UX problem. |
| `src/soyle/ui/settings.py` | New tab "Cloud Sync" with: status label, last-sync timestamp label, "Connect" / "Disconnect" button (state-dependent), "Sync now" button. | Settings is the established surface for opt-in features. |

### 5.3 OAuth flow — PKCE (no client_secret)

Standard installed-app pattern for distributable binaries:

1. Söyle generates `code_verifier` (43-128 random URL-safe chars via `secrets.token_urlsafe(64)`)
2. Derives `code_challenge = base64url(sha256(verifier))`
3. Spawns local `http.server` listener on `localhost:<random_free_port>` with a `/callback` handler
4. Opens browser via `webbrowser.open(auth_url)` where auth_url is:
   ```
   https://accounts.google.com/o/oauth2/v2/auth
       ?client_id=<our_id>
       &redirect_uri=http://localhost:<port>/callback
       &response_type=code
       &scope=https://www.googleapis.com/auth/drive.appdata
       &code_challenge=<challenge>
       &code_challenge_method=S256
       &access_type=offline
       &prompt=consent
   ```
5. User authorizes in browser → Google redirects to `localhost:<port>/callback?code=<auth_code>`
6. Söyle receives the redirect, extracts `auth_code`, closes the listener
7. Söyle POSTs to `https://oauth2.googleapis.com/token` with `code`, `code_verifier`, `client_id`, `redirect_uri` — receives `{"refresh_token": "...", "access_token": "..."}`
8. Stores `refresh_token` via `keyring.set_password("Söyle Cloud", "google-refresh-token", token)`

`client_id` is a value baked into the Söyle source code — created in a Google Cloud project owned by `nurgysa`, configured as "Desktop app" type. **There is no `client_secret`** in the binary because PKCE replaces the need for it. This is Google's officially recommended pattern for installed apps.

### 5.4 Dependencies

**Zero new pip dependencies.** Phase 1 is implemented entirely with:

- `secrets` (stdlib) — PKCE `code_verifier` generation
- `hashlib` (stdlib) — SHA-256 for `code_challenge`
- `base64` (stdlib) — URL-safe base64 encoding
- `urllib.parse` (stdlib) — query string building
- `http.server` + `socketserver` (stdlib) — local OAuth callback listener
- `webbrowser` (stdlib) — opening the Google consent screen
- `httpx` (already in [pyproject.toml:19](../../../pyproject.toml)) — Drive REST + token endpoint
- `keyring` (already there) — refresh token storage in Windows Credential Manager
- `pydantic`, `tomli-w`, `tomllib` (already there) — schema + serialization

This is a deliberate choice over `google-api-python-client`. That library would add ~50 MB to PyInstaller bundles (protobuf, grpc, googleapiclient, google-auth) for ~5 endpoint calls we actually make. Stdlib + httpx is ~80 lines of code for the OAuth listener and a thin Drive-API wrapper.

## 6. Data flow

### 6.1 First-time connection (in first-run wizard or via Settings)

```
User clicks "Connect Google Drive"
  ↓
CloudSync.begin_oauth_flow()
  ├── generate code_verifier + code_challenge
  ├── start localhost listener on random free port
  └── open browser to Google consent screen
  ↓
[user authorizes in browser → redirect to localhost]
  ↓
CloudSync.complete_oauth_flow(callback_data)
  ├── exchange auth_code + verifier → refresh_token
  ├── keyring.set_password("Söyle Cloud", "google-refresh-token", token)
  ├── close listener
  └── return success
  ↓
detect_existing_backup() → drive_get("dictionary.toml") metadata
  ├── 404 → no existing backup, just enable sync
  └── 200 → return RestoreOption(term_count, last_modified)
            → wizard shows "Found backup with N terms (last updated <date>). Restore?"
            → on YES: download + DictionaryStore.save()
            → on MERGE: merge with local + DictionaryStore.save()
```

### 6.2 Daily / manual sync — `CloudSync.sync_now()`

The pure-union round-trip:

```
sync_now()
  ↓
refresh access_token using stored refresh_token
  ├── 401 from Google → token revoked → toast + clear keyring → return AUTH_REVOKED
  ├── network error → log warning → return NETWORK (no toast)
  └── 200 → continue with new access_token
  ↓
local = DictionaryStore.load()                    # list[str] from disk
  ↓
remote, etag = drive_get_with_etag("dictionary.toml")
  ├── 404 (file doesn't exist yet) → remote = [], etag = None
  ├── parse error → return CORRUPTED_REMOTE → backup-rename in Drive → upload local
  └── 200 + content → parse TOML → terms, etag from response header
  ↓
merged = DictionaryStore.merge_with(local, remote)  # _dedupe_preserving_order
  ↓
if merged != local:
    DictionaryStore.save(merged)                   # write to %APPDATA%\Soyle\dictionary.toml
    transcriber.set_initial_prompt(dict_store.as_whisper_prompt())
    postprocess.set_dictionary_hint(dict_store.as_llm_instruction())

if merged != remote:
    response = drive_put_if_match("dictionary.toml", merged_serialized, etag)
    if response.status == 412:
        # Concurrent write happened — re-read + re-merge + retry
        log.info("cloud_sync_concurrent_write_detected")
        return await self.sync_now()  # idempotent retry
  ↓
config.cloud_sync.last_synced_at = now()
config_store.save(config)
return SyncResult.OK(added_local=N, added_remote=M)
```

Idempotency holds because pure union is stable: after `sync_now()` succeeds, `local == remote == merged`. A second immediate call sees no diffs and just bumps `last_synced_at`.

### 6.3 Restore prompt (post-OAuth, in wizard)

```
local_terms = DictionaryStore.load()  # often [] on a fresh install
backup = await detect_existing_backup()  # None | RestoreOption

if backup is None:
    # First-ever device — proceed with empty dict, sync runs going forward
    return

if not local_terms:
    # Fresh install + existing backup — pure restore case
    show_dialog(f"Found backup with {backup.term_count} terms (last updated {backup.last_modified}). Restore?")
    if user_confirms:
        terms = await drive_download("dictionary.toml")
        DictionaryStore.save(terms)
        toast(f"Restored {len(terms)} terms from Drive.")
else:
    # User added terms locally before connecting — merge case
    show_dialog(f"You have {len(local_terms)} local terms; backup has {backup.term_count}. Merge?")
    if user_confirms:
        terms = await drive_download("dictionary.toml")
        merged = DictionaryStore.merge_with(local_terms, terms)
        DictionaryStore.save(merged)
        toast(f"Merged dictionaries: {len(merged)} total terms.")
```

### 6.4 Disconnect

```
disconnect():
    POST https://oauth2.googleapis.com/revoke?token=<refresh_token>
    keyring.delete_password("Söyle Cloud", "google-refresh-token")
    config.cloud_sync.last_synced_at = None
    toast("Google Drive disconnected. Local data preserved.")
```

**Local data is never touched on disconnect.** User can disconnect, dictate locally for an hour, and reconnect later — their dictionary stays intact and re-syncs on the next `sync_now()`.

## 7. Error handling

Core principle: **dictation must never block on cloud sync.** If sync fails for any reason, Söyle keeps working locally; the user shouldn't notice unless action is required.

### 7.1 Failure modes

| Scenario | Detection | User feedback | Recovery |
|---|---|---|---|
| Transient network | `httpx.ConnectError`, `httpx.ReadTimeout` | **Silent.** Log `cloud_sync_network_error`. | Skip, retry on next `sync_now()`. Don't toast — annoying on planes/cafés. |
| Token expired (transient) | `401` on Drive call, refresh succeeds | Silent | Refresh access token → retry once. Normal lifecycle (access tokens live ~1h). |
| Refresh token revoked | `400 invalid_grant` from token endpoint | **Toast (warning):** "Google Drive отключён. Заново подключи в Settings." | Clear keyring, set `is_connected = False`. Settings UI shows "Connect" instead of "Sync now". Local data untouched. |
| Drive quota exceeded | `403 storageQuotaExceeded` | **Toast (warning):** "Google Drive переполнен. Освободи место или disconnect." | Stop retrying until user reconnects manually. App Data file is kilobytes — only happens when user's whole 15GB is full. |
| App suspended by Google | `403 appSuspended` | **Toast (critical):** "Söyle временно заблокирован Google. Контакт: andasbek.nurgysa@gmail.com" | Stop sync until resolved. Indicates TOS violation in OAuth client. |
| Corrupted remote (broken TOML) | `tomllib.TOMLDecodeError` parsing Drive content | **Toast (info):** "Backup в Drive повреждён, восстанавливаю из локального." | Mirror [config.py:184-194](../../../src/soyle/core/config.py): rename remote file to `dictionary.toml.broken-<ts>`, upload fresh local. |
| Insufficient scope | `403 insufficientScopes` | **Toast (warning):** "Нужно заново разрешить доступ к Drive." | Trigger re-OAuth flow. Rare — only fires if Söyle adds new scope in a future version. |
| 5xx from Google | `500/502/503` | Silent | Exponential backoff: 1s → 2s → 4s, max 3 retries. Then defer to next `sync_now()`. |

### 7.2 Concurrent writes

Two devices may trigger `sync_now()` near-simultaneously. Without a locking mechanism, both could read the same remote state, compute different merged sets, and overwrite each other.

**With pure union + ETag** the worst case is one extra round-trip:

1. Both devices read remote at state `R0` with same ETag `E0`
2. Device A writes `merged_A` with `If-Match: E0` → succeeds, server now at `R1` with `E1`
3. Device B writes `merged_B` with `If-Match: E0` → **412 Precondition Failed**
4. Device B logs `cloud_sync_concurrent_write_detected` and retries `sync_now()` from the top
5. Device B's retry now reads `R1`, merges with its local (which still includes its unique additions), uploads `R2`
6. Both devices' next `sync_now()` will pull `R2` and converge

**Result:** strongly-consistent merge with one extra round-trip in the rare concurrent-write case. ~5 lines of code (the 412 check and recursive retry).

## 8. Testing strategy

### 8.1 Unit tests — `tests/unit/test_cloud_sync.py`

Pure-logic + mocked network. Uses `respx` (already in [pyproject.toml:33](../../../pyproject.toml)) to intercept httpx calls.

**Pure-logic tests** (no network, no OAuth):
- `test_merge_pure_union_dedupes` — `[A, B] + [B, C] = [A, B, C]`
- `test_merge_preserves_first_appearance_order` — order of keeps insertion order
- `test_should_run_scheduled_returns_false_when_disconnected`
- `test_should_run_scheduled_returns_false_when_synced_within_24h`
- `test_should_run_scheduled_returns_true_when_24h_elapsed_and_connected`
- `test_pkce_code_challenge_is_sha256_base64url`

**Mocked Drive flow tests:**
- `test_sync_now_uploads_new_terms_to_empty_remote`
- `test_sync_now_downloads_remote_into_empty_local`
- `test_sync_now_unions_when_both_have_unique_terms`
- `test_sync_now_skips_writes_when_already_in_sync`
- `test_sync_now_handles_corrupted_remote_with_backup_rename`
- `test_sync_now_retries_on_412_etag_mismatch`
- `test_sync_now_returns_NETWORK_on_connect_error_no_toast`
- `test_sync_now_clears_keyring_on_invalid_grant`

**OAuth listener tests:**
- `test_local_listener_captures_callback_query_params`
- `test_local_listener_picks_free_port_above_1024`
- `test_local_listener_times_out_after_2_minutes`
- `test_complete_oauth_exchanges_code_for_refresh_token`
- `test_complete_oauth_stores_token_in_keyring`

**Restore-flow tests:**
- `test_first_run_wizard_offers_restore_when_drive_has_data`
- `test_first_run_wizard_skips_restore_when_drive_empty`
- `test_first_run_wizard_offers_merge_when_both_have_data`

Target: ~25-30 new unit tests, all mocked.

### 8.2 Integration tests — `tests/integration/test_cloud_sync_real_drive.py` (opt-in)

Marked with `@pytest.mark.real_drive` and excluded from default `pytest` runs (mirroring the existing `gpu` marker pattern in [pyproject.toml:96-98](../../../pyproject.toml)). Run manually before releases via `pytest -m real_drive`. Requires a test Google account and the `client_id` configured in env.

Two scenarios:
1. End-to-end round-trip: connect → upload → modify → sync → assert remote matches
2. Token refresh after access token expires (or simulated 401)

### 8.3 Manual test plan — `docs/testing/cloud-sync-manual.md`

Things unit tests cannot cover:
1. Real OAuth consent screen wording, app name, scope description
2. PyInstaller-built binary's local listener doesn't trigger Windows Firewall warning
3. Restore flow on a freshly-imaged Windows machine
4. UX of disconnect → reconnect cycle (does account picker show?)
5. Söyle doesn't hang if user closes browser without authorizing

### 8.4 Out of scope for testing

- Real Drive in CI (requires secrets, flaky, race conditions with Google rate limits)
- Browser-launching itself (`webbrowser.open` is OS-level, trust the platform)
- Behavior during reboot mid-sync (rare; sync is idempotent → next startup completes)
- 100GB dictionaries (`MAX_TERMS=200` cap means file is always < 10KB)

## 9. Open questions / future phases

Deferred to later phases — captured here so they're not lost:

- **Phase 1.5 — Qt timer for long-running sessions.** If user keeps Söyle running for 3+ days without restart, daily sync stalls. ~1 hour to add a 6-hour QTimer that re-checks `should_run_scheduled()`.
- **Phase 2 — `config.toml` sync with per-field rules.** Some settings are device-specific (`audio.device`, `behavior.autostart`); others are user preferences (`whisper.language`, `hotkey.combination`). Needs a small deny-list of device-local fields.
- **Phase 2 — `usage.json` sync** for cross-device cost tracking. Append-only nature makes this trivial once Phase 1 infrastructure exists.
- **Phase 3 — delete propagation.** If user feedback shows lingering-term annoyance is real, add tombstones with a 30-day TTL and `auto_remove_on_sync_count >= 2` semantics.
- **Phase 3 — real-time sync.** File-watcher on `dictionary.toml`, debounced upload to Drive, plus Drive `changes.watch` push notifications.
- **Phase 3 — encryption at rest in Drive.** Currently relies on Google's default at-rest encryption. If user demand emerges for higher privacy, add AES-GCM with key in keyring.
- **Phase 4 — multi-account support.** Switching between personal and work Google accounts without losing dictionary.

## 10. References

- Existing roadmap item: user `MEMORY.md` — "OAuth PKCE / UI i18n / Drive sync remain"
- Established codebase patterns reused:
  - `keyring` for secret storage — [config.py:208-216](../../../src/soyle/core/config.py)
  - `httpx.AsyncClient` for REST — [postprocess.py:282](../../../src/soyle/core/postprocess.py)
  - Pydantic-backed `[section]` config — [config.py:62-105](../../../src/soyle/core/config.py)
  - `_dedupe_preserving_order` for set semantics — [dictionary.py:133-142](../../../src/soyle/core/dictionary.py)
  - `_backup_broken` symlink-defended file rename — [config.py:184-194](../../../src/soyle/core/config.py)
  - `respx` mocking for httpx tests — [test_postprocess.py:43](../../../tests/unit/test_postprocess.py)
  - `pytest.mark` for opt-in slow tests — [pyproject.toml:96-98](../../../pyproject.toml)
- Google official docs:
  - PKCE for installed apps: https://developers.google.com/identity/protocols/oauth2/native-app
  - `drive.appdata` scope: https://developers.google.com/drive/api/guides/appdata
  - Token revocation: https://developers.google.com/identity/protocols/oauth2/web-server#tokenrevoke
- Background motivation:
  - Dictionary loss incident — earlier in this same session, see `soyle.log.before-task-*` for timestamps
