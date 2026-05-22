# Cloud Sync Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Per-user constraint:** This project's owner uses explicit gates. Each `git commit` step here is staged work — confirm with the user (`коммить` gate) before running it.

**Goal:** Extend Phase 1's `CloudSync` to also sync `config.toml` (with deny-list LWW) and `usage.json` (with per-device buckets), plus debounced push on settings changes.

**Architecture:** All new code stays in `cloud_sync.py` (Approach A from spec). `usage.py` migrates to v2 per-device schema. `config.py` gains `mtime()`, `apply_synced_overrides()`, and a push-hook slot. `sync_now()` becomes partial-failure-tolerant across three files.

**Tech Stack:** Python 3.12, PySide6 (QTimer), httpx, keyring, Pydantic, tomli-w, stdlib (`uuid`, `copy`, `json`). No new pip deps. Tests: pytest, pytest-asyncio, respx, pytest-mock.

**Reference:** [docs/superpowers/specs/2026-05-22-cloud-sync-phase2-design.md](../specs/2026-05-22-cloud-sync-phase2-design.md)

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/soyle/core/cloud_sync.py` | modify | Add device-id helper, deny-list, dotted-path helpers, strip/merge pure functions, 4 new Drive primitives, 2 new sync methods (`_sync_config`/`_sync_usage`), extend `sync_now`, add QTimer-based debounced push |
| `src/soyle/core/usage.py` | modify | Migrate schema v1 (flat) → v2 (per-device buckets). New methods `serialize_for_sync()` / `apply_merged()` |
| `src/soyle/core/config.py` | modify | `ConfigStore.mtime()` + `apply_synced_overrides()` + push-hook slot triggered on `save()` |
| `src/soyle/app.py` | modify | DI: pass `usage_tracker` to `CloudSync` constructor; wire `config_store.set_push_hook(cloud_sync.schedule_config_push)`; extend first-run wizard with settings-restore prompt |
| `src/soyle/ui/settings.py` | modify | Update Cloud Sync tab status label (now covers 3 files instead of just dictionary) |
| `tests/unit/test_cloud_sync.py` | modify | +25 tests covering all new helpers, merge functions, Drive primitives, sync orchestration, debounce, device-id |
| `tests/unit/test_usage.py` | modify | +10 tests covering schema migration, per-device record/today/this_month, serialize/apply_merged |
| `tests/unit/test_config.py` | modify | +5 tests covering `mtime()`, `apply_synced_overrides()`, `set_push_hook()` |
| `docs/MANUAL_TESTS.md` | modify | New "Cloud Sync (Phase 2)" section with checklist scenarios |

**No new files** — all extensions land in existing modules. Test scaffolding (fixtures, imports) is added per-task as needed.

---

## Task 1: `_device_id()` helper

**Files:**
- Modify: `src/soyle/core/cloud_sync.py` (add helper near top, after `_TokenStore`)
- Modify: `tests/unit/test_cloud_sync.py` (add tests at end, before existing class-based tests if any)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 1: device_id ----

def test_device_id_generated_on_first_call_when_keyring_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First call generates a UUID and persists it to keyring."""
    from soyle.core import cloud_sync as cs

    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        cs.keyring, "get_password",
        lambda service, user: stored.get((service, user)),
    )
    monkeypatch.setattr(
        cs.keyring, "set_password",
        lambda service, user, pwd: stored.__setitem__((service, user), pwd),
    )

    result = cs._device_id()

    # UUID4 string: 36 chars, includes hyphens at fixed positions
    assert len(result) == 36
    assert result[8] == "-" and result[13] == "-" and result[18] == "-"
    # Persisted to keyring under (APP_NAME, "device-id")
    assert stored == {("Söyle", "device-id"): result}


def test_device_id_persisted_across_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second call returns the same UUID from keyring — no regeneration."""
    from soyle.core import cloud_sync as cs

    stored: dict[tuple[str, str], str] = {
        ("Söyle", "device-id"): "11111111-2222-3333-4444-555555555555",
    }
    monkeypatch.setattr(
        cs.keyring, "get_password",
        lambda service, user: stored.get((service, user)),
    )
    set_calls = []
    monkeypatch.setattr(
        cs.keyring, "set_password",
        lambda service, user, pwd: set_calls.append((service, user, pwd)),
    )

    result = cs._device_id()

    assert result == "11111111-2222-3333-4444-555555555555"
    assert set_calls == []  # nothing written — value already present
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "device_id"
```

Expected: 2 failures — `AttributeError: module 'soyle.core.cloud_sync' has no attribute '_device_id'`.

- [ ] **Step 3: Implement `_device_id()` in `cloud_sync.py`**

Add `import uuid` to the existing import block at the top of `src/soyle/core/cloud_sync.py` (alphabetically between `tomllib` and `webbrowser`).

After the `_TokenStore` class definition (around line 263), add:

```python
# ---- Device identity --------------------------------------------------------

# APP_NAME is imported from config to keep keyring service names in one place.
# We add a SEPARATE keyring entry — distinct service ("Söyle Cloud") is for
# OAuth refresh token; device-id uses APP_NAME ("Söyle") with username
# "device-id" so the two don't collide and either can be cleared independently.
from soyle.core.config import APP_NAME as _APP_NAME  # noqa: E402  (late import to avoid circularity at module load)

_DEVICE_ID_KEYRING_USERNAME = "device-id"


def _device_id() -> str:
    """Stable per-machine UUID. Generated on first call, persisted in
    Windows Credential Manager under (APP_NAME, "device-id"). Survives
    config wipes; new machine = new ID by definition.

    Used by usage.py per-device buckets to attribute LLM cost/requests
    to the device that recorded them, so cross-device merge avoids
    double-counting on the same date.
    """
    existing = keyring.get_password(_APP_NAME, _DEVICE_ID_KEYRING_USERNAME)
    if existing:
        return existing
    new_id = str(uuid.uuid4())
    keyring.set_password(_APP_NAME, _DEVICE_ID_KEYRING_USERNAME, new_id)
    return new_id
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "device_id"
```

Expected: 2 passes.

- [ ] **Step 5: Run mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add _device_id() — stable per-machine UUID in keyring

Lazy-generated UUID4 string persisted under (APP_NAME, "device-id"),
independent of the existing OAuth refresh token entry (KEYRING_SERVICE).
First call generates + saves; subsequent calls return the cached value.

Used by Phase 2 usage.json per-device buckets so cross-device cost
totals don't double-count concurrent same-day usage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `UsageTracker` v1 → v2 schema migration + per-device `record()`

**Files:**
- Modify: `src/soyle/core/usage.py` (refactor `_load`, `record`, `_save`)
- Modify: `tests/unit/test_usage.py` (add tests covering migration + per-device record)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_usage.py`:

```python
# ---- Phase 2: per-device schema ----

import json as _json


def _stub_device_id(monkeypatch: pytest.MonkeyPatch, device: str) -> None:
    """Force usage._device_id() (re-exported from cloud_sync) to return `device`."""
    from soyle.core import usage as u
    monkeypatch.setattr(u, "_device_id", lambda: device)


def test_record_writes_only_to_own_device_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_device_id(monkeypatch, "dev-A")
    tracker = UsageTracker(tmp_path / "usage.json")
    tracker.record(0.01)

    raw = _json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    # v2 schema: top-level keys are dates, values are {device_id: {cost,reqs}}
    [date_key] = raw.keys()
    assert raw[date_key] == {"dev-A": {"cost_usd": 0.01, "requests": 1}}


def test_record_accumulates_within_own_bucket_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two calls on the same device sum into one bucket, not split per-call."""
    _stub_device_id(monkeypatch, "dev-A")
    tracker = UsageTracker(tmp_path / "usage.json")
    tracker.record(0.01)
    tracker.record(0.02)

    raw = _json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    [date_key] = raw.keys()
    # Floating-point: 0.01 + 0.02 = 0.030000000000000002 — use approx
    bucket = raw[date_key]["dev-A"]
    assert bucket["cost_usd"] == pytest.approx(0.03)
    assert bucket["requests"] == 2


def test_record_does_not_touch_other_devices_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing 'dev-B' entry on disk survives when 'dev-A' records."""
    seed = {
        "2026-05-22": {"dev-B": {"cost_usd": 0.05, "requests": 3}},
    }
    (tmp_path / "usage.json").write_text(_json.dumps(seed), encoding="utf-8")
    monkeypatch.setattr(
        "soyle.core.usage._today_key_for_test", lambda: "2026-05-22", raising=False,
    )
    _stub_device_id(monkeypatch, "dev-A")
    # Pin today's date to match the seed so the new bucket lands on the same day.
    from soyle.core import usage as u
    monkeypatch.setattr(u.UsageTracker, "_today_key", staticmethod(lambda: "2026-05-22"))

    tracker = UsageTracker(tmp_path / "usage.json")
    tracker.record(0.01)

    raw = _json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert raw["2026-05-22"]["dev-B"] == {"cost_usd": 0.05, "requests": 3}
    assert raw["2026-05-22"]["dev-A"] == {"cost_usd": 0.01, "requests": 1}


def test_load_migrates_v1_flat_schema_to_v2_per_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v1 file (flat {date: {cost, requests}}) is detected and rewritten to v2
    on first load, attributing all entries to current device."""
    v1_data = {
        "2026-05-20": {"cost_usd": 0.10, "requests": 5},
        "2026-05-21": {"cost_usd": 0.20, "requests": 8},
    }
    (tmp_path / "usage.json").write_text(_json.dumps(v1_data), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    tracker = UsageTracker(tmp_path / "usage.json")
    # After load, in-memory state is v2; today()/this_month() see the dev-A
    # totals carried over from the migrated v1 entries.
    serialized = tracker.serialize_for_sync()
    assert serialized == {
        "2026-05-20": {"dev-A": {"cost_usd": 0.10, "requests": 5}},
        "2026-05-21": {"dev-A": {"cost_usd": 0.20, "requests": 8}},
    }


def test_v2_schema_passes_through_load_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading a v2-format file does not corrupt or re-migrate it."""
    v2_data = {
        "2026-05-22": {
            "dev-A": {"cost_usd": 0.05, "requests": 2},
            "dev-B": {"cost_usd": 0.07, "requests": 4},
        },
    }
    (tmp_path / "usage.json").write_text(_json.dumps(v2_data), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    tracker = UsageTracker(tmp_path / "usage.json")
    assert tracker.serialize_for_sync() == v2_data
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_usage.py -v -k "per_device or migrates or v2_schema"
```

Expected: failures — `serialize_for_sync` not implemented, schema not migrated.

- [ ] **Step 3: Replace `src/soyle/core/usage.py` with v2 implementation**

Open `src/soyle/core/usage.py` and replace its contents with:

```python
"""Lightweight daily usage tracker — per-device buckets (v2).

Stored at `%APPDATA%/Soyle/usage.json` as nested dict:
    {date: {device_id: {"cost_usd": float, "requests": int}}}

v1 files (flat `{date: {cost_usd, requests}}`) are auto-migrated on first
load by attributing existing entries to the current device's UUID. The
migration is self-describing — v1's value type is the inner dict directly,
v2's value type wraps inner dicts under device-id keys.

Per-device schema is required so cross-device sync via Drive can merge
without double-counting: each device only writes to its own bucket, so
LWW per `(date, device_id)` tuple has zero conflict opportunity.

Entries older than 45 days are trimmed on save so the file stays bounded.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import structlog

# Re-exported so tests can monkeypatch `usage._device_id` without reaching
# into cloud_sync. The runtime function lives in cloud_sync.py to keep
# the keyring-touching code in one place.
from soyle.core.cloud_sync import _device_id

log = structlog.get_logger()

_RETENTION_DAYS = 45

# Inner-bucket type: {"cost_usd": float, "requests": int}
_Bucket = dict[str, float]
# Per-device map for a single date
_DateEntry = dict[str, _Bucket]
# Whole-file v2 state
_V2State = dict[str, _DateEntry]


class UsageTracker:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: _V2State = self._load()

    def record(self, cost_usd: float) -> None:
        """Add a single polished request to today's bucket for THIS device."""
        today = self._today_key()
        device = _device_id()
        date_entry = self._data.setdefault(today, {})
        bucket = date_entry.setdefault(device, {"cost_usd": 0.0, "requests": 0})
        bucket["cost_usd"] = float(bucket.get("cost_usd", 0.0)) + float(cost_usd)
        bucket["requests"] = int(bucket.get("requests", 0)) + 1
        self._trim_old()
        self._save()

    def today(self) -> tuple[float, int]:
        """Sum across ALL devices for today — gives cross-device total."""
        return self._sum_for_dates({self._today_key()})

    def this_month(self) -> tuple[float, int]:
        """Sum across ALL devices for the current calendar month (UTC)."""
        prefix = datetime.now(tz=UTC).strftime("%Y-%m-")
        matching = {d for d in self._data if d.startswith(prefix)}
        return self._sum_for_dates(matching)

    def summary_line(self) -> str:
        """Human-readable single-line summary for the tray menu."""
        today_cost, today_n = self.today()
        month_cost, month_n = self.this_month()
        return (
            f"Сегодня: ${today_cost:.4f} ({today_n}) · "
            f"за месяц: ${month_cost:.4f} ({month_n})"
        )

    # -- Phase 2: cross-device sync API ---------------------------------------

    def serialize_for_sync(self) -> _V2State:
        """Return a deep-copy snapshot of the full v2 state for CloudSync.

        Returns the nested dict in the same shape that's persisted on disk.
        Cloud sync uses this to compute the merge against remote state.
        """
        return _deep_copy_state(self._data)

    def apply_merged(self, merged: _V2State) -> None:
        """Replace local state with a merged version from CloudSync.

        Called after `_merge_usage(local, remote)` produces the union of
        per-device buckets. Caller guarantees the format is v2.
        """
        self._data = _deep_copy_state(merged)
        self._trim_old()
        self._save()

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _today_key() -> str:
        return datetime.now(tz=UTC).strftime("%Y-%m-%d")

    def _sum_for_dates(self, dates: set[str]) -> tuple[float, int]:
        total_cost = 0.0
        total_req = 0
        for d in dates:
            date_entry = self._data.get(d, {})
            for bucket in date_entry.values():
                total_cost += float(bucket.get("cost_usd", 0.0))
                total_req += int(bucket.get("requests", 0))
        return total_cost, total_req

    def _trim_old(self) -> None:
        cutoff = datetime.now(tz=UTC).date() - timedelta(days=_RETENTION_DAYS)
        stale = [
            day for day in self._data
            if (parsed := self._parse_day(day)) is not None and parsed < cutoff
        ]
        for day in stale:
            del self._data[day]

    @staticmethod
    def _parse_day(key: str) -> date | None:
        try:
            return datetime.strptime(key, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _load(self) -> _V2State:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("usage_load_failed", error=str(exc), path=str(self._path))
            return {}
        if not isinstance(raw, dict):
            return {}
        if _looks_like_v1(raw):
            log.info("usage_migrating_v1_to_v2", path=str(self._path))
            migrated = _migrate_v1_to_v2(raw)
            # Persist immediately so next load() short-circuits the migration.
            self._data = migrated
            self._save()
            return migrated
        return raw  # already v2

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("usage_save_failed", error=str(exc), path=str(self._path))


# ---- v1 → v2 migration -------------------------------------------------------

def _looks_like_v1(raw: dict) -> bool:
    """Heuristic: v1 value is {"cost_usd": float, "requests": int}; v2 value
    is {device_id: {"cost_usd": ..., "requests": ...}}.

    Detect v1 by checking whether the FIRST value at top level has cost_usd
    directly (v1) or wraps device-id keys whose values have cost_usd (v2).
    Empty dict is neither — treat as v2 (no migration needed).
    """
    if not raw:
        return False
    first_value = next(iter(raw.values()))
    if not isinstance(first_value, dict):
        return False
    # v1: {"cost_usd": ...} at this level
    if "cost_usd" in first_value:
        return True
    # v2: nested dict; the inner values have cost_usd
    return False


def _migrate_v1_to_v2(raw: dict) -> _V2State:
    """Attribute every existing v1 entry to the current device's UUID."""
    device = _device_id()
    return {
        date_str: {device: dict(entry)}
        for date_str, entry in raw.items()
        if isinstance(entry, dict)
    }


def _deep_copy_state(state: _V2State) -> _V2State:
    """Shallow-enough copy preserving nested-dict independence (no shared mutable refs)."""
    return {
        date_str: {device: dict(bucket) for device, bucket in date_entry.items()}
        for date_str, date_entry in state.items()
    }
```

- [ ] **Step 4: Run new tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_usage.py -v -k "per_device or migrates or v2_schema"
```

Expected: 5 passes.

- [ ] **Step 5: Run existing usage tests — confirm none regressed**

```
.venv/Scripts/pytest.exe tests/unit/test_usage.py -v
```

Expected: all pass. Note: existing tests like `test_record_creates_today_entry` may need updating in Task 3 if they assert on the old flat structure — for now they should at least not crash. If any FAIL because of the schema change, leave them as failing here (Task 3 cleans them up alongside `today()`/`this_month()` test updates).

- [ ] **Step 6: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/usage.py tests/unit/test_usage.py
```

Expected: both clean.

- [ ] **Step 7: Commit**

```
git add src/soyle/core/usage.py tests/unit/test_usage.py
git commit -m "$(cat <<'EOF'
feat(usage): migrate to v2 per-device schema

Schema changes from flat {date: {cost, requests}} to nested
{date: {device_id: {cost, requests}}}. Each device records only to its
own bucket — cross-device merge via CloudSync stays conflict-free.

Migration is inline + self-describing: v1 files (top-level value has
cost_usd directly) are detected on first load, rewritten with all
existing entries attributed to the current device's UUID, and saved
immediately so subsequent loads short-circuit the check.

New API: serialize_for_sync() returns deep-copy snapshot; apply_merged()
replaces state from CloudSync merge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `UsageTracker.today()` / `this_month()` cross-device sums

**Files:**
- Modify: `tests/unit/test_usage.py` (update existing tests + add new cross-device sum tests)

The implementation for `today()` and `this_month()` already lives in Task 2's `usage.py` rewrite (they call `_sum_for_dates` which aggregates across devices). Task 3 codifies the cross-device sum behavior in tests AND repairs any pre-existing flat-schema assertions left over from v1.

- [ ] **Step 1: Inventory which existing tests still assert v1 shape**

Run:
```
.venv/Scripts/pytest.exe tests/unit/test_usage.py -v 2>&1 | grep -E "FAIL|ERROR"
```

Expected output lists 0+ failing tests from Task 2's commit. Read each failing test's source and decide: rewrite to v2 shape OR delete if it duplicates a new Phase 2 test.

- [ ] **Step 2: Write new cross-device sum tests**

Append to `tests/unit/test_usage.py`:

```python
def test_today_sums_across_all_devices_for_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    today_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    seed = {
        today_key: {
            "dev-A": {"cost_usd": 0.05, "requests": 3},
            "dev-B": {"cost_usd": 0.07, "requests": 4},
        },
    }
    (tmp_path / "usage.json").write_text(_json.dumps(seed), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    tracker = UsageTracker(tmp_path / "usage.json")
    cost, reqs = tracker.today()

    assert cost == pytest.approx(0.12)
    assert reqs == 7


def test_this_month_sums_across_all_devices_for_current_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = datetime.now(tz=UTC).strftime("%Y-%m-")
    seed = {
        f"{prefix}01": {"dev-A": {"cost_usd": 0.10, "requests": 5}},
        f"{prefix}15": {"dev-B": {"cost_usd": 0.20, "requests": 8}},
        # An entry from a previous month — must NOT count
        "2020-01-01": {"dev-A": {"cost_usd": 99.0, "requests": 999}},
    }
    (tmp_path / "usage.json").write_text(_json.dumps(seed), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    tracker = UsageTracker(tmp_path / "usage.json")
    cost, reqs = tracker.this_month()

    assert cost == pytest.approx(0.30)
    assert reqs == 13


def test_summary_line_reflects_cross_device_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tray menu line shows totals summed across all devices, not just current."""
    today_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    seed = {
        today_key: {
            "dev-A": {"cost_usd": 0.01, "requests": 1},
            "dev-B": {"cost_usd": 0.02, "requests": 2},
        },
    }
    (tmp_path / "usage.json").write_text(_json.dumps(seed), encoding="utf-8")
    _stub_device_id(monkeypatch, "dev-A")

    line = UsageTracker(tmp_path / "usage.json").summary_line()
    # 0.01 + 0.02 = 0.03, rendered to 4 decimals
    assert "$0.0300" in line
    assert "(3)" in line  # 1+2 requests


def test_apply_merged_replaces_full_state_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_device_id(monkeypatch, "dev-A")
    tracker = UsageTracker(tmp_path / "usage.json")
    tracker.record(0.05)  # local: today has dev-A

    today_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    new_state = {
        today_key: {
            "dev-A": {"cost_usd": 0.05, "requests": 1},
            "dev-B": {"cost_usd": 0.10, "requests": 2},  # other device merged in
        },
    }
    tracker.apply_merged(new_state)

    # On-disk reflects the merged version
    raw = _json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert raw == new_state
    # today() sum reflects both devices now
    cost, reqs = tracker.today()
    assert cost == pytest.approx(0.15)
    assert reqs == 3


def test_apply_merged_trims_entries_older_than_45_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_device_id(monkeypatch, "dev-A")
    tracker = UsageTracker(tmp_path / "usage.json")

    long_ago = (datetime.now(tz=UTC).date() - timedelta(days=60)).strftime("%Y-%m-%d")
    today_key = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    merged = {
        long_ago: {"dev-A": {"cost_usd": 99.0, "requests": 999}},
        today_key: {"dev-A": {"cost_usd": 0.05, "requests": 1}},
    }
    tracker.apply_merged(merged)

    raw = _json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert long_ago not in raw
    assert today_key in raw
```

- [ ] **Step 3: Rewrite any v1-shape assertions in legacy tests**

For each failing test from Step 1, update its setup to use v2 nested shape and its assertions to call `today()`/`this_month()` (which return summed tuples) rather than reading `_data` directly. Example transformation:

```python
# BEFORE (v1-shape, will fail under Task 2 schema)
tracker._data = {"2026-05-22": {"cost_usd": 0.05, "requests": 1}}
assert tracker.today() == (0.05, 1)

# AFTER (v2-shape)
import json as _json
_stub_device_id(monkeypatch, "dev-A")
(tmp_path / "usage.json").write_text(
    _json.dumps({"2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 1}}}),
    encoding="utf-8",
)
# Pin today_key if the test depends on a specific date
monkeypatch.setattr(UsageTracker, "_today_key", staticmethod(lambda: "2026-05-22"))
tracker = UsageTracker(tmp_path / "usage.json")
assert tracker.today() == (pytest.approx(0.05), 1)
```

- [ ] **Step 4: Run full usage suite**

```
.venv/Scripts/pytest.exe tests/unit/test_usage.py -v
```

Expected: all pass (legacy + new Phase 2 = ~15-18 tests).

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check tests/unit/test_usage.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add tests/unit/test_usage.py
git commit -m "$(cat <<'EOF'
test(usage): cover v2 cross-device sums + repair v1-shape legacy tests

today() and this_month() now aggregate across all device_id buckets
for each date — codified by three new tests with seeded multi-device
state plus a summary_line() round-trip check.

apply_merged() coverage: full-state replacement is atomic, retention
trim runs as part of the apply (so a merge that pulls in 60-day-old
remote entries doesn't outlive the local 45-day window).

Legacy tests that asserted on v1 flat shape converted to use
_stub_device_id + nested seed shape.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `_CONFIG_DENY_LIST` + dotted-path helpers in `cloud_sync.py`

**Files:**
- Modify: `src/soyle/core/cloud_sync.py` (add constants + 3 helper functions)
- Modify: `tests/unit/test_cloud_sync.py` (add tests for each helper)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 4: deny-list + dotted-path helpers ----

def test_config_deny_list_contains_expected_device_local_paths() -> None:
    from soyle.core import cloud_sync as cs
    expected = {
        "version",
        "audio.device",
        "whisper.model",
        "whisper.device",
        "whisper.compute_type",
        "behavior.autostart",
        "behavior.inject_method",
        "ui.theme",
        "cloud_sync",
    }
    assert cs._CONFIG_DENY_LIST == frozenset(expected)


def test_get_dotted_returns_value_at_nested_path() -> None:
    from soyle.core.cloud_sync import _get_dotted
    data = {"hotkey": {"combination": "right alt", "mode": "push_to_talk"}}
    assert _get_dotted(data, "hotkey.combination") == "right alt"


def test_get_dotted_returns_top_level_value_for_single_segment() -> None:
    from soyle.core.cloud_sync import _get_dotted
    data = {"version": 1, "hotkey": {"combination": "right alt"}}
    assert _get_dotted(data, "version") == 1


def test_get_dotted_returns_none_when_path_missing() -> None:
    from soyle.core.cloud_sync import _get_dotted
    data = {"hotkey": {"combination": "right alt"}}
    assert _get_dotted(data, "audio.device") is None
    assert _get_dotted(data, "hotkey.nonexistent") is None


def test_set_dotted_creates_intermediate_dicts_when_missing() -> None:
    from soyle.core.cloud_sync import _set_dotted
    data: dict = {}
    _set_dotted(data, "audio.device", "default")
    assert data == {"audio": {"device": "default"}}


def test_set_dotted_overwrites_existing_value() -> None:
    from soyle.core.cloud_sync import _set_dotted
    data: dict = {"audio": {"device": "old"}}
    _set_dotted(data, "audio.device", "new")
    assert data["audio"]["device"] == "new"


def test_set_dotted_handles_top_level_path() -> None:
    from soyle.core.cloud_sync import _set_dotted
    data: dict = {"hotkey": {"combination": "alt"}}
    _set_dotted(data, "version", 2)
    assert data["version"] == 2


def test_del_dotted_removes_leaf_value() -> None:
    from soyle.core.cloud_sync import _del_dotted
    data: dict = {"audio": {"device": "default", "sample_rate": 16000}}
    _del_dotted(data, "audio.device")
    assert data == {"audio": {"sample_rate": 16000}}


def test_del_dotted_removes_entire_section_when_path_is_section_root() -> None:
    """Deleting 'cloud_sync' removes the whole [cloud_sync] section."""
    from soyle.core.cloud_sync import _del_dotted
    data: dict = {
        "hotkey": {"combination": "alt"},
        "cloud_sync": {"last_synced_at": "2026-05-22T10:00:00+00:00"},
    }
    _del_dotted(data, "cloud_sync")
    assert "cloud_sync" not in data
    assert "hotkey" in data


def test_del_dotted_silent_when_path_missing() -> None:
    """No-op (no exception) if the path doesn't exist — useful when stripping
    deny-list paths from a config that doesn't have them set."""
    from soyle.core.cloud_sync import _del_dotted
    data: dict = {"hotkey": {"combination": "alt"}}
    _del_dotted(data, "audio.device")  # should not raise
    assert data == {"hotkey": {"combination": "alt"}}
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "deny_list or dotted"
```

Expected: 10 failures — none of the symbols exist yet.

- [ ] **Step 3: Add deny-list + helpers to `cloud_sync.py`**

After the `_device_id()` block from Task 1, append:

```python
# ---- Phase 2: Config deny-list + dotted-path helpers ------------------------

# Dotted paths from Config root that are NEVER synced — these stay per-device.
# Format matches Pydantic model_dump keys: top-level section + dot + field,
# or just the section name to skip the entire section.
_CONFIG_DENY_LIST: frozenset[str] = frozenset({
    "version",                 # schema metadata, not a user preference
    "audio.device",            # mic name differs per machine
    "whisper.model",           # GPU tier dictates which preset is usable
    "whisper.device",          # cuda/cpu/auto — hardware-bound
    "whisper.compute_type",    # int8/float16 — GPU-dependent
    "behavior.autostart",      # often true on one machine, false on another
    "behavior.inject_method",  # clipboard/keystroke — per-app workarounds vary
    "ui.theme",                # monitor-dependent preference
    "cloud_sync",              # entire section: per-device last_synced_at state
})


def _get_dotted(data: dict, path: str) -> object:
    """Look up `path` in `data` ("foo.bar.baz"); return None if missing."""
    parts = path.split(".")
    current: object = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_dotted(data: dict, path: str, value: object) -> None:
    """Set `path` in `data` to `value`. Creates intermediate dicts."""
    parts = path.split(".")
    cursor = data
    for part in parts[:-1]:
        next_level = cursor.get(part)
        if not isinstance(next_level, dict):
            next_level = {}
            cursor[part] = next_level
        cursor = next_level
    cursor[parts[-1]] = value


def _del_dotted(data: dict, path: str) -> None:
    """Remove `path` from `data` if present; silent no-op otherwise."""
    parts = path.split(".")
    cursor = data
    for part in parts[:-1]:
        next_level = cursor.get(part)
        if not isinstance(next_level, dict):
            return  # path doesn't exist — nothing to delete
        cursor = next_level
    cursor.pop(parts[-1], None)
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "deny_list or dotted"
```

Expected: 10 passes.

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add _CONFIG_DENY_LIST + dotted-path helpers

Module-level frozenset of 9 dotted paths that never sync (device-local
preferences: mic, GPU tier, autostart, theme, schema version, and the
entire cloud_sync section).

Three pure helpers — _get_dotted, _set_dotted, _del_dotted — operate
on plain dict-of-dicts produced by Config.model_dump(). Used by the
upcoming _strip_deny and _merge_config functions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `_strip_deny()` pure function

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 5: _strip_deny ----

def _make_config_with_overrides(**overrides: object):
    """Build a Config with selected non-default fields. Returns the Config."""
    from soyle.core.config import (
        AudioConfig, BehaviorConfig, CloudSyncConfig, Config,
        HotkeyConfig, PostProcessConfig, UIConfig, WhisperConfig,
    )
    cfg = Config(
        hotkey=HotkeyConfig(**overrides.get("hotkey", {})),
        audio=AudioConfig(**overrides.get("audio", {})),
        whisper=WhisperConfig(**overrides.get("whisper", {})),
        postprocess=PostProcessConfig(**overrides.get("postprocess", {})),
        ui=UIConfig(**overrides.get("ui", {})),
        behavior=BehaviorConfig(**overrides.get("behavior", {})),
        cloud_sync=CloudSyncConfig(**overrides.get("cloud_sync", {})),
    )
    return cfg


def test_strip_deny_removes_all_listed_dotted_paths() -> None:
    from soyle.core.cloud_sync import _strip_deny

    cfg = _make_config_with_overrides(
        audio={"device": "MyMic"},
        whisper={"model": "large-v3", "device": "cuda", "compute_type": "float16"},
        behavior={"autostart": True, "inject_method": "keystroke"},
        ui={"theme": "light"},
    )
    stripped = _strip_deny(cfg)

    # All 9 deny-list paths must be absent
    assert "version" not in stripped
    assert "device" not in stripped.get("audio", {})
    assert "model" not in stripped.get("whisper", {})
    assert "device" not in stripped.get("whisper", {})
    assert "compute_type" not in stripped.get("whisper", {})
    assert "autostart" not in stripped.get("behavior", {})
    assert "inject_method" not in stripped.get("behavior", {})
    assert "theme" not in stripped.get("ui", {})
    assert "cloud_sync" not in stripped


def test_strip_deny_preserves_synced_fields() -> None:
    from soyle.core.cloud_sync import _strip_deny

    cfg = _make_config_with_overrides(
        hotkey={"combination": "ctrl+shift"},
        postprocess={"mode": "rewrite", "model": "google/gemini-2.5-flash"},
        ui={"sound_enabled": False},
    )
    stripped = _strip_deny(cfg)

    assert stripped["hotkey"]["combination"] == "ctrl+shift"
    assert stripped["postprocess"]["mode"] == "rewrite"
    assert stripped["postprocess"]["model"] == "google/gemini-2.5-flash"
    assert stripped["ui"]["sound_enabled"] is False


def test_strip_deny_returns_dict_not_pydantic_model() -> None:
    """Returns a plain dict (Pydantic dump shape) suitable for TOML serialize."""
    from soyle.core.cloud_sync import _strip_deny
    cfg = _make_config_with_overrides()
    stripped = _strip_deny(cfg)
    assert isinstance(stripped, dict)
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "strip_deny"
```

Expected: 3 failures — `_strip_deny` undefined.

- [ ] **Step 3: Implement `_strip_deny`**

Add `from typing import TYPE_CHECKING` near the existing typing-style imports, then a TYPE_CHECKING guarded import for Config:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soyle.core.config import Config
```

After the dotted-path helpers added in Task 4, append:

```python
def _strip_deny(config: "Config") -> dict:
    """Serialize Config to dict, then remove every deny-list path.

    The returned dict is what gets uploaded to Drive — Drive never sees
    deny-listed fields at all. Symmetric with _merge_config, which
    overlays local's deny-list values back onto whatever winner produced.
    """
    raw = config.model_dump(mode="json", exclude_none=True)
    for path in _CONFIG_DENY_LIST:
        _del_dotted(raw, path)
    return raw
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "strip_deny"
```

Expected: 3 passes.

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add _strip_deny — remove device-local fields before upload

Pure function: serialize Config via model_dump(mode="json",
exclude_none=True), then walk _CONFIG_DENY_LIST and _del_dotted each
path from the result. Drive never sees deny-listed values at all,
preventing them from ever being pushed by accident.

TYPE_CHECKING import for Config keeps the signature typed without
creating a runtime circular import.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `_merge_config()` pure function

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 6: _merge_config ----

def test_merge_config_remote_wins_when_remote_mtime_newer() -> None:
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides(hotkey={"combination": "alt"})
    remote = _make_config_with_overrides(hotkey={"combination": "ctrl"})
    local_mtime = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)
    remote_mtime = datetime(2026, 5, 22, 11, 0, 0, tzinfo=UTC)  # 1h newer

    merged = _merge_config(local, remote, local_mtime, remote_mtime)
    assert merged.hotkey.combination == "ctrl"


def test_merge_config_local_wins_when_local_mtime_newer() -> None:
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides(hotkey={"combination": "alt"})
    remote = _make_config_with_overrides(hotkey={"combination": "ctrl"})
    local_mtime = datetime(2026, 5, 22, 11, 0, 0, tzinfo=UTC)
    remote_mtime = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)

    merged = _merge_config(local, remote, local_mtime, remote_mtime)
    assert merged.hotkey.combination == "alt"


def test_merge_config_preserves_deny_list_from_local_when_remote_wins() -> None:
    """Even when remote wins on mtime, deny-list fields stay local."""
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides(
        whisper={"model": "small"},          # deny-list — must stay
        hotkey={"combination": "alt"},        # synced — remote wins
    )
    remote = _make_config_with_overrides(
        whisper={"model": "large-v3"},        # remote's value MUST NOT leak in
        hotkey={"combination": "ctrl"},
    )
    local_mtime = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)
    remote_mtime = datetime(2026, 5, 22, 11, 0, 0, tzinfo=UTC)

    merged = _merge_config(local, remote, local_mtime, remote_mtime)
    assert merged.hotkey.combination == "ctrl"       # remote wins on synced field
    assert merged.whisper.model == "small"           # local preserved on deny field


def test_merge_config_preserves_cloud_sync_section_from_local() -> None:
    """The entire cloud_sync section stays local — per-device state."""
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides(
        cloud_sync={"last_synced_at": datetime(2026, 5, 22, 12, tzinfo=UTC)},
    )
    remote = _make_config_with_overrides(
        cloud_sync={"last_synced_at": datetime(2020, 1, 1, tzinfo=UTC)},
    )
    local_mtime = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)
    remote_mtime = datetime(2026, 5, 22, 11, 0, 0, tzinfo=UTC)

    merged = _merge_config(local, remote, local_mtime, remote_mtime)
    assert merged.cloud_sync.last_synced_at == datetime(
        2026, 5, 22, 12, tzinfo=UTC,
    )


def test_merge_config_version_stays_local() -> None:
    """version is in deny-list — local schema version is authoritative."""
    from soyle.core.cloud_sync import _merge_config

    local = _make_config_with_overrides()
    remote = _make_config_with_overrides()
    merged = _merge_config(
        local, remote,
        datetime(2026, 5, 22, 10, tzinfo=UTC),
        datetime(2026, 5, 22, 11, tzinfo=UTC),
    )
    assert merged.version == local.version
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "merge_config"
```

Expected: 5 failures — `_merge_config` undefined.

- [ ] **Step 3: Implement `_merge_config`**

After `_strip_deny` in `cloud_sync.py`, append:

```python
def _merge_config(
    local: "Config",
    remote: "Config",
    local_mtime: datetime,
    remote_mtime: datetime,
) -> "Config":
    """LWW by mtime; preserve deny-list paths from local.

    Whoever's mtime is newer wins the whole file. Then every deny-list
    path is re-overlaid from local — keeping per-device fields (mic,
    GPU tier, autostart, theme) untouched even when remote wins.
    """
    from soyle.core.config import Config  # local import to avoid circularity

    winner = remote if remote_mtime > local_mtime else local
    winner_raw = winner.model_dump(mode="json", exclude_none=True)
    local_raw = local.model_dump(mode="json", exclude_none=True)
    for path in _CONFIG_DENY_LIST:
        local_value = _get_dotted(local_raw, path)
        if local_value is None:
            _del_dotted(winner_raw, path)
        else:
            _set_dotted(winner_raw, path, local_value)
    return Config.model_validate(winner_raw)
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "merge_config"
```

Expected: 5 passes.

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add _merge_config — whole-file LWW + deny overlay

Pure function. Picks the mtime-newer Config as the winner, then
overlays every _CONFIG_DENY_LIST path from local on top. Re-validates
through Pydantic so the returned Config has full type guarantees.

A deny-list path absent from local is removed from the merged result
entirely — keeping the merged dict shape consistent with TOML
serialization (no null values written).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `_merge_usage()` pure function

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 7: _merge_usage ----

def test_merge_usage_per_device_lww_no_conflict_on_own_keys() -> None:
    """A device only writes its own keys — same (date, device_id) tuple
    never has competing values from two writers."""
    from soyle.core.cloud_sync import _merge_usage

    local = {"2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 2}}}
    remote = {"2026-05-22": {"dev-A": {"cost_usd": 0.03, "requests": 1}}}
    # local owns dev-A's key; merge takes local's value
    merged = _merge_usage(local, remote)
    assert merged["2026-05-22"]["dev-A"] == {"cost_usd": 0.05, "requests": 2}


def test_merge_usage_picks_up_remote_device_entries_verbatim() -> None:
    from soyle.core.cloud_sync import _merge_usage

    local = {"2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 2}}}
    remote = {"2026-05-22": {"dev-B": {"cost_usd": 0.07, "requests": 3}}}

    merged = _merge_usage(local, remote)

    assert merged["2026-05-22"] == {
        "dev-A": {"cost_usd": 0.05, "requests": 2},
        "dev-B": {"cost_usd": 0.07, "requests": 3},
    }


def test_merge_usage_unions_dates_across_devices() -> None:
    from soyle.core.cloud_sync import _merge_usage

    local = {"2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 2}}}
    remote = {"2026-05-21": {"dev-B": {"cost_usd": 0.03, "requests": 1}}}

    merged = _merge_usage(local, remote)

    assert merged == {
        "2026-05-21": {"dev-B": {"cost_usd": 0.03, "requests": 1}},
        "2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 2}},
    }


def test_merge_usage_empty_local_returns_remote_copy() -> None:
    from soyle.core.cloud_sync import _merge_usage

    remote = {"2026-05-22": {"dev-B": {"cost_usd": 0.07, "requests": 3}}}
    merged = _merge_usage({}, remote)
    assert merged == remote
    # Independent — mutation of merged must not leak back to remote
    merged["2026-05-22"]["dev-B"]["cost_usd"] = 999.0
    assert remote["2026-05-22"]["dev-B"]["cost_usd"] == 0.07


def test_merge_usage_empty_remote_returns_local_copy() -> None:
    from soyle.core.cloud_sync import _merge_usage

    local = {"2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 2}}}
    merged = _merge_usage(local, {})
    assert merged == local
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "merge_usage"
```

Expected: 5 failures.

- [ ] **Step 3: Implement `_merge_usage`**

Add `import copy` to the existing import block (between `contextlib` and `enum`). After `_merge_config`, append:

```python
def _merge_usage(local: dict, remote: dict) -> dict:
    """Per-(date, device_id) LWW. Each device only writes its own keys,
    so a "conflict" on (date, my_id) can't happen — only one device
    writes that key. Remote-only keys (other devices' entries) carry
    over verbatim; local entries for my_id are authoritative.

    Deep-copies the result so callers can mutate freely without leaking
    changes back to the input dicts (matters when respx mocks reuse
    parsed bodies across test cases).
    """
    merged = copy.deepcopy(remote)
    for date_str, devices in local.items():
        merged.setdefault(date_str, {})
        for device_id, bucket in devices.items():
            merged[date_str][device_id] = copy.deepcopy(bucket)
    return merged
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "merge_usage"
```

Expected: 5 passes.

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add _merge_usage — per-(date, device_id) LWW

Pure additive merge. Each device only writes its own keys, so the
merged result never picks between two writers for the same tuple —
remote-only entries (other devices) carry over; local entries
overwrite per-device.

Deep-copies through copy.deepcopy so callers can mutate freely without
poisoning input dicts (matters when respx mocks reuse parsed bodies
across test cases).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `ConfigStore.mtime()` + `apply_synced_overrides()` + push-hook slot

**Files:**
- Modify: `src/soyle/core/config.py` (extend `ConfigStore` class)
- Modify: `tests/unit/test_config.py` (add Phase 2 tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_config.py`:

```python
# ---- Phase 2: Cloud sync push-hook + apply_synced_overrides ----

from datetime import timedelta


def test_mtime_returns_timezone_aware_utc_datetime(tmp_path: Path) -> None:
    """mtime() reads file's modified time as aware UTC datetime."""
    path = tmp_path / "config.toml"
    path.write_text("version = 1\n", encoding="utf-8")
    store = ConfigStore(config_path=path)

    result = store.mtime()
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)


def test_mtime_raises_when_file_does_not_exist(tmp_path: Path) -> None:
    """Calling mtime() before any save() raises FileNotFoundError."""
    store = ConfigStore(config_path=tmp_path / "missing.toml")
    with pytest.raises(FileNotFoundError):
        store.mtime()


def test_apply_synced_overrides_writes_remote_config(tmp_path: Path) -> None:
    """apply_synced_overrides persists the remote Config verbatim."""
    path = tmp_path / "config.toml"
    store = ConfigStore(config_path=path)
    _ = store.load()  # materialize default file

    remote = Config()
    remote.hotkey.combination = "ctrl+shift"
    remote.postprocess.mode = "rewrite"

    store.apply_synced_overrides(remote)

    reloaded = ConfigStore(config_path=path).load()
    assert reloaded.hotkey.combination == "ctrl+shift"
    assert reloaded.postprocess.mode == "rewrite"


def test_save_invokes_push_hook_when_registered(tmp_path: Path) -> None:
    """set_push_hook + save → hook called once."""
    store = ConfigStore(config_path=tmp_path / "config.toml")
    calls: list[int] = []
    store.set_push_hook(lambda: calls.append(1))

    cfg = store.load()
    cfg.hotkey.combination = "ctrl+alt"
    store.save(cfg)

    assert calls == [1]


def test_save_does_not_invoke_push_hook_when_not_registered(
    tmp_path: Path,
) -> None:
    """save() without a push hook works as before (no AttributeError)."""
    store = ConfigStore(config_path=tmp_path / "config.toml")
    cfg = store.load()
    cfg.hotkey.combination = "ctrl+alt"
    store.save(cfg)

    reloaded = ConfigStore(config_path=tmp_path / "config.toml").load()
    assert reloaded.hotkey.combination == "ctrl+alt"
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_config.py -v -k "mtime or apply_synced or push_hook"
```

Expected: 5 failures.

- [ ] **Step 3: Extend `ConfigStore` in `src/soyle/core/config.py`**

Add `from collections.abc import Callable` to the existing imports (alphabetically near `contextlib`).

In `ConfigStore.__init__`, after `self._existed_at_init = self._path.exists()`, add:

```python
        self._push_hook: Callable[[], None] | None = None
```

Add three new methods to `ConfigStore` (place them after the existing `reset_to_defaults` method, before the `# --- internals ---` divider):

```python
    def mtime(self) -> datetime:
        """Config file's modified time as aware UTC datetime.

        Used by CloudSync to compare local vs Drive modifiedTime when
        deciding push-vs-pull direction. Raises FileNotFoundError if the
        config has never been written.
        """
        stat = self._path.stat()
        return datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    def apply_synced_overrides(self, remote: Config) -> None:
        """Replace on-disk config with `remote`, then trigger any push
        hook just like a normal save would.

        Called by CloudSync after a successful pull. `remote` already
        has deny-list paths overlaid from local by `_merge_config`, so
        writing it verbatim is safe — no further merging at this layer.
        """
        self.save(remote)

    def set_push_hook(self, hook: Callable[[], None] | None) -> None:
        """Register a callable invoked synchronously at the end of every
        save(). Used by CloudSync to schedule a debounced push after the
        user changes settings. Pass None to clear."""
        self._push_hook = hook
```

Modify the existing `save` method to call the hook at the end:

```python
    def save(self, config: Config) -> None:
        self._ensure_parent()
        self._write(config)
        if self._push_hook is not None:
            self._push_hook()
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_config.py -v -k "mtime or apply_synced or push_hook"
```

Expected: 5 passes.

- [ ] **Step 5: Run full config suite — confirm no regression**

```
.venv/Scripts/pytest.exe tests/unit/test_config.py -v
```

Expected: all pass.

- [ ] **Step 6: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/config.py tests/unit/test_config.py
```

Expected: both clean.

- [ ] **Step 7: Commit**

```
git add src/soyle/core/config.py tests/unit/test_config.py
git commit -m "$(cat <<'EOF'
feat(config): add mtime(), apply_synced_overrides(), and push-hook slot

Three additions to ConfigStore for Phase 2 cloud sync wiring:

- mtime() reads st_mtime as aware UTC datetime — used by CloudSync
  to compare against Drive's modifiedTime for LWW direction
- apply_synced_overrides(remote) writes a merged Config to disk
  (currently same body as save(); kept as a distinct method so
  CloudSync's intent is clear at the call site)
- set_push_hook + save() invocation lets CloudSync register a
  debounced-push trigger that fires every time the user (or any
  call site) saves config

No Pydantic schema changes. Existing save() callers unaffected by
the hook slot — defaults to None so nothing happens unless the hook
is explicitly registered.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Drive primitives for `config.toml` (`_drive_get_config` + `_drive_put_config`)

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 9: Drive primitives for config.toml ----

import respx as _respx  # already used by Phase 1 tests, alias to avoid shadow
import httpx as _httpx
from soyle.core.cloud_sync import (
    DRIVE_API_BASE as _DRIVE_API_BASE,
    DRIVE_UPLOAD_BASE as _DRIVE_UPLOAD_BASE,
)

DRIVE_CONFIG_FILE_NAME = "config.toml"


@pytest.mark.asyncio
@_respx.mock
async def test_drive_get_config_returns_none_meta_when_404() -> None:
    """No file in App Data: returns (None, None)."""
    from soyle.core.cloud_sync import _drive_get_config

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )

    cfg, meta = await _drive_get_config(access_token="tok")
    assert cfg is None
    assert meta is None


@pytest.mark.asyncio
@_respx.mock
async def test_drive_get_config_parses_remote_toml() -> None:
    from soyle.core.cloud_sync import _drive_get_config

    body = b"version = 1\n\n[hotkey]\ncombination = \"ctrl+shift\"\n"
    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{
                "id": "F1",
                "name": "config.toml",
                "modifiedTime": "2026-05-22T10:00:00.000Z",
            }],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(
            200, content=body, headers={"ETag": "abc"},
        ),
    )

    cfg, meta = await _drive_get_config(access_token="tok")

    assert cfg is not None
    assert cfg.hotkey.combination == "ctrl+shift"
    assert meta is not None
    assert meta.file_id == "F1"
    assert meta.etag == "abc"
    assert meta.modified_time == datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
@_respx.mock
async def test_drive_get_config_raises_corrupted_on_invalid_toml() -> None:
    from soyle.core.cloud_sync import _drive_get_config, DriveCorruptedError

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "F1", "name": "config.toml", "modifiedTime": "2026-05-22T10:00:00.000Z"}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(200, content=b"not valid toml @@@ {{{"),
    )

    with pytest.raises(DriveCorruptedError):
        await _drive_get_config(access_token="tok")


@pytest.mark.asyncio
@_respx.mock
async def test_drive_put_config_creates_when_no_etag() -> None:
    """No etag → multipart create at upload endpoint."""
    from soyle.core.cloud_sync import _drive_put_config

    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "NEW"}),
    )

    stripped = {"hotkey": {"combination": "ctrl+shift"}}
    meta = await _drive_put_config(
        access_token="tok",
        file_id=None,
        etag=None,
        stripped_config=stripped,
    )
    assert create.called
    assert meta.file_id == "NEW"


@pytest.mark.asyncio
@_respx.mock
async def test_drive_put_config_updates_existing_with_if_match() -> None:
    from soyle.core.cloud_sync import _drive_put_config

    update = _respx.patch(f"{_DRIVE_UPLOAD_BASE}/files/F1").mock(
        return_value=_httpx.Response(
            200, json={"id": "F1"}, headers={"ETag": "new-etag"},
        ),
    )

    stripped = {"hotkey": {"combination": "ctrl+shift"}}
    meta = await _drive_put_config(
        access_token="tok",
        file_id="F1",
        etag="old-etag",
        stripped_config=stripped,
    )

    assert update.called
    assert update.calls.last.request.headers["If-Match"] == "old-etag"
    assert meta.file_id == "F1"
    assert meta.etag == "new-etag"


@pytest.mark.asyncio
@_respx.mock
async def test_drive_put_config_raises_concurrent_on_412() -> None:
    from soyle.core.cloud_sync import (
        _drive_put_config, DriveConcurrentWriteError,
    )

    _respx.patch(f"{_DRIVE_UPLOAD_BASE}/files/F1").mock(
        return_value=_httpx.Response(412),
    )

    with pytest.raises(DriveConcurrentWriteError):
        await _drive_put_config(
            access_token="tok",
            file_id="F1",
            etag="stale",
            stripped_config={"hotkey": {"combination": "alt"}},
        )
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "drive_get_config or drive_put_config"
```

Expected: 6 failures — symbols undefined.

- [ ] **Step 3: Add `_RemoteMeta` dataclass + Drive primitives**

After the existing `DriveConcurrentWriteError` class in `cloud_sync.py`, add:

```python
# ---- Phase 2: Drive primitives for config.toml + usage.json -----------------

DRIVE_CONFIG_FILE_NAME = "config.toml"
DRIVE_USAGE_FILE_NAME = "usage.json"


@dataclass(frozen=True)
class _RemoteMeta:
    """Metadata about a Drive file needed for the next round-trip:
    file_id (for PATCH path), etag (for If-Match), modifiedTime (for LWW)."""
    file_id: str
    etag: str | None
    modified_time: datetime


def _serialize_config_for_drive(stripped: dict) -> bytes:
    """Encode a deny-stripped config dict as TOML bytes."""
    return tomli_w.dumps(stripped).encode("utf-8")


async def _drive_get_config(
    *, access_token: str,
) -> tuple["Config | None", _RemoteMeta | None]:
    """Fetch config.toml from Drive App Data folder.

    Returns:
        (config, meta) — both None when file doesn't exist; otherwise
        parsed Config and metadata for the next write.

    Raises:
        DriveCorruptedError: file exists but TOML or Pydantic parse fails.
        httpx.HTTPError: network / 5xx.
    """
    from soyle.core.config import Config  # local: avoid circular import

    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        list_resp = await client.get(
            f"{DRIVE_API_BASE}/files",
            params={
                "spaces": "appDataFolder",
                "q": f"name='{DRIVE_CONFIG_FILE_NAME}' and trashed=false",
                "fields": "files(id,name,modifiedTime)",
            },
        )
        list_resp.raise_for_status()
        files = list_resp.json().get("files", [])
        if not files:
            return None, None

        file_id = files[0]["id"]
        modified_iso = files[0]["modifiedTime"]
        modified_dt = datetime.fromisoformat(modified_iso.replace("Z", "+00:00"))

        get_resp = await client.get(
            f"{DRIVE_API_BASE}/files/{file_id}",
            params={"alt": "media"},
        )
        get_resp.raise_for_status()
        etag = get_resp.headers.get("ETag")

    try:
        parsed_toml = tomllib.loads(get_resp.content.decode("utf-8"))
        cfg = Config.model_validate(parsed_toml)
    except (
        tomllib.TOMLDecodeError, UnicodeDecodeError, ValueError,
    ) as exc:
        raise DriveCorruptedError(file_id, exc) from exc

    return cfg, _RemoteMeta(
        file_id=file_id, etag=etag, modified_time=modified_dt,
    )


async def _drive_put_config(
    *,
    access_token: str,
    file_id: str | None,
    etag: str | None,
    stripped_config: dict,
) -> _RemoteMeta:
    """Upload config.toml to Drive App Data. Multipart create if file_id
    is None; PATCH with If-Match guard otherwise.

    Returns _RemoteMeta with the new file_id, etag, and modifiedTime so
    the caller can update its local cache without a re-GET.

    Raises:
        DriveConcurrentWriteError: 412 on update.
        httpx.HTTPError: other transport / 5xx.
    """
    body = _serialize_config_for_drive(stripped_config)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        if file_id is None:
            metadata = {
                "name": DRIVE_CONFIG_FILE_NAME,
                "parents": ["appDataFolder"],
            }
            metadata_bytes = json.dumps(metadata).encode("utf-8")
            files = {
                "metadata": ("metadata", metadata_bytes, "application/json"),
                "media": (DRIVE_CONFIG_FILE_NAME, body, "application/toml"),
            }
            resp = await client.post(
                f"{DRIVE_UPLOAD_BASE}/files",
                params={"uploadType": "multipart"},
                files=files,
            )
            resp.raise_for_status()
            body_json = resp.json()
            return _RemoteMeta(
                file_id=body_json["id"],
                etag=resp.headers.get("ETag"),
                modified_time=datetime.now(UTC),
            )

        update_headers = {"Content-Type": "application/toml"}
        if etag is not None:
            update_headers["If-Match"] = etag
        resp = await client.patch(
            f"{DRIVE_UPLOAD_BASE}/files/{file_id}",
            params={"uploadType": "media"},
            content=body,
            headers=update_headers,
        )
        if resp.status_code == 412:
            raise DriveConcurrentWriteError(
                f"ETag mismatch for config (file_id={file_id})"
            )
        resp.raise_for_status()
        return _RemoteMeta(
            file_id=file_id,
            etag=resp.headers.get("ETag"),
            modified_time=datetime.now(UTC),
        )
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "drive_get_config or drive_put_config"
```

Expected: 6 passes.

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add Drive primitives for config.toml

_drive_get_config returns (Config | None, _RemoteMeta | None). The
new _RemoteMeta dataclass carries file_id, etag, and modifiedTime
together so callers do one round-trip instead of separate list/get.
Parse failures (TOML, Pydantic ValidationError, Unicode) all raise
DriveCorruptedError so the existing rename-broken recovery path
applies uniformly.

_drive_put_config mirrors _drive_put_dictionary: multipart create
when file_id is None, PATCH with If-Match guard otherwise. Returns a
fresh _RemoteMeta so the caller can update its local cache without
a re-GET.

Body is TOML-serialized from the deny-stripped dict passed in by the
caller — this primitive never sees a full Config or deny-list.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Drive primitives for `usage.json` (`_drive_get_usage` + `_drive_put_usage`)

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 10: Drive primitives for usage.json ----

@pytest.mark.asyncio
@_respx.mock
async def test_drive_get_usage_returns_empty_when_404() -> None:
    from soyle.core.cloud_sync import _drive_get_usage

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )

    data, meta = await _drive_get_usage(access_token="tok")
    assert data == {}
    assert meta is None


@pytest.mark.asyncio
@_respx.mock
async def test_drive_get_usage_parses_remote_json() -> None:
    from soyle.core.cloud_sync import _drive_get_usage

    body = b'{"2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 2}}}'
    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{
                "id": "F2",
                "name": "usage.json",
                "modifiedTime": "2026-05-22T10:00:00.000Z",
            }],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F2").mock(
        return_value=_httpx.Response(
            200, content=body, headers={"ETag": "xyz"},
        ),
    )

    data, meta = await _drive_get_usage(access_token="tok")

    assert data == {
        "2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 2}},
    }
    assert meta is not None
    assert meta.file_id == "F2"
    assert meta.etag == "xyz"


@pytest.mark.asyncio
@_respx.mock
async def test_drive_get_usage_raises_corrupted_on_invalid_json() -> None:
    from soyle.core.cloud_sync import _drive_get_usage, DriveCorruptedError

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "F2", "name": "usage.json", "modifiedTime": "2026-05-22T10:00:00.000Z"}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F2").mock(
        return_value=_httpx.Response(200, content=b"not json {{{"),
    )

    with pytest.raises(DriveCorruptedError):
        await _drive_get_usage(access_token="tok")


@pytest.mark.asyncio
@_respx.mock
async def test_drive_put_usage_creates_when_no_etag() -> None:
    from soyle.core.cloud_sync import _drive_put_usage

    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "NEW"}),
    )

    meta = await _drive_put_usage(
        access_token="tok",
        file_id=None,
        etag=None,
        usage_data={"2026-05-22": {"dev-A": {"cost_usd": 0.05, "requests": 2}}},
    )
    assert create.called
    assert meta.file_id == "NEW"


@pytest.mark.asyncio
@_respx.mock
async def test_drive_put_usage_updates_existing_with_if_match() -> None:
    from soyle.core.cloud_sync import _drive_put_usage

    update = _respx.patch(f"{_DRIVE_UPLOAD_BASE}/files/F2").mock(
        return_value=_httpx.Response(
            200, json={"id": "F2"}, headers={"ETag": "new"},
        ),
    )

    meta = await _drive_put_usage(
        access_token="tok",
        file_id="F2",
        etag="old",
        usage_data={"2026-05-22": {"dev-A": {"cost_usd": 0.01, "requests": 1}}},
    )
    assert update.called
    assert update.calls.last.request.headers["If-Match"] == "old"
    assert meta.etag == "new"
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "drive_get_usage or drive_put_usage"
```

Expected: 5 failures.

- [ ] **Step 3: Implement primitives**

After `_drive_put_config` in `cloud_sync.py`, append:

```python
def _serialize_usage_for_drive(data: dict) -> bytes:
    """Encode usage v2 state as compact JSON bytes."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8",
    )


async def _drive_get_usage(
    *, access_token: str,
) -> tuple[dict, _RemoteMeta | None]:
    """Fetch usage.json from Drive App Data folder.

    Returns:
        (data, meta) — data is {} when file doesn't exist (meta None);
        otherwise the parsed v2 nested dict and metadata for the next
        write.

    Raises:
        DriveCorruptedError: file exists but JSON parse fails or shape
            doesn't look like v2.
        httpx.HTTPError: network / 5xx.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        list_resp = await client.get(
            f"{DRIVE_API_BASE}/files",
            params={
                "spaces": "appDataFolder",
                "q": f"name='{DRIVE_USAGE_FILE_NAME}' and trashed=false",
                "fields": "files(id,name,modifiedTime)",
            },
        )
        list_resp.raise_for_status()
        files = list_resp.json().get("files", [])
        if not files:
            return {}, None

        file_id = files[0]["id"]
        modified_iso = files[0]["modifiedTime"]
        modified_dt = datetime.fromisoformat(modified_iso.replace("Z", "+00:00"))

        get_resp = await client.get(
            f"{DRIVE_API_BASE}/files/{file_id}",
            params={"alt": "media"},
        )
        get_resp.raise_for_status()
        etag = get_resp.headers.get("ETag")

    try:
        parsed = json.loads(get_resp.content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DriveCorruptedError(file_id, exc) from exc

    if not isinstance(parsed, dict):
        raise DriveCorruptedError(
            file_id, TypeError(f"usage root is {type(parsed).__name__}, expected dict"),
        )

    return parsed, _RemoteMeta(
        file_id=file_id, etag=etag, modified_time=modified_dt,
    )


async def _drive_put_usage(
    *,
    access_token: str,
    file_id: str | None,
    etag: str | None,
    usage_data: dict,
) -> _RemoteMeta:
    """Upload usage.json to Drive App Data. Multipart create when
    file_id is None, PATCH with If-Match guard otherwise."""
    body = _serialize_usage_for_drive(usage_data)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        if file_id is None:
            metadata = {
                "name": DRIVE_USAGE_FILE_NAME,
                "parents": ["appDataFolder"],
            }
            metadata_bytes = json.dumps(metadata).encode("utf-8")
            files = {
                "metadata": ("metadata", metadata_bytes, "application/json"),
                "media": (DRIVE_USAGE_FILE_NAME, body, "application/json"),
            }
            resp = await client.post(
                f"{DRIVE_UPLOAD_BASE}/files",
                params={"uploadType": "multipart"},
                files=files,
            )
            resp.raise_for_status()
            body_json = resp.json()
            return _RemoteMeta(
                file_id=body_json["id"],
                etag=resp.headers.get("ETag"),
                modified_time=datetime.now(UTC),
            )

        update_headers = {"Content-Type": "application/json"}
        if etag is not None:
            update_headers["If-Match"] = etag
        resp = await client.patch(
            f"{DRIVE_UPLOAD_BASE}/files/{file_id}",
            params={"uploadType": "media"},
            content=body,
            headers=update_headers,
        )
        if resp.status_code == 412:
            raise DriveConcurrentWriteError(
                f"ETag mismatch for usage (file_id={file_id})"
            )
        resp.raise_for_status()
        return _RemoteMeta(
            file_id=file_id,
            etag=resp.headers.get("ETag"),
            modified_time=datetime.now(UTC),
        )
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "drive_get_usage or drive_put_usage"
```

Expected: 5 passes.

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add Drive primitives for usage.json

_drive_get_usage returns (data, meta). Data is {} on 404; on
successful fetch the v2 nested dict is parsed straight from JSON
bytes. Non-dict root or JSONDecodeError raises DriveCorruptedError,
funneling into the existing rename-broken recovery path.

_drive_put_usage mirrors _drive_put_config exactly: multipart create
when file_id is None, PATCH with If-Match guard otherwise. Body is
compact JSON (no indent, no spaces) since the file can grow with
many devices × dates and we want to minimize bandwidth.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `CloudSync._sync_config()` orchestration

**Files:**
- Modify: `src/soyle/core/cloud_sync.py` (extend `CloudSync` class)
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 11: _sync_config orchestration ----

# Tolerance constant from spec — keep in sync with cloud_sync.py
_MTIME_SKEW_SECONDS = 5


def _make_cloud_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> "CloudSync":
    """Construct a CloudSync with isolated config + dict + usage stores
    rooted in tmp_path. Doesn't connect (no refresh token in keyring)."""
    from soyle.core.cloud_sync import CloudSync
    from soyle.core.config import ConfigStore
    from soyle.core.dictionary import DictionaryStore
    from soyle.core.usage import UsageTracker

    _stub_device_id(monkeypatch, "dev-A")
    config_store = ConfigStore(config_path=tmp_path / "config.toml")
    dict_store = DictionaryStore(path=tmp_path / "dictionary.toml")
    usage_tracker = UsageTracker(tmp_path / "usage.json")
    return CloudSync(
        dict_store=dict_store,
        config_store=config_store,
        usage_tracker=usage_tracker,
        client_id="test-client-id.apps.googleusercontent.com",
    )


@pytest.mark.asyncio
@_respx.mock
async def test_sync_config_uploads_when_remote_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First device: no remote config → upload local (deny-stripped)."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._config_store.load()  # materialize the file so mtime() works

    list_route = _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )
    create_route = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "NEW"}),
    )

    result = await cs._sync_config(access_token="tok")
    assert result.outcome.name == "OK"
    assert list_route.called
    assert create_route.called


@pytest.mark.asyncio
@_respx.mock
async def test_sync_config_pulls_when_remote_mtime_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    local = cs._config_store.load()
    assert local.hotkey.combination == "right alt"

    # Remote has different hotkey, modifiedTime 1h in the future
    future = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)
    iso = future.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    remote_body = b"version = 1\n\n[hotkey]\ncombination = \"ctrl+shift\"\n"

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "F1", "name": "config.toml", "modifiedTime": iso}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(200, content=remote_body, headers={"ETag": "e1"}),
    )

    result = await cs._sync_config(access_token="tok")
    assert result.outcome.name == "OK"

    reloaded = cs._config_store.load()
    assert reloaded.hotkey.combination == "ctrl+shift"


@pytest.mark.asyncio
@_respx.mock
async def test_sync_config_pushes_when_local_mtime_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    local = cs._config_store.load()
    local.hotkey.combination = "ctrl+shift"
    cs._config_store.save(local)  # bumps local mtime to now()

    # Remote modifiedTime 1h in the past
    past = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    iso = past.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    remote_body = b"version = 1\n\n[hotkey]\ncombination = \"alt\"\n"

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "F1", "name": "config.toml", "modifiedTime": iso}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(
            200, content=remote_body, headers={"ETag": "e-old"},
        ),
    )
    push = _respx.patch(f"{_DRIVE_UPLOAD_BASE}/files/F1").mock(
        return_value=_httpx.Response(
            200, json={"id": "F1"}, headers={"ETag": "e-new"},
        ),
    )

    result = await cs._sync_config(access_token="tok")
    assert result.outcome.name == "OK"
    assert push.called
    assert push.calls.last.request.headers["If-Match"] == "e-old"


@pytest.mark.asyncio
@_respx.mock
async def test_sync_config_noop_when_mtimes_within_tolerance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Within ±5s → no PATCH, no POST issued."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._config_store.load()
    local_mtime = cs._config_store.mtime()

    iso = local_mtime.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    remote_body = b"version = 1\n"

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "F1", "name": "config.toml", "modifiedTime": iso}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(
            200, content=remote_body, headers={"ETag": "e"},
        ),
    )
    patch_route = _respx.patch(f"{_DRIVE_UPLOAD_BASE}/files/F1").mock(
        return_value=_httpx.Response(200, json={"id": "F1"}),
    )

    result = await cs._sync_config(access_token="tok")
    assert result.outcome.name == "OK"
    assert not patch_route.called


@pytest.mark.asyncio
@_respx.mock
async def test_sync_config_corrupted_remote_renames_and_pushes_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Broken TOML on Drive → rename to .broken-<ts> + push local."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._config_store.load()

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "F1", "name": "config.toml", "modifiedTime": "2026-05-22T10:00:00.000Z"}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(200, content=b"@@@ not valid toml @@@"),
    )
    rename = _respx.patch(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(200, json={"id": "F1"}),
    )
    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "F2"}),
    )

    result = await cs._sync_config(access_token="tok")
    assert result.outcome.name == "OK"
    assert rename.called
    assert create.called


@pytest.mark.asyncio
@_respx.mock
async def test_sync_config_schema_mismatch_skipped_silently_preserves_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote has unknown field (newer Söyle): skip the sync, leave both
    sides intact, do NOT rename, do NOT push."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._config_store.load()

    # Field unknown to this Söyle's Config — extra="forbid" → ValidationError
    remote_body = b'version = 1\n\n[hotkey]\nfuture_field = "from-newer-Söyle"\n'
    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "F1", "name": "config.toml", "modifiedTime": "2026-05-22T10:00:00.000Z"}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(200, content=remote_body),
    )
    rename = _respx.patch(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(200, json={"id": "F1"}),
    )
    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "F2"}),
    )

    result = await cs._sync_config(access_token="tok")
    # Outcome is OK (not corrupted) — sync was a no-op skip, not a failure
    assert result.outcome.name == "OK"
    # Neither rename nor push happened
    assert not rename.called
    assert not create.called
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "sync_config"
```

Expected: 6 failures — `_sync_config` undefined; also `CloudSync.__init__` doesn't yet accept `usage_tracker`.

- [ ] **Step 3: Extend `CloudSync.__init__` to accept `usage_tracker`**

In `src/soyle/core/cloud_sync.py`, modify the `CloudSync.__init__` signature and body (currently around line 317):

```python
    def __init__(
        self,
        *,
        dict_store: DictionaryStore,
        config_store: ConfigStore,
        usage_tracker: "UsageTracker",
        client_id: str,
    ) -> None:
        self._dict_store = dict_store
        self._config_store = config_store
        self._usage_tracker = usage_tracker
        self._client_id = client_id
        self._token_store = _TokenStore()
        self._oauth_listener: _OAuthCallbackListener | None = None
        self._oauth_verifier: str | None = None
```

Add the TYPE_CHECKING import for UsageTracker alongside Config:

```python
if TYPE_CHECKING:
    from soyle.core.config import Config
    from soyle.core.usage import UsageTracker
```

- [ ] **Step 4: Add module-level constant + `_sync_config` method**

After the existing `SYNC_INTERVAL` near the top of the CloudSync class context, add:

```python
# Clock-skew tolerance for mtime comparisons (seconds). Within this window
# we treat local and remote as already in sync — prevents push/pull
# ping-pong when two devices have slightly drifting clocks.
_MTIME_SKEW_SECONDS = 5
```

Inside the `CloudSync` class, after the existing `sync_now`/`_sync_with_token` block, add:

```python
    async def _sync_config(self, access_token: str) -> SyncResult:
        """Single round-trip for config.toml — pulls or pushes by mtime.

        Returns SyncResult with OK for any success path (including
        corrupted-remote recovery and schema-mismatch skip). Network /
        auth / quota errors are converted to the matching SyncOutcome.
        """
        local_cfg = self._config_store.load()
        try:
            local_mtime = self._config_store.mtime()
        except FileNotFoundError:
            local_mtime = datetime.now(UTC)

        try:
            remote_cfg, remote_meta = await _drive_get_config(
                access_token=access_token,
            )
        except DriveCorruptedError as corrupted:
            _log.warning(
                "cloud_sync_config_corrupted_remote",
                file_id=corrupted.file_id,
                exc_type=type(corrupted.original).__name__,
            )
            # Distinguish schema mismatch (ValidationError) from TOML
            # corruption: schema mismatch must NOT rename — see spec §7.
            from pydantic import ValidationError
            if isinstance(corrupted.original, ValidationError):
                _log.warning(
                    "cloud_sync_config_schema_mismatch",
                    file_id=corrupted.file_id,
                )
                return SyncResult(outcome=SyncOutcome.OK)
            # Real TOML/Unicode corruption: rename + push local
            await _drive_rename_corrupted(
                access_token=access_token, file_id=corrupted.file_id,
            )
            remote_cfg, remote_meta = None, None
        except (
            httpx.ConnectError, httpx.ReadError, httpx.TimeoutException,
        ):
            _log.warning("cloud_sync_network_error", phase="config_get")
            return SyncResult(outcome=SyncOutcome.NETWORK)
        except httpx.HTTPStatusError as exc:
            return self._classify_drive_error(exc, phase="config_get")

        if remote_cfg is None:
            # First-device upload
            return await self._push_config(
                access_token=access_token,
                file_id=None,
                etag=None,
                local_cfg=local_cfg,
            )

        assert remote_meta is not None  # remote_cfg is not None ⇒ meta set
        skew = timedelta(seconds=_MTIME_SKEW_SECONDS)
        if remote_meta.modified_time > local_mtime + skew:
            merged = _merge_config(
                local_cfg, remote_cfg, local_mtime, remote_meta.modified_time,
            )
            self._config_store.apply_synced_overrides(merged)
            return SyncResult(outcome=SyncOutcome.OK)
        elif local_mtime > remote_meta.modified_time + skew:
            return await self._push_config(
                access_token=access_token,
                file_id=remote_meta.file_id,
                etag=remote_meta.etag,
                local_cfg=local_cfg,
            )
        else:
            # Within tolerance — already in sync
            return SyncResult(outcome=SyncOutcome.OK)

    async def _push_config(
        self,
        *,
        access_token: str,
        file_id: str | None,
        etag: str | None,
        local_cfg: "Config",
    ) -> SyncResult:
        """Wrap _drive_put_config with our standard error classification."""
        try:
            await _drive_put_config(
                access_token=access_token,
                file_id=file_id,
                etag=etag,
                stripped_config=_strip_deny(local_cfg),
            )
        except DriveConcurrentWriteError:
            _log.info("cloud_sync_concurrent_write_config_retrying")
            # Recursive retry from the top of _sync_config so we pick up
            # the latest remote state. Bounded only by network/cap layer.
            return await self._sync_config(access_token=access_token)
        except (
            httpx.ConnectError, httpx.ReadError, httpx.TimeoutException,
        ):
            _log.warning("cloud_sync_network_error", phase="config_put")
            return SyncResult(outcome=SyncOutcome.NETWORK)
        except httpx.HTTPStatusError as exc:
            return self._classify_drive_error(exc, phase="config_put")
        return SyncResult(outcome=SyncOutcome.OK)
```

- [ ] **Step 5: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "sync_config"
```

Expected: 6 passes. **Note:** Existing Phase 1 tests that instantiate `CloudSync` without `usage_tracker` will now fail with TypeError. The test helper `_make_cloud_sync` introduced in Step 1 handles this for new tests; existing helpers (search for `CloudSync(` in the test file) need the `usage_tracker=...` kwarg added. Patch them in this step.

- [ ] **Step 6: Verify no Phase 1 regression**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v
```

Expected: all tests pass — Phase 1 sync tests now construct CloudSync with the added usage_tracker arg.

- [ ] **Step 7: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 8: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add _sync_config — LWW round-trip with skew tolerance

Single-file sync method covering all branches:
- remote 404 → upload local (deny-stripped)
- remote newer (by mtime + 5s skew) → pull + apply_synced_overrides
- local newer → push with If-Match guard
- within ±5s tolerance → no-op
- corrupted remote (TOML/Unicode) → rename .broken-<ts> + push local
- schema mismatch (ValidationError) → skip silently, both sides intact

Also extends CloudSync.__init__ with usage_tracker parameter (used
by Task 12 _sync_usage). Phase 1 test helpers updated to pass it.

Concurrent-write 412 recursive retry mirrors Phase 1 dictionary
pattern — bounded by caller, idempotent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `CloudSync._sync_usage()` orchestration

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 12: _sync_usage orchestration ----

@pytest.mark.asyncio
@_respx.mock
async def test_sync_usage_uploads_to_empty_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._usage_tracker.record(0.05)  # populate local

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )
    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "U1"}),
    )

    result = await cs._sync_usage(access_token="tok")
    assert result.outcome.name == "OK"
    assert create.called


@pytest.mark.asyncio
@_respx.mock
async def test_sync_usage_picks_up_remote_device_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote has dev-B's bucket → after sync, local sees both A and B."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._usage_tracker.record(0.05)  # dev-A locally

    today_key = datetime.now(UTC).strftime("%Y-%m-%d")
    remote_body = _json.dumps({
        today_key: {"dev-B": {"cost_usd": 0.07, "requests": 3}},
    }).encode("utf-8")

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "U1", "name": "usage.json", "modifiedTime": "2026-05-22T10:00:00.000Z"}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/U1").mock(
        return_value=_httpx.Response(
            200, content=remote_body, headers={"ETag": "u-old"},
        ),
    )
    push = _respx.patch(f"{_DRIVE_UPLOAD_BASE}/files/U1").mock(
        return_value=_httpx.Response(
            200, json={"id": "U1"}, headers={"ETag": "u-new"},
        ),
    )

    result = await cs._sync_usage(access_token="tok")
    assert result.outcome.name == "OK"
    assert push.called  # merged differs from remote (dev-A added)
    cost, reqs = cs._usage_tracker.today()
    assert cost == pytest.approx(0.12)
    assert reqs == 4


@pytest.mark.asyncio
@_respx.mock
async def test_sync_usage_noop_when_local_matches_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local == remote → no PUT issued."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._usage_tracker.record(0.05)
    snapshot = cs._usage_tracker.serialize_for_sync()
    body = _json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "U1", "name": "usage.json", "modifiedTime": "2026-05-22T10:00:00.000Z"}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/U1").mock(
        return_value=_httpx.Response(200, content=body, headers={"ETag": "u"}),
    )
    patch_route = _respx.patch(f"{_DRIVE_UPLOAD_BASE}/files/U1").mock(
        return_value=_httpx.Response(200, json={"id": "U1"}),
    )

    result = await cs._sync_usage(access_token="tok")
    assert result.outcome.name == "OK"
    assert not patch_route.called


@pytest.mark.asyncio
@_respx.mock
async def test_sync_usage_corrupted_remote_renames_and_pushes_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._usage_tracker.record(0.05)

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "U1", "name": "usage.json", "modifiedTime": "2026-05-22T10:00:00.000Z"}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/U1").mock(
        return_value=_httpx.Response(200, content=b"not json {{{ @@@"),
    )
    rename = _respx.patch(f"{_DRIVE_API_BASE}/files/U1").mock(
        return_value=_httpx.Response(200, json={"id": "U1"}),
    )
    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "U2"}),
    )

    result = await cs._sync_usage(access_token="tok")
    assert result.outcome.name == "OK"
    assert rename.called
    assert create.called
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "sync_usage"
```

Expected: 4 failures — `_sync_usage` undefined.

- [ ] **Step 3: Implement `_sync_usage` and `_push_usage` in `CloudSync`**

After `_push_config` (added in Task 11), append to the `CloudSync` class:

```python
    async def _sync_usage(self, access_token: str) -> SyncResult:
        """Pure-additive round-trip for usage.json — see spec §6.3."""
        local_usage = self._usage_tracker.serialize_for_sync()

        try:
            remote_usage, remote_meta = await _drive_get_usage(
                access_token=access_token,
            )
        except DriveCorruptedError as corrupted:
            _log.warning(
                "cloud_sync_usage_corrupted_remote",
                file_id=corrupted.file_id,
            )
            await _drive_rename_corrupted(
                access_token=access_token, file_id=corrupted.file_id,
            )
            remote_usage, remote_meta = {}, None
        except (
            httpx.ConnectError, httpx.ReadError, httpx.TimeoutException,
        ):
            _log.warning("cloud_sync_network_error", phase="usage_get")
            return SyncResult(outcome=SyncOutcome.NETWORK)
        except httpx.HTTPStatusError as exc:
            return self._classify_drive_error(exc, phase="usage_get")

        merged = _merge_usage(local_usage, remote_usage)

        if merged != local_usage:
            self._usage_tracker.apply_merged(merged)

        if merged != remote_usage:
            return await self._push_usage(
                access_token=access_token,
                file_id=remote_meta.file_id if remote_meta else None,
                etag=remote_meta.etag if remote_meta else None,
                merged=merged,
            )
        return SyncResult(outcome=SyncOutcome.OK)

    async def _push_usage(
        self,
        *,
        access_token: str,
        file_id: str | None,
        etag: str | None,
        merged: dict,
    ) -> SyncResult:
        try:
            await _drive_put_usage(
                access_token=access_token,
                file_id=file_id,
                etag=etag,
                usage_data=merged,
            )
        except DriveConcurrentWriteError:
            _log.info("cloud_sync_concurrent_write_usage_retrying")
            return await self._sync_usage(access_token=access_token)
        except (
            httpx.ConnectError, httpx.ReadError, httpx.TimeoutException,
        ):
            _log.warning("cloud_sync_network_error", phase="usage_put")
            return SyncResult(outcome=SyncOutcome.NETWORK)
        except httpx.HTTPStatusError as exc:
            return self._classify_drive_error(exc, phase="usage_put")
        return SyncResult(outcome=SyncOutcome.OK)
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "sync_usage"
```

Expected: 4 passes.

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add _sync_usage — pure-additive round-trip

Reads remote usage state (or {} on 404), merges with local via
_merge_usage (per-device LWW so no double-count), then writes back if
either side differs from the merged result.

Corrupted remote (invalid JSON or non-dict root) renames file to
.broken-<ts> and uploads local — same recovery pattern as dict/config.

Concurrent-write 412 retries _sync_usage from the top, mirroring
Phase 1 dictionary's idempotent retry.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Extend `sync_now()` for three-file orchestration + worst-outcome aggregation

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 13: sync_now three-file orchestration ----

@pytest.mark.asyncio
@_respx.mock
async def test_sync_now_runs_dict_config_usage_in_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One sync_now call hits all three: dict GET, config GET, usage GET."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._token_store.save("rt")
    cs._config_store.load()

    # Token refresh
    _respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=_httpx.Response(200, json={"access_token": "tok"}),
    )
    # All three Drive GETs return 404 (empty App Data)
    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )
    # Each missing file triggers a multipart create
    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "X"}),
    )

    result = await cs.sync_now()
    assert result.outcome.name == "OK"
    # 3 creates: dict + config + usage
    assert create.call_count == 3


@pytest.mark.asyncio
@_respx.mock
async def test_sync_now_continues_when_config_sync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config network fail → outcome=NETWORK, but dict + usage still tried."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._token_store.save("rt")
    cs._config_store.load()

    _respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=_httpx.Response(200, json={"access_token": "tok"}),
    )

    list_calls = {"n": 0}

    def list_side_effect(request) -> _httpx.Response:
        list_calls["n"] += 1
        # First call (dict) → empty
        # Second call (config) → simulate network error
        # Third call (usage) → empty
        if list_calls["n"] == 2:
            raise _httpx.ConnectError("simulated")
        return _httpx.Response(200, json={"files": []})

    _respx.get(f"{_DRIVE_API_BASE}/files").mock(side_effect=list_side_effect)
    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "X"}),
    )

    result = await cs.sync_now()
    # Worst outcome is NETWORK (from config)
    assert result.outcome.name == "NETWORK"
    # dict + usage each got a create call (config errored before reaching create)
    assert create.call_count == 2


@pytest.mark.asyncio
@_respx.mock
async def test_sync_now_aggregates_worst_outcome_auth_revoked_over_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUTH_REVOKED on token refresh short-circuits everything — no Drive
    calls happen because there's no access token to use."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._token_store.save("rt")

    _respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=_httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "revoked"},
        ),
    )
    drive_get = _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )

    result = await cs.sync_now()
    assert result.outcome.name == "AUTH_REVOKED"
    assert not drive_get.called


@pytest.mark.asyncio
@_respx.mock
async def test_sync_now_bumps_last_synced_at_on_at_least_one_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._token_store.save("rt")
    cs._config_store.load()

    _respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=_httpx.Response(200, json={"access_token": "tok"}),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )
    _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "X"}),
    )

    before = cs.last_synced_at
    await cs.sync_now()
    after = cs.last_synced_at

    assert before != after
    assert after is not None
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "sync_now_runs or sync_now_continues or sync_now_aggregates or sync_now_bumps"
```

Expected: 4 failures — `sync_now` still only handles dictionary.

- [ ] **Step 3: Refactor `sync_now` for three-file flow**

In `src/soyle/core/cloud_sync.py`, locate the existing `_sync_with_token` method. Extract its current body (dictionary-only sync) into a new private method `_sync_dictionary`, then rewrite `_sync_with_token` to orchestrate three files with outcome aggregation:

```python
    async def _sync_with_token(self, access: str) -> SyncResult:
        """Run dict + config + usage in sequence; aggregate worst outcome.

        Each phase is independently fallible: per spec §6.1 we don't
        stop the loop on partial failure — a corrupted usage file
        shouldn't prevent the dictionary from syncing.
        """
        # Order by user-impact: dictionary first (highest value), then
        # config (medium), then usage (history). Aggregation is by
        # worst-outcome ordinal.
        dict_result = await self._sync_dictionary(access)
        config_result = await self._sync_config(access_token=access)
        usage_result = await self._sync_usage(access_token=access)

        worst = _worst_outcome(
            dict_result.outcome,
            config_result.outcome,
            usage_result.outcome,
        )

        # Stamp last_synced_at only if AT LEAST one file made progress.
        if worst != SyncOutcome.AUTH_REVOKED:
            cfg = self._config_store.load()
            cfg.cloud_sync.last_synced_at = datetime.now(UTC)
            self._config_store.save(cfg)

        _log.info(
            "cloud_sync_round_trip_done",
            dict=dict_result.outcome.name,
            config=config_result.outcome.name,
            usage=usage_result.outcome.name,
            worst=worst.name,
        )
        return SyncResult(
            outcome=worst,
            added_local=dict_result.added_local,
            added_remote=dict_result.added_remote,
        )

    async def _sync_dictionary(self, access: str, _attempt: int = 0) -> SyncResult:
        """Phase 1 dictionary sync logic — body of old _sync_with_token."""
        # ... (move the existing _sync_with_token body verbatim here,
        # except for the last cfg.cloud_sync.last_synced_at bump and
        # log line — those now live in _sync_with_token) ...
```

**Important:** when moving the Phase 1 logic into `_sync_dictionary`, remove the trailing `cfg.cloud_sync.last_synced_at = datetime.now(UTC); self._config_store.save(cfg); _log.info("cloud_sync_ok", ...)` block — that responsibility now lives in `_sync_with_token`.

Add the `_worst_outcome` helper at module scope (just below the `SyncResult` dataclass):

```python
# Outcome severity for sync_now aggregation. Higher index = worse.
# Order: anything where we know we tried beats "didn't try"; auth_revoked
# at the top because it tells the user "you need to act now".
_OUTCOME_SEVERITY: dict[SyncOutcome, int] = {
    SyncOutcome.OK: 0,
    SyncOutcome.NOT_CONNECTED: 1,
    SyncOutcome.NETWORK: 2,
    SyncOutcome.QUOTA: 3,
    SyncOutcome.UNEXPECTED: 4,
    SyncOutcome.APP_SUSPENDED: 5,
    SyncOutcome.AUTH_REVOKED: 6,
}


def _worst_outcome(*outcomes: SyncOutcome) -> SyncOutcome:
    """Return the outcome with the highest severity."""
    return max(outcomes, key=lambda o: _OUTCOME_SEVERITY[o])
```

- [ ] **Step 4: Run new tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "sync_now_runs or sync_now_continues or sync_now_aggregates or sync_now_bumps"
```

Expected: 4 passes.

- [ ] **Step 5: Run full cloud_sync suite — confirm no Phase 1 regression**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v
```

Expected: all pass. Phase 1 sync tests now go through `_sync_dictionary` but the response shape and behavior are identical.

- [ ] **Step 6: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 7: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): extend sync_now to three-file flow with worst-outcome aggregation

Refactor: extract Phase 1 dictionary-only logic into _sync_dictionary
(verbatim); rewrite _sync_with_token to invoke dict + config + usage
in sequence under one access token, aggregate to the worst outcome
via _worst_outcome helper, and bump last_synced_at only when at least
one phase didn't AUTH_REVOKED.

Severity ordering puts AUTH_REVOKED highest so users get the toast
that demands action even if other phases happened to succeed.

Partial failure tolerated by design: corrupted usage doesn't block
dict; network blip on config doesn't block usage. Each phase reports
its own outcome and we surface the worst.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Debounced push — `schedule_config_push()` + QTimer

**Files:**
- Modify: `src/soyle/core/cloud_sync.py`
- Modify: `tests/unit/test_cloud_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 14: schedule_config_push + QTimer debounce ----

@pytest.fixture
def qapp():
    """Headless Qt app for QTimer tests. PySide6 requires a QApplication
    instance for QTimer to fire."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_schedule_config_push_starts_qtimer_with_8s_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs.schedule_config_push()

    timer = cs._config_push_timer
    assert timer.isActive()
    # QTimer.interval() returns ms
    assert timer.interval() == 8000


def test_schedule_config_push_resets_timer_on_rapid_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp,
) -> None:
    """Second call within debounce window restarts the timer at full 8s."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs.schedule_config_push()

    timer = cs._config_push_timer
    # Manually decrement so we can detect a reset
    # (QTimer doesn't expose remainingTime() reliably in non-event-loop tests;
    # check that calling schedule_config_push again leaves it active and
    # at the original 8000ms — implying a fresh start())
    cs.schedule_config_push()
    assert timer.isActive()
    assert timer.interval() == 8000


def test_schedule_config_push_silent_when_not_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp,
) -> None:
    """Hook still arms the timer; the actual push checks is_connected
    when the timer fires. This test asserts arming is unconditional."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    # Not connected (no token in keyring) — schedule_config_push still arms
    cs.schedule_config_push()
    assert cs._config_push_timer.isActive()


@pytest.mark.asyncio
@_respx.mock
async def test_push_config_now_skips_when_not_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp,
) -> None:
    """When _push_config_now fires but keyring is empty, return silently."""
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    # Mock to ensure NO Drive call happens
    drive_get = _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )
    await cs._push_config_now()
    assert not drive_get.called


@pytest.mark.asyncio
@_respx.mock
async def test_push_config_now_does_full_round_trip_when_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._token_store.save("rt")
    cs._config_store.load()

    _respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=_httpx.Response(200, json={"access_token": "tok"}),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )
    create = _respx.post(f"{_DRIVE_UPLOAD_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"id": "X"}),
    )

    await cs._push_config_now()
    assert create.called  # config was pushed
```

- [ ] **Step 2: Run tests — verify they fail**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "schedule_config_push or push_config_now"
```

Expected: 5 failures.

- [ ] **Step 3: Wire QTimer into `CloudSync`**

Add `from PySide6.QtCore import QTimer` near other PySide6 imports (none in cloud_sync.py currently — add to the import block alphabetically, with a brief comment):

```python
# QTimer for Phase 2 debounced config push. Imported at module scope
# (not lazy) because CloudSync owns one as an instance attribute.
from PySide6.QtCore import QTimer
```

Extend `CloudSync.__init__` to create and configure the timer:

```python
        # ... existing assignments ...
        self._token_store = _TokenStore()
        self._oauth_listener: _OAuthCallbackListener | None = None
        self._oauth_verifier: str | None = None

        # Debounced config-push timer. Single-shot semantics: arms on
        # ConfigStore.save(), restarts the countdown on rapid re-saves,
        # fires _push_config_now exactly once after 8s of quiescence.
        self._config_push_timer = QTimer()
        self._config_push_timer.setSingleShot(True)
        self._config_push_timer.setInterval(8000)
        self._config_push_timer.timeout.connect(self._on_config_push_timer)
```

Add three new methods on `CloudSync` (after `_sync_usage`/`_push_usage` from Task 12):

```python
    # -- Debounced push -------------------------------------------------------

    def schedule_config_push(self) -> None:
        """Restart the 8-second debounce timer. Called from
        ConfigStore.save() via the push-hook slot wired in app.py.

        Safe to call from any thread that holds a QApplication — Qt
        marshals QTimer.start() to the main thread automatically when
        invoked from a slot context; here we're invoked synchronously
        from ConfigStore.save() which happens on the Qt main thread.
        """
        self._config_push_timer.start()  # restart from interval()

    def _on_config_push_timer(self) -> None:
        """QTimer fire callback. Dispatches the async push via the
        existing AsyncRunnable adapter so we don't block the Qt main
        thread on Drive REST."""
        from soyle.ui.async_runnable import AsyncRunnable

        runner = AsyncRunnable(self._push_config_now())
        runner.start()

    async def _push_config_now(self) -> None:
        """Run a single config sync round-trip. Silent if not connected."""
        refresh_token = self._token_store.load()
        if refresh_token is None:
            return  # not connected — nothing to push

        try:
            access = await _refresh_access_token(
                client_id=self._client_id, refresh_token=refresh_token,
            )
        except OAuthAuthRevokedError:
            self._token_store.clear()
            _log.warning("cloud_sync_auth_revoked_during_debounced_push")
            return
        except (
            httpx.ConnectError, httpx.ReadError,
            httpx.TimeoutException, httpx.HTTPStatusError,
        ):
            _log.warning("cloud_sync_network_error_during_debounced_push")
            return

        result = await self._sync_config(access_token=access)
        # Bump last_synced_at even on partial success — user-visible
        # "Last synced: X" stays accurate after explicit Settings edits.
        if result.outcome == SyncOutcome.OK:
            cfg = self._config_store.load()
            cfg.cloud_sync.last_synced_at = datetime.now(UTC)
            self._config_store.save(cfg)
```

- [ ] **Step 4: Run tests — verify they pass**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "schedule_config_push or push_config_now"
```

Expected: 5 passes.

- [ ] **Step 5: Run full cloud_sync suite — confirm no regression**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v
```

Expected: all pass.

- [ ] **Step 6: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
```

Expected: both clean.

- [ ] **Step 7: Commit**

```
git add src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(cloud_sync): add debounced config push via QTimer + AsyncRunnable

schedule_config_push() restarts an 8-second single-shot QTimer. On
fire, _on_config_push_timer dispatches an async _push_config_now via
AsyncRunnable (existing Phase 1 Qt-asyncio bridge) so the Qt main
thread never blocks on Drive REST.

_push_config_now is silent on the "not connected" path (no token in
keyring), silent on AUTH_REVOKED (clears keyring, logs warning), and
silent on any network error — by design. The user just clicked Save;
surprising them with "cloud sync failed" 8 seconds later breaks the
mental model. Daily sync_now will retry and surface persistent issues.

On SyncOutcome.OK, bumps last_synced_at so the Settings UI stays
accurate after explicit edits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: `app.py` DI wiring — UsageTracker, push hook, device-id

**Files:**
- Modify: `src/soyle/app.py`

- [ ] **Step 1: Locate the `SoyleApp.__init__` block where stores are constructed**

Open `src/soyle/app.py` and find the section where `DictionaryStore`, `ConfigStore`, `UsageTracker`, and `CloudSync` are instantiated. (Search for `CloudSync(` to land on the existing construction site.)

- [ ] **Step 2: Update `UsageTracker` and `CloudSync` calls to pass new dependencies**

`UsageTracker.__init__` still takes only `path` (the device-id is fetched internally via `_device_id()` re-export). No change needed there.

`CloudSync.__init__` now requires `usage_tracker`. Modify the construction site:

```python
        # BEFORE
        self._cloud_sync = CloudSync(
            dict_store=self._dict_store,
            config_store=self._config_store,
            client_id=_GOOGLE_CLIENT_ID,
        )

        # AFTER
        self._cloud_sync = CloudSync(
            dict_store=self._dict_store,
            config_store=self._config_store,
            usage_tracker=self._usage_tracker,
            client_id=_GOOGLE_CLIENT_ID,
        )

        # Wire the debounced push: every ConfigStore.save() will arm the
        # 8-second QTimer in CloudSync. No-op when not connected.
        self._config_store.set_push_hook(self._cloud_sync.schedule_config_push)
```

- [ ] **Step 3: Smoke-test imports + construction**

```
.venv/Scripts/python.exe -c "from soyle.app import SoyleApp; print('SoyleApp import OK')"
```

Expected: `SoyleApp import OK` (no exceptions). Construction itself requires Qt + audio devices so we don't actually instantiate here.

- [ ] **Step 4: Run full unit suite to catch any unexpected regression**

```
.venv/Scripts/pytest.exe tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 5: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/app.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/app.py
git commit -m "$(cat <<'EOF'
feat(app): wire UsageTracker into CloudSync + register push hook

Two small DI changes in SoyleApp:
- Pass self._usage_tracker into CloudSync(usage_tracker=...) so Phase
  2 _sync_usage has access to local state.
- self._config_store.set_push_hook(self._cloud_sync.schedule_config_push)
  so every Settings save arms the 8-second debounced push timer.

No other lifecycle changes — sync_now still kicks off via the existing
post-warm-up scheduler, just now covers three files instead of one.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: First-run wizard — settings restore prompt

**Files:**
- Modify: `src/soyle/app.py` (extend `_show_first_run_wizard` or the post-OAuth handler that already prompts for dict restore)

- [ ] **Step 1: Locate the existing dict-restore prompt path**

Search `src/soyle/app.py` for `detect_existing_backup` and the surrounding "Restore dict" dialog code. Phase 1 wizard runs `await cloud_sync.detect_existing_backup()` and prompts the user. We extend the same handler.

- [ ] **Step 2: Add a `_detect_existing_config_backup` helper on `CloudSync`**

In `src/soyle/core/cloud_sync.py`, alongside the existing `detect_existing_backup`, add:

```python
    async def detect_existing_config_backup(self) -> "Config | None":
        """Probe Drive App Data for config.toml. Returns the parsed Config
        if found, else None. Used by the first-run wizard to offer
        settings restore after OAuth completes."""
        refresh_token = self._token_store.load()
        if refresh_token is None:
            return None
        try:
            access = await _refresh_access_token(
                client_id=self._client_id, refresh_token=refresh_token,
            )
            remote_cfg, _meta = await _drive_get_config(access_token=access)
        except (
            OAuthAuthRevokedError, httpx.HTTPError, DriveCorruptedError,
        ):
            # Wizard runs once on fresh OAuth — silent on any probe error;
            # daily sync_now will surface issues if they persist.
            return None
        return remote_cfg
```

- [ ] **Step 3: Add a test for the probe**

Append to `tests/unit/test_cloud_sync.py`:

```python
# ---- Task 16: settings restore probe ----

@pytest.mark.asyncio
@_respx.mock
async def test_detect_existing_config_backup_returns_none_when_drive_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._token_store.save("rt")

    _respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=_httpx.Response(200, json={"access_token": "tok"}),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={"files": []}),
    )

    result = await cs.detect_existing_config_backup()
    assert result is None


@pytest.mark.asyncio
@_respx.mock
async def test_detect_existing_config_backup_returns_config_when_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._token_store.save("rt")

    body = b"version = 1\n\n[hotkey]\ncombination = \"ctrl+shift\"\n"

    _respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=_httpx.Response(200, json={"access_token": "tok"}),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files").mock(
        return_value=_httpx.Response(200, json={
            "files": [{"id": "F1", "name": "config.toml", "modifiedTime": "2026-05-22T10:00:00.000Z"}],
        }),
    )
    _respx.get(f"{_DRIVE_API_BASE}/files/F1").mock(
        return_value=_httpx.Response(200, content=body, headers={"ETag": "e"}),
    )

    result = await cs.detect_existing_config_backup()
    assert result is not None
    assert result.hotkey.combination == "ctrl+shift"


@pytest.mark.asyncio
@_respx.mock
async def test_detect_existing_config_backup_returns_none_on_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = _make_cloud_sync(tmp_path, monkeypatch)
    cs._token_store.save("rt")

    _respx.post("https://oauth2.googleapis.com/token").mock(
        side_effect=_httpx.ConnectError("simulated"),
    )

    result = await cs.detect_existing_config_backup()
    assert result is None
```

- [ ] **Step 4: Wire the prompt into the existing OAuth-complete handler in `app.py`**

After the existing dict-restore dialog logic in `app.py`, add a new section. Find the comment / dialog block for dict restore and append below it:

```python
        # Phase 2 — settings restore prompt
        remote_cfg = await self._cloud_sync.detect_existing_config_backup()
        if remote_cfg is not None:
            response = QMessageBox.question(
                None,
                "Söyle — настройки с другого устройства",
                "Найдены настройки с другого устройства. Применить?\n"
                "(Локальные значения для микрофона, модели Whisper и темы\n"
                "оформления останутся как есть.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if response == QMessageBox.StandardButton.Yes:
                # _merge_config preserves deny-list paths from local even
                # though local mtime is "newer" here (we just wrote it via
                # ConfigStore.load default materialization).
                from soyle.core.cloud_sync import _merge_config
                from datetime import UTC, datetime
                local_cfg = self._config_store.load()
                local_mtime = self._config_store.mtime()
                # Force remote to win regardless of mtime — user clicked Yes
                far_future = datetime.now(UTC) + timedelta(days=365)
                merged = _merge_config(
                    local_cfg, remote_cfg, local_mtime, far_future,
                )
                self._config_store.apply_synced_overrides(merged)
                self._show_toast("Настройки восстановлены с другого устройства.")
```

Ensure `from datetime import timedelta` is available at the top of `app.py` (likely already imported; add if missing).

- [ ] **Step 5: Run new tests**

```
.venv/Scripts/pytest.exe tests/unit/test_cloud_sync.py -v -k "detect_existing_config_backup"
```

Expected: 3 passes.

- [ ] **Step 6: Run full suite + smoke import**

```
.venv/Scripts/pytest.exe tests/unit/ -q
.venv/Scripts/python.exe -c "from soyle.app import SoyleApp; print('OK')"
```

Expected: all pass; import OK.

- [ ] **Step 7: mypy + ruff**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/app.py src/soyle/core/cloud_sync.py
```

Expected: both clean.

- [ ] **Step 8: Commit**

```
git add src/soyle/app.py src/soyle/core/cloud_sync.py tests/unit/test_cloud_sync.py
git commit -m "$(cat <<'EOF'
feat(wizard): offer settings restore after OAuth on first device connect

After dict-restore prompt (Phase 1), wizard now also probes for an
existing config.toml in Drive. If found, asks the user "Apply settings
from another device?" — yes goes through _merge_config (so deny-list
paths like whisper.model and ui.theme stay device-local even though
the wizard semantically wants remote to win).

detect_existing_config_backup is silent on any probe error: wizard
runs once, daily sync_now surfaces persistent issues later.

Usage merges silently as part of the regular sync_now triggered by
the wizard's "Connect" step — no prompt for cost history.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: Settings UI label update + Manual test plan

**Files:**
- Modify: `src/soyle/ui/settings.py`
- Modify: `docs/MANUAL_TESTS.md`

- [ ] **Step 1: Update Settings UI status label**

Search `src/soyle/ui/settings.py` for the Cloud Sync tab — find the description string that mentions only "Словарь" / "dictionary". Update it to reflect three-file coverage:

```python
        # BEFORE (approximate — match what's actually in the file)
        QLabel(
            "Sync твоего пользовательского словаря через Google Drive."
            " Синхронизация ежедневная при старте Söyle.",
        )

        # AFTER
        QLabel(
            "Синхронизация словаря, настроек и истории usage через Google "
            "Drive. Запускается ежедневно при старте Söyle; изменения "
            "настроек уходят сразу же (с задержкой ~8 секунд). Поля "
            "привязанные к железу (микрофон, модель Whisper, тема) "
            "остаются локальными.",
        )
```

The exact original text may differ — preserve the file's existing tone and just expand the scope.

- [ ] **Step 2: Smoke-test settings import**

```
.venv/Scripts/python.exe -c "from soyle.ui.settings import SettingsWindow; print('settings import OK')"
```

Expected: `settings import OK`.

- [ ] **Step 3: Add a new manual-test section to `docs/MANUAL_TESTS.md`**

Find the existing "Cloud Sync (Phase 1)" section (introduced when Phase 1 shipped). Add a new sibling section immediately after it:

```markdown
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
```

- [ ] **Step 4: Verify the section is in the right place**

```
.venv/Scripts/python.exe -c "import pathlib; t = pathlib.Path('docs/MANUAL_TESTS.md').read_text(encoding='utf-8'); a = t.index('Cloud Sync (Phase 1)'); b = t.index('Cloud Sync (Phase 2)'); assert a < b, 'Phase 2 must follow Phase 1'; print('section order OK')"
```

Expected: `section order OK`.

- [ ] **Step 5: mypy + ruff (settings.py change)**

```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/ui/settings.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/ui/settings.py docs/MANUAL_TESTS.md
git commit -m "$(cat <<'EOF'
feat(ui+docs): Cloud Sync tab label + Phase 2 manual test checklist

Settings → Cloud Sync описание расширено: упоминает 3 файла, debounce
8с для config, и оставшиеся device-local поля (mic / Whisper model /
theme) — чтобы пользователь сразу понимал, что НЕ синкается.

MANUAL_TESTS.md gains "Cloud Sync (Phase 2)" section with six
checklists: settings push/pull, deny-list соблюдён, cross-device
cost tracking, first-run wizard restore prompt, disconnect/reconnect
не теряет данные, и forward-compat schema mismatch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Final validation gates + push + open PR

**Files:** none directly — verification + push.

- [ ] **Step 1: Full unit suite**

```
.venv/Scripts/pytest.exe tests/unit/ -q
```

Expected: all tests pass. New Phase 2 tests should add ~35-40 tests on top of existing ~250 (~290 total).

- [ ] **Step 2: mypy strict mode across all sources**

```
.venv/Scripts/python.exe -m mypy src/
```

Expected: `Success: no issues found in 30+ source files`.

- [ ] **Step 3: ruff clean on entire tree**

```
.venv/Scripts/ruff.exe check src/ tests/
```

Expected: `All checks passed!`.

- [ ] **Step 4: Import + construction smoke test**

```
.venv/Scripts/python.exe -c "
from soyle.app import SoyleApp
from soyle.core.cloud_sync import (
    CloudSync, _CONFIG_DENY_LIST, _device_id,
    _merge_config, _merge_usage, _strip_deny,
    _drive_get_config, _drive_put_config,
    _drive_get_usage, _drive_put_usage,
)
print('imports OK; deny-list size:', len(_CONFIG_DENY_LIST))
"
```

Expected: `imports OK; deny-list size: 9`.

- [ ] **Step 5: Manual sections A + B + D (locally, before push)**

This is the explicit pre-merge gate from the spec. Two test devices are ideal; one device + cleared `%APPDATA%\Soyle\` works as a fallback for sections A and B.

If sections A or B regress, STOP. Likely root cause is mtime tolerance too tight, debounce QTimer not firing, or DI wiring incorrect.

- [ ] **Step 6: Push branch**

```
git push -u origin claude/cloud-sync-phase2-spec
```

Note: the branch already exists from the spec commit. The push uploads all Phase 2 implementation commits stacked on top.

- [ ] **Step 7: Open the PR**

```
gh pr create --base main --head claude/cloud-sync-phase2-spec \
  --title "feat(cloud_sync): Phase 2 — config.toml + usage.json sync" \
  --body "$(cat <<'EOF'
## Summary
Implementation of Cloud Sync Phase 2 per [the design spec](docs/superpowers/specs/2026-05-22-cloud-sync-phase2-design.md).

### Scope (3 syncing files now)
- **dictionary.toml** — unchanged from Phase 1 (pure-union merge)
- **config.toml** — new: LWW whole-file with 9-path deny-list for device-local fields, debounced push (8s) on Settings save, daily pull on sync_now
- **usage.json** — new: v2 per-device buckets `{date: {device_id: {cost, requests}}}`; cross-device sums for `today()`, `this_month()`, monthly cap; auto-migration from v1 flat schema

### Changes by file
- `cloud_sync.py` — +400 LOC: device-id helper, deny-list, dotted-path helpers, strip/merge/sync functions for config and usage, 4 new Drive primitives, QTimer-debounced push
- `usage.py` — refactored to v2 per-device schema with inline migration
- `config.py` — `mtime()`, `apply_synced_overrides()`, push-hook slot
- `app.py` — DI wiring + first-run wizard settings restore prompt
- `ui/settings.py` — Cloud Sync tab description updated for 3-file coverage
- `MANUAL_TESTS.md` — new "Cloud Sync (Phase 2)" section with 6 scenarios

### Pre-merge validation
- [x] pytest — all unit tests pass
- [x] mypy clean (strict)
- [x] ruff clean
- [x] imports OK
- [x] Manual section A (settings push/pull) passed locally
- [x] Manual section B (deny-list соблюдён) passed locally
- [x] Manual section D (first-run wizard restore) passed locally

### Architectural notes
- Approach A from spec: extended CloudSync in place (~1200 LOC total). No refactor of Phase 1 code paths.
- usage.json schema migration is self-describing — v1 detected by inner value shape (`cost_usd` at top of value dict) and rewritten on first load.
- Debounced push uses Qt-native QTimer + existing AsyncRunnable adapter — no new concurrency primitives.
- `_worst_outcome` aggregation so partial failures (e.g., corrupted usage doesn't stop dict sync) surface the most-actionable error to the user toast.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for codex review + CI; address P1/P2 in follow-up commits per `codex_bot_feedback_pattern` memory**

Codex P2+ findings get a follow-up commit on the same branch BEFORE the next plan task. For Phase 2 there is no "next plan task" — the PR itself is the deliverable. Land via squash-merge or merge-commit per project convention.

If codex finds nothing → user merges → branch deleted → update `cloud_sync_phase1_state` memory (or supersede it) to reflect Phase 2 shipped.

---

## Self-Review

After writing the plan above, I checked it against the spec.

**Spec coverage check:** every spec requirement has a task:

| Spec section / requirement | Task |
|---|---|
| `_CONFIG_DENY_LIST` with 9 paths | Task 4 |
| `_device_id()` helper in keyring | Task 1 |
| Drive primitives for config | Task 9 |
| Drive primitives for usage | Task 10 |
| `_strip_deny` pure function | Task 5 |
| `_merge_config` pure function | Task 6 |
| `_merge_usage` pure function | Task 7 |
| usage.py schema migration v1→v2 | Task 2 |
| usage.py cross-device sums | Task 3 |
| `ConfigStore.mtime()` | Task 8 |
| `ConfigStore.apply_synced_overrides()` | Task 8 |
| `ConfigStore.set_push_hook()` + save invocation | Task 8 |
| `CloudSync._sync_config` orchestration | Task 11 |
| `CloudSync._sync_usage` orchestration | Task 12 |
| `CloudSync.sync_now` extension + worst-outcome | Task 13 |
| Debounced push via QTimer | Task 14 |
| `_push_config_now` silent on disconnect | Task 14 |
| `app.py` DI wiring | Task 15 |
| First-run wizard settings restore | Task 16 |
| Settings UI label update | Task 17 |
| `MANUAL_TESTS.md` Phase 2 section | Task 17 |
| Schema mismatch skip-silently | Task 11 (test + impl branch) |
| Corrupted-remote rename for config | Task 11 |
| Corrupted-remote rename for usage | Task 12 |
| Concurrent-write 412 retry (config) | Task 11 (in `_push_config`) |
| Concurrent-write 412 retry (usage) | Task 12 (in `_push_usage`) |
| Pre-merge validation gates | Task 18 |

✓ All spec-defined items mapped to a task.

**Placeholder scan:** searched for TBD / TODO / fill-in / "similar to". None found in step bodies. The only "..." in the plan is inside the `_sync_dictionary` extraction instruction (Task 13 Step 3) where I explicitly tell the engineer "move the existing _sync_with_token body verbatim here" — this is an extraction instruction with full context, not a placeholder.

**Type / signature consistency:**
- `_drive_get_config(*, access_token: str) -> tuple[Config | None, _RemoteMeta | None]` — same signature used in Task 9 implementation, Task 11 call, Task 16 `detect_existing_config_backup`. ✓
- `_drive_put_config(*, access_token, file_id, etag, stripped_config) -> _RemoteMeta` — consistent between Task 9 def, Task 11 call (`_push_config`). ✓
- `_drive_get_usage(*, access_token) -> tuple[dict, _RemoteMeta | None]` — consistent. ✓
- `_drive_put_usage(*, access_token, file_id, etag, usage_data) -> _RemoteMeta` — consistent. ✓
- `_merge_config(local, remote, local_mtime, remote_mtime) -> Config` — consistent.
- `_merge_usage(local, remote) -> dict` — consistent.
- `UsageTracker.serialize_for_sync() -> dict` and `apply_merged(merged) -> None` — consistent between Task 2 def, Task 3 tests, Task 12 calls.
- `ConfigStore.mtime() -> datetime` and `apply_synced_overrides(remote)` and `set_push_hook(hook)` — consistent across Tasks 8, 11, 15.
- `CloudSync.__init__(*, dict_store, config_store, usage_tracker, client_id)` — Task 11 introduces `usage_tracker` and Task 15 wires it; existing Phase 1 test helpers must be updated, explicitly called out in Task 11 Step 5.

✓ No inconsistencies found.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-cloud-sync-phase2-implementation.md`.

Two execution options:

1. **Subagent-driven (recommended)** — fresh subagent per task, review between tasks. Best when the user wants asynchronous progress and explicit checkpoints, matches Phase 1's flow that produced PRs #10–#21.
2. **Inline execution** — execute tasks in the current session using `superpowers:executing-plans`. Faster, but the session context grows with each task.

User: which approach?
