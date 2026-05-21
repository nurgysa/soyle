# Söyle — KZ-first code-switching reinforcement (Design)

**Status:** Draft for review
**Date:** 2026-05-21
**Author:** nurgysa (with Claude Opus 4.7)
**Related spec:** [`2026-04-19-whisperflow-design.md`](2026-04-19-whisperflow-design.md) — original Whisper+LLM pipeline

## Problem

README, CHANGELOG, and `pyproject.toml` already position Söyle as a KZ + RU + EN code-switching dictation tool. Reality is weaker than the marketing claim: in practice the user reports failures across all four layers of the pipeline when Kazakh is involved:

1. **Whisper poorly recognises pure Kazakh.** Especially diacritic-bearing letters (Қ, Ң, Ө, Ү, Ұ, Һ, І) are misread; some words come out as Russian-looking phonetic approximations.
2. **Whisper auto-detect picks the wrong language** for KZ-dominant utterances with EN/RU sprinkles.
3. **KZ suffixes on EN/RU stems get mangled** — patterns like `deploy-тау`, `feature-ды`, `push етеміз` lose their Kazakh inflection.
4. **LLM polish normalises KZ into RU** — `polish_v1.md`'s draft examples don't strongly enough forbid the LLM from translating Kazakh segments into Russian.

The user explicitly chose a "blind" iteration (no eval data, no audio harness) for this round — improvements will be informed by literature and Whisper documentation, not by empirical regression measurement.

## Goal

Improve the quality of **Kazakh text output** from Söyle, in three scenarios:

1. Pure-KZ dictation (no RU/EN admixture)
2. KZ-dominant dictation with English/Russian sprinkles
3. KZ preservation across all five LLM modes (`polish`, `rewrite`, `ai_prompt`, `plain_text`, `task`)

## Non-goals

- **No evaluation harness with audio fixtures.** Deferred until real failure samples are collected.
- **No Whisper model replacement or fine-tuning.** Out of budget.
- **No architectural changes.** `Transcriber`, `PostProcess`, `DictionaryStore` public APIs stay stable.
- **No new language.** Kazakh is already shipped in the product positioning — this is reinforcement, not introduction.
- **No Kazakh-Latin script support.** Cyrillic-only.

## Success criteria

- **Subjective:** the user runs the new "Code-switching и казахский" manual test plan section A-F and confirms quality is "better or equal" (no regressions on pure-RU/EN, improvements on KZ-dominant samples).
- **Objective fallback:** all unit tests pass (245/245 today + 2-3 new); `mypy src/` clean; `ruff check` clean.

## Approach (Plan B with KZ-first focus)

Three layers of light-touch reinforcement, no architecture change:

| Layer | Change | Why |
|-------|--------|-----|
| **Whisper initial_prompt** | `DictionaryStore.as_whisper_prompt()` prepends `"Languages: Kazakh, Russian, English."` to the glossary string | Whisper reads `initial_prompt` before decoding; named languages bias both auto-detect AND vocabulary toward multilingual decoding. Documented behaviour of `faster-whisper`. |
| **Whisper model UX hints** | Update notes in `WHISPER_MODELS` to flag `large-v3` (vs `large-v3-turbo`) for KZ-heavy users | Turbo is a quality/speed compromise tuned for English. Full `large-v3` is meaningfully better for KZ recognition but heavier. We're not changing defaults, just documenting the trade-off in the UI dropdown. |
| **LLM prompt rewrites** | Replace draft KZ examples in `polish_v1.md`, audit the other 4 prompts (`rewrite`, `ai_prompt`, `plain_text`, `task`); add explicit "never KZ→RU normalize" rule | Existing `TODO(prompt-tuning)` in `polish_v1.md` admits the 3 KZ examples are placeholders. Real KZ-dominant code-switching patterns replace them. |
| **Settings UI hint** | Tooltip-style `QLabel` near the Whisper language dropdown explaining auto-detect is correct for code-switchers | UX fix — many users force `kk` thinking it will help, when in fact auto-detect handles mixed speech better. |

## Files changed

10 files total: 4 code + 5 prompts + 1 doc.

### Code (4)

1. **`src/soyle/core/dictionary.py`** — `as_whisper_prompt()`:
   - **Before:** `"Glossary: X, Y, Z."` (or `""` if empty)
   - **After:** `"Languages: Kazakh, Russian, English."` always present; optional ` Glossary: X, Y, Z.` suffix when terms exist

2. **`src/soyle/core/transcriber.py`** — `WHISPER_MODELS` notes only:
   - `large-v3-turbo`: "рекомендую для смешанной диктовки; для чистой KZ — `large-v3` качественнее"
   - `large-v3`: "лучшее качество KZ; тяжело без GPU"
   - `medium` / `small`: clarify they degrade noticeably for KZ-dominant input
   - No changes to `Transcriber.transcribe()` logic.

3. **`src/soyle/ui/settings.py`** — Whisper tab:
   - Add a `QLabel` under the language dropdown, styled `color: #888; font-size: 11px;` (same as Cloud Sync's last-synced label)
   - Text: "Auto-detect (по умолчанию) лучше для смешанной KZ+RU+EN диктовки. Принудительный язык даст лучше recognition pure-monoязычной диктовки, но сломает code-switching."

4. **`tests/unit/test_dictionary.py`** — update `as_whisper_prompt()` assertions:
   - Adjust existing tests for the new format
   - **NEW** `test_as_whisper_prompt_returns_languages_only_when_empty`
   - **NEW** `test_as_whisper_prompt_languages_prefix_precedes_glossary`

### Prompts (5)

5. **`src/soyle/prompts/polish_v1.md`**:
   - Remove the `TODO(prompt-tuning)` HTML comment and the 3 draft KZ examples
   - Replace with realistic KZ-dominant patterns: tech speech, code review, daily conversation
   - Tighten Rule 4: explicit anti-pattern "If input is Kazakh, NEVER output Russian translation"

6. **`src/soyle/prompts/ai_prompt_v1.md`**, **`rewrite_v1.md`**, **`plain_text_v1.md`**, **`task_v1.md`**:
   - Audit each for KZ examples; add at least one realistic KZ-dominant example per file
   - Replicate the "no KZ→RU normalize" rule (with per-mode wording — `task` mode for example has structured output, so the rule applies to fields, not free text)
   - Preserve each mode's distinct purpose (task = structured 4-field output, plain_text = prose, etc.)

### Docs (1)

7. **`docs/MANUAL_TESTS.md`** — new "Code-switching и казахский" section:
   - A. Pure KZ recognition (Whisper layer) — 3-4 phrases with diacritics
   - B. KZ + English code-switching — agglutination patterns
   - C. KZ + Russian code-switching — Russian stems with KZ inflection
   - D. LLM polish preserves KZ across all 5 modes
   - E. Regression: pure-RU still works
   - F. Regression: pure-EN still works

## Data flow

```
[user speaks]
   ↓
[Transcriber.transcribe(audio)]
   ├── initial_prompt = self._initial_prompt
   │    Comes from DictionaryStore.as_whisper_prompt()    ← CHANGED
   │    Before: "Glossary: X, Y, Z."
   │    After:  "Languages: Kazakh, Russian, English. Glossary: X, Y, Z."
   └── language = config.whisper.language  (default None = auto-detect)
   ↓
[faster-whisper decode]
   - initial_prompt influences (a) language detection bias, (b) vocab biasing
   ↓
[PostProcess.polish(text, language)]
   - System prompt loaded from prompts/<mode>_v1.md       ← CHANGED
     (new KZ examples + explicit "never KZ→RU normalize" rule)
   ↓
[output → injector]
```

Two changes, two well-isolated touch points. No new code paths.

## Edge cases

| # | Scenario | Resolution |
|---|----------|------------|
| 1 | Empty dictionary | `as_whisper_prompt()` still returns the language hint. All users — even without custom terms — get the multilingual bias. |
| 2 | Large dictionary (≈200 terms) | `MAX_TERMS=200` already has headroom under Whisper's ~224-token `initial_prompt` budget. New prefix adds ~8 tokens; still in budget. |
| 3 | User forces `language=kk` | Whisper decodes as `kk`; the language hint in `initial_prompt` is consistent (no conflict, just additional vocab biasing). |
| 4 | User forces `language=en` or `ru` | Same — prefix includes both, no conflict. |
| 5 | PostProcess receives `language="kk"` + mixed text | Already correct: prompts treat language as a hint, not a command. New rule "never normalize KZ→RU" reinforces this. |
| 6 | Whisper returns exotic language code (e.g. `uz`, `ky`) | Already handled: prompts state "Other codes are language hints, not strict commands." |
| 7 | Existing user upgrades | Backward compatible: only the rendered string changes. No data migration. |
| 8 | LLM fails on new KZ examples | Existing fallback path: `_fallback(raw_text)` returns Whisper output as-is. No new failure modes. |

## Risks

- **R1: Pure-EN regression.** Adding `Kazakh, Russian` to the hint when a user speaks only English may slightly bias Whisper's auto-detect. Mitigation: Whisper's prior on English is strong; manual test plan section F is the explicit regression gate before merge.
- **R2: Initial_prompt token budget overflow.** A user with a maxed-out dictionary (200 terms) gets ~8 extra tokens. `MAX_TERMS=200` already had headroom. If a future iteration adds more prefix content, revisit the order (glossary first, language hint optional).
- **R3: LLM becomes more creative on new examples.** Denser real-world KZ examples might tempt the LLM to embellish. Mitigation: keep Rule 1 (preserve meaning) and the ±30% length discipline intact — these are existing safety nets.
- **R4: Settings UI overcrowding.** A hint label adds visual weight to the Whisper tab. Mitigation: minimal 1-2 lines, muted color (`#888`), same pattern as Cloud Sync's last-synced subtitle.

## Testing

### Unit

- Update `test_dictionary.py` assertions for new `as_whisper_prompt()` format
- Add 2 new tests covering empty-dict and prefix-ordering invariants
- All existing tests (245) must pass unchanged

### Manual

New section in `docs/MANUAL_TESTS.md`:

- A. Pure KZ recognition
- B. KZ + EN code-switching
- C. KZ + RU code-switching
- D. KZ preserved across all 5 LLM modes
- E. Regression: pure-RU
- F. Regression: pure-EN

Sections E and F are the explicit gate to run **before** merge — they guard against the R1 risk.

### Validation gates (CI + local)

1. `pytest tests/unit/` — ~248 / ~248 pass
2. `mypy src/` — clean
3. `ruff check src/` — clean
4. `python -c "from soyle.app import SoyleApp"` — imports OK
5. Manual sections E, F — pre-merge sanity check on dev machine

## Versioning of prompt files

`prompt_file: str = "polish_v1.md"` is the current config default. Two options were considered:

- **Edit-in-place in `_v1.md`** — chosen. Git history is the version; existing users get improvements at next launch automatically.
- **Create `_v2.md`, switch default** — rejected. Users with saved `prompt_file = "polish_v1.md"` in their config would stay on old prompts indefinitely.

## Rollback

Single PR with 10 files. `git revert <merge-commit>` is the entire rollback path:
- No data migrations to undo
- No new config fields to clean up
- No infrastructure changes

If a targeted regression appears, the change in `dictionary.py` (single function), `settings.py` (single label widget), or any individual prompt file can each be reverted in a follow-up PR without touching the others.

## Release strategy

1. Single PR, all 10 files atomic.
2. Pre-merge: run manual test plan sections E, F on dev machine; document results in PR description.
3. Update `CHANGELOG.md` "Unreleased" with a concrete improvement entry.
4. Merge → users automatically get the change on next launch (prompt files are loaded fresh by `PostProcess._load_prompts`; dictionary's `as_whisper_prompt` is called on every transcribe).
5. No telemetry / monitoring (none exists in the project). Feedback channel is informal.

## Out of scope (explicit non-goals, recap)

- Audio evaluation harness — deferred until real failure samples accumulate
- Whisper model replacement / fine-tuning
- Feature flag / phased rollout
- Kazakh-Latin script
- New config fields or new commands

## Open questions

- None at design time. All decisions either explicit in this doc or deferred (audio harness).

## Future iterations (out of scope here)

- **Audio eval harness**: once real KZ failure samples accumulate, build a small text-and-audio fixture set, gate releases on it.
- **Per-language model selection**: Settings could let the user pin different Whisper models for `kk` vs `ru` vs `en` regimes.
- **Smarter `initial_prompt` composition**: order terms by recent usage, weight KZ-suffixed terms higher, etc.
- **Telemetry opt-in**: aggregate `language` distribution from `info.language` over time to validate the multilingual-bias assumption with data.
