# Söyle UX redesign — Stage 0: Foundation

- **Date:** 2026-06-13
- **Status:** approved, ready for implementation plan
- **Parent:** [UX redesign roadmap](2026-06-13-ux-redesign-roadmap-design.md)
- **Stack:** QWidget + QSS (no QML)

## Goal

Lay the visual and localization foundation the rest of the redesign builds on:
a design-token system, the chosen visual language (modern minimal, indigo accent),
trilingual RU/KZ/EN infrastructure, and a small indicator fix pulled forward.

## Locked decisions

- **Visual language:** modern minimal (direction B), generous whitespace, single
  signature accent on calm surfaces.
- **Accent color:** indigo `#5B5BD6` (light) — distinct from the three dictation
  state colors (recording red, transcribing amber, polishing blue).
- **Localization:** RU + KZ + EN shipped together.
- **Source strings (msgid):** Russian. `ru` is the identity locale (no translation
  file); only `kk` and `en` get translation files. Keeps the diff to wrapping
  existing literals and preserves already-reviewed Russian copy verbatim.
- **Language switch:** applies on restart (no live retranslation).
- **`ui.language`:** stored locally like `ui.theme` — not synced via Cloud Sync in
  this stage.

## In scope / out of scope

**In scope:** token system + QSS render pipeline, indigo accent, OS dark/light
detection for `system` theme, i18n infrastructure + language switcher, indicator
text-centering and stage-label localization.

**Out of scope (later stages):** indicator stage icons, animations/transitions,
live microphone level (Stage 1); settings regrouping (Stage 3); onboarding wizard
(Stage 4); making `ui.language` a synced preference.

## Architecture

### Design tokens

Qt QSS has no variables, so tokens live in Python and are rendered into a
stylesheet string at theme-apply time.

- `src/soyle/ui/theme/tokens.py`
  - `@dataclass(frozen=True) Tokens` with fields:
    - surfaces: `bg_base`, `bg_surface`, `bg_elevated`
    - text: `text_primary`, `text_secondary`, `text_tertiary`
    - borders: `border_default`, `border_strong`
    - accent: `accent`, `accent_hover`, `accent_text` (text drawn on accent fill)
    - states: `state_recording`, `state_transcribing`, `state_polishing`,
      `state_error` (centralizes hex currently scattered in `indicator.py` and
      `floating_button.py`)
    - scale: `radius_sm/md/lg`, `space_xs/sm/md/lg`, `font_family`,
      `font_size_base`, `font_size_small`
  - module constants `LIGHT: Tokens` and `DARK: Tokens`.
  - `active_tokens(theme: str) -> Tokens`: maps `"light"|"dark"` directly;
    `"system"` resolves via OS color scheme (`QApplication.styleHints().colorScheme()`,
    Qt 6.5+), defaulting to `DARK` if unknown.
- `src/soyle/ui/theme/qss.py`
  - `render_qss(tokens: Tokens) -> str`: builds the full stylesheet from token
    values (QWidget base, buttons incl. an accented primary button, inputs,
    combos, tabs, lists, labels — covering today's `dark.qss`/`light.qss`
    selectors plus the accent button class).
- `_apply_theme()` ([app.py:598](../../../src/soyle/app.py)) becomes:
  `tokens = active_tokens(self._cfg.ui.theme); self._qapp.setStyleSheet(render_qss(tokens))`.
  The hand-written `dark.qss` / `light.qss` files and `qss_path()` are removed.
- Painter-drawn widgets (`indicator.py`, `floating_button.py`) read their state
  colors from the active `Tokens` rather than module-level `QColor` constants, so
  the dictation palette is single-sourced.

### i18n

- Wrap every user-visible string in `self.tr(...)` (QObject subclasses) or
  `QCoreApplication.translate(context, ...)` for module-level text. Source text
  stays Russian.
- New config field on `UIConfig`: `language: Literal["system","ru","kk","en"] = "system"`.
- `resolve_language(config_value, system_locale) -> "ru"|"kk"|"en"`:
  - explicit `ru/kk/en` → itself
  - `system` → map `QLocale` language: Russian→`ru`, Kazakh→`kk`, else→`en`
- App startup installs a `QTranslator` for the resolved language (none needed for
  `ru`, the identity locale).
- Translation sources in `src/soyle/i18n/`: `soyle_kk.ts`, `soyle_en.ts`
  (no `ru` file — identity). Compiled `.qm` bundled via PyInstaller `datas`.
- Tooling in `scripts/`: `update_translations` (runs `pyside6-lupdate` over
  `src/soyle`) and `build_translations` (runs `pyside6-lrelease`). `.qm` build
  wired into the packaging step.
- Language switcher: a combo in the "Внешний вид" tab. On change + save, show a
  tray toast that the language applies after restart.

### Indicator fix (now)

- `indicator.py` paint: replace the `+90px` text offset
  ([indicator.py:94](../../../src/soyle/ui/indicator.py)) with a left status dot
  (filled circle in the stage color from tokens) plus text padded to sit just
  right of the dot. Net effect: readable, balanced pill.
- Stage labels ("Recording", "Transcribing…", "Polishing…") go through `tr()`.
- Stage→color lookup reads from active tokens.

## Data flow

`Config.ui.{theme,language}` → on startup and on `_reload_config()`:
`active_tokens(theme)` → `render_qss` → `setStyleSheet`; `resolve_language` →
`QTranslator`. Painter widgets pull the same `Tokens` instance for state colors.

## Error handling

- Missing/failed `.qm` load → fall back to identity (Russian) without crashing;
  log a warning (mirrors existing `theme_file_missing` pattern).
- Unknown `theme`/`language` config values → safe defaults (`DARK` / `system`).
- `colorScheme()` unavailable → default `DARK`.

## Testing

- `resolve_language`: explicit values pass through; locale mapping ru/kk/en;
  unknown locale → `en`.
- `UIConfig.language`: save/load round-trip; unknown value tolerated.
- `render_qss(LIGHT) != render_qss(DARK)`; both contain the accent hex and key
  selectors; `active_tokens("system")` returns a valid `Tokens`.
- Indicator: stage→color sourced from tokens; labels run through `tr()`.
- Regression: existing suite green, including `SettingsWindow` built without
  `cloud_sync`; `ruff` and `mypy --strict src/` clean.

## PR breakdown (stacked on one branch)

- **PR 0.1 — Visual system:** `tokens.py` + `qss.py` + `active_tokens`; rewire
  `_apply_theme`; remove `dark.qss`/`light.qss`; painter widgets read tokens;
  indigo accent; indicator dot + centered text. No behavior change, no i18n.
- **PR 0.2 — i18n infrastructure:** `tr()` wrapping pass; `QTranslator` loading;
  `UIConfig.language` + `resolve_language`; `en.ts` + tooling scripts; language
  switcher in settings. (RU + EN working.)
- **PR 0.3 — Kazakh + coverage:** `kk.ts` translations; localize remaining
  tray / indicator / floating strings; KZ review by user.

## Open follow-ups (not this stage)

- Make `ui.language` a synced preference (touches `cloud_sync._merge_config`).
- Bundle a custom UI font vs. staying on Segoe UI (decide during Stage 3 polish).
