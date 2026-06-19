# Söyle UX Stage 2 — result & history Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tray-reachable two-pane history window that records every dictation (raw + processed) to a local capped JSON log and lets the user recover, copy, and re-inject past results.

**Architecture:** A `HistoryStore` (JSON, mirrors `core/usage.py`) records entries from `app.py::_finish_inference` after each successful inject. A `HistoryWindow` (QWidget, two-pane) reads the store, shows newest-first, and re-injects into the window that was focused when the window opened (captured hwnd → `Injector.inject`). History is on by default with a Settings toggle; it is local-only (never cloud-synced).

**Tech Stack:** Python 3.12, PySide6 (QWidget + QSS), pydantic config, structlog, pytest + pytest-qt, mypy strict.

**Spec:** `docs/superpowers/specs/2026-06-16-ux-stage2-result-history-design.md`

---

## Conventions (read once)

- **Branch-per-stage, sequential.** This plan ships as three PRs. Each lands on
  `main`; the next branches off updated `main`. The current branch
  `claude/ux-stage2-history` carries the spec, this plan, and **PR 2.1** work.
  PR 2.2 branches off `main` after 2.1 merges; PR 2.3 after 2.2.
- **Local check before every commit** (CI gates on all three):
  `python -m pytest -q && python -m ruff check src tests && python -m mypy src/`
- **Commits are English**; chat/PR discussion is Russian. The user drives every
  PR merge click — do not merge.
- **Source language is Russian.** New `tr()` / `QCoreApplication.translate`
  strings use Russian literals; `kk`/`en` get translated in Task 13.

---

## File Structure

**PR 2.1 — storage + capture plumbing**
- Create `src/soyle/core/history.py` — `HistoryEntry`, `build_entry`,
  `should_record`, `HistoryStore`. One responsibility: persist + retrieve the
  capped history log.
- Create `tests/unit/test_history.py` — store + helpers.
- Modify `src/soyle/core/config.py` — add `UIConfig.history_enabled`.
- Modify `tests/unit/test_config.py` — assert the new field round-trips.
- Modify `src/soyle/app.py` — thread `raw_text` through `_InferenceJob` and the
  `_inference_done` signal; construct `HistoryStore`; record in
  `_finish_inference`.
- Create `tests/unit/test_history_recording.py` — the recording composition
  (`should_record` + `build_entry` + `append`), mirror-pure style.

**PR 2.2 — history window + tray + re-inject**
- Create `src/soyle/ui/history_window.py` — `format_relative`, `_HistoryRow`,
  `HistoryWindow`.
- Create `tests/unit/test_history_window.py` — widget smoke + actions.
- Modify `src/soyle/ui/tray.py` — `history_requested` signal + "История…" action.
- Modify `tests/unit/` — new `test_tray_history.py` for the signal.
- Modify `src/soyle/app.py` — `_history_window`, `_show_history`,
  `_reinject_from_history`, tray wiring.

**PR 2.3 — settings toggle + i18n + polish**
- Modify `src/soyle/ui/settings.py` — "Вести историю" checkbox + `_save`.
- Modify `src/soyle/app.py` — clear history on disable in `_reload_config`.
- Modify `tests/unit/test_settings_language.py` (or new `test_settings_history.py`).
- Modify `src/soyle/i18n/soyle_kk.ts`, `soyle_en.ts` (+ compiled `.qm`).
- Modify `src/soyle/ui/history_window.py` + `theme/qss.py` — final QSS polish.

---

# PR 2.1 — storage + capture plumbing

Branch: `claude/ux-stage2-history` (already checked out).

### Task 1: HistoryEntry + build_entry + should_record

**Files:**
- Create: `src/soyle/core/history.py`
- Test: `tests/unit/test_history.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for HistoryStore — local capped dictation log."""
from __future__ import annotations

from datetime import UTC, datetime

from soyle.core.history import build_entry, should_record


def test_build_entry_stamps_microsecond_iso() -> None:
    fixed = datetime(2026, 6, 16, 10, 32, 5, 123456, tzinfo=UTC)
    entry = build_entry("обработанный", "сырой", "ru", "polish", False, now=fixed)
    assert entry.timestamp == "2026-06-16T10:32:05.123456Z"
    assert entry.processed_text == "обработанный"
    assert entry.raw_text == "сырой"
    assert entry.language == "ru"
    assert entry.mode == "polish"
    assert entry.fallback is False


def test_should_record_gates_on_enabled_and_nonempty() -> None:
    assert should_record("текст", enabled=True) is True
    assert should_record("текст", enabled=False) is False
    assert should_record("   ", enabled=True) is False
    assert should_record("", enabled=True) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_history.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'soyle.core.history'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Local dictation history — newest-first, capped JSON log.

Stored at %APPDATA%/Soyle/history.json as:
    {"version": 1, "entries": [ {entry}, ... ]}   # newest first

Mirrors core/usage.py: plain JSON, broken-file recovery, bounded size.
Local-only by design — history is NOT part of cloud sync, so transcripts
never leave the device.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

log = structlog.get_logger()

MAX_ENTRIES = 100


@dataclass
class HistoryEntry:
    timestamp: str       # ISO 8601 UTC, microsecond precision; unique delete key
    processed_text: str
    raw_text: str
    language: str
    mode: str
    fallback: bool


def build_entry(
    processed_text: str,
    raw_text: str,
    language: str,
    mode: str,
    fallback: bool,
    *,
    now: datetime | None = None,
) -> HistoryEntry:
    """Build a HistoryEntry stamped now (UTC, microsecond precision).

    `now` is injectable so tests get a deterministic timestamp.
    """
    stamp = (now or datetime.now(tz=UTC)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return HistoryEntry(
        timestamp=stamp,
        processed_text=processed_text,
        raw_text=raw_text,
        language=language,
        mode=mode,
        fallback=fallback,
    )


def should_record(text: str, *, enabled: bool) -> bool:
    """History records only non-empty text, and only when enabled."""
    return enabled and bool(text.strip())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_history.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/soyle/core/history.py tests/unit/test_history.py
git commit -m "feat(history): HistoryEntry + build_entry + should_record"
```

### Task 2: HistoryStore append + cap + all()

**Files:**
- Modify: `src/soyle/core/history.py`
- Test: `tests/unit/test_history.py`

- [ ] **Step 1: Write the failing test** (append to the test file)

```python
from pathlib import Path

from soyle.core.history import MAX_ENTRIES, HistoryEntry, HistoryStore


def _entry(n: int) -> HistoryEntry:
    return build_entry(
        f"processed-{n}", f"raw-{n}", "ru", "polish", False,
        now=datetime(2026, 6, 16, 10, 0, n % 60, n, tzinfo=UTC),
    )


def test_append_prepends_newest_first(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.append(_entry(1))
    store.append(_entry(2))
    texts = [e.processed_text for e in store.all()]
    assert texts == ["processed-2", "processed-1"]


def test_append_enforces_cap_dropping_oldest(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    for n in range(MAX_ENTRIES + 5):
        store.append(_entry(n))
    entries = store.all()
    assert len(entries) == MAX_ENTRIES
    # Newest kept, oldest five dropped.
    assert entries[0].processed_text == f"processed-{MAX_ENTRIES + 4}"
    assert entries[-1].processed_text == "processed-5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_history.py -q`
Expected: FAIL — `ImportError: cannot import name 'HistoryStore'`

- [ ] **Step 3: Write minimal implementation** (append to `history.py`)

```python
class HistoryStore:
    """JSON-backed, newest-first, capped at MAX_ENTRIES."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: list[HistoryEntry] = self._load()

    def append(self, entry: HistoryEntry) -> None:
        """Prepend newest, drop the oldest beyond the cap, persist."""
        self._entries.insert(0, entry)
        del self._entries[MAX_ENTRIES:]
        self._save()

    def all(self) -> list[HistoryEntry]:
        """Newest-first snapshot (a copy — callers may not mutate internals)."""
        return list(self._entries)

    # -- internals --

    def _load(self) -> list[HistoryEntry]:
        return []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "entries": [asdict(e) for e in self._entries]}
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("history_save_failed", error=str(exc), path=str(self._path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_history.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/soyle/core/history.py tests/unit/test_history.py
git commit -m "feat(history): HistoryStore append + cap + all"
```

### Task 3: HistoryStore delete + clear

**Files:**
- Modify: `src/soyle/core/history.py`
- Test: `tests/unit/test_history.py`

- [ ] **Step 1: Write the failing test**

```python
def test_delete_removes_one_by_timestamp(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.append(_entry(1))
    store.append(_entry(2))
    target = store.all()[0].timestamp  # the newest (entry 2)
    store.delete(target)
    remaining = [e.processed_text for e in store.all()]
    assert remaining == ["processed-1"]


def test_clear_empties_store(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.append(_entry(1))
    store.clear()
    assert store.all() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_history.py -q`
Expected: FAIL — `AttributeError: 'HistoryStore' object has no attribute 'delete'`

- [ ] **Step 3: Write minimal implementation** (add methods to `HistoryStore`)

```python
    def delete(self, timestamp: str) -> None:
        """Remove the entry whose timestamp matches (no-op if absent)."""
        self._entries = [e for e in self._entries if e.timestamp != timestamp]
        self._save()

    def clear(self) -> None:
        """Wipe all entries."""
        self._entries = []
        self._save()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_history.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/soyle/core/history.py tests/unit/test_history.py
git commit -m "feat(history): HistoryStore delete + clear"
```

### Task 4: HistoryStore load + persistence + broken-file recovery

**Files:**
- Modify: `src/soyle/core/history.py`
- Test: `tests/unit/test_history.py`

- [ ] **Step 1: Write the failing test**

```python
import json


def test_entries_persist_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    HistoryStore(path).append(_entry(1))
    reopened = HistoryStore(path)
    assert [e.processed_text for e in reopened.all()] == ["processed-1"]


def test_on_disk_shape_has_version_and_entries(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    HistoryStore(path).append(_entry(1))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert isinstance(raw["entries"], list)
    assert raw["entries"][0]["processed_text"] == "processed-1"


def test_load_survives_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")
    store = HistoryStore(path)
    assert store.all() == []
    store.append(_entry(1))  # still works after recovery
    assert len(store.all()) == 1


def test_load_skips_malformed_rows(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "entries": [
                {"timestamp": "t", "processed_text": "ok", "raw_text": "r",
                 "language": "ru", "mode": "polish", "fallback": False},
                {"garbage": True},
            ],
        }),
        encoding="utf-8",
    )
    store = HistoryStore(path)
    assert [e.processed_text for e in store.all()] == ["ok"]


def test_load_caps_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    rows = [
        {"timestamp": f"t{n}", "processed_text": f"p{n}", "raw_text": "r",
         "language": "ru", "mode": "polish", "fallback": False}
        for n in range(MAX_ENTRIES + 10)
    ]
    path.write_text(json.dumps({"version": 1, "entries": rows}), encoding="utf-8")
    assert len(HistoryStore(path).all()) == MAX_ENTRIES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_history.py -q`
Expected: FAIL — `test_entries_persist_across_instances` fails (`_load` returns `[]`)

- [ ] **Step 3: Write minimal implementation** (replace the stub `_load`)

```python
    def _load(self) -> list[HistoryEntry]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("history_load_failed", error=str(exc), path=str(self._path))
            return []
        if not isinstance(raw, dict):
            return []
        rows = raw.get("entries", [])
        if not isinstance(rows, list):
            return []
        out: list[HistoryEntry] = []
        for item in rows:
            try:
                out.append(HistoryEntry(**item))
            except TypeError:
                continue  # skip malformed rows, keep the rest
        return out[:MAX_ENTRIES]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_history.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/soyle/core/history.py tests/unit/test_history.py
git commit -m "feat(history): load + persistence + broken-file recovery"
```

### Task 5: Config field — ui.history_enabled

**Files:**
- Modify: `src/soyle/core/config.py:104` (inside `UIConfig`)
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test** (add to `tests/unit/test_config.py`)

```python
def test_history_enabled_defaults_true_and_round_trips(tmp_path: Path) -> None:
    from soyle.core.config import ConfigStore

    store = ConfigStore(config_path=tmp_path / "config.toml")
    cfg = store.load()
    assert cfg.ui.history_enabled is True

    cfg.ui.history_enabled = False
    store.save(cfg)
    assert store.load().ui.history_enabled is False
```

(If `Path` / `pytest` are not already imported at the top of `test_config.py`,
add `from pathlib import Path`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_config.py::test_history_enabled_defaults_true_and_round_trips -q`
Expected: FAIL — `AttributeError: 'UIConfig' object has no attribute 'history_enabled'`

- [ ] **Step 3: Write minimal implementation**

In `src/soyle/core/config.py`, add the field to `UIConfig` (after
`show_floating_button` at line 104):

```python
    # Local dictation history (Stage 2). On by default; the Settings toggle
    # turns it off and clears the stored file. Stored locally; NOT synced.
    history_enabled: bool = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/soyle/core/config.py tests/unit/test_config.py
git commit -m "feat(config): ui.history_enabled (default on)"
```

### Task 6: Thread raw_text through inference + record in _finish_inference

**Files:**
- Modify: `src/soyle/app.py` (signal, `_InferenceJob`, handlers, `__init__`, `_finish_inference`)
- Test: `tests/unit/test_history_recording.py`

This task changes the `_inference_done` signal arity, so every producer and
consumer must change together. Make all edits, then run the suite.

- [ ] **Step 1: Write the failing test**

```python
"""The recording composition used by SoyleApp._finish_inference.

Mirrors the gate without booting Qt (same approach as test_monthly_limit):
should_record + build_entry + HistoryStore.append, exactly as the app
composes them.
"""
from __future__ import annotations

from pathlib import Path

from soyle.core.history import HistoryStore, build_entry, should_record


def _record(store: HistoryStore, *, text: str, raw: str, enabled: bool) -> None:
    if should_record(text, enabled=enabled):
        store.append(build_entry(text, raw, "ru", "polish", False))


def test_records_when_enabled_and_nonempty(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    _record(store, text="привет", raw="привет сырой", enabled=True)
    entries = store.all()
    assert len(entries) == 1
    assert entries[0].processed_text == "привет"
    assert entries[0].raw_text == "привет сырой"


def test_skips_when_disabled(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    _record(store, text="привет", raw="r", enabled=False)
    assert store.all() == []


def test_skips_when_empty(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    _record(store, text="   ", raw="", enabled=True)
    assert store.all() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_history_recording.py -q`
Expected: PASS already (it imports only `history.py`). This test pins the
composition contract; the real wiring below must match it. Proceed.

- [ ] **Step 3: Edit `app.py` — import + signal**

Add to the imports near the other core imports (after line 29):

```python
from soyle.core.history import HistoryStore, build_entry, should_record
```

Change the signal declaration (line 106) from:

```python
    _inference_done = Signal(str, bool, str, str, float)  # text, fallback, lang, reason, cost
```

to:

```python
    # text, raw_text, fallback, lang, reason, cost
    _inference_done = Signal(str, str, bool, str, str, float)
```

- [ ] **Step 4: Edit `app.py` — `_InferenceJob` carries raw_text**

Change the `on_done` type (the `__init__` param around line 69) from:

```python
        on_done: Callable[[str, bool, str, str, float], None],
```

to:

```python
        # on_done receives (final_text, raw_text, fallback_used, language,
        # reason_or_polish_outcome, cost_usd). See `run()` for the call sites.
        on_done: Callable[[str, str, bool, str, str, float], None],
```

In `_InferenceJob.run()` change the empty-input call from:

```python
                self._on_done(transcript.raw_text, True, transcript.language, "empty_input", 0.0)
```

to:

```python
                self._on_done(
                    transcript.raw_text, transcript.raw_text, True,
                    transcript.language, "empty_input", 0.0,
                )
```

and the success call from:

```python
            self._on_done(
                polish.text,
                polish.fallback,
                transcript.language,
                polish.reason,
                polish.cost_usd,
            )
```

to:

```python
            self._on_done(
                polish.text,
                transcript.raw_text,
                polish.fallback,
                transcript.language,
                polish.reason,
                polish.cost_usd,
            )
```

- [ ] **Step 5: Edit `app.py` — construct HistoryStore**

In `SoyleApp.__init__`, after the `_usage` line (line 128 area):

```python
        self._history_store = HistoryStore(
            default_config_path().parent / "history.json"
        )
```

- [ ] **Step 6: Edit `app.py` — `_on_inference_done` + `_finish_inference` signatures**

Change `_on_inference_done` (line 431) from:

```python
    def _on_inference_done(
        self, text: str, fallback: bool, language: str, reason: str, cost_usd: float
    ) -> None:
```

to:

```python
    def _on_inference_done(
        self, text: str, raw_text: str, fallback: bool, language: str,
        reason: str, cost_usd: float,
    ) -> None:
```

and its emit from:

```python
        self._inference_done.emit(text, fallback, language, reason, cost_usd)
```

to:

```python
        self._inference_done.emit(text, raw_text, fallback, language, reason, cost_usd)
```

Change `_finish_inference` (line 453) signature from:

```python
    def _finish_inference(
        self,
        text: str,
        fallback: bool,
        _language: str,
        reason: str,
        cost_usd: float,
    ) -> None:
```

to:

```python
    def _finish_inference(
        self,
        text: str,
        raw_text: str,
        fallback: bool,
        language: str,
        reason: str,
        cost_usd: float,
    ) -> None:
```

- [ ] **Step 7: Edit `app.py` — record into history**

In `_finish_inference`, immediately before the final
`QTimer.singleShot(200, self._after_inject)` line, add:

```python
        if should_record(text, enabled=self._cfg.ui.history_enabled):
            self._history_store.append(
                build_entry(
                    processed_text=text,
                    raw_text=raw_text,
                    language=language,
                    mode=self._cfg.postprocess.mode,
                    fallback=fallback,
                )
            )
```

- [ ] **Step 8: Run the full local check**

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src/`
Expected: PASS. mypy confirms the signal/callback arities line up across all
call sites.

- [ ] **Step 9: Commit**

```bash
git add src/soyle/app.py tests/unit/test_history_recording.py
git commit -m "feat(history): record each dictation (raw+processed) after inject"
```

### Task 7: Open PR 2.1

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin claude/ux-stage2-history
gh pr create --title "feat(history): Stage 2.1 — storage + capture plumbing" --body "$(cat <<'EOF'
## Summary
- New `core/history.py` `HistoryStore`: local, newest-first, capped at 100, broken-file recovery (mirrors `usage.py`).
- Thread `raw_text` through `_InferenceJob` / `_inference_done` so both raw and processed reach the main thread.
- Record every dictation in `_finish_inference` (gated on non-empty + `ui.history_enabled`).
- `ui.history_enabled` config field (default on). History is local-only — not cloud-synced.

No UI yet (Stage 2.2). Verify via `tests/unit/test_history*.py` and the `history.json` written under `%APPDATA%/Soyle/`.

Spec: `docs/superpowers/specs/2026-06-16-ux-stage2-result-history-design.md`
EOF
)"
```

- [ ] **Step 2: Hand off to the user for review + merge.** Do not merge.

---

# PR 2.2 — history window + tray + re-inject

**Branch off updated `main` after 2.1 merges:**

```bash
git checkout main && git pull && git checkout -b claude/ux-stage2.2-window
```

### Task 8: format_relative helper

**Files:**
- Create: `src/soyle/ui/history_window.py`
- Test: `tests/unit/test_history_window.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the history window + its pure helpers."""
from __future__ import annotations

from datetime import UTC, datetime

from soyle.ui.history_window import format_relative

_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


def test_relative_just_now() -> None:
    ts = "2026-06-16T11:59:30.000000Z"
    assert format_relative(ts, now=_NOW) == "только что"


def test_relative_minutes() -> None:
    ts = "2026-06-16T11:45:00.000000Z"
    assert "15" in format_relative(ts, now=_NOW)
    assert "мин" in format_relative(ts, now=_NOW)


def test_relative_hours() -> None:
    ts = "2026-06-16T09:00:00.000000Z"
    assert "3" in format_relative(ts, now=_NOW)
    assert "ч" in format_relative(ts, now=_NOW)


def test_relative_yesterday() -> None:
    ts = "2026-06-15T10:00:00.000000Z"
    assert format_relative(ts, now=_NOW) == "вчера"


def test_relative_older_is_date() -> None:
    ts = "2026-06-10T10:00:00.000000Z"
    assert format_relative(ts, now=_NOW) == "10.06.2026"


def test_relative_unparseable_returns_input() -> None:
    assert format_relative("garbage", now=_NOW) == "garbage"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_history_window.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'soyle.ui.history_window'`

- [ ] **Step 3: Write minimal implementation**

```python
"""History window — two-pane recover-and-reinject UI (Stage 2)."""
from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QCoreApplication


def _tr(text: str) -> str:
    return QCoreApplication.translate("HistoryWindow", text)


def format_relative(timestamp: str, *, now: datetime | None = None) -> str:
    """Human relative time for a HistoryEntry.timestamp.

    Russian source strings (identity locale); kk/en come from .qm. Returns
    the raw input unchanged if it cannot be parsed, so a corrupt row never
    crashes the list.
    """
    now = now or datetime.now(tz=UTC)
    try:
        then = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return timestamp
    secs = (now - then).total_seconds()
    if secs < 60:
        return _tr("только что")
    if secs < 3600:
        return _tr("{n} мин назад").format(n=int(secs // 60))
    if secs < 86400:
        return _tr("{n} ч назад").format(n=int(secs // 3600))
    if secs < 172800:
        return _tr("вчера")
    return then.strftime("%d.%m.%Y")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_history_window.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/history_window.py tests/unit/test_history_window.py
git commit -m "feat(history): format_relative helper"
```

### Task 9: HistoryWindow — two-pane, populate, detail

**Files:**
- Modify: `src/soyle/ui/history_window.py`
- Test: `tests/unit/test_history_window.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from soyle.core.history import HistoryStore, build_entry
from soyle.ui.history_window import HistoryWindow


def _seed(tmp_path: Path) -> HistoryStore:
    store = HistoryStore(tmp_path / "history.json")
    store.append(build_entry("первый processed", "первый raw", "ru", "polish", False,
                             now=datetime(2026, 6, 16, 9, 0, 0, tzinfo=UTC)))
    store.append(build_entry("второй processed", "второй raw", "kk", "rewrite", False,
                             now=datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)))
    return store


def test_window_lists_newest_first_and_autoselects(qtbot, tmp_path: Path) -> None:
    store = _seed(tmp_path)
    win = HistoryWindow(store, on_inject=lambda _t: None)
    qtbot.addWidget(win)
    win.show()

    assert win._list.count() == 2
    # Newest ("второй") is row 0 and auto-selected; detail shows it.
    assert win._list.currentRow() == 0
    assert "второй processed" in win._detail_processed.text()


def test_selecting_row_updates_detail(qtbot, tmp_path: Path) -> None:
    store = _seed(tmp_path)
    win = HistoryWindow(store, on_inject=lambda _t: None)
    qtbot.addWidget(win)
    win.show()

    win._list.setCurrentRow(1)  # the older "первый"
    assert "первый processed" in win._detail_processed.text()
    assert "первый raw" in win._detail_raw.text()


def test_empty_store_shows_no_rows(qtbot, tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    win = HistoryWindow(store, on_inject=lambda _t: None)
    qtbot.addWidget(win)
    win.show()
    assert win._list.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_history_window.py -q`
Expected: FAIL — `ImportError: cannot import name 'HistoryWindow'`

- [ ] **Step 3: Write minimal implementation** (append to `history_window.py`)

Add imports at the top (extend the existing import block):

```python
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from soyle.core.history import HistoryEntry, HistoryStore
```

Then the widgets:

```python
class _HistoryRow(QWidget):
    """List row: relative time + mode/lang badges + a one-line preview."""

    def __init__(self, entry: HistoryEntry) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(6)
        time_lbl = QLabel(format_relative(entry.timestamp))
        time_lbl.setObjectName("historyRowTime")
        badge = QLabel(f"{entry.mode} · {entry.language}")
        badge.setObjectName("historyRowBadge")
        top.addWidget(time_lbl)
        top.addStretch(1)
        top.addWidget(badge)
        layout.addLayout(top)

        preview = QLabel(entry.processed_text)
        preview.setObjectName("historyRowPreview")
        preview.setWordWrap(False)
        preview.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(preview)


class HistoryWindow(QWidget):
    """Two-pane history: list left, detail right. Recover & re-inject."""

    def __init__(
        self,
        store: HistoryStore,
        on_inject: Callable[[str], None],
        *,
        clipboard: Any = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._on_inject = on_inject
        # Injected for tests; defaults to the app clipboard at runtime.
        from PySide6.QtWidgets import QApplication

        self._clipboard: Any = clipboard or QApplication.clipboard()
        self._current: HistoryEntry | None = None

        self.setWindowTitle(_tr("История"))
        self.resize(720, 460)

        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(_tr("Поиск…"))
        self._search.textChanged.connect(self._populate)
        self._btn_clear = QPushButton(_tr("Очистить"))
        self._btn_clear.clicked.connect(self._on_clear)
        toolbar.addWidget(self._search, 1)
        toolbar.addWidget(self._btn_clear)
        root.addLayout(toolbar)

        panes = QHBoxLayout()

        self._list = QListWidget()
        self._list.setObjectName("historyList")
        self._list.setFixedWidth(260)
        self._list.currentItemChanged.connect(self._on_select)
        panes.addWidget(self._list)

        detail = QVBoxLayout()
        self._detail_processed = QLabel()
        self._detail_processed.setObjectName("historyProcessed")
        self._detail_processed.setWordWrap(True)
        self._detail_processed.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail.addWidget(self._detail_processed)

        self._raw_toggle = QPushButton(_tr("Показать сырой текст"))
        self._raw_toggle.setObjectName("historyRawToggle")
        self._raw_toggle.setFlat(True)
        self._raw_toggle.clicked.connect(self._toggle_raw)
        detail.addWidget(self._raw_toggle)

        self._detail_raw = QLabel()
        self._detail_raw.setObjectName("historyRaw")
        self._detail_raw.setWordWrap(True)
        self._detail_raw.setVisible(False)
        self._detail_raw.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail.addWidget(self._detail_raw)

        detail.addStretch(1)

        actions = QHBoxLayout()
        self._btn_inject = QPushButton(_tr("Вставить"))
        self._btn_inject.setObjectName("primary")  # reuse the existing accent-button QSS
        self._btn_inject.clicked.connect(self._on_inject_clicked)
        self._btn_copy = QPushButton(_tr("Копировать"))
        self._btn_copy.clicked.connect(self._on_copy)
        self._btn_delete = QPushButton(_tr("Удалить"))
        self._btn_delete.clicked.connect(self._on_delete)
        actions.addWidget(self._btn_inject)
        actions.addWidget(self._btn_copy)
        actions.addStretch(1)
        actions.addWidget(self._btn_delete)
        detail.addLayout(actions)

        panes.addLayout(detail, 1)
        root.addLayout(panes)

        self._populate()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt override)
        # Re-read the store every time the window is shown so it reflects
        # dictations made while it was closed.
        self._populate()
        super().showEvent(event)

    def _populate(self, _filter: str = "") -> None:
        needle = self._search.text().strip().lower()
        self._list.clear()
        for entry in self._store.all():
            if needle and needle not in entry.processed_text.lower() \
                    and needle not in entry.raw_text.lower():
                continue
            item = QListWidgetItem(self._list)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            row = _HistoryRow(entry)
            item.setSizeHint(row.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._current = None
            self._detail_processed.clear()
            self._detail_raw.clear()

    def _on_select(self, current: QListWidgetItem | None, _prev: object = None) -> None:
        if current is None:
            return
        entry: HistoryEntry = current.data(Qt.ItemDataRole.UserRole)
        self._current = entry
        self._detail_processed.setText(entry.processed_text)
        self._detail_raw.setText(entry.raw_text)
        self._detail_raw.setVisible(False)
        self._raw_toggle.setText(_tr("Показать сырой текст"))

    def _toggle_raw(self) -> None:
        shown = not self._detail_raw.isVisible()
        self._detail_raw.setVisible(shown)
        self._raw_toggle.setText(
            _tr("Скрыть сырой текст") if shown else _tr("Показать сырой текст")
        )

    def _on_inject_clicked(self) -> None:
        if self._current is not None:
            self._on_inject(self._current.processed_text)

    def _on_copy(self) -> None:
        if self._current is not None:
            self._clipboard.setText(self._current.processed_text)

    def _on_delete(self) -> None:
        if self._current is not None:
            self._store.delete(self._current.timestamp)
            self._populate()

    def _on_clear(self) -> None:
        if self._list.count() == 0:
            return
        confirm = QMessageBox.question(
            self,
            _tr("Очистить историю"),
            _tr("Удалить все записи истории? Это действие необратимо."),
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._store.clear()
            self._populate()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_history_window.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the local check**

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src/`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/soyle/ui/history_window.py tests/unit/test_history_window.py
git commit -m "feat(history): two-pane HistoryWindow with detail + raw toggle"
```

### Task 10: HistoryWindow actions — inject, copy, delete, clear, search

**Files:**
- Test: `tests/unit/test_history_window.py` (behaviour already implemented in Task 9)

- [ ] **Step 1: Write the failing test**

```python
class _FakeClipboard:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API shape)
        self.text = text


def test_inject_calls_back_with_processed_text(qtbot, tmp_path: Path) -> None:
    store = _seed(tmp_path)
    captured: list[str] = []
    win = HistoryWindow(store, on_inject=captured.append)
    qtbot.addWidget(win)
    win.show()  # newest "второй" auto-selected

    win._btn_inject.click()
    assert captured == ["второй processed"]


def test_copy_writes_processed_to_clipboard(qtbot, tmp_path: Path) -> None:
    store = _seed(tmp_path)
    clip = _FakeClipboard()
    win = HistoryWindow(store, on_inject=lambda _t: None, clipboard=clip)
    qtbot.addWidget(win)
    win.show()

    win._btn_copy.click()
    assert clip.text == "второй processed"


def test_delete_removes_selected_entry(qtbot, tmp_path: Path) -> None:
    store = _seed(tmp_path)
    win = HistoryWindow(store, on_inject=lambda _t: None)
    qtbot.addWidget(win)
    win.show()

    win._btn_delete.click()  # deletes "второй"
    assert win._list.count() == 1
    assert [e.processed_text for e in store.all()] == ["первый processed"]


def test_search_filters_list(qtbot, tmp_path: Path) -> None:
    store = _seed(tmp_path)
    win = HistoryWindow(store, on_inject=lambda _t: None)
    qtbot.addWidget(win)
    win.show()

    win._search.setText("первый")
    assert win._list.count() == 1
    assert "первый processed" in win._detail_processed.text()
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python -m pytest tests/unit/test_history_window.py -q`
Expected: PASS — the Task 9 implementation already satisfies these. (If a test
fails, fix the corresponding method in `history_window.py`; do not weaken the
test.)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_history_window.py
git commit -m "test(history): cover inject/copy/delete/search actions"
```

### Task 11: Tray entry — "История…" + history_requested

**Files:**
- Modify: `src/soyle/ui/tray.py`
- Test: `tests/unit/test_tray_history.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tray history entry wiring."""
from __future__ import annotations

from soyle.ui.tray import TrayIcon


def test_history_action_emits_signal(qtbot) -> None:
    tray = TrayIcon()
    received: list[bool] = []
    tray.history_requested.connect(lambda: received.append(True))

    tray._act_history.trigger()
    assert received == [True]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_tray_history.py -q`
Expected: FAIL — `AttributeError: 'TrayIcon' object has no attribute 'history_requested'`

- [ ] **Step 3: Write minimal implementation**

In `src/soyle/ui/tray.py`, add the signal next to the others (after line 16):

```python
    history_requested = Signal()
```

In `__init__`, add the action just above `act_settings` (around line 61):

```python
        self._act_history = QAction(self.tr("История…"), self)
        self._act_history.triggered.connect(self.history_requested.emit)
        menu.addAction(self._act_history)
```

(Place this line before `menu.addAction(act_settings)` so the order is
History → Settings → Logs.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_tray_history.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/tray.py tests/unit/test_tray_history.py
git commit -m "feat(tray): История… entry + history_requested signal"
```

### Task 12: App wiring — _show_history + _reinject_from_history

**Files:**
- Modify: `src/soyle/app.py`

This is integration glue. The behaviour (capture-before-show, hide-before-inject)
is verified manually and by mypy; no new unit test (the testable pieces —
store, window, tray — are already covered).

- [ ] **Step 1: Add imports + state**

In `app.py`, add to the UI imports (near the `from soyle.ui.tray import TrayIcon`):

```python
from soyle.ui.history_window import HistoryWindow
```

In `SoyleApp.__init__`, near `self._settings_window: SettingsWindow | None = None`:

```python
        self._history_window: HistoryWindow | None = None
        # Foreground window captured when the history window opens — re-inject
        # targets this, not the history window itself.
        self._history_target_hwnd = 0
```

- [ ] **Step 2: Wire the tray signal**

In `_wire_tray`, add:

```python
        self._tray.history_requested.connect(self._show_history)
```

- [ ] **Step 3: Add `_show_history` + `_reinject_from_history`**

Add these methods near `_show_settings`:

```python
    def _show_history(self) -> None:
        # Capture the foreground window BEFORE the history window steals focus —
        # re-inject puts text back into the document the user was in.
        self._history_target_hwnd = self._injector.capture_target()
        if self._history_window is None:
            self._history_window = HistoryWindow(
                self._history_store,
                on_inject=self._reinject_from_history,
            )
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()

    def _reinject_from_history(self, text: str) -> None:
        # Hide first so focus returns to the captured window, then inject there.
        if self._history_window is not None:
            self._history_window.hide()
        result = self._injector.inject(text, target_hwnd=self._history_target_hwnd)
        if result.blocked:
            self._tray.toast(
                self.tr("Söyle"),
                self.tr("Терминал: текст в буфере — вставьте вручную (Ctrl+V)"),
            )
        elif result.target_changed:
            self._tray.toast(
                self.tr("Söyle"),
                self.tr("Текст скопирован — окно изменилось, вставьте вручную (Ctrl+V)"),
            )
```

- [ ] **Step 4: Run the local check**

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src/`
Expected: PASS

- [ ] **Step 5: Manual smoke (user-run)**

Launch the app (`python -m soyle`), dictate once, open tray → "История…",
confirm the entry appears, click "Вставить" into a text editor, confirm the
text lands. Note any issues for follow-up.

- [ ] **Step 6: Commit**

```bash
git add src/soyle/app.py
git commit -m "feat(history): tray-open window + remembered-window re-inject"
```

### Task 13: Open PR 2.2

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin claude/ux-stage2.2-window
gh pr create --title "feat(history): Stage 2.2 — history window + tray + re-inject" --body "$(cat <<'EOF'
## Summary
- `HistoryWindow` (two-pane): newest-first list, processed-primary detail with raw disclosure, search, delete-one, clear-all (confirmed).
- Tray "История…" entry → opens the window.
- Re-inject captures the foreground window on open and injects there (hide → inject `target_hwnd`); clipboard copy + manual-paste toasts as fallback.

Builds on 2.1 storage. Spec: `docs/superpowers/specs/2026-06-16-ux-stage2-result-history-design.md`
EOF
)"
```

- [ ] **Step 2: Hand off to the user for review + merge.** Do not merge.

---

# PR 2.3 — settings toggle + i18n + polish

**Branch off updated `main` after 2.2 merges:**

```bash
git checkout main && git pull && git checkout -b claude/ux-stage2.3-settings-i18n
```

### Task 14: Settings "Вести историю" toggle + clear-on-disable

**Files:**
- Modify: `src/soyle/ui/settings.py` (`_build_ui_tab` ~line 724, `_save` ~line 888)
- Modify: `src/soyle/app.py` (`_reload_config`)
- Test: `tests/unit/test_settings_history.py`

- [ ] **Step 1: Write the failing test**

```python
"""Settings history toggle persists and reflects config."""
from __future__ import annotations

from pathlib import Path

from soyle.core.config import ConfigStore
from soyle.ui.settings import SettingsWindow


def test_history_checkbox_saves_choice(qtbot, tmp_path: Path) -> None:
    store = ConfigStore(config_path=tmp_path / "config.toml")
    win = SettingsWindow(store)
    qtbot.addWidget(win)

    assert win._ui_history.isChecked() is True  # default on
    win._ui_history.setChecked(False)
    win._save()

    assert store.load().ui.history_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_settings_history.py -q`
Expected: FAIL — `AttributeError: 'SettingsWindow' object has no attribute '_ui_history'`

- [ ] **Step 3: Implement — checkbox in `_build_ui_tab`**

In `settings.py`, after the floating-button checkbox block (the
`self._ui_floating` rows near line 727), add:

```python
        self._ui_history = QCheckBox(self.tr("Вести историю диктовок"))
        self._ui_history.setChecked(self._cfg.ui.history_enabled)
        layout.addRow(self._ui_history)
```

In `_save`, after `self._cfg.ui.show_floating_button = self._ui_floating.isChecked()`
(line 888):

```python
        self._cfg.ui.history_enabled = self._ui_history.isChecked()
```

- [ ] **Step 4: Implement — clear-on-disable in `app.py::_reload_config`**

Change the first line of `_reload_config` from:

```python
    def _reload_config(self) -> None:
        self._cfg = self._store.load()
```

to:

```python
    def _reload_config(self) -> None:
        was_history_enabled = self._cfg.ui.history_enabled
        self._cfg = self._store.load()
        # Turning history off wipes what's already stored.
        if was_history_enabled and not self._cfg.ui.history_enabled:
            self._history_store.clear()
```

- [ ] **Step 5: Run test + local check**

Run: `python -m pytest tests/unit/test_settings_history.py -q`
Expected: PASS

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src/`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/soyle/ui/settings.py src/soyle/app.py tests/unit/test_settings_history.py
git commit -m "feat(history): Settings toggle + clear-on-disable"
```

### Task 15: i18n — extract + translate kk/en + compile

**Files:**
- Modify: `src/soyle/i18n/soyle_kk.ts`, `src/soyle/i18n/soyle_en.ts` (+ `.qm`)

- [ ] **Step 1: Extract new strings into the .ts files**

Run: `python scripts/update_translations.py`
Expected: `pyside6-lupdate` rewrites `soyle_kk.ts` / `soyle_en.ts` with the new
`HistoryWindow`, `TrayIcon`, and `SettingsWindow` source strings marked
`type="unfinished"`.

- [ ] **Step 2: Fill in the translations**

Edit `soyle_en.ts` and `soyle_kk.ts`: for each new `<message>` with the Russian
source, provide the `<translation>`. New strings to translate:

| Russian source | English | Kazakh |
|---|---|---|
| История | History | Тарих |
| История… | History… | Тарих… |
| Поиск… | Search… | Іздеу… |
| Очистить | Clear | Тазалау |
| Очистить историю | Clear history | Тарихты тазалау |
| Удалить все записи истории? Это действие необратимо. | Delete all history entries? This cannot be undone. | Барлық тарих жазбаларын жою? Бұл әрекет қайтарылмайды. |
| Показать сырой текст | Show raw text | Шикі мәтінді көрсету |
| Скрыть сырой текст | Hide raw text | Шикі мәтінді жасыру |
| Вставить | Insert | Кірістіру |
| Копировать | Copy | Көшіру |
| Удалить | Delete | Жою |
| только что | just now | жаңа ғана |
| {n} мин назад | {n} min ago | {n} мин бұрын |
| {n} ч назад | {n} h ago | {n} сағ бұрын |
| вчера | yesterday | кеше |
| Вести историю диктовок | Keep dictation history | Диктовка тарихын сақтау |
| Текст скопирован — окно изменилось, вставьте вручную (Ctrl+V) | Text copied — the window changed, paste manually (Ctrl+V) | Мәтін көшірілді — терезе өзгерді, қолмен қойыңыз (Ctrl+V) |

Remove the `type="unfinished"` attribute on each as you translate it. (The
Kazakh strings are first-pass; the user refines loanword/phrasing choices later,
per the Stage 0 precedent.)

- [ ] **Step 3: Compile the .qm files**

Run: `python scripts/build_translations.py`
Expected: prints two `pyside6-lrelease` lines, exit 0, regenerates
`soyle_kk.qm` / `soyle_en.qm`.

- [ ] **Step 4: Verify i18n + full check**

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src/`
Expected: PASS (the existing `test_i18n.py` confirms .qm files load).

- [ ] **Step 5: Commit**

```bash
git add src/soyle/i18n/
git commit -m "i18n(history): kk + en translations for Stage 2 strings"
```

### Task 16: QSS polish — badges + two-pane styling

**Files:**
- Modify: `src/soyle/ui/theme/qss.py`
- Test: `tests/unit/test_theme_qss.py` (assert the new selectors render)

- [ ] **Step 1: Write the failing test** (add to `tests/unit/test_theme_qss.py`)

```python
def test_qss_includes_history_selectors() -> None:
    from soyle.ui.theme.qss import render_qss
    from soyle.ui.theme.tokens import active_tokens

    qss = render_qss(active_tokens("dark"))
    assert "#historyRowBadge" in qss
    assert "#historyProcessed" in qss
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_theme_qss.py -q`
Expected: FAIL — selectors absent.

- [ ] **Step 3: Implement** — the "Вставить" button already gets accent styling
from the existing `QPushButton#primary` rule (Task 9 sets its objectName to
`"primary"`), so only the badges/rows/detail need new rules. In
`src/soyle/ui/theme/qss.py`, inside `render_qss(t: Tokens)`, add these blocks to
the returned f-string immediately **before the final closing `"""`** (after the
`QListWidget {{ … }}` block). The f-string param is `t`; use `t.`-prefixed token
fields (verified against `tokens.py`: `accent`, `text_primary`,
`text_secondary`, `font_size_small`):

```python
QLabel#historyRowTime {{ color: {t.text_secondary}; font-size: {t.font_size_small}px; }}
QLabel#historyRowBadge {{ color: {t.accent}; font-size: {t.font_size_small}px; }}
QLabel#historyRowPreview {{ color: {t.text_primary}; }}
QLabel#historyProcessed {{ font-size: 15px; }}
QPushButton#historyRawToggle {{
    background: transparent;
    border: none;
    color: {t.text_secondary};
    text-align: left;
    padding: 2px 0;
}}
QLabel#historyRaw {{ color: {t.text_secondary}; }}
```

- [ ] **Step 4: Run test + local check**

Run: `python -m pytest tests/unit/test_theme_qss.py -q`
Expected: PASS

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src/`
Expected: PASS

- [ ] **Step 5: Manual visual check (user-run)**

Launch the app, open History, confirm: accent "Вставить" button, muted badges,
readable in both dark and light themes (toggle theme in Settings).

- [ ] **Step 6: Commit**

```bash
git add src/soyle/ui/theme/qss.py tests/unit/test_theme_qss.py
git commit -m "style(history): QSS for badges, accent inject, two-pane list"
```

### Task 17: Open PR 2.3

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin claude/ux-stage2.3-settings-i18n
gh pr create --title "feat(history): Stage 2.3 — settings toggle + i18n + polish" --body "$(cat <<'EOF'
## Summary
- Settings "Вести историю диктовок" toggle (default on); turning it off clears the stored history.
- Full kk + en translations for all Stage 2 strings (first-pass Kazakh).
- QSS polish: accent inject button, mode/lang badges, two-pane list styling, dark/light parity.

Completes Stage 2. Spec: `docs/superpowers/specs/2026-06-16-ux-stage2-result-history-design.md`
EOF
)"
```

- [ ] **Step 2: Hand off to the user for review + merge.** Do not merge.

---

## Done criteria (whole stage)

- Every dictation is recorded (raw + processed) to local `history.json`, capped at 100, when history is enabled.
- Tray → "История…" opens a two-pane window; newest is auto-selected.
- "Вставить" puts the processed text back into the window the user was in; "Копировать" always works as fallback.
- Raw text is one disclosure click away; search, delete-one, and clear-all work.
- Settings toggle turns history off and wipes the file.
- Full ru/kk/en localization; dark/light parity.
- `python -m pytest -q && python -m ruff check src tests && python -m mypy src/` is green.
