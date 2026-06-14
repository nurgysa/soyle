# Söyle UX redesign — Stage 1: Dictation loop

- **Date:** 2026-06-15
- **Status:** approved, ready for implementation plan
- **Parent:** [UX redesign roadmap](2026-06-13-ux-redesign-roadmap-design.md)
- **Stack:** QWidget + QSS / QPainter (no QML)

## Goal

Make the dictation feedback loop feel alive and legible: a calm fixed-position
recording HUD that shows a live microphone-level waveform, clear per-stage icons
with smooth (non-spinning) transitions through recording → transcribing →
polishing → done, and a floating button that mirrors the same state language.

## Locked decisions

- **Indicator model:** fixed-position HUD (bottom-center, ~120 px above the
  taskbar). The cursor-following behavior is retired.
- **Recording visualization:** a live waveform (equalizer bars) driven by the
  microphone level — the "we hear you" signal.
- **Waveform color:** recording-state red `#e74c3c` (consistent with the state
  palette; easily retunable later).
- **Stages & icons:** recording = `mic` (red), transcribing = `file-text`
  (amber), polishing = `sparkles` (blue), done = `check` (teal, ~600 ms) then
  fade out; error keeps the existing flash, restyled.
- **"Working" indication is NOT a spinner.** Processing stages keep a STATIC
  icon that gently breathes (opacity pulse ~1.5 s). No rotating elements anywhere
  (this applies to the floating button too).
- **Transitions:** fade-in on show, fade-out on hide (`windowOpacity`); a short
  ~120 ms opacity dip on stage change. No true two-layer crossfade.
- **Floating button parity:** shares the `Stage` palette; recording = ring pulses
  with the mic level, processing = ring breathes (no spinner), idle = current.

## In scope / out of scope

**In scope:** live mic-level plumbing, fixed HUD with waveform + stage icons +
transitions + done state, floating-button stage/level parity.

**Out of scope (later / YAGNI):** caret-anchored positioning; result/history
window (Stage 2); user-configurable HUD position; a waveform inside the 56 px
floating button; removing the now-unused `indicator_*` config fields (kept for
back-compat — see Config note).

## Architecture

### Microphone level data flow

The `Recorder` does not currently expose a live level (`stop()` computes
`rms_peak` only). Add a minimal, testable path:

- `src/soyle/core/recorder.py`
  - In the audio callback, compute `compute_rms(frame)` and store it in
    `self._latest_rms: float` (plain float assignment is atomic in CPython; the
    callback runs on the PortAudio thread, the reader on the UI thread — no lock
    needed for a single float). Reset to `0.0` on `start()` and `stop()`.
  - `current_level(self) -> float`: return `self._latest_rms` (raw RMS).
  - `normalize_level(rms: float, *, ref: float = 0.15) -> float` (module-level,
    pure): `min(1.0, sqrt(max(0.0, rms) / ref))` — maps raw RMS to 0..1 with a
    perceptual sqrt curve so quiet speech still moves the bars. **Unit-tested.**
- `src/soyle/app.py`
  - A `QTimer` (~40 ms) started on `RECORDING_STARTED` / stopped on
    `RECORDING_STOPPED`. Each tick: `lvl = recorder.current_level()` →
    `indicator.set_level(lvl)` and `floating_button.set_level(lvl)`.

Display-side smoothing (EMA) lives in the widgets, not the recorder, so the raw
signal stays inspectable.

### Recording HUD (`src/soyle/ui/indicator.py`)

Reworked from a cursor-following pill into a fixed HUD. Keeps the class name
`Indicator` and the existing public methods (`show_recording`,
`show_transcribing`, `show_polishing`, `flash_error`, `hide_indicator`) to limit
churn in `app.py`; adds `set_level(rms: float)`.

- **Position:** computed once (and on screen-geometry change) to the primary
  screen's bottom-center, `available.bottom() - height - 120`. The
  `_follow_cursor` timer is removed.
- **Stage model:** existing `Stage` literal gains `"done"`. Stage → (color, icon,
  label) table drives paint. Colors from `theme/tokens.py` (add one new
  module constant `STATE_DONE = "#1d9e75"`, a teal-green readable on both
  themes, matching the existing single-value `STATE_*` palette).
- **Waveform:** a fixed-size ring buffer (e.g. 24 slots) of EMA-smoothed levels.
  `set_level` pushes the normalized+smoothed value; `paintEvent` draws bars
  left→right (newest at right), height ∝ level, in the recording color. Only
  drawn in the `recording` stage.
- **Breathing icon:** for `transcribing`/`polishing`, a repaint timer (~33 ms)
  advances a phase; the stage icon is painted at opacity `0.4..1.0` from a sine
  of the phase. No rotation.
- **Transitions:** `QPropertyAnimation(self, b"windowOpacity")` for show (0→1,
  ~120 ms) and hide (1→0). On stage change, a brief opacity dip animation.
- **Done:** `show_done()` paints the check + "Готово" for ~600 ms (single-shot
  timer) then triggers the fade-out hide.

Icons: render Tabler-style glyphs. Since the app bundles no icon webfont for Qt,
draw simple glyphs with `QPainter` (mic, document, sparkle, check) — small,
self-contained paint helpers. (No new asset dependency.)

### Floating button (`src/soyle/ui/floating_button.py`)

- Add `set_stage(stage: Stage)` and `set_level(rms: float)`; import the shared
  `Stage`/colors so its palette tracks the HUD.
- Recording: the ring pulses — radius/alpha driven by the smoothed level.
- Processing (transcribing/polishing): the ring breathes (opacity pulse), colored
  per stage. No spinner arc.
- Idle: unchanged (gray ring + mic glyph).
- `app.py` drives `set_stage` on both the HUD and the floating button from the
  same lifecycle points, replacing the current `set_recording`/`set_processing`
  pair (those can be kept as thin wrappers or removed if no other caller).

### Config note (back-compat)

`UIConfig.indicator_position` and `indicator_follow_mouse` become unused (the HUD
is always fixed this stage). They are **kept in the model** — `extra="forbid"`
means removing them would fail validation on existing `config.toml` files. Mark
them deprecated in comments; a later migration can drop them.

## Data flow

`RECORDING_STARTED` → start level timer; `hud.show_recording()` +
`floating.set_stage("recording")`. Timer ticks feed `set_level` to both.
`RECORDING_STOPPED` → stop timer. Transcribe → `show_transcribing` +
`set_stage("transcribing")`. Polish → `show_polishing` + `set_stage("polishing")`.
Inject done → `show_done()` → fade out; floating back to idle. Errors →
`flash_error` (HUD) + floating to idle.

## Error handling

- No mic frames yet → `current_level()` returns `0.0` (flat waveform), no crash.
- Screen geometry unavailable → HUD falls back to its last position / a safe default.
- `normalize_level` clamps to `[0, 1]`; negative/NaN-safe via `max(0.0, …)`.
- Animations are cosmetic: if a `QPropertyAnimation` can't run, the widget still
  shows/hides correctly (set final value directly).

## Testing

- `normalize_level`: 0→0, ref→1.0, above-ref clamps to 1.0, sqrt curve monotonic,
  negative input → 0.
- `current_level`: returns the last RMS set by a simulated frame; `0.0` before
  any frame and after `stop()`.
- HUD: stage → color/icon/label table correct; `set_level` updates the smoothed
  level and ring buffer; `show_done()` sets the `"done"` stage; fixed position
  computed within margin of the primary screen's bottom-center (mirror the
  existing floating-button position test). No pixel assertions.
- Floating button: `set_stage` / `set_level` update internal fields; existing
  click/position tests stay green.
- Regression: full suite green; `ruff` and `mypy --strict src/` clean.

## PR breakdown (stacked, sequential — branch per PR)

- **PR 1.1 — Live mic level:** `recorder.current_level()` + `normalize_level()` +
  the app-side poll timer; HUD/floating gain `set_level` with EMA smoothing
  (waveform can render minimally here). Tests for the level math.
- **PR 1.2 — Recording HUD:** fixed position, stage table + icons, waveform paint,
  breathing processing icon, fade/dip transitions, `done` state. Retire
  `_follow_cursor`.
- **PR 1.3 — Floating-button parity:** `set_stage`/level pulse + breathing ring;
  unify stage routing in `app.py`; final polish pass.

## Out of scope follow-ups

- Drop the deprecated `indicator_*` config fields in a future config migration.
- Localize `usage.py::summary_line()` (carried over from Stage 0).
