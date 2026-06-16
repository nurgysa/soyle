# Söyle UX Stage 2 — result and history

- **Date:** 2026-06-16
- **Status:** approved at design level; implementation via subagent-driven plan
- **Stage:** 2 of 6 — see `2026-06-13-ux-redesign-roadmap-design.md`
- **Stack:** QWidget + QSS (unchanged)

## Background

Results are currently invisible. Once text is injected it cannot be reviewed,
copied, or re-injected, and there is no record of past dictations
(`app.py::_finish_inference` injects and discards). Stage 2 of the redesign
roadmap closes this: a history window reachable from the tray, showing recent
transcripts (raw + processed), with copy and re-inject actions, backed by local
storage with a cap and a clear control.

## Decisions (brainstorm outcomes)

- **Primary scenario — recover & re-inject.** Newest entry first; the inject
  action is the prominent one. The window exists mainly to get a recent result
  back into the document when injection missed, went to the wrong window, or the
  window was closed.
- **Re-inject target — remembered window.** The foreground window is captured
  when the history window opens; "Вставить" injects into that window via
  `Injector.inject(text, target_hwnd=...)`, the same mechanism the dictation
  loop uses. Clipboard copy is always available as the reliable fallback.
- **Privacy — on by default, with a toggle.** History is enabled by default
  (cap + "Очистить"); a Settings switch ("Вести историю") lets the user turn it
  off. Turning it off clears the stored file.
- **Content — processed primary, raw secondary.** The processed (post-LLM) text
  is shown prominently and is what the primary "Вставить" injects. The raw
  (Whisper, pre-LLM) text is available secondarily (collapsible) for the
  fallback case where the LLM mangled the text.
- **Layout — two-pane.** List of entries on the left, detail of the selected
  entry on the right; the newest entry is auto-selected on open so recover stays
  one click.
- **Storage — single JSON file.** `history.json` mirrors the `usage.json`
  pattern: cap **100** entries, oldest trimmed on append, broken-file recovery.
  **Local-only** — history is NOT part of cloud sync (which covers dictionary,
  config, usage). Transcripts never leave the device.

## Architecture

### Storage layer — `src/soyle/core/history.py`

Mirrors `core/usage.py` in style (plain JSON, atomic write, broken-file
recovery, bounded size).

```python
@dataclass
class HistoryEntry:
    timestamp: str   # ISO 8601 UTC, microsecond precision; also the unique key
                     # used by delete() (two dictations cannot share a microsecond)
    processed_text: str
    raw_text: str
    language: str    # "ru" | "kk" | "en" | ...
    mode: str        # postprocess mode at capture time: polish/rewrite/...
    fallback: bool   # True when raw was injected (LLM unavailable)
```

`HistoryStore(path)`:

- `append(entry: HistoryEntry) -> None` — adds the entry, enforces the 100-entry
  cap by dropping the oldest, writes atomically.
- `all() -> list[HistoryEntry]` — newest first.
- `delete(timestamp: str) -> None` — remove one entry.
- `clear() -> None` — wipe all entries (file becomes empty list).
- On-disk shape: `{"version": 1, "entries": [ {entry...}, ... ]}`.
- Path: `default_config_path().parent / "history.json"` (alongside
  `usage.json`).
- The store is dumb storage. Whether to record is the app's decision (gated on
  `cfg.ui.history_enabled`); the store does not read config.

### Capture flow — `app.py` + `_InferenceJob`

The result raw text currently never reaches the main thread — only the polished
`text` does. One plumbing change threads it through:

- `_InferenceJob` `on_done` callback gains a `raw_text` argument; the
  `_inference_done` Qt signal gains a matching `str` parameter.
- In `_InferenceJob.run()`, pass `transcript.raw_text` alongside `polish.text`
  (on the empty-input early return, raw == processed == "").
- `_finish_inference` records to history **after** a successful inject, only
  when the text is non-empty **and** `cfg.ui.history_enabled` is true. It writes
  `processed_text=text`, `raw_text`, `language`, `mode=cfg.postprocess.mode`,
  `fallback`.
- The empty / cancelled / too-short paths do **not** record.

### UI — `src/soyle/ui/history_window.py`

`HistoryWindow(QWidget)` — a singleton window (same lifecycle pattern as
`SettingsWindow`), built lazily on first open.

- **Two-pane** (matches the approved mockup A):
  - Left: list of entries — each row shows relative time, a one-to-two-line
    preview of the processed text, and mode / language badges. Newest first;
    newest auto-selected on show.
  - Right: detail of the selected entry — processed text prominent; a
    "Показать сырой текст" disclosure reveals the raw text with its own
    "Копировать"; action row with **Вставить** (primary, accent indigo),
    **Копировать**, **Удалить**.
- **Toolbar:** a search field that filters the list by substring (processed +
  raw), and **Очистить** (clear all, with a confirmation dialog).
- Repopulates from the store each time it is shown.

`TrayIcon` (`tray.py`): add an "История…" action and a `history_requested`
signal, placed above "Настройки…".

`app.py` wiring:

- `self._history_store = HistoryStore(default_config_path().parent /
  "history.json")`
- `self._history_window: HistoryWindow | None = None`
- `_wire_tray`: connect `history_requested -> _show_history`.
- `_show_history()`: capture `remembered_hwnd = self._injector.capture_target()`
  **before** building/showing the window (so it is the user's document, not the
  history window); lazy-construct; `show()/raise_()/activateWindow()`. The
  remembered hwnd is handed to the window for its re-inject action.
- Re-inject path: the window asks the app to inject; the app **hides the window
  first** (so focus leaves it), then calls
  `self._injector.inject(text, target_hwnd=remembered_hwnd)`. Reuse the existing
  "терминал: текст в буфере" blocked-inject toast.

### Config + privacy — `config.py` + `settings.py`

- `UiConfig.history_enabled: bool = True` (new field, `extra="forbid"` keeps the
  schema strict).
- Settings: a checkbox "Вести историю" in the existing UI/General group (near
  theme / language / floating-button options). On save, when it transitions to
  off, the app calls `history_store.clear()`.

### i18n

All new user-visible strings wrapped in `tr()`; added to `ru` / `kk` / `en`
`.ts` files and recompiled to `.qm` via `pyside6-lupdate` / `pyside6-lrelease`
(the Stage 0 tooling).

## Error handling

- Storage I/O errors degrade, never crash: a broken `history.json` is logged and
  treated as empty, exactly like `UsageTracker`.
- Re-inject when the remembered window is gone or invalid: inject is
  best-effort; the clipboard copy is the guaranteed path. Blocked inject (e.g. a
  terminal) reuses the existing buffer-fallback toast.
- Disabled history: appends are skipped; the window still opens (and may be
  empty).

## Testing

- **Unit — `HistoryStore`:** append + cap trim (oldest dropped at 101),
  `all()` newest-first ordering, `delete`, `clear`, broken-file recovery,
  `version` field present.
- **Unit — capture flow:** `raw_text` is propagated through the signal; a record
  is written only when text is non-empty and history is enabled; skipped on
  empty input and when disabled.
- **Smoke — `HistoryWindow`:** builds, populates from a store, search filters the
  list, selecting a row updates the detail pane, and the action buttons are
  wired (using a fake injector + clipboard).

## PR breakdown (branch-per-stage, sequential)

Each lands on `main` as its own PR; the next branches off updated `main` (same
cadence as Stages 0 and 1).

- **2.1 — storage + capture plumbing.** `core/history.py`, `raw_text`
  propagation through `_InferenceJob` / `_inference_done`, recording in
  `_finish_inference`, the `history_enabled` config field, and unit tests. No UI
  yet — verifiable via tests and the `history.json` written on disk.
- **2.2 — history window.** `HistoryWindow` (two-pane), the tray entry,
  `_show_history` + re-inject/copy, search, delete-one, clear-all.
- **2.3 — settings toggle + i18n + polish.** The "Вести историю" checkbox and
  its clear-on-disable behaviour, full `ru`/`kk`/`en` translation, and a final
  visual pass.

## Out of scope

- Editing transcript text before re-inject (YAGNI for the recover scenario;
  separate enhancement if requested later).
- Audio storage or replay.
- Cloud-sync of history — it stays local by design.
- Per-entry export to file.
