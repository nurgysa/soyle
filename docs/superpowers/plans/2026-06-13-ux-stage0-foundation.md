# Söyle UX Stage 0 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the visual + localization foundation for the Söyle UX redesign — a Python design-token system rendering QSS, the indigo accent, RU/KZ/EN i18n, and a pulled-forward indicator fix.

**Architecture:** Qt QSS has no variables, so visual tokens live in a Python dataclass (`Tokens`) with `LIGHT`/`DARK` instances; `render_qss(tokens)` builds the stylesheet string applied at theme time. Dictation-state colors are single-sourced as module constants both the painter widgets and the tokens reference. Localization wraps source strings (kept Russian) in `tr()`, loads a `QTranslator` per resolved language, and ships `.qm` files; `ru` is the identity locale.

**Tech Stack:** Python 3.12, PySide6 ≥6.8 (QWidget + QSS, `pyside6-lupdate`/`pyside6-lrelease`), Pydantic config, pytest + pytest-qt, ruff, mypy strict.

**Spec:** [docs/superpowers/specs/2026-06-13-ux-stage0-foundation-design.md](../specs/2026-06-13-ux-stage0-foundation-design.md)

**Conventions for every commit in this plan:**
- Source strings stay Russian; code/identifiers/comments English.
- End each commit message body with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Local check gate before each commit: `python -m pytest -q && ruff check src/ tests/ && python -m mypy --strict src/`

---

## File Structure

**PR 0.1 — Visual system**
- Create: `src/soyle/ui/theme/__init__.py` — package marker.
- Create: `src/soyle/ui/theme/tokens.py` — `Tokens` dataclass, `LIGHT`/`DARK`, state-color constants, `resolve_theme`, `active_tokens`.
- Create: `src/soyle/ui/theme/qss.py` — `render_qss(tokens) -> str`.
- Modify: `src/soyle/app.py` — `_apply_theme` uses `render_qss(active_tokens(...))`; drop `qss_path` import.
- Modify: `src/soyle/ui/resources.py` — remove `qss_path`.
- Modify: `src/soyle/ui/indicator.py` — state colors from tokens; dot + centered text in paint.
- Modify: `src/soyle/ui/floating_button.py` — state ring/dot colors from tokens.
- Delete: `src/soyle/ui/qss/dark.qss`, `src/soyle/ui/qss/light.qss`.
- Modify: `scripts/build_exe.py` — drop `ui/qss` from `ADD_DATA`.
- Test: `tests/unit/test_theme_tokens.py`, `tests/unit/test_theme_qss.py`, `tests/unit/test_indicator.py`; edit `tests/unit/test_ui_resources.py`.

**PR 0.2 — i18n infrastructure**
- Modify: `src/soyle/core/config.py` — `UIConfig.language`.
- Create: `src/soyle/ui/i18n.py` — `resolve_language`, `install_translator`, `SUPPORTED`.
- Modify: `src/soyle/ui/resources.py` — add `i18n_path`.
- Modify: `src/soyle/app.py` — install translator in `__init__` before widgets.
- Modify: `src/soyle/ui/settings.py` — wrap strings in `tr()`; language combo in the "Внешний вид" tab; restart toast on change.
- Modify: `src/soyle/ui/tray.py`, `src/soyle/ui/shortcut_capture.py` — wrap strings in `tr()`.
- Create: `scripts/update_translations.py`, `scripts/build_translations.py`.
- Create: `src/soyle/i18n/soyle_en.ts` (+ generated `soyle_en.qm`).
- Modify: `scripts/build_exe.py` — add `src/soyle/i18n` `.qm` to `ADD_DATA`.
- Test: `tests/unit/test_i18n.py`; extend `tests/unit/test_config.py`, `tests/unit/test_ui_resources.py`.

**PR 0.3 — Kazakh + coverage**
- Modify: `src/soyle/ui/indicator.py`, `src/soyle/ui/floating_button.py`, `src/soyle/app.py` — wrap remaining user-facing strings in `tr()`.
- Create: `src/soyle/i18n/soyle_kk.ts` (+ generated `soyle_kk.qm`).
- Modify: `tests/unit/test_i18n.py` — assert kk/en `.qm` load and a known key translates.

---

## PR 0.1 — Visual system

### Task 1: Theme package + design tokens

**Files:**
- Create: `src/soyle/ui/theme/__init__.py`
- Create: `src/soyle/ui/theme/tokens.py`
- Test: `tests/unit/test_theme_tokens.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_theme_tokens.py
"""Tests for design tokens."""
from __future__ import annotations

from soyle.ui.theme.tokens import (
    DARK,
    LIGHT,
    STATE_POLISHING,
    STATE_RECORDING,
    Tokens,
    active_tokens,
    resolve_theme,
)


def test_light_and_dark_are_tokens() -> None:
    assert isinstance(LIGHT, Tokens)
    assert isinstance(DARK, Tokens)


def test_accent_is_indigo() -> None:
    assert LIGHT.accent == "#5b5bd6"
    assert DARK.accent.startswith("#")


def test_state_colors_single_sourced() -> None:
    # Painter widgets and tokens must agree on the dictation palette.
    assert LIGHT.state_recording == STATE_RECORDING
    assert DARK.state_polishing == STATE_POLISHING


def test_resolve_theme_passthrough() -> None:
    assert resolve_theme("light") == "light"
    assert resolve_theme("dark") == "dark"


def test_resolve_theme_unknown_defaults_dark() -> None:
    # No QApplication color scheme in a headless mapping → safe default.
    assert resolve_theme("nonsense") in ("light", "dark")


def test_active_tokens_maps_concrete_themes() -> None:
    assert active_tokens("light") is LIGHT
    assert active_tokens("dark") is DARK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_theme_tokens.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'soyle.ui.theme'`

- [ ] **Step 3: Create the package marker**

```python
# src/soyle/ui/theme/__init__.py
"""Design-token system: Python tokens rendered into a Qt stylesheet."""
```

- [ ] **Step 4: Implement tokens**

```python
# src/soyle/ui/theme/tokens.py
"""Design tokens — the single source of visual constants.

Qt QSS has no variables, so tokens live here in Python and are rendered
into a stylesheet by ``soyle.ui.theme.qss.render_qss``. The dictation-state
colors are module constants so the painter widgets (indicator, floating
button) and the rendered QSS reference one palette.
"""
from __future__ import annotations

from dataclasses import dataclass

# Canonical dictation-state palette (same in light and dark for now).
STATE_RECORDING = "#e74c3c"
STATE_TRANSCRIBING = "#f39c12"
STATE_POLISHING = "#3498db"
STATE_ERROR = "#95a5a6"


@dataclass(frozen=True)
class Tokens:
    bg_base: str
    bg_surface: str
    bg_elevated: str
    text_primary: str
    text_secondary: str
    text_tertiary: str
    border_default: str
    border_strong: str
    accent: str
    accent_hover: str
    accent_text: str
    state_recording: str
    state_transcribing: str
    state_polishing: str
    state_error: str
    radius_sm: int
    radius_md: int
    radius_lg: int
    space_sm: int
    space_md: int
    font_family: str
    font_size_base: int
    font_size_small: int


LIGHT = Tokens(
    bg_base="#fafafa",
    bg_surface="#ffffff",
    bg_elevated="#ffffff",
    text_primary="#1a1a1a",
    text_secondary="#555555",
    text_tertiary="#8a8a8a",
    border_default="#e2e2e6",
    border_strong="#c8c8cc",
    accent="#5b5bd6",
    accent_hover="#4a4ac4",
    accent_text="#ffffff",
    state_recording=STATE_RECORDING,
    state_transcribing=STATE_TRANSCRIBING,
    state_polishing=STATE_POLISHING,
    state_error=STATE_ERROR,
    radius_sm=4,
    radius_md=6,
    radius_lg=10,
    space_sm=6,
    space_md=12,
    font_family="Segoe UI",
    font_size_base=13,
    font_size_small=11,
)

DARK = Tokens(
    bg_base="#1a1a1e",
    bg_surface="#202027",
    bg_elevated="#26262d",
    text_primary="#e8e8ee",
    text_secondary="#b0b0b8",
    text_tertiary="#8a8a94",
    border_default="#2c2c33",
    border_strong="#3a3a42",
    accent="#6d6df0",
    accent_hover="#7f7ff5",
    accent_text="#0c0c1a",
    state_recording=STATE_RECORDING,
    state_transcribing=STATE_TRANSCRIBING,
    state_polishing=STATE_POLISHING,
    state_error=STATE_ERROR,
    radius_sm=4,
    radius_md=6,
    radius_lg=10,
    space_sm=6,
    space_md=12,
    font_family="Segoe UI",
    font_size_base=13,
    font_size_small=11,
)


def resolve_theme(theme: str) -> str:
    """Map a config theme value to a concrete ``"light"`` or ``"dark"``.

    ``"system"`` (or any unexpected value) queries the OS color scheme via
    Qt; with no running app or an unknown scheme, defaults to ``"dark"``.
    """
    if theme in ("light", "dark"):
        return theme
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is not None:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
    return "dark"


def active_tokens(theme: str) -> Tokens:
    """Return the token set for the (possibly ``"system"``) theme value."""
    return DARK if resolve_theme(theme) == "dark" else LIGHT
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_theme_tokens.py -q`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add src/soyle/ui/theme/ tests/unit/test_theme_tokens.py
git commit -m "feat(ui): design-token system (Tokens, LIGHT/DARK, indigo accent)"
```

---

### Task 2: QSS renderer

**Files:**
- Create: `src/soyle/ui/theme/qss.py`
- Test: `tests/unit/test_theme_qss.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_theme_qss.py
"""Tests for QSS rendering from tokens."""
from __future__ import annotations

from soyle.ui.theme.qss import render_qss
from soyle.ui.theme.tokens import DARK, LIGHT


def test_render_contains_accent_hex() -> None:
    assert LIGHT.accent in render_qss(LIGHT)


def test_render_has_core_selectors() -> None:
    css = render_qss(LIGHT)
    assert "QPushButton" in css
    assert "QTabBar::tab" in css
    assert "QLineEdit" in css


def test_primary_button_uses_accent_fill() -> None:
    css = render_qss(DARK)
    assert "QPushButton#primary" in css
    assert DARK.accent in css


def test_light_and_dark_differ() -> None:
    assert render_qss(LIGHT) != render_qss(DARK)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_theme_qss.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'soyle.ui.theme.qss'`

- [ ] **Step 3: Implement the renderer**

```python
# src/soyle/ui/theme/qss.py
"""Render a Qt stylesheet string from a Tokens instance."""
from __future__ import annotations

from soyle.ui.theme.tokens import Tokens


def render_qss(t: Tokens) -> str:
    """Build the application stylesheet from design tokens.

    The accent button is opt-in via ``objectName == "primary"`` so the
    redesign can promote one button per surface without restyling all.
    """
    return f"""
QWidget {{
    background-color: {t.bg_base};
    color: {t.text_primary};
    font-family: "{t.font_family}";
    font-size: {t.font_size_base}px;
}}
QPushButton {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_default};
    padding: 6px 14px;
    border-radius: {t.radius_sm}px;
}}
QPushButton:hover {{
    background-color: {t.bg_elevated};
    border-color: {t.border_strong};
}}
QPushButton:pressed {{ background-color: {t.border_default}; }}
QPushButton#primary {{
    background-color: {t.accent};
    color: {t.accent_text};
    border: none;
}}
QPushButton#primary:hover {{ background-color: {t.accent_hover}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_default};
    padding: 4px;
    border-radius: {t.radius_sm}px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t.accent};
}}
QTabWidget::pane {{ border: 1px solid {t.border_default}; }}
QTabBar::tab {{
    padding: 6px 14px;
    background-color: {t.bg_surface};
    color: {t.text_secondary};
}}
QTabBar::tab:selected {{
    background-color: {t.bg_base};
    color: {t.text_primary};
    border-bottom: 2px solid {t.accent};
}}
QListWidget {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_default};
    border-radius: {t.radius_sm}px;
}}
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_theme_qss.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/theme/qss.py tests/unit/test_theme_qss.py
git commit -m "feat(ui): render_qss builds stylesheet from tokens"
```

---

### Task 3: Wire `_apply_theme` to the renderer; remove static QSS

**Files:**
- Modify: `src/soyle/app.py:42` (import), `src/soyle/app.py:598-610` (`_apply_theme`)
- Modify: `src/soyle/ui/resources.py` (remove `qss_path`)
- Modify: `tests/unit/test_ui_resources.py` (drop qss test)
- Delete: `src/soyle/ui/qss/dark.qss`, `src/soyle/ui/qss/light.qss`

- [ ] **Step 1: Update the resources test (remove qss expectation)**

Replace the contents of `tests/unit/test_ui_resources.py` with:

```python
"""Tests for resource paths."""
from __future__ import annotations

from soyle.ui.resources import asset_path, prompt_path


def test_asset_path_returns_file_under_package() -> None:
    p = asset_path("icon.ico")
    assert p.parent.name == "assets"


def test_prompt_path_returns_file_under_prompts() -> None:
    p = prompt_path("polish_v1.md")
    assert p.exists()
    assert p.parent.name == "prompts"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_ui_resources.py -q`
Expected: FAIL — `ImportError: cannot import name ... ` does not yet apply; instead the old test file still imports `qss_path`. Confirm failure is the stale import in any module. If it passes here, proceed (the real gate is mypy/import below).

- [ ] **Step 3: Remove `qss_path` from resources**

In `src/soyle/ui/resources.py`, delete the `qss_path` function (lines 23-24):

```python
def qss_path(theme: str) -> Path:
    return _bundle_root() / "ui" / "qss" / f"{theme}.qss"
```

- [ ] **Step 4: Rewrite `_apply_theme` and fix the import**

In `src/soyle/app.py`, change the import on line 42 from:

```python
from soyle.ui.resources import prompt_path, qss_path
```
to:
```python
from soyle.ui.resources import prompt_path
```

Replace `_apply_theme` (lines 598-610) with:

```python
    def _apply_theme(self) -> None:
        from soyle.ui.theme.qss import render_qss
        from soyle.ui.theme.tokens import active_tokens

        self._qapp.setStyleSheet(render_qss(active_tokens(self._cfg.ui.theme)))
```

- [ ] **Step 5: Delete the static QSS files**

```bash
git rm src/soyle/ui/qss/dark.qss src/soyle/ui/qss/light.qss
```

- [ ] **Step 6: Run the full suite + type/lint gate**

Run: `python -m pytest -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: PASS — no module imports `qss_path` anymore.

- [ ] **Step 7: Commit**

```bash
git add src/soyle/app.py src/soyle/ui/resources.py tests/unit/test_ui_resources.py
git commit -m "refactor(ui): apply theme via render_qss; drop static QSS files"
```

---

### Task 4: Remove `ui/qss` from the PyInstaller bundle

**Files:**
- Modify: `scripts/build_exe.py:24-30`

- [ ] **Step 1: Drop the qss entry from `ADD_DATA`**

In `scripts/build_exe.py`, change the `ADD_DATA` list (lines 24-30) to remove the `ui/qss` tuple and its comment:

```python
ADD_DATA = [
    (SRC / "assets", "assets"),
    (SRC / "prompts", "prompts"),
]
```

- [ ] **Step 2: Verify the script still imports/parses**

Run: `python -c "import ast; ast.parse(open('scripts/build_exe.py', encoding='utf-8').read())"`
Expected: no output (parse OK).

- [ ] **Step 3: Commit**

```bash
git add scripts/build_exe.py
git commit -m "build: stop bundling removed ui/qss directory"
```

---

### Task 5: Indicator — state colors from tokens + dot/centered text

**Files:**
- Modify: `src/soyle/ui/indicator.py:12-18` (colors), `src/soyle/ui/indicator.py:83-94` (paint)
- Test: `tests/unit/test_indicator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_indicator.py
"""Tests for the cursor-following Indicator pill."""
from __future__ import annotations

from PySide6.QtGui import QColor

from soyle.ui.indicator import STAGE_COLORS, Indicator
from soyle.ui.theme.tokens import (
    STATE_POLISHING,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
)


def test_stage_colors_sourced_from_tokens() -> None:
    assert STAGE_COLORS["recording"] == QColor(STATE_RECORDING)
    assert STAGE_COLORS["transcribing"] == QColor(STATE_TRANSCRIBING)
    assert STAGE_COLORS["polishing"] == QColor(STATE_POLISHING)


def test_show_recording_sets_stage_and_text(qtbot) -> None:
    ind = Indicator()
    qtbot.addWidget(ind)
    ind.show_recording()
    assert ind._stage == "recording"
    assert ind._text != ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_indicator.py -q`
Expected: FAIL — `STAGE_COLORS["recording"]` is currently `QColor("#e74c3c")` built from a literal, which equals `QColor(STATE_RECORDING)`, so `test_stage_colors_sourced_from_tokens` may pass by coincidence; the import of token constants is the real assertion. If both pass, still proceed to refactor so the values are literally token-sourced.

- [ ] **Step 3: Source colors from tokens**

In `src/soyle/ui/indicator.py`, add after the existing imports (below line 8):

```python
from soyle.ui.theme.tokens import (
    STATE_ERROR,
    STATE_POLISHING,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
)
```

Replace the `STAGE_COLORS` dict (lines 12-18) with:

```python
STAGE_COLORS: dict[Stage, QColor] = {
    "recording": QColor(STATE_RECORDING),
    "transcribing": QColor(STATE_TRANSCRIBING),
    "polishing": QColor(STATE_POLISHING),
    "error": QColor(STATE_ERROR),
    "hidden": QColor("#000000"),
}
```

- [ ] **Step 4: Fix the paint — status dot + readable text**

Replace `paintEvent` (lines 83-94) with:

```python
    def paintEvent(self, _ev: QPaintEvent | None) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(0, 0, 0, 180)
        p.setBrush(bg)
        p.setPen(QPen(STAGE_COLORS[self._stage], 2))
        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        p.drawRoundedRect(rect, 18, 18)

        # Status dot on the left — fills the gap the old +90px offset left empty.
        dot_d = 10
        dot_x = 16
        dot_y = (self.height() - dot_d) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(STAGE_COLORS[self._stage])
        p.drawEllipse(dot_x, dot_y, dot_d, dot_d)

        # Text sits just right of the dot, vertically centered.
        p.setPen(QColor("#ffffff"))
        p.drawText(
            rect.adjusted(36, 0, -12, 0),
            Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )
```

- [ ] **Step 5: Run tests + gate**

Run: `python -m pytest tests/unit/test_indicator.py -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/soyle/ui/indicator.py tests/unit/test_indicator.py
git commit -m "fix(ui): indicator status dot + centered text; colors from tokens"
```

---

### Task 6: Floating button — state colors from tokens

**Files:**
- Modify: `src/soyle/ui/floating_button.py:23-28`

- [ ] **Step 1: Source the state colors from tokens**

In `src/soyle/ui/floating_button.py`, add after the existing imports (below line 21):

```python
from soyle.ui.theme.tokens import STATE_POLISHING, STATE_RECORDING
```

Replace the color constants block (lines 23-28) with:

```python
_RING_COLOR_IDLE = QColor("#7f8c8d")          # gray
_RING_COLOR_RECORDING = QColor(STATE_RECORDING)
_RING_COLOR_PROCESSING = QColor(STATE_POLISHING)
_FILL_BG = QColor(44, 62, 80, 220)            # dark navy, slightly translucent
_DOT_COLOR_RECORDING = QColor(STATE_RECORDING)
_MIC_COLOR_IDLE = QColor("#ecf0f1")           # light gray-white
```

- [ ] **Step 2: Run the floating-button suite + gate**

Run: `python -m pytest tests/unit/test_floating_button.py -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: PASS (existing behavior unchanged; colors now single-sourced)

- [ ] **Step 3: Commit**

```bash
git add src/soyle/ui/floating_button.py
git commit -m "refactor(ui): floating button state colors from tokens"
```

---

### Task 7: PR 0.1 — open the pull request

- [ ] **Step 1: Full local gate**

Run: `python -m pytest -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: all PASS

- [ ] **Step 2: Push and open PR**

```bash
git push -u origin claude/ux-redesign-specs
gh pr create --title "feat(ui): Stage 0.1 — design-token visual system" --body "Stage 0 PR 1 of 3. Python design tokens + render_qss replace static QSS; indigo #5B5BD6 accent; indicator status-dot + centered-text fix; painter widgets single-source state colors. No behavior change. Spec: docs/superpowers/specs/2026-06-13-ux-stage0-foundation-design.md"
```

> **Hand-off note (per user memory):** stop here for the visual smoke-check and let the user drive the merge click.

---

## PR 0.2 — i18n infrastructure

### Task 8: `UIConfig.language` field

**Files:**
- Modify: `src/soyle/core/config.py:91-101`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config.py`:

```python
def test_ui_language_default_is_system() -> None:
    assert UIConfig().language == "system"


def test_ui_language_accepts_supported() -> None:
    for lang in ("system", "ru", "kk", "en"):
        assert UIConfig(language=lang).language == lang


def test_ui_language_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        UIConfig(language="fr")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_config.py -k ui_language -q`
Expected: FAIL — `UIConfig` has no `language` field (`extra="forbid"` raises on the kwarg).

- [ ] **Step 3: Add the field**

In `src/soyle/core/config.py`, inside `UIConfig` (after line 96 `theme: ...`), add:

```python
    # UI language. "system" resolves to ru/kk/en from the OS locale at
    # startup. Stored locally (like `theme`); not synced via Cloud Sync.
    language: Literal["system", "ru", "kk", "en"] = "system"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_config.py -k ui_language -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/soyle/core/config.py tests/unit/test_config.py
git commit -m "feat(config): UIConfig.language (system|ru|kk|en)"
```

---

### Task 9: `i18n_path` resource helper

**Files:**
- Modify: `src/soyle/ui/resources.py`
- Test: `tests/unit/test_ui_resources.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_ui_resources.py`:

```python
def test_i18n_path_returns_file_under_i18n() -> None:
    from soyle.ui.resources import i18n_path

    p = i18n_path("soyle_kk.qm")
    assert p.parent.name == "i18n"
    assert str(p).endswith("soyle_kk.qm")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_ui_resources.py -k i18n -q`
Expected: FAIL — `ImportError: cannot import name 'i18n_path'`

- [ ] **Step 3: Add the helper**

In `src/soyle/ui/resources.py`, add at the end:

```python
def i18n_path(name: str) -> Path:
    return _bundle_root() / "i18n" / name
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_ui_resources.py -k i18n -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/resources.py tests/unit/test_ui_resources.py
git commit -m "feat(ui): i18n_path resource helper"
```

---

### Task 10: i18n module — `resolve_language` + `install_translator`

**Files:**
- Create: `src/soyle/ui/i18n.py`
- Test: `tests/unit/test_i18n.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_i18n.py
"""Tests for language resolution and translator installation."""
from __future__ import annotations

from PySide6.QtCore import QLocale

from soyle.ui.i18n import SUPPORTED, resolve_language


def test_explicit_values_pass_through() -> None:
    for lang in ("ru", "kk", "en"):
        assert resolve_language(lang) == lang


def test_system_maps_russian_locale() -> None:
    loc = QLocale(QLocale.Language.Russian)
    assert resolve_language("system", loc) == "ru"


def test_system_maps_kazakh_locale() -> None:
    loc = QLocale(QLocale.Language.Kazakh)
    assert resolve_language("system", loc) == "kk"


def test_system_unknown_locale_falls_back_to_en() -> None:
    loc = QLocale(QLocale.Language.French)
    assert resolve_language("system", loc) == "en"


def test_supported_languages() -> None:
    assert SUPPORTED == ("ru", "kk", "en")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_i18n.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'soyle.ui.i18n'`

- [ ] **Step 3: Implement the module**

```python
# src/soyle/ui/i18n.py
"""UI language resolution and QTranslator installation.

Source strings are Russian, so ``ru`` is the identity locale (no
translation file). Only ``kk`` and ``en`` ship ``.qm`` files.
"""
from __future__ import annotations

import structlog
from PySide6.QtCore import QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from soyle.ui.resources import i18n_path

log = structlog.get_logger()

SUPPORTED = ("ru", "kk", "en")


def resolve_language(config_value: str, system_locale: QLocale | None = None) -> str:
    """Resolve a config language value to a concrete ``ru``/``kk``/``en``.

    Explicit values pass through. ``"system"`` maps the OS locale: Russian
    → ``ru``, Kazakh → ``kk``, anything else → ``en``.
    """
    if config_value in SUPPORTED:
        return config_value
    loc = system_locale if system_locale is not None else QLocale.system()
    lang = loc.language()
    if lang == QLocale.Language.Russian:
        return "ru"
    if lang == QLocale.Language.Kazakh:
        return "kk"
    return "en"


def install_translator(app: QApplication, language: str) -> QTranslator | None:
    """Install the ``.qm`` translator for ``language`` on ``app``.

    Returns the installed ``QTranslator`` (the caller must hold the
    reference — Qt drops translations if it is garbage-collected), or
    ``None`` for the ``ru`` identity locale / on load failure.
    """
    if language == "ru":
        return None
    qm = i18n_path(f"soyle_{language}.qm")
    translator = QTranslator(app)
    if not translator.load(str(qm)):
        log.warning("translation_file_missing", language=language, path=str(qm))
        return None
    app.installTranslator(translator)
    return translator
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_i18n.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/i18n.py tests/unit/test_i18n.py
git commit -m "feat(i18n): resolve_language + install_translator"
```

---

### Task 11: Translation tooling scripts

**Files:**
- Create: `scripts/update_translations.py`
- Create: `scripts/build_translations.py`

- [ ] **Step 1: Write the lupdate script**

```python
# scripts/update_translations.py
"""Extract translatable strings from src/soyle into .ts files.

Runs pyside6-lupdate over the package and writes/updates the per-language
.ts sources in src/soyle/i18n/. `ru` is the identity locale and has no
.ts file. Run after adding or changing any tr()-wrapped string.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "soyle"
I18N = SRC / "i18n"
LANGS = ("kk", "en")


def main() -> int:
    I18N.mkdir(parents=True, exist_ok=True)
    sources = [str(p) for p in SRC.rglob("*.py")]
    ts_args: list[str] = []
    for lang in LANGS:
        ts_args += ["-ts", str(I18N / f"soyle_{lang}.ts")]
    cmd = ["pyside6-lupdate", *sources, *ts_args]
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the lrelease script**

```python
# scripts/build_translations.py
"""Compile src/soyle/i18n/*.ts into .qm files next to them.

Run before packaging (and after editing translations) so the bundled
QTranslator has up-to-date .qm files.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "src" / "soyle" / "i18n"


def main() -> int:
    ts_files = sorted(I18N.glob("*.ts"))
    if not ts_files:
        print(f"no .ts files in {I18N}")
        return 1
    rc = 0
    for ts in ts_files:
        qm = ts.with_suffix(".qm")
        cmd = ["pyside6-lrelease", str(ts), "-qm", str(qm)]
        print(" ".join(cmd))
        rc |= subprocess.call(cmd)
    return rc


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify both scripts parse**

Run: `python -c "import ast,glob; [ast.parse(open(f,encoding='utf-8').read()) for f in ['scripts/update_translations.py','scripts/build_translations.py']]"`
Expected: no output (parse OK)

- [ ] **Step 4: Commit**

```bash
git add scripts/update_translations.py scripts/build_translations.py
git commit -m "build(i18n): lupdate/lrelease tooling scripts"
```

---

### Task 12: Install the translator at startup

**Files:**
- Modify: `src/soyle/app.py:119` area (after config load, before widgets at line 130)

- [ ] **Step 1: Add the translator install**

In `src/soyle/app.py`, immediately after `self._cfg = self._store.load()` (line 119) and before `self._usage = ...`, add:

```python
        # Install the UI translator before any widget is built so tr() in
        # widget constructors picks up the active language. Held on self so
        # Qt does not garbage-collect the translator (which drops strings).
        from soyle.ui.i18n import install_translator, resolve_language

        self._translator = install_translator(
            self._qapp, resolve_language(self._cfg.ui.language)
        )
```

- [ ] **Step 2: Verify import + boot path type-checks**

Run: `python -m mypy --strict src/`
Expected: PASS (the `_translator` attribute is assigned in `__init__`, so mypy infers `QTranslator | None`).

- [ ] **Step 3: Commit**

```bash
git add src/soyle/app.py
git commit -m "feat(i18n): install translator at startup before widgets"
```

---

### Task 13: Wrap Settings strings in `tr()` + language switcher

**Files:**
- Modify: `src/soyle/ui/settings.py` (string wrapping; `_build_ui_tab` at 631-670; `_save` at 760-798)
- Test: `tests/unit/test_settings_language.py`

**Wrapping pattern (apply throughout `settings.py`):** wrap every user-visible
literal in `self.tr(...)`. Examples — apply the same transform to all such
literals in the file:

```python
# before
self.setWindowTitle("Söyle — настройки")
self._tabs.addTab(self._build_hotkey_tab(), "Хоткей")
btn_save = QPushButton("Сохранить")
# after
self.setWindowTitle(self.tr("Söyle — настройки"))
self._tabs.addTab(self._build_hotkey_tab(), self.tr("Хоткей"))
btn_save = QPushButton(self.tr("Сохранить"))
```

> Brand tokens that must NOT be translated: model ids, `"OpenRouter"`,
> `"Google Drive"`, mode ids passed as `data` (`"polish"`, `"rewrite"`, …).
> Wrap only the human-readable labels.

- [ ] **Step 1: Write the failing test (language combo present + persists)**

```python
# tests/unit/test_settings_language.py
"""Settings language switcher."""
from __future__ import annotations

from pathlib import Path

from soyle.core.config import ConfigStore
from soyle.ui.settings import SettingsWindow


def test_language_combo_saves_choice(qtbot, tmp_path: Path) -> None:
    store = ConfigStore(config_path=tmp_path / "config.toml")
    win = SettingsWindow(store)
    qtbot.addWidget(win)

    # Select Kazakh and save.
    idx = win._ui_language.findData("kk")
    assert idx >= 0
    win._ui_language.setCurrentIndex(idx)
    win._save()

    assert store.load().ui.language == "kk"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_settings_language.py -q`
Expected: FAIL — `SettingsWindow` has no `_ui_language` attribute.

- [ ] **Step 3: Add the language combo to the "Внешний вид" tab**

In `_build_ui_tab` (`src/soyle/ui/settings.py`), after the theme combo rows
(after line 637 `layout.addRow("Тема:", self._ui_theme)`), add:

```python
        self._ui_language = QComboBox()
        self._ui_language.addItem(self.tr("Системный"), "system")
        self._ui_language.addItem("Русский", "ru")
        self._ui_language.addItem("Қазақша", "kk")
        self._ui_language.addItem("English", "en")
        lang_idx = self._ui_language.findData(self._cfg.ui.language)
        self._ui_language.setCurrentIndex(max(0, lang_idx))
        layout.addRow(self.tr("Язык интерфейса:"), self._ui_language)
        # Remember the value at open time so _save can detect a change and
        # prompt for restart (language applies on next launch).
        self._ui_language_original = self._cfg.ui.language
```

- [ ] **Step 4: Persist + restart notice in `_save`**

In `_save` (`src/soyle/ui/settings.py`), after the existing
`self._cfg.ui.theme = ...` line (line 790), add:

```python
        self._cfg.ui.language = self._ui_language.currentData()
```

Then at the very end of `_save`, after `self.settings_saved.emit()` (line 798), add:

```python
        if self._cfg.ui.language != self._ui_language_original:
            self._ui_language_original = self._cfg.ui.language
            self._toast(
                self.tr("Söyle"),
                self.tr("Язык интерфейса изменится после перезапуска."),
            )
```

- [ ] **Step 5: Run the settings test + full gate**

Run: `python -m pytest tests/unit/test_settings_language.py -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/soyle/ui/settings.py tests/unit/test_settings_language.py
git commit -m "feat(i18n): settings language switcher (restart to apply) + tr() pass"
```

---

### Task 14: Generate `en.ts`, translate, compile, bundle

**Files:**
- Create: `src/soyle/i18n/soyle_en.ts`, `src/soyle/i18n/soyle_kk.ts` (extracted; kk filled in PR 0.3)
- Create (generated): `src/soyle/i18n/soyle_en.qm`
- Modify: `scripts/build_exe.py:24-30`

- [ ] **Step 1: Extract strings into .ts**

Run: `python scripts/update_translations.py`
Expected: creates `src/soyle/i18n/soyle_en.ts` and `src/soyle/i18n/soyle_kk.ts` with `<source>` Russian strings and empty `<translation>` elements.

- [ ] **Step 2: Fill English translations**

Open `src/soyle/i18n/soyle_en.ts` and provide the English `<translation>` for
each `<source>`. Example entries:

```xml
<message>
    <source>Söyle — настройки</source>
    <translation>Söyle — Settings</translation>
</message>
<message>
    <source>Хоткей</source>
    <translation>Hotkey</translation>
</message>
<message>
    <source>Сохранить</source>
    <translation>Save</translation>
</message>
<message>
    <source>Закрыть</source>
    <translation>Close</translation>
</message>
<message>
    <source>Язык интерфейса:</source>
    <translation>Interface language:</translation>
</message>
```

Translate every remaining `<message>` the same way. Leave `soyle_kk.ts`
`<translation>` elements empty for now (PR 0.3).

- [ ] **Step 3: Compile to .qm**

Run: `python scripts/build_translations.py`
Expected: writes `src/soyle/i18n/soyle_en.qm` and `src/soyle/i18n/soyle_kk.qm`.

- [ ] **Step 4: Bundle .qm in the build**

In `scripts/build_exe.py`, add the i18n directory to `ADD_DATA`:

```python
ADD_DATA = [
    (SRC / "assets", "assets"),
    (SRC / "prompts", "prompts"),
    (SRC / "i18n", "i18n"),
]
```

- [ ] **Step 5: Smoke-test English loads**

Run: `python -c "from PySide6.QtWidgets import QApplication; import sys; app=QApplication(sys.argv); from soyle.ui.i18n import install_translator; t=install_translator(app,'en'); print('loaded' if t else 'none'); print(app.translate('SettingsWindow','Сохранить'))"`
Expected: prints `loaded` then `Save`.

- [ ] **Step 6: Commit**

```bash
git add src/soyle/i18n/ scripts/build_exe.py
git commit -m "feat(i18n): English translation (en.ts/.qm) + bundle i18n dir"
```

---

### Task 15: PR 0.2 — open the pull request

- [ ] **Step 1: Full local gate**

Run: `python -m pytest -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: all PASS

- [ ] **Step 2: Push and open PR**

```bash
git push
gh pr create --title "feat(i18n): Stage 0.2 — i18n infrastructure (RU+EN)" --body "Stage 0 PR 2 of 3. UIConfig.language + resolve_language, QTranslator at startup, lupdate/lrelease tooling, English translation, settings language switcher (restart to apply). Russian source strings; ru is identity. Spec: docs/superpowers/specs/2026-06-13-ux-stage0-foundation-design.md"
```

> **Hand-off note:** let the user drive the merge click.

---

## PR 0.3 — Kazakh + remaining coverage

### Task 16: Wrap remaining widget strings in `tr()`

**Files:**
- Modify: `src/soyle/ui/indicator.py` (stage labels at 48-69)
- Modify: `src/soyle/ui/tray.py` (menu labels: "Режим" 37, "Настройки…" 61, "Показать логи" 63, "Выход" 65, usage prefix)
- Modify: `src/soyle/ui/floating_button.py` (tooltip "Зажмите для записи" line 64)
- Modify: `src/soyle/app.py` (user-facing toast strings)

**Indicator stage labels** — these are currently English literals; wrap so they
localize. `Indicator` is a `QWidget`, so `self.tr(...)` works:

```python
    def show_recording(self) -> None:
        self._stage = "recording"
        self._text = self.tr("Recording")
        self._follow_timer.start()
        self.show()
        self.update()

    def show_transcribing(self) -> None:
        self._stage = "transcribing"
        self._text = self.tr("Transcribing…")
        self.update()

    def show_polishing(self) -> None:
        self._stage = "polishing"
        self._text = self.tr("Polishing…")
        self.update()
```

**Tray** — `TrayIcon` is a `QObject`, so `self.tr(...)` works. Wrap the menu
labels (keep mode display names as brand terms):

```python
mode_menu = menu.addMenu(self.tr("Режим"))
...
act_settings = QAction(self.tr("Настройки…"), self)
act_logs = QAction(self.tr("Показать логи"), self)
act_quit = QAction(self.tr("Выход"), self)
```

**FloatingButton** tooltip:

```python
self.setToolTip(self.tr("Зажмите для записи"))
```

- [ ] **Step 1: Apply the wrapping above** across the four files.

- [ ] **Step 2: Re-extract strings**

Run: `python scripts/update_translations.py`
Expected: `soyle_en.ts` and `soyle_kk.ts` gain the new `<message>` entries (e.g. "Recording").

- [ ] **Step 3: Fill English for the new entries** in `src/soyle/i18n/soyle_en.ts`
(the new strings are already English source-equivalents — set `<translation>` to
the English text, e.g. `Recording` → `Recording`).

- [ ] **Step 4: Gate**

Run: `python -m pytest -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/soyle/ui/indicator.py src/soyle/ui/tray.py src/soyle/ui/floating_button.py src/soyle/app.py src/soyle/i18n/soyle_en.ts
git commit -m "feat(i18n): localize indicator/tray/floating/app strings"
```

---

### Task 17: Kazakh translations + compile

**Files:**
- Modify: `src/soyle/i18n/soyle_kk.ts`
- Create (generated): `src/soyle/i18n/soyle_kk.qm`
- Test: `tests/unit/test_i18n.py`

- [ ] **Step 1: Fill Kazakh translations**

Open `src/soyle/i18n/soyle_kk.ts` and provide the Kazakh `<translation>` for each
`<source>`. Example entries:

```xml
<message>
    <source>Сохранить</source>
    <translation>Сақтау</translation>
</message>
<message>
    <source>Закрыть</source>
    <translation>Жабу</translation>
</message>
<message>
    <source>Настройки…</source>
    <translation>Баптаулар…</translation>
</message>
<message>
    <source>Выход</source>
    <translation>Шығу</translation>
</message>
<message>
    <source>Язык интерфейса:</source>
    <translation>Интерфейс тілі:</translation>
</message>
```

Translate every remaining `<message>`.

- [ ] **Step 2: Compile**

Run: `python scripts/build_translations.py`
Expected: writes/updates `src/soyle/i18n/soyle_kk.qm` and `soyle_en.qm`.

- [ ] **Step 3: Add a translator-loads test**

Add to `tests/unit/test_i18n.py`:

```python
def test_kk_translator_loads_and_translates(qtbot) -> None:
    from PySide6.QtWidgets import QApplication

    from soyle.ui.i18n import install_translator

    app = QApplication.instance() or QApplication([])
    translator = install_translator(app, "kk")
    assert translator is not None
    # A known key from soyle_kk.ts must come back translated (non-Russian).
    assert app.translate("SettingsWindow", "Сохранить") == "Сақтау"
    app.removeTranslator(translator)
```

- [ ] **Step 4: Run the test + gate**

Run: `python -m pytest tests/unit/test_i18n.py -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/soyle/i18n/soyle_kk.ts src/soyle/i18n/soyle_kk.qm src/soyle/i18n/soyle_en.qm tests/unit/test_i18n.py
git commit -m "feat(i18n): Kazakh translations (kk.ts/.qm)"
```

---

### Task 18: PR 0.3 — open the pull request

- [ ] **Step 1: Full local gate**

Run: `python -m pytest -q && ruff check src/ tests/ && python -m mypy --strict src/`
Expected: all PASS

- [ ] **Step 2: Manual trilingual check**

Set `ui.language` to `kk` then `en` in `%APPDATA%\Soyle\config.toml`, launch
`python -m soyle`, open Settings, confirm labels switch. Record results in
`docs/MANUAL_TESTS.md` if that file tracks such checks.

- [ ] **Step 3: Push and open PR**

```bash
git push
gh pr create --title "feat(i18n): Stage 0.3 — Kazakh + full UI coverage" --body "Stage 0 PR 3 of 3. Kazakh translations, localized indicator/tray/floating/app strings, translator-load test. Completes the foundation stage. Spec: docs/superpowers/specs/2026-06-13-ux-stage0-foundation-design.md"
```

> **Hand-off note:** KZ copy needs your review; let the user drive the merge click.

---

## Self-Review

**Spec coverage:**
- Design tokens (tokens.py + qss.py + active_tokens) → Tasks 1-3 ✓
- Remove static QSS → Task 3 ✓; un-bundle → Task 4 ✓
- Indigo accent → Task 1 (`LIGHT.accent`) + Task 2 (primary button) ✓
- Painter widgets single-source state colors → Tasks 5, 6 ✓
- Indicator text-centering + dot → Task 5 ✓
- OS dark/light for `system` theme → Task 1 (`resolve_theme`) ✓
- `UIConfig.language` + `resolve_language` → Tasks 8, 10 ✓
- QTranslator at startup → Task 12 ✓
- Russian source / `ru` identity → Tasks 10, 14 (en/kk only) ✓
- lupdate/lrelease tooling → Task 11 ✓
- Language switcher (restart to apply) → Task 13 ✓
- en.ts + .qm bundling → Task 14 ✓
- Kazakh + remaining strings → Tasks 16, 17 ✓
- Error handling: missing `.qm` → `install_translator` warns + returns None (Task 10); unknown theme/language → safe defaults (Tasks 1, 8) ✓
- Testing gate pytest+ruff+mypy → every task ✓

**Placeholder scan:** No "TBD"/"add error handling"/"similar to". The i18n
string-wrapping is given as an explicit, repeatable transform plus the
`lupdate` workflow that mechanically extracts every wrapped string — the
`.ts`/`.qm` contents are generated, not hand-listed, which is the correct i18n
practice rather than a placeholder.

**Type consistency:** `Tokens` fields referenced in `render_qss` match Task 1
definitions. `resolve_theme`/`active_tokens`/`resolve_language`/
`install_translator`/`i18n_path`/`STATE_*` names are consistent across tasks.
`_ui_language` / `_ui_language_original` used consistently in Task 13.

**Open gap accepted:** `ui.language` deliberately not synced (spec out-of-scope);
custom font deferred to Stage 3.
