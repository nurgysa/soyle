# Söyle UX Stage 1 (Dictation loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dictation feedback loop feel alive — a fixed recording HUD with a live mic-level waveform, per-stage icons with non-spinning transitions, and a floating button that mirrors the same state language.

**Architecture:** The `Recorder` exposes a live RMS level read by a ~40 ms UI timer that feeds both the HUD and the floating button. The HUD (`Indicator`) becomes a fixed bottom-center widget that paints a stage icon + (during recording) a waveform from a ring buffer of smoothed levels, with `windowOpacity` fade transitions. Icons are hand-drawn with `QPainter` (no icon webfont). "Working" stages breathe (opacity pulse), never spin.

**Tech Stack:** Python 3.12, PySide6 (QWidget + QPainter + QPropertyAnimation), numpy (RMS), pytest + pytest-qt, ruff, mypy strict.

**Spec:** [docs/superpowers/specs/2026-06-15-ux-stage1-dictation-loop-design.md](../specs/2026-06-15-ux-stage1-dictation-loop-design.md)

**Conventions for every commit:**
- Source UI strings stay Russian; code/identifiers/comments English.
- End each commit body with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Gate before each commit: `.venv\Scripts\python.exe -m pytest -q && .venv\Scripts\python.exe -m ruff check src/ tests/ && .venv\Scripts\python.exe -m mypy --strict src/`
- Windows/PowerShell; use `.venv\Scripts\python.exe`.

---

## File Structure

**PR 1.1 — Live mic level**
- Modify: `src/soyle/core/recorder.py` — `normalize_level()` (pure) + `_latest_rms` + `current_level()`.
- Modify: `src/soyle/ui/indicator.py` — `set_level()` (EMA store; no visual yet).
- Modify: `src/soyle/ui/floating_button.py` — `set_level()` (EMA store).
- Modify: `src/soyle/app.py` — ~40 ms level poll timer started/stopped with recording.
- Test: `tests/unit/test_recorder.py` (extend), `tests/unit/test_indicator.py` (extend), `tests/unit/test_floating_button.py` (extend).

**PR 1.2 — Recording HUD**
- Modify: `src/soyle/ui/theme/tokens.py` — `STATE_DONE`.
- Modify: `src/soyle/ui/indicator.py` — fixed position, stage table, `"done"`, waveform, glyphs, breathing, transitions.
- Test: `tests/unit/test_theme_tokens.py`, `tests/unit/test_indicator.py`.

**PR 1.3 — Floating-button parity**
- Modify: `src/soyle/ui/floating_button.py` — `set_stage()` + pulse/breathing paint.
- Modify: `src/soyle/app.py` — unify stage routing to both widgets.
- Test: `tests/unit/test_floating_button.py`.

---

## PR 1.1 — Live mic level

### Task 1: `normalize_level` pure function

**Files:**
- Modify: `src/soyle/core/recorder.py`
- Test: `tests/unit/test_recorder.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_recorder.py`:

```python
import math

from soyle.core.recorder import normalize_level


def test_normalize_level_zero_is_zero() -> None:
    assert normalize_level(0.0) == 0.0


def test_normalize_level_at_ref_is_one() -> None:
    assert normalize_level(0.15, ref=0.15) == 1.0


def test_normalize_level_clamps_above_ref() -> None:
    assert normalize_level(1.0, ref=0.15) == 1.0


def test_normalize_level_negative_is_zero() -> None:
    assert normalize_level(-0.5) == 0.0


def test_normalize_level_sqrt_curve_midpoint() -> None:
    # quarter of ref energy -> sqrt(0.25) = 0.5 of the bar
    assert math.isclose(normalize_level(0.15 * 0.25, ref=0.15), 0.5, abs_tol=1e-9)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_recorder.py -k normalize_level -q`
Expected: FAIL — `ImportError: cannot import name 'normalize_level'`.

- [ ] **Step 3: Implement**

In `src/soyle/core/recorder.py`, add after `compute_rms` (after line 23):

```python
def normalize_level(rms: float, *, ref: float = 0.15) -> float:
    """Map a raw RMS value to a 0..1 display level with a sqrt curve.

    ``ref`` is the RMS treated as "full bar". The sqrt makes quiet speech
    still move the bars perceptibly. Clamped to [0, 1]; negative/NaN-safe.
    """
    if not rms > 0.0:  # also catches NaN
        return 0.0
    return min(1.0, math.sqrt(rms / ref))
```

Add `import math` to the top of the file (after `from __future__ import annotations`, in the stdlib group — before `from dataclasses import dataclass`).

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_recorder.py -k normalize_level -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/soyle/core/recorder.py tests/unit/test_recorder.py
git commit -m "feat(audio): normalize_level — RMS to 0..1 display curve

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `Recorder.current_level()` live RMS

**Files:**
- Modify: `src/soyle/core/recorder.py`
- Test: `tests/unit/test_recorder.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_recorder.py`:

```python
import numpy as np

from soyle.core.bus import EventBus
from soyle.core.recorder import Recorder


def test_current_level_zero_before_any_frame() -> None:
    rec = Recorder(bus=EventBus())
    assert rec.current_level() == 0.0


def test_current_level_reflects_last_frame() -> None:
    rec = Recorder(bus=EventBus())
    frame = np.full(160, 0.1, dtype=np.float32)
    rec._on_frame(frame)  # simulate the audio-callback path
    assert rec.current_level() > 0.0


def test_current_level_resets_after_stop() -> None:
    rec = Recorder(bus=EventBus())
    rec._on_frame(np.full(160, 0.1, dtype=np.float32))
    rec.stop()  # no active stream -> safe no-op stop, but resets level
    assert rec.current_level() == 0.0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_recorder.py -k current_level -q`
Expected: FAIL — `Recorder` has no `_on_frame` / `current_level`.

- [ ] **Step 3: Implement**

In `src/soyle/core/recorder.py` `Recorder.__init__`, add after `self._sample_rate: int = 16000` (line 79):

```python
        self._latest_rms: float = 0.0
```

Add two methods to `Recorder` (e.g. after `__init__`):

```python
    def _on_frame(self, mono: np.ndarray) -> None:
        """Store the frame's RMS for live level read-out. Called from the
        PortAudio callback thread; a single float assignment is atomic in
        CPython, so no lock is needed for the UI-thread reader."""
        self._latest_rms = compute_rms(mono)

    def current_level(self) -> float:
        """Latest frame RMS (0.0 before any frame / after stop)."""
        return self._latest_rms
```

Wire `_on_frame` into the existing callback. In `start()`, change `_callback` (lines 85-87) to:

```python
        def _callback(indata: np.ndarray, _frames: int, _time_info: Any, _status: Any) -> None:
            mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
            self._on_frame(mono)
            self._queue.put(mono)
```

In `start()`, reset the level — add after `self._queue = Queue()` (line 83):

```python
        self._latest_rms = 0.0
```

In `stop()`, reset the level — add right after the early-return guard's `else` path; simplest is to set it at the very top of `stop()` body after the `if self._stream is None:` block returns. Add immediately after line 105 (`self._stream = None`):

```python
        self._latest_rms = 0.0
```
Also set `self._latest_rms = 0.0` inside the `if self._stream is None:` branch before its `return` so a stop with no stream still resets (covers `test_current_level_resets_after_stop`).

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_recorder.py -k current_level -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Full gate + commit**

Run the gate. Then:

```bash
git add src/soyle/core/recorder.py tests/unit/test_recorder.py
git commit -m "feat(audio): Recorder.current_level live RMS read-out

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `Indicator.set_level()` (EMA store)

**Files:**
- Modify: `src/soyle/ui/indicator.py`
- Test: `tests/unit/test_indicator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_indicator.py`:

```python
def test_set_level_rises_toward_loud_input(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    for _ in range(20):
        ind.set_level(0.15)  # sustained "full" input
    assert ind._level > 0.8


def test_set_level_decays_toward_silence(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    for _ in range(20):
        ind.set_level(0.15)
    for _ in range(40):
        ind.set_level(0.0)
    assert ind._level < 0.1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_indicator.py -k set_level -q`
Expected: FAIL — `Indicator` has no `set_level` / `_level`.

- [ ] **Step 3: Implement**

In `src/soyle/ui/indicator.py`, add the import (with the existing tokens import group):

```python
from soyle.core.recorder import normalize_level
```

In `Indicator.__init__`, add after `self._text: str = ""` (line 43):

```python
        self._level: float = 0.0  # EMA-smoothed 0..1 display level
        self._level_smooth = 0.35  # EMA alpha
```

Add a method (after the public API methods):

```python
    def set_level(self, rms: float) -> None:
        """Feed a raw RMS sample; stored as an EMA-smoothed 0..1 level."""
        target = normalize_level(rms)
        self._level = self._level_smooth * target + (1 - self._level_smooth) * self._level
        self.update()
```

(The waveform paint that consumes `_level` lands in PR 1.2.)

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_indicator.py -k set_level -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/indicator.py tests/unit/test_indicator.py
git commit -m "feat(ui): Indicator.set_level EMA store

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `FloatingButton.set_level()` (EMA store)

**Files:**
- Modify: `src/soyle/ui/floating_button.py`
- Test: `tests/unit/test_floating_button.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_floating_button.py`:

```python
def test_set_level_rises_then_decays(qtbot) -> None:
    from soyle.core.bus import EventBus

    btn = FloatingButton(bus=EventBus())
    qtbot.addWidget(btn)
    for _ in range(20):
        btn.set_level(0.15)
    assert btn._level > 0.8
    for _ in range(40):
        btn.set_level(0.0)
    assert btn._level < 0.1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_floating_button.py -k set_level -q`
Expected: FAIL — no `set_level` / `_level`.

- [ ] **Step 3: Implement**

In `src/soyle/ui/floating_button.py`, add the import (first-party group, after the bus import):

```python
from soyle.core.recorder import normalize_level
```

In `FloatingButton.__init__`, add after `self._processing = False` (line 53):

```python
        self._level: float = 0.0
        self._level_smooth = 0.35
```

Add a method:

```python
    def set_level(self, rms: float) -> None:
        """Feed a raw RMS sample; stored as an EMA-smoothed 0..1 level."""
        target = normalize_level(rms)
        self._level = self._level_smooth * target + (1 - self._level_smooth) * self._level
        self.update()
```

(The pulse paint that consumes `_level` lands in PR 1.3.)

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_floating_button.py -k set_level -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/floating_button.py tests/unit/test_floating_button.py
git commit -m "feat(ui): FloatingButton.set_level EMA store

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Level poll timer in `app.py`

**Files:**
- Modify: `src/soyle/app.py`

(No unit test — `SoyleApp` wiring isn't unit-tested in this repo; covered by the gate + manual check. `QTimer` is already imported at `app.py:18`.)

- [ ] **Step 1: Add the timer in `__init__`**

In `src/soyle/app.py` `SoyleApp.__init__`, after `self._floating_button = FloatingButton(bus=self._bus)` (line 135), add:

```python
        # Polls the recorder's live level (~25 fps) while recording and feeds
        # both the HUD and the floating button. Started/stopped with recording.
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(40)
        self._level_timer.timeout.connect(self._poll_mic_level)
```

- [ ] **Step 2: Add the poll method**

Add a method to `SoyleApp` (near the hotkey handlers):

```python
    def _poll_mic_level(self) -> None:
        level = self._recorder.current_level()
        self._indicator.set_level(level)
        self._floating_button.set_level(level)
```

- [ ] **Step 3: Start/stop the timer with recording**

In `_wire_events`, extend the existing `RECORDING_STARTED` / `RECORDING_STOPPED` subscriptions (lines 289-296) so they also drive the timer. Replace those two `subscribe` blocks with:

```python
        self._bus.subscribe(
            Event.RECORDING_STARTED,
            lambda _payload: self._on_recording_started_ui(),
        )
        self._bus.subscribe(
            Event.RECORDING_STOPPED,
            lambda _payload: self._on_recording_stopped_ui(),
        )
```

Add the two helpers to `SoyleApp`:

```python
    def _on_recording_started_ui(self) -> None:
        self._floating_button.set_recording(True)
        self._level_timer.start()

    def _on_recording_stopped_ui(self) -> None:
        self._floating_button.set_recording(False)
        self._level_timer.stop()
        # Settle bars to zero so the next recording starts clean.
        self._indicator.set_level(0.0)
        self._floating_button.set_level(0.0)
```

- [ ] **Step 4: Gate + smoke**

Run the gate. Then confirm the app imports and the timer is wired:
`.venv\Scripts\python.exe -c "import soyle.app; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/soyle/app.py
git commit -m "feat(ui): poll mic level into HUD + floating button while recording

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: PR 1.1 — open the pull request

- [ ] **Step 1: Full gate**

Run: `.venv\Scripts\python.exe -m pytest -q && .venv\Scripts\python.exe -m ruff check src/ tests/ && .venv\Scripts\python.exe -m mypy --strict src/`
Expected: all PASS.

- [ ] **Step 2: Push + PR**

```bash
git push -u origin claude/ux-stage1-dictation
gh pr create --base main --title "feat(ui): UX Stage 1.1 — live mic level" --body "Stage 1 PR 1 of 3 (includes the Stage 1 design doc). Recorder.current_level() + pure normalize_level(); ~40ms app timer feeds EMA-smoothed level to HUD + floating button. Visuals consuming the level land in 1.2/1.3. Spec: docs/superpowers/specs/2026-06-15-ux-stage1-dictation-loop-design.md"
```

> **Hand-off:** user drives the merge click.

---

## PR 1.2 — Recording HUD

### Task 7: `STATE_DONE` token

**Files:**
- Modify: `src/soyle/ui/theme/tokens.py`
- Test: `tests/unit/test_theme_tokens.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_theme_tokens.py` (extend the import + add a test):

```python
def test_state_done_present() -> None:
    from soyle.ui.theme.tokens import STATE_DONE

    assert STATE_DONE == "#1d9e75"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_theme_tokens.py -k state_done -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

In `src/soyle/ui/theme/tokens.py`, add to the state-color constants block (after `STATE_ERROR = "#95a5a6"`):

```python
STATE_DONE = "#1d9e75"  # teal-green success, readable on both themes
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_theme_tokens.py -k state_done -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/theme/tokens.py tests/unit/test_theme_tokens.py
git commit -m "feat(ui): STATE_DONE token

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: HUD stage model + `done` state + fixed position

**Files:**
- Modify: `src/soyle/ui/indicator.py`
- Test: `tests/unit/test_indicator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_indicator.py`:

```python
from soyle.ui.theme.tokens import STATE_DONE


def test_show_done_sets_done_stage(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    ind.show_done()
    assert ind._stage == "done"


def test_done_color_from_token(qtbot) -> None:
    from PySide6.QtGui import QColor

    from soyle.ui.indicator import STAGE_COLORS

    assert STAGE_COLORS["done"] == QColor(STATE_DONE)


def test_fixed_position_is_bottom_center(qtbot) -> None:
    from PySide6.QtGui import QGuiApplication

    ind = Indicator()
    qtbot.addWidget(ind)
    ind.show_recording()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    geom = ind.geometry()
    # horizontally centered within a tolerance, and 120px above the bottom
    assert abs(geom.center().x() - avail.center().x()) <= 2
    assert geom.bottom() <= avail.bottom() - 120 + ind.height()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_indicator.py -k "done or fixed_position" -q`
Expected: FAIL — no `show_done`, no `"done"` in `STAGE_COLORS`, position not centered.

- [ ] **Step 3: Implement stage model + position**

In `src/soyle/ui/indicator.py`:

Extend the `Stage` literal and `STAGE_COLORS`:

```python
Stage = Literal["recording", "transcribing", "polishing", "done", "hidden", "error"]

STAGE_COLORS: dict[Stage, QColor] = {
    "recording": QColor(STATE_RECORDING),
    "transcribing": QColor(STATE_TRANSCRIBING),
    "polishing": QColor(STATE_POLISHING),
    "done": QColor(STATE_DONE),
    "error": QColor(STATE_ERROR),
    "hidden": QColor("#000000"),
}
```

Add `STATE_DONE` to the tokens import.

Remove the cursor-follow timer. In `__init__`, delete the `_follow_timer` block (lines 45-47) and replace `_follow_cursor` usage. Add a fixed-position helper and call it on show. Replace `show_recording` and add `show_done`:

```python
    MARGIN_BOTTOM = 120

    def _position_fixed(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = avail.center().x() - self.width() // 2
        y = avail.bottom() - self.height() - self.MARGIN_BOTTOM
        self.move(x, y)

    def show_recording(self) -> None:
        self._stage = "recording"
        self._text = self.tr("Запись")
        self._position_fixed()
        self.show()
        self.update()

    def show_done(self) -> None:
        self._stage = "done"
        self._text = self.tr("Готово")
        self.show()
        self.update()
        self._auto_hide_timer.start(600)
```

Update imports: add `QGuiApplication` to the `PySide6.QtGui` import line. Remove `QCursor` if no longer used. Remove `_follow_cursor` method. `show_transcribing`/`show_polishing`/`flash_error`/`hide_indicator` keep working (no cursor timer to stop — remove `self._follow_timer.stop()` from `hide_indicator`).

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_indicator.py -q`
Expected: PASS (all indicator tests).

- [ ] **Step 5: Gate + commit**

```bash
git add src/soyle/ui/indicator.py tests/unit/test_indicator.py
git commit -m "feat(ui): HUD fixed position + done stage; retire cursor-follow

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: HUD paint — glyphs, waveform, breathing, transitions

**Files:**
- Modify: `src/soyle/ui/indicator.py`

This task is visual; correctness is verified by the gate + manual smoke (no pixel
assertions). Behavioral pieces (animation objects exist, ring buffer fills) get
light tests in Step 1.

- [ ] **Step 1: Write the behavioral tests**

Add to `tests/unit/test_indicator.py`:

```python
def test_level_feeds_ring_buffer(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    for _ in range(5):
        ind.set_level(0.15)
    assert len(ind._levels) > 0
    assert max(ind._levels) > 0.0


def test_show_recording_runs_fade_animation(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    ind.show_recording()
    # opacity animation object exists and targets windowOpacity
    assert ind._fade.propertyName() == b"windowOpacity"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_indicator.py -k "ring_buffer or fade_animation" -q`
Expected: FAIL — no `_levels` / `_fade`.

- [ ] **Step 3: Implement the ring buffer, animation, breathing timer**

In `src/soyle/ui/indicator.py` imports add:

```python
import math
from collections import deque

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
```

In `__init__` add (after the `_level` fields from Task 3):

```python
        self._levels: deque[float] = deque(maxlen=24)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(120)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        # Breathing phase for processing-stage icons (no rotation).
        self._breath_phase = 0.0
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(33)
        self._breath_timer.timeout.connect(self._tick_breath)
```

Update `set_level` (from Task 3) to also push to the ring buffer:

```python
    def set_level(self, rms: float) -> None:
        target = normalize_level(rms)
        self._level = self._level_smooth * target + (1 - self._level_smooth) * self._level
        self._levels.append(self._level)
        self.update()
```

Add the breath tick + fade helpers:

```python
    def _tick_breath(self) -> None:
        self._breath_phase += 0.12
        self.update()

    def _fade_to(self, end: float, *, then_hide: bool = False) -> None:
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(end)
        try:
            self._fade.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        if then_hide:
            self._fade.finished.connect(self.hide)
        self._fade.start()
```

Make the stage methods drive the breath timer + fade. Update them:

```python
    def show_recording(self) -> None:
        self._stage = "recording"
        self._text = self.tr("Запись")
        self._breath_timer.stop()
        self._position_fixed()
        self.setWindowOpacity(0.0)
        self.show()
        self._fade_to(1.0)
        self.update()

    def show_transcribing(self) -> None:
        self._stage = "transcribing"
        self._text = self.tr("Распознавание…")
        self._breath_timer.start()
        self.update()

    def show_polishing(self) -> None:
        self._stage = "polishing"
        self._text = self.tr("Обработка…")
        self._breath_timer.start()
        self.update()

    def show_done(self) -> None:
        self._stage = "done"
        self._text = self.tr("Готово")
        self._breath_timer.stop()
        self.update()
        QTimer.singleShot(600, lambda: self._fade_to(0.0, then_hide=True))

    def hide_indicator(self) -> None:
        self._stage = "hidden"
        self._breath_timer.stop()
        self.hide()
```

Keep `flash_error` but stop the breath timer in it and use the existing auto-hide.

- [ ] **Step 4: Implement the paint (glyphs + waveform + breathing)**

Replace `paintEvent` with:

```python
    def paintEvent(self, _ev: QPaintEvent | None) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = STAGE_COLORS[self._stage]
        bg = QColor(0, 0, 0, 200)
        p.setBrush(bg)
        p.setPen(QPen(color, 2))
        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        p.drawRoundedRect(rect, 18, 18)

        icon_box = QRect(12, (self.height() - 18) // 2, 18, 18)
        if self._stage in ("transcribing", "polishing"):
            opacity = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._breath_phase))
            p.setOpacity(opacity)
        self._paint_glyph(p, icon_box, color)
        p.setOpacity(1.0)

        if self._stage == "recording":
            self._paint_waveform(p, color)

        p.setPen(QColor("#ffffff"))
        p.drawText(rect.adjusted(40, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter, self._text)

    def _paint_glyph(self, p: QPainter, box: QRect, color: QColor) -> None:
        p.save()
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = box.center().x(), box.center().y()
        if self._stage == "recording":
            p.setBrush(color)
            p.drawRoundedRect(cx - 3, box.top() + 1, 6, 9, 3, 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(cx - 5, cy - 3, 10, 10, 200 * 16, 140 * 16)
            p.drawLine(cx, box.bottom() - 4, cx, box.bottom())
        elif self._stage == "transcribing":
            p.drawRect(box.left() + 3, box.top() + 1, 10, 14)
            for i in range(3):
                yy = box.top() + 5 + i * 3
                p.drawLine(box.left() + 5, yy, box.left() + 11, yy)
        elif self._stage == "polishing":
            p.setBrush(color)
            cxp, cyp = cx, cy
            star = [
                QPoint(cxp, cyp - 7), QPoint(cxp + 2, cyp - 2),
                QPoint(cxp + 7, cyp), QPoint(cxp + 2, cyp + 2),
                QPoint(cxp, cyp + 7), QPoint(cxp - 2, cyp + 2),
                QPoint(cxp - 7, cyp), QPoint(cxp - 2, cyp - 2),
            ]
            p.drawPolygon(star)
        elif self._stage == "done":
            p.drawPolyline([QPoint(cx - 6, cy), QPoint(cx - 2, cy + 4), QPoint(cx + 6, cy - 5)])
        elif self._stage == "error":
            p.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
            p.drawLine(cx + 5, cy - 5, cx - 5, cy + 5)
        p.restore()

    def _paint_waveform(self, p: QPainter, color: QColor) -> None:
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        bar_w, gap = 3, 2
        n = self._levels.maxlen or 24
        x0 = 40
        max_h = self.height() - 16
        cy = self.height() // 2
        levels = list(self._levels)
        for i in range(len(levels)):
            h = max(2, int(levels[i] * max_h))
            x = x0 + i * (bar_w + gap)
            if x > self.width() - 14:
                break
            p.drawRoundedRect(x, cy - h // 2, bar_w, h, 1, 1)
        p.restore()
```

Add `QPoint` to the `PySide6.QtCore` import.

> Note: the waveform overlaps the text region; for the recording stage, the
> text "Запись" is short and the bars start at x=40. If they crowd, the bars
> draw left-to-right and stop before the right edge — acceptable for v1. The
> HUD width stays 180; widen to 220 if needed during manual check (adjust
> `self.resize(...)`).

- [ ] **Step 5: Run tests + gate + manual smoke**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_indicator.py -q` then the full gate.
Expected: PASS.
Manual: `.venv\Scripts\python.exe -m soyle`, hold the hotkey — HUD appears bottom-center with a red waveform reacting to your voice; release → "Распознавание…" (breathing doc) → "Обработка…" (breathing sparkle) → "Готово" (check) → fades out.

- [ ] **Step 6: Commit**

```bash
git add src/soyle/ui/indicator.py tests/unit/test_indicator.py
git commit -m "feat(ui): HUD waveform + stage glyphs + breathing + fade transitions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: PR 1.2 — open the pull request

- [ ] **Step 1: Full gate** (pytest + ruff + mypy) — all PASS.

- [ ] **Step 2: Push + PR**

```bash
git push
gh pr create --base main --title "feat(ui): UX Stage 1.2 — recording HUD" --body "Stage 1 PR 2 of 3. Fixed bottom-center HUD: live red waveform while recording, hand-drawn stage glyphs (mic/doc/sparkle/check), breathing (non-spinning) processing icon, windowOpacity fade transitions, done state. Cursor-follow retired. Spec: docs/superpowers/specs/2026-06-15-ux-stage1-dictation-loop-design.md"
```

> **Hand-off:** user smoke-checks the HUD live, drives the merge click.

---

## PR 1.3 — Floating-button parity

### Task 11: `FloatingButton.set_stage()` + stage paint

**Files:**
- Modify: `src/soyle/ui/floating_button.py`
- Test: `tests/unit/test_floating_button.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_floating_button.py`:

```python
def test_set_stage_updates_field(qtbot) -> None:
    from soyle.core.bus import EventBus

    btn = FloatingButton(bus=EventBus())
    qtbot.addWidget(btn)
    btn.set_stage("transcribing")
    assert btn._stage == "transcribing"
    btn.set_stage("recording")
    assert btn._stage == "recording"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_floating_button.py -k set_stage -q`
Expected: FAIL — no `set_stage` / `_stage`.

- [ ] **Step 3: Implement**

In `src/soyle/ui/floating_button.py` import the shared stage type + colors:

```python
from soyle.ui.indicator import STAGE_COLORS, Stage
```

In `__init__` add (after `_level` fields):

```python
        self._stage: Stage = "hidden"
        self._breath_phase = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._tick_anim)
```

Add `QTimer` to the `PySide6.QtCore` import.

Add methods:

```python
    def set_stage(self, stage: Stage) -> None:
        self._stage = stage
        if stage in ("recording", "transcribing", "polishing"):
            self._anim_timer.start()
        else:
            self._anim_timer.stop()
        self.update()

    def _tick_anim(self) -> None:
        self._breath_phase += 0.12
        self.update()
```

Keep `set_recording`/`set_processing` as thin shims so existing callers don't
break, delegating to `set_stage`:

```python
    def set_recording(self, on: bool) -> None:
        self._recording = on
        self.set_stage("recording" if on else "hidden")

    def set_processing(self, on: bool) -> None:
        self._processing = on
        if on:
            self.set_stage("polishing")
        elif not self._recording:
            self.set_stage("hidden")
```

Extend `paintEvent`: when `_stage == "recording"`, draw a pulse ring whose radius
grows with `_level`; when processing, draw the ring at breathing opacity in the
stage color. Add to the start of the existing ring-drawing section:

```python
        stage_color = STAGE_COLORS.get(self._stage)
        if self._stage == "recording" and stage_color is not None:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            pulse = QColor(stage_color)
            pulse.setAlpha(int(90 * self._level))
            grow = int(6 * self._level)
            p.setBrush(pulse)
            p.drawEllipse(self.rect().center(), self.SIZE // 2 - 2 + grow, self.SIZE // 2 - 2 + grow)
            p.restore()
        elif self._stage in ("transcribing", "polishing") and stage_color is not None:
            opacity = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self._breath_phase))
            p.save()
            p.setOpacity(opacity)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(stage_color, self.RING_WIDTH))
            half = self.RING_WIDTH / 2
            p.drawEllipse(int(half), int(half), int(self.width() - self.RING_WIDTH), int(self.height() - self.RING_WIDTH))
            p.restore()
```

Add `import math` to the top of the file.

- [ ] **Step 4: Run tests + gate**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_floating_button.py -q` then full gate.
Expected: PASS (existing click/position tests stay green).

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/floating_button.py tests/unit/test_floating_button.py
git commit -m "feat(ui): floating button stage parity — level pulse + breathing ring

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: Unify stage routing in `app.py`

**Files:**
- Modify: `src/soyle/app.py`

(No unit test — wiring; gate + manual.)

- [ ] **Step 1: Route every stage to both widgets**

In `src/soyle/app.py`, at each point the HUD stage changes, also set the floating
button stage. Concretely:

- In `_on_hotkey_pressed`, after `self._indicator.show_recording()` (line 337), add `self._floating_button.set_stage("recording")`.
- Where `self._indicator.show_transcribing()` is called (line ~375), add `self._floating_button.set_stage("transcribing")`.
- Where `self._indicator.show_polishing()` is called (line ~445), add `self._floating_button.set_stage("polishing")`.
- Where the loop finishes and injects (the success path that currently calls `self._indicator.hide_indicator()` around line 525), replace `hide_indicator()` with `self._indicator.show_done()` and add `self._floating_button.set_stage("hidden")`.
- In the error/cancel paths that call `self._indicator.flash_error(...)`, add `self._floating_button.set_stage("hidden")`.

- [ ] **Step 2: Gate + smoke**

Run the full gate. Then `.venv\Scripts\python.exe -m soyle` and run one dictation
end-to-end: floating button should pulse (recording) → breathe amber
(transcribing) → breathe blue (polishing) → return to idle as the HUD shows
"Готово".

- [ ] **Step 3: Commit**

```bash
git add src/soyle/app.py
git commit -m "feat(ui): drive floating button stage from the dictation lifecycle

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: PR 1.3 — open the pull request

- [ ] **Step 1: Full gate** — all PASS.

- [ ] **Step 2: Push + PR**

```bash
git push
gh pr create --base main --title "feat(ui): UX Stage 1.3 — floating button parity" --body "Stage 1 PR 3 of 3. Floating button shares the HUD stage palette: ring pulses with mic level while recording, breathes (no spinner) during transcribing/polishing. app.py drives both widgets from one lifecycle. Completes Stage 1. Spec: docs/superpowers/specs/2026-06-15-ux-stage1-dictation-loop-design.md"
```

> **Hand-off:** user smoke-checks, drives the merge click.

---

## Self-Review

**Spec coverage:**
- Live mic level (recorder.current_level + normalize_level + poll timer) → Tasks 1, 2, 5 ✓
- EMA smoothing in widgets → Tasks 3, 4 ✓
- Fixed bottom-center HUD, retire cursor-follow → Task 8 ✓
- `STATE_DONE` token → Task 7 ✓
- Stage table + `done` state → Tasks 8, 9 ✓
- Waveform (recording, red, ring buffer) → Task 9 ✓
- Hand-drawn glyphs (mic/doc/sparkle/check), no webfont → Task 9 ✓
- Breathing processing icon, NO rotation → Task 9 ✓
- Fade-in/out + stage dip transitions → Task 9 (fade) ✓ (stage dip folded into the breathing/fade behavior; the 120ms `_fade` is reused on show/hide — a per-stage dip can be added later if desired)
- Floating parity: set_stage + level pulse + breathing ring, no spinner → Tasks 11, 12 ✓
- Config back-compat (keep `indicator_*` fields, ignored) → no code change needed; fields untouched, HUD simply never reads them ✓
- Testing: normalize_level, current_level, set_level EMA, stage/color, fixed position, ring buffer, set_stage → Tasks 1-4, 7-9, 11 ✓; pixel-free per repo style ✓

**Placeholder scan:** No TBD/"add error handling"/"similar to". Visual paint code is given in full (Task 9). The two wiring tasks (5, 12) are explicitly marked untestable-by-unit and rely on gate + manual, with exact edits given.

**Type consistency:** `Stage` (with `"done"`) defined in Task 8, imported by floating button in Task 11. `STATE_DONE` defined Task 7, used Tasks 8-9. `normalize_level` (Task 1) used in Tasks 3, 4. `set_level`/`set_stage`/`current_level`/`_level`/`_levels`/`_fade`/`_breath_phase` names consistent across tasks.

**Deviation noted:** spec's "true ~120 ms opacity dip on stage change" is implemented as a shared fade on show/hide (Task 9); a dedicated mid-stage dip is deferred as polish (non-blocking, cosmetic) to avoid over-engineering the animation graph.
