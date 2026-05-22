# Cloud Sync (Phase 2) — Design Specification

| Field | Value |
|-------|-------|
| Feature | Google Drive sync of `config.toml` and `usage.json` |
| Phase | 2 of N (extends Phase 1 dictionary sync) |
| Date | 2026-05-22 |
| Status | Approved for implementation |
| Target platform | Windows 10/11 x64 |
| Predecessor | [Cloud Sync Phase 1](2026-04-30-cloud-sync-design.md) — dictionary sync, shipped 2026-05-21 |

---

## 1. Problem statement

Phase 1 shipped `dictionary.toml` sync via Google Drive's `drive.appdata` scope. It solved the highest-pain item from the original roadmap: glossary loss on a wiped machine. Two related pain points remain:

1. **Settings re-entry on a new device.** On a fresh install, the user re-picks hotkey combination, Whisper model preset, post-process mode, monthly cost limit, prompt files, and a dozen smaller flags. Even with the dictionary restored, dictation feels alien until Settings is rebuilt manually. The user's setup spans laptop + desktop — every Settings tweak on one machine needs manual replication on the other.

2. **Cost tracking is per-device.** `usage.json` accumulates per-day LLM spend locally. The user genuinely wants one cross-device total: `monthly_cost_limit_usd` is "my total budget", not "budget per machine". Currently a $5 cap on each of two devices means $10 actual spend before either warns.

Both problems share Phase 1's root cause: cloud-side persistence exists only for the glossary. This spec extends the same `drive.appdata` infrastructure to cover the remaining two state files.

## 2. Goals

- **Restore user preferences on a new/wiped machine** — after Drive connect, settings sync down (with deny-list for device-local fields).
- **Cross-device cost tracking** — `today()`, `this_month()`, and the monthly cap reflect total spend across all connected devices.
- **Predictable propagation** — explicit settings changes on one device appear on the other within seconds (debounced push), not at the next daily sync.
- **Per-device autonomy** — fields that are genuinely machine-specific (microphone device, Whisper model, autostart) stay local even when the rest of config syncs.
- **Zero data loss** for `usage.json` — concurrent same-day usage on two devices must NOT be double-counted or under-counted.
- **No new pip dependencies.** Builds entirely on Phase 1's stdlib + httpx + keyring + Pydantic stack.
- **No refactor of Phase 1 code.** Extend `CloudSync` in place; existing dictionary sync paths and tests remain untouched.

## 3. Non-goals (Phase 2)

- **Real-time pull.** Settings changed on device A appear on device B only at B's next daily startup sync (or manual "Sync now"). Push from A is near-immediate; pull on B is not. Symmetric real-time requires Drive `changes.watch` push notifications and is deferred to Phase 3.
- **Per-field LWW with timestamps.** This spec uses whole-file LWW for `config.toml` (last device to push wins; deny-list preserves device-locals). Per-field timestamping would require schema migration on every Pydantic field and is YAGNI for a two-device single-user setup.
- **User-visible Drive folder.** Continues to use `drive.appdata` (hidden) per Phase 1's locked decision.
- **Manual conflict resolution dialogs.** If two devices change `hotkey.combination` near-simultaneously, the later push wins silently. No modal "which value to keep" prompt.
- **Settings history / undo.** Drive stores only the current state. No "revert to yesterday's settings" feature.
- **Multi-account.** Inherits Phase 1's single-account constraint.
- **Encryption at rest beyond Drive's defaults.** Inherits Phase 1's scope.

## 4. Design decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Files in scope | `config.toml` + `usage.json` | Spec section 9 of Phase 1 grouped these as Phase 2. Both have non-trivial merge semantics worth designing together for shared infrastructure. |
| Config merge | Whole-file LWW + deny-list | Matches Phase 1's "simple winning policy" spirit. Per-field LWW is YAGNI; manual conflict is too friction-heavy for a single-user two-device setup. |
| Config deny-list | `version`, `audio.device`, `whisper.{model,device,compute_type}`, `behavior.{autostart,inject_method}`, `ui.theme`, entire `cloud_sync` section | Each is genuinely per-machine: schema metadata, hardware-bound (mic, GPU), per-app workaround (inject method), or already device-local (cloud_sync state). User confirmed `whisper.model`, `behavior.inject_method`, `ui.theme` after enumeration. |
| Usage merge | Per-device buckets `{date: {device_id: {cost_usd, requests}}}` with stable UUID per device | The only schema where concurrent same-day usage doesn't double-count: each device owns only its own keys, so LWW per `(date, device_id)` tuple has zero conflict opportunity. Naive sum-merge is provably wrong on idempotency. |
| Device identity | UUID stored in keyring under `(APP_NAME, "device-id")`, lazy-generated on first call | Bulletproof uniqueness; survives config wipes; no migration step needed. Hostname is unsuitable (default Windows installs can collide). |
| Push timing | Immediate after `ConfigStore.save()` with 8-second debounce | Settings changes are explicit user actions; daily latency feels broken. Debounce avoids spam when user changes 5 fields and clicks Save once (each `_w_*.commit()` could trigger save). Usage push remains daily — auto-accumulating, no UX expectation of instant sync. |
| First-run wizard | Dictionary restore prompt (existing) + new settings restore prompt; usage merges silently | Settings restore is a meaningful user choice (new device may want fresh defaults). Usage is opaque history — no value in asking. |
| Architecture | Extend `CloudSync` class in place | Phase 1 spec section 5.1 locked "CloudSync is the ONLY module that talks to Google". Refactor to per-file handlers (Approach B) would re-touch all ~50 Phase 1 tests for no behavior change. |
| Partial failure handling | `sync_now()` continues after per-file failure; aggregated `SyncResult.outcome` = worst-of-three | Phase 1 all-or-nothing was acceptable with one file. With three files, a corrupted `usage.json` should NOT stop dictionary sync from succeeding. |

## 5. Architecture & components

### 5.1 Extensions to `src/soyle/core/cloud_sync.py`

Single class continues to own all Google interaction. Phase 2 adds:

```python
_CONFIG_DENY_LIST: frozenset[str] = frozenset({
    "version",
    "audio.device",
    "whisper.model",
    "whisper.device",
    "whisper.compute_type",
    "behavior.autostart",
    "behavior.inject_method",
    "ui.theme",
    "cloud_sync",  # entire section
})


def _device_id() -> str:
    """Stable per-machine UUID. Generated on first call, persisted in
    Windows Credential Manager under (APP_NAME, "device-id"). Survives
    config wipes; new machine = new ID by definition."""


# Module-level Drive primitives (mirror Phase 1's _drive_get/put_dictionary)
async def _drive_get_config(access_token, client) -> tuple[Config | None, _RemoteMeta | None]
async def _drive_put_config(access_token, client, config, etag) -> _RemoteMeta
async def _drive_get_usage(access_token, client) -> tuple[dict, str | None]   # etag
async def _drive_put_usage(access_token, client, usage_dict, etag) -> str    # new etag


# Pure merge helpers (no I/O, easy to unit-test)
def _strip_deny(config: Config) -> dict
def _merge_config(local: Config, remote: Config, local_mtime, remote_mtime) -> Config
def _merge_usage(local: dict, remote: dict) -> dict


class CloudSync:
    # --- Phase 2 additions ---
    async def _sync_config(self, access_token: str) -> SyncResult: ...
    async def _sync_usage(self, access_token: str) -> SyncResult: ...

    def schedule_config_push(self) -> None:
        """Debounced trigger called from ConfigStore.save(). Resets an
        8-second QTimer; on fire, spawns asyncio task via AsyncRunnable
        that runs _push_config_now()."""

    async def _push_config_now(self) -> None:
        """Quietly run one config sync round-trip. Skips if not connected."""

    # --- Phase 1 extended ---
    async def sync_now(self) -> SyncResult:
        """Now runs dict + config + usage sequentially. Continues past
        per-file errors; returns aggregated worst-outcome SyncResult."""
```

### 5.2 Extensions to existing modules

| File | Change | Notes |
|---|---|---|
| `src/soyle/core/usage.py` | Schema migration from flat `{date: {cost, requests}}` to per-device `{date: {device_id: {cost, requests}}}`. Inline-detected on `_load()`. `record()` writes only to current device's bucket. `today()`/`this_month()` sum across all devices for the date(s). New `serialize_for_sync()` and `apply_merged(merged)` for CloudSync. | Migration is self-describing: v1 values have `cost_usd` at the top of the value dict; v2 has nested `device_id` keys. Idempotent. |
| `src/soyle/core/config.py` | `ConfigStore.mtime()` returns the file's modified-time as aware UTC datetime. `ConfigStore.apply_synced_overrides(remote: Config)` overlays non-deny-list fields onto local and writes to disk. `ConfigStore.save()` optionally calls a registered push hook (set by app.py via DI: `config_store.set_push_hook(cloud_sync.schedule_config_push)`). | No Pydantic schema changes; only behavioral additions. |
| `src/soyle/app.py` | DI wiring: `config_store.set_push_hook(cloud_sync.schedule_config_push)` after both are constructed. UsageTracker init no longer takes path only — also needs to know the device-id, fetched via `_device_id()`. | ~15 lines. |
| `src/soyle/ui/settings.py` | Status label in Cloud Sync tab updated from "Словарь синхронизируется ежедневно" to a 3-line summary or a single broader label. Adds nothing functionally new — settings UX of opening the dialog itself drives the push. | UI-only. |
| `src/soyle/ui/async_runnable.py` | Reused as-is to run `_push_config_now` off the Qt main thread. No code change. | — |

### 5.3 Why QTimer for debounce (not asyncio)

`ConfigStore.save()` is called from the Qt main thread when the user clicks Save in Settings. asyncio's event loop is not running there. QTimer is the native Qt primitive: single-threaded, restartable, cheap. Each `schedule_config_push()` call resets the timer — typing-style rapid saves coalesce to one fire. On fire, `AsyncRunnable.run()` (existing Phase 1 adapter) spawns the actual async work on a worker thread so the GUI doesn't block on Drive's ~500ms REST round-trip.

### 5.4 Dependencies

Zero new pip dependencies. Phase 2 reuses Phase 1's stack:
- `httpx`, `keyring`, `pydantic`, `tomli-w`, `tomllib`, `structlog` (existing)
- `uuid` (stdlib) — device ID generation
- `copy` (stdlib) — deep-copy in `_merge_usage`
- `PySide6.QtCore.QTimer` (existing, already imported by other UI code)

## 6. Data flow

### 6.1 Daily / manual `sync_now()`

```
sync_now()
  ├── refresh_access_token()
  ├── _sync_dictionary(token)          # Phase 1 — unchanged
  ├── _sync_config(token)              # NEW
  ├── _sync_usage(token)               # NEW
  └── config.cloud_sync.last_synced_at = now()

[per-file outcomes aggregated]
   - if any → AUTH_REVOKED: surface AUTH_REVOKED (Phase 1 toast + clear keyring)
   - elif any → CORRUPTED_REMOTE: surface CORRUPTED_REMOTE (Phase 1 toast)
   - elif any → QUOTA / APP_SUSPENDED: surface that
   - elif any → NETWORK: surface NETWORK (silent)
   - else → OK
```

### 6.2 `_sync_config(token)` — single round-trip

```
local_config = config_store.load()
local_mtime = config_store.mtime()

remote_config, remote_meta = await _drive_get_config(token, client)
  ├── 404 → remote_config = None
  └── parse error → return CORRUPTED_REMOTE
       → rename remote to config.toml.broken-<ts>
       → push local (deny-stripped)

if remote_config is None:
    await _drive_put_config(token, _strip_deny(local_config), etag=None)
    return SyncResult.OK(pushed=True)

# Compare with ±5s tolerance for clock skew
if remote_meta.modified_time > local_mtime + 5s:
    # Pull
    merged = _merge_config(local_config, remote_config, local_mtime, remote_meta.modified_time)
    config_store.apply_synced_overrides(merged)
    return SyncResult.OK(pulled=True)

elif local_mtime > remote_meta.modified_time + 5s:
    # Push
    await _drive_put_config(token, _strip_deny(local_config), etag=remote_meta.etag)
    return SyncResult.OK(pushed=True)

else:
    # Within tolerance — already in sync
    return SyncResult.OK(noop=True)
```

`_merge_config` is pure:

```python
def _merge_config(local, remote, local_mtime, remote_mtime):
    """LWW: pick whole-file winner by mtime; preserve deny-list from local."""
    winner = remote if remote_mtime > local_mtime else local
    return _overlay_deny_from(local, winner)


def _overlay_deny_from(local, winner):
    """Take winner verbatim, then overwrite deny-list paths with local's values."""
    result = winner.model_copy(deep=True)
    for path in _CONFIG_DENY_LIST:
        _set_dotted(result, path, _get_dotted(local, path))
    return result
```

`_strip_deny(config)` returns a dict-of-dicts with deny-list paths removed entirely (so Drive never sees them at all):

```python
def _strip_deny(config: Config) -> dict:
    raw = config.model_dump(mode="json", exclude_none=True)
    for path in _CONFIG_DENY_LIST:
        _del_dotted(raw, path)
    return raw
```

### 6.3 `_sync_usage(token)` — pure-additive

```
local_usage = usage_tracker.serialize_for_sync()
# format: {"2026-05-22": {"dev-A-uuid": {"cost_usd": 0.05, "requests": 3}}, ...}

remote_usage, remote_etag = await _drive_get_usage(token, client)
  ├── 404 → remote_usage = {}, remote_etag = None
  └── parse error → return CORRUPTED_REMOTE → rename + push local

merged = _merge_usage(local_usage, remote_usage)

if merged != local_usage:
    usage_tracker.apply_merged(merged)

if merged != remote_usage:
    await _drive_put_usage(token, merged, etag=remote_etag)

return SyncResult.OK(...)
```

Merge:

```python
def _merge_usage(local, remote):
    """Per-(date, device_id) LWW. Each device only writes its own keys,
    so a "conflict" on (date, my_id) can't happen — only one device
    writes that key. Remote-only keys (other devices' entries) carry
    over verbatim. Local entries for my_id are authoritative for me."""
    merged = copy.deepcopy(remote)
    for date, devices in local.items():
        merged.setdefault(date, {})
        for device_id, entry in devices.items():
            merged[date][device_id] = entry
    return _trim_old(merged)  # 45-day retention, same as Phase 1's UsageTracker
```

### 6.4 Debounced push on `ConfigStore.save()`

```
[User edits Settings, clicks Save]
  ↓
ConfigStore.save(new_config)
  ├── write TOML to disk (existing)
  └── if push_hook is set:
        push_hook()                      # = cloud_sync.schedule_config_push
          └── QTimer.start(8000)         # restarts if already running

[8 seconds elapse with no further saves]
  ↓
QTimer fires
  ↓
AsyncRunnable.run(cloud_sync._push_config_now)
  ├── if not is_connected: return silently
  ├── refresh_access_token()
  ├── _sync_config(token)                # full round-trip
  └── bump last_synced_at
```

Errors from debounced push are silent (no toast). Rationale: the user just clicked Save; surprising them with "cloud sync failed" 8 seconds later breaks the mental model. Daily sync_now on next startup will retry and surface the issue then if persistent.

### 6.5 First-run wizard extension

After OAuth completes (Phase 1 unchanged), the wizard runs three Drive probes in sequence:

```
1. dictionary backup check (Phase 1 — unchanged)
   └── if found: prompt "Restore dict with N terms?"

2. config backup check (NEW)
   └── _drive_get_config(token)   # returns (Config | None, _RemoteMeta | None)
   └── if remote_config is not None:
        prompt "Найдены настройки с другого устройства (сохранены <date>). Применить?"
        └── YES → apply_synced_overrides(remote_config) + toast
        └── NO  → skip (local defaults stay)

3. usage merge (NEW, silent)
   └── _sync_usage(token)
   └── no dialog — just a quiet merge
```

### 6.6 Disconnect (Phase 1 — unchanged)

Disconnect revokes tokens and clears keyring. Local `dictionary.toml`, `config.toml`, `usage.json` are NEVER touched. Reconnect later resumes from current local state.

## 7. Error handling

Inherits Phase 1's matrix. New rows:

| Scenario | Detection | User feedback | Recovery |
|---|---|---|---|
| Config TOML corrupted in Drive | `tomllib.TOMLDecodeError` or `ValidationError` parsing remote | **Toast (info):** "Backup настроек в Drive повреждён, восстанавливаю из локального." | Rename remote `config.toml.broken-<ts>`; push deny-stripped local. |
| Usage JSON corrupted in Drive | `json.JSONDecodeError` or schema validation fail | **Toast (info):** "История usage в Drive повреждена, начинаю заново." | Rename remote `usage.json.broken-<ts>`; push local. |
| Config schema mismatch (Drive has fields from a newer Söyle version that this device hasn't upgraded to yet) | `ValidationError` from Pydantic when loading remote (current `extra="forbid"`) | Silent log `cloud_sync_config_schema_mismatch` with both version markers | **Skip this sync entirely** — do NOT rename, do NOT push local. Both local and remote stay intact. Older device retries on next `sync_now`; succeeds automatically once the user upgrades it to match. This preserves the newer device's just-set fields rather than overwriting them with the older device's narrower schema. |
| Usage v1 → v2 migration fails | Exception during `_load_with_migration` | **Toast (warning):** "Usage migrated, история обнулена." | Backup `usage.json.broken-<ts>`; start fresh v2 state. |
| Concurrent config write (412) | ETag mismatch on PUT | Silent log `cloud_sync_concurrent_config_write` | Refresh + recursive `_sync_config` retry (mirrors Phase 1 dict pattern). |
| Debounced push: network fail | `httpx.ConnectError` etc. | Silent | Daily `sync_now` retries naturally. |
| Debounced push: AUTH_REVOKED | `400 invalid_grant` on token refresh | Toast as per Phase 1 (clear keyring, "reconnect" message) | Settings UI shows "Connect" button on next open. |
| Partial sync_now (1 of 3 fails) | Per-file SyncOutcome aggregation | Toast for worst outcome; silent log for the others | Other two files succeed; failed file retries next cycle. |

## 8. Testing strategy

### 8.1 Unit tests

Extends Phase 1 pattern: `respx` mock for httpx, `pytest-asyncio` for `async def`. No new test framework dependencies.

**`tests/unit/test_cloud_sync.py`** (~+25 tests on top of Phase 1's ~50):

Pure merge logic (no network):
- `test_merge_config_remote_wins_when_remote_mtime_newer`
- `test_merge_config_local_wins_when_local_mtime_newer`
- `test_merge_config_preserves_deny_list_from_local_on_pull`
- `test_merge_config_mtime_tolerance_treats_5s_skew_as_equal`
- `test_strip_deny_removes_all_listed_dotted_paths`
- `test_strip_deny_handles_section_level_paths_like_cloud_sync`
- `test_merge_usage_per_device_LWW_no_conflict_on_own_keys`
- `test_merge_usage_picks_up_other_device_entries_verbatim`
- `test_merge_usage_applies_45_day_retention`

Mocked Drive — config:
- `test_sync_config_uploads_when_remote_404`
- `test_sync_config_pulls_when_remote_mtime_newer`
- `test_sync_config_pushes_when_local_mtime_newer`
- `test_sync_config_noop_when_mtimes_within_tolerance`
- `test_sync_config_corrupted_remote_renames_and_pushes_local`
- `test_sync_config_schema_mismatch_skipped_silently_preserves_remote`
- `test_sync_config_412_concurrent_write_triggers_recursive_retry`
- `test_sync_config_strips_deny_list_before_upload`
- `test_sync_config_preserves_deny_list_on_apply`

Mocked Drive — usage:
- `test_sync_usage_uploads_to_empty_remote`
- `test_sync_usage_unions_dates_across_devices`
- `test_sync_usage_picks_up_remote_device_entries`
- `test_sync_usage_corrupted_remote_renames_and_pushes_local`

Orchestration:
- `test_sync_now_runs_dict_config_usage_in_sequence_under_one_token`
- `test_sync_now_continues_if_config_sync_fails`
- `test_sync_now_continues_if_usage_sync_fails`
- `test_sync_now_aggregates_worst_outcome`
- `test_sync_now_bumps_last_synced_at_when_at_least_one_file_succeeded`

Debounce + device ID:
- `test_schedule_config_push_starts_qtimer_with_8s_interval`
- `test_schedule_config_push_resets_timer_on_rapid_saves`
- `test_schedule_config_push_silent_when_disconnected`
- `test_push_config_now_does_full_round_trip_when_connected`
- `test_device_id_generated_on_first_call_when_keyring_empty`
- `test_device_id_persisted_across_restarts`

First-run wizard:
- `test_wizard_offers_settings_restore_when_drive_has_config`
- `test_wizard_skips_settings_restore_when_drive_404`
- `test_wizard_usage_merge_silent_no_dialog`

**`tests/unit/test_usage.py`** (~+10):
- `test_record_writes_only_to_own_device_bucket`
- `test_today_sums_across_all_devices_for_today`
- `test_this_month_sums_across_all_devices_for_current_month`
- `test_summary_line_reflects_cross_device_totals`
- `test_load_migrates_v1_flat_schema_to_v2_per_device`
- `test_migrated_v1_entries_attributed_to_current_device_id`
- `test_v2_schema_passes_through_load_unchanged`
- `test_serialize_for_sync_returns_full_nested_state`
- `test_apply_merged_replaces_full_state_atomically`
- `test_trim_old_works_correctly_in_v2_schema`

**`tests/unit/test_config.py`** (~+5):
- `test_mtime_returns_timezone_aware_utc_datetime`
- `test_mtime_raises_when_file_does_not_exist`
- `test_apply_synced_overrides_applies_synced_fields`
- `test_apply_synced_overrides_preserves_deny_list_fields_from_local`
- `test_save_invokes_push_hook_when_registered`

### 8.2 Integration tests

`tests/integration/test_cloud_sync_real_drive.py` — extend existing Phase 1 round-trip:
- Connect → modify config field → wait debounce (10s) → assert remote modifiedTime advanced
- Same account, simulate second device (different device-id) → record usage → sync → assert merged file contains both device buckets

Marked `@pytest.mark.real_drive`, excluded from default pytest runs.

### 8.3 Manual test plan

Extend `docs/MANUAL_TESTS.md` "Cloud Sync" section with Phase 2 scenarios:
1. Edit a synced setting (hotkey, postprocess.mode), wait 10s, verify on second device's next startup
2. Edit a deny-list setting (whisper.model), wait 10s, verify second device's value NOT changed
3. Use both devices on same day for LLM calls, verify monthly_cost_limit_usd warning fires at correct total
4. Disconnect on device A, change settings, reconnect — verify changes pushed on reconnect
5. Wipe `%APPDATA%\Soyle\`, connect, accept settings restore prompt — verify hotkey/postprocess/etc all restored

### 8.4 Out of scope for testing

- Drive `modifiedTime` precision (Google guarantees ms-resolution; tolerance handles drift)
- Cross-version Söyle compatibility (forward-compat covered by schema mismatch handling; backward not a real scenario for single-user app)
- QTimer accuracy under heavy GUI load (Qt's native; trust the platform)

## 9. Open questions / future phases

- **Phase 3 — real-time pull via Drive `changes.watch`.** Push notifications when remote file changes. Complex: requires long-running HTTP listener or polling fallback, debouncing burst notifications, race-condition handling for "remote changed while I was editing locally". Not justified for two-device single-user setup; revisit if user count grows.
- **Phase 3 — per-field LWW for `config.toml`.** Add `_modified_at` per Pydantic field. Mostly useful if conflict frequency proves annoying in practice.
- **Phase 3 — selective sync UI.** Per-section toggle in Settings ("don't sync hotkey to this device"). Currently deny-list is hardcoded; user-editable would address rare edge cases (lefty desktop vs righty laptop with different hotkeys).
- **Phase 3 — delete propagation for usage history.** If a user wants to wipe `usage.json` everywhere ("clear all history"), today they'd have to disconnect, wipe locally, and reconnect — the merge would re-pull other devices' entries. Phase 3 tombstone semantics from Phase 1's roadmap apply here too.
- **Phase 3 — encryption at rest.** Inherits Phase 1's deferred item; applies to all 3 synced files.
- **Phase 4 — multi-account.** Inherits Phase 1's deferred item.

## 10. References

- **Predecessor spec:** [Cloud Sync Phase 1](2026-04-30-cloud-sync-design.md) — `dictionary.toml` sync (shipped 2026-05-21).
- **Reused codebase patterns:**
  - `CloudSync` class — [cloud_sync.py:311](../../../src/soyle/core/cloud_sync.py)
  - Phase 1 Drive primitive pair — [cloud_sync.py:685](../../../src/soyle/core/cloud_sync.py) (`_drive_get_dictionary`)
  - Per-day usage tracking — [usage.py:21](../../../src/soyle/core/usage.py)
  - Pydantic `CloudSyncConfig` section (already exists) — [config.py:116](../../../src/soyle/core/config.py)
  - `_backup_broken` symlink-defended file rename — [config.py:211](../../../src/soyle/core/config.py)
  - AsyncRunnable Qt-asyncio bridge — [async_runnable.py](../../../src/soyle/ui/async_runnable.py)
  - keyring secret storage — [config.py:235](../../../src/soyle/core/config.py)
  - `respx` mocking pattern — [test_cloud_sync.py](../../../tests/unit/test_cloud_sync.py)
- **External docs:**
  - Drive `modifiedTime` field — https://developers.google.com/drive/api/reference/rest/v3/files
  - PKCE for installed apps — https://developers.google.com/identity/protocols/oauth2/native-app
- **Background motivation:**
  - User memory `cloud_sync_phase1_state` — Phase 1 shipped, GCP client_id is the only remaining gate to end-to-end use.
  - Original Phase 1 spec section 9 — explicitly grouped `config.toml` and `usage.json` as Phase 2 scope.
