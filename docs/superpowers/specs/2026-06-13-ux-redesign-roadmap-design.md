# Söyle UX redesign — program roadmap

- **Date:** 2026-06-13
- **Status:** approved at program level; each stage gets its own spec → plan → PR series
- **Stack decision:** stay on QWidget + QSS (no QML rewrite)

## Background

A UX audit of all UI surfaces found systemic issues rather than isolated bugs:

- **Settings** mirror the `Config` model 1:1 — 8 tabs, raw parameters (debounce ms,
  RMS silence threshold, compute type) exposed to end users, mixed RU/EN labels.
- **Onboarding** is two tray toasts plus the settings window focused on the API-key
  field; no link to obtain a key, no key verification.
- **Dictation feedback** is thin: no mic level indication while recording, and the
  cursor-following indicator draws its text with a 90 px left offset
  (`indicator.py:94`) in a 180 px pill — half the pill is empty. Stage labels are
  English-only inside an otherwise Russian UI.
- **Results are invisible**: injected text cannot be reviewed, copied, or re-injected;
  there is no history.
- **Visual layer** is ~27 lines of QSS over stock QWidgets — reads as an internal tool.

## Goals and constraints

- **Audience:** public release (installer, unknown users).
- **Localization:** full trilingual UI — Russian, Kazakh, English — with an in-app
  language switcher, shipped in this redesign (not deferred).
- **Delivery:** staged; every stage lands on `main` as a small PR series at
  functional boundaries. No long-lived redesign branch.

## Stage order and rationale

i18n touches every user-visible string, so it is foundation work — doing it after
the surface redesigns would mean touching every screen twice. Surfaces are then
ordered by user-contact frequency (dictation loop daily, settings weekly,
onboarding once). Onboarding is deliberately last despite the public-release goal:
the wizard teaches the hotkey, key setup, and settings screens, which must be
stable before the wizard points at them.

## Stages

### Stage 0 — Foundation (~3–4 PRs)

- i18n infrastructure: wrap all user-visible strings in `tr()`, `QTranslator`
  loading, `.ts`/`.qm` files for `ru` / `kk` / `en`, `pyside6-lupdate` /
  `pyside6-lrelease` wired into tooling.
- UI language config field + switcher in settings; default from system locale.
- Design tokens in QSS: typography scale, spacing, accent color, control states,
  dark/light parity.
- Indicator fixes pulled forward: center the text (90 px offset bug), localize
  stage labels.

### Stage 1 — Dictation loop (~2–3 PRs)

- Indicator: positioning model, stage icons, smooth transitions.
- Live microphone level while recording.
- Floating button state parity with the indicator.

### Stage 2 — Result and history (~2–3 PRs)

- History window reachable from tray: recent transcripts (raw + processed).
- Copy and re-inject actions.
- Local storage with cap and clear control.

### Stage 3 — Settings (~3–4 PRs)

- Regroup by user tasks, not config fields; raw parameters move to an
  Advanced section.
- API key: verify button, link to obtain a key.
- Microphone test.

### Stage 4 — Onboarding (~2 PRs)

- First-run wizard: language → hotkey → API key (link + verify) → trial dictation.
- Builds on the already-redesigned screens.

### Stage 5 — Tray and polish (~1–2 PRs)

- Tray menu: history entry, full localization.
- Reduce toast noise; quieter status reporting.
- Final visual pass across all surfaces.

## Out of scope

- QML / Fluent WinUI3 rewrite or any framework migration.
- New dictation features beyond the history window.
- Kazakh model quality work (separate track, see KZ dual-model docs).
