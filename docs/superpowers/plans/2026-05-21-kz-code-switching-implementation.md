# KZ Code-Switching Reinforcement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Söyle's Kazakh recognition + code-switching survive the full Whisper → LLM pipeline, without changing architecture or running an audio eval harness.

**Architecture:** Three light-touch reinforcement layers over the existing pipeline. (1) Bias Whisper's auto-detect toward multilingual by prepending a `"Languages: Kazakh, Russian, English."` hint into `initial_prompt`. (2) Rewrite all five LLM prompt files with realistic KZ-dominant examples and an explicit "never normalize KZ→RU" rule. (3) UX nudge in Settings telling users that auto-detect is correct for code-switchers (no new code paths).

**Tech Stack:** Python 3.12, faster-whisper, OpenRouter (Gemini), PySide6, pytest + mypy + ruff.

**Spec:** [`docs/superpowers/specs/2026-05-21-kz-code-switching-design.md`](../specs/2026-05-21-kz-code-switching-design.md)

**Files (10 total):**
- 4 code: `src/soyle/core/dictionary.py`, `src/soyle/core/transcriber.py`, `src/soyle/ui/settings.py`, `tests/unit/test_dictionary.py`
- 5 prompts: `src/soyle/prompts/{polish,ai_prompt,rewrite,plain_text,task}_v1.md`
- 1 doc: `docs/MANUAL_TESTS.md`

**Branch:** `claude/kz-codeswitching-spec` (spec already on this branch; implementation commits stack on top).

**Note on KZ phrases:** Example phrases below are best-effort by Claude. Native speakers should sanity-check during execution; flag any that sound unnatural and substitute equivalents that preserve the same demonstrated pattern (filler stripping, suffix preservation, code-switch retention).

---

## Task 1: Languages-hint in `DictionaryStore.as_whisper_prompt` (TDD)

**Files:**
- Modify: `src/soyle/core/dictionary.py:113-121` (`as_whisper_prompt`)
- Modify: `tests/unit/test_dictionary.py:17-21` (`test_empty_when_missing`)
- Modify: `tests/unit/test_dictionary.py:93-99` (`test_whisper_prompt_format`)
- Modify: `tests/unit/test_dictionary.py` (add two new tests at end)

- [ ] **Step 1: Update existing assertions to expect the new prefix**

In `tests/unit/test_dictionary.py`, replace `test_empty_when_missing`:

```python
def test_empty_when_missing(store: DictionaryStore) -> None:
    # No terms saved, but as_whisper_prompt still emits the Languages
    # hint — multilingual bias should reach Whisper even with empty glossary.
    assert store.load() == []
    assert store.as_whisper_prompt() == "Languages: Kazakh, Russian, English."
    assert store.as_llm_instruction() == ""
```

Replace `test_whisper_prompt_format`:

```python
def test_whisper_prompt_format(store: DictionaryStore) -> None:
    store.save(["Söyle", "OpenRouter", "Astana"])
    prompt = store.as_whisper_prompt()
    assert prompt.startswith("Languages: Kazakh, Russian, English.")
    assert "Glossary:" in prompt
    assert "Söyle" in prompt
    assert "OpenRouter" in prompt
    assert "Astana" in prompt
```

- [ ] **Step 2: Add two new tests at the bottom of `test_dictionary.py`**

Append before the final newline:

```python
def test_as_whisper_prompt_returns_languages_only_when_empty(
    store: DictionaryStore,
) -> None:
    """Empty dictionary still produces a language hint — biases Whisper
    auto-detect toward multilingual decoding even without custom terms."""
    assert store.load() == []
    assert store.as_whisper_prompt() == "Languages: Kazakh, Russian, English."


def test_as_whisper_prompt_languages_prefix_precedes_glossary(
    store: DictionaryStore,
) -> None:
    """The Languages hint must come BEFORE the glossary in the prompt.
    Whisper reads initial_prompt left-to-right; the language list anchors
    auto-detect before vocabulary biasing kicks in."""
    store.save(["Алматы", "deploy"])
    prompt = store.as_whisper_prompt()
    lang_idx = prompt.index("Languages:")
    gloss_idx = prompt.index("Glossary:")
    assert lang_idx < gloss_idx
```

- [ ] **Step 3: Run tests — verify they fail**

Run:
```
.venv/Scripts/pytest.exe tests/unit/test_dictionary.py -v -k "whisper_prompt or empty_when_missing or languages"
```

Expected: 4 failures (existing test assertions changed; new tests reference behavior not yet implemented).

- [ ] **Step 4: Implement the change in `dictionary.py`**

In `src/soyle/core/dictionary.py`, replace the `as_whisper_prompt` method (around lines 113-121):

```python
    def as_whisper_prompt(self) -> str:
        """Return a Whisper-friendly hint string with language + glossary.

        Always emits the "Languages: ..." prefix so auto-detect is biased
        toward multilingual decoding even when the user's glossary is
        empty. When terms exist, the glossary clause is appended for
        vocabulary biasing.

        Kept short so it fits within faster-whisper's ~224-token
        initial_prompt budget (8 prefix tokens + up to MAX_TERMS terms).
        """
        prefix = "Languages: Kazakh, Russian, English."
        terms = self.load()
        if not terms:
            return prefix
        return f"{prefix} Glossary: {', '.join(terms)}."
```

- [ ] **Step 5: Run tests — verify they pass**

Run:
```
.venv/Scripts/pytest.exe tests/unit/test_dictionary.py -v
```

Expected: all `test_dictionary.py` tests pass (the 4 modified/new + 18 existing = 22 passes).

- [ ] **Step 6: Run mypy + ruff on changed files**

Run:
```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/dictionary.py tests/unit/test_dictionary.py
```

Expected: both clean.

- [ ] **Step 7: Commit**

```
git add src/soyle/core/dictionary.py tests/unit/test_dictionary.py
git commit -m "$(cat <<'EOF'
feat(dictionary): prepend Languages hint to Whisper initial_prompt

as_whisper_prompt() now always emits "Languages: Kazakh, Russian,
English." — empty-dict users get multilingual bias too. When terms
exist, the glossary clause is appended. ~8 tokens of prefix sits well
within faster-whisper's ~224-token initial_prompt budget alongside
MAX_TERMS=200.

Codified by two new tests: empty-dict prefix and prefix-precedes-
glossary ordering invariant.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: WHISPER_MODELS notes — clarify KZ trade-off

**Files:**
- Modify: `src/soyle/core/transcriber.py:107-132` (`WHISPER_MODELS` tuple, `WhisperModelPreset.note` field on each)

No tests — this is dropdown-label text only, no behavior change.

- [ ] **Step 1: Read the current preset comment block to know the surrounding context**

Look at lines 107-132 of `src/soyle/core/transcriber.py`. The four presets are `large-v3-turbo`, `large-v3`, `medium`, `small`. The current notes are KZ-aware but ambiguous about the turbo-vs-v3 trade-off.

- [ ] **Step 2: Replace the WHISPER_MODELS tuple**

Replace the existing definition (lines 107-132) with:

```python
# Order is what the dropdown shows top-to-bottom. Keep the recommended
# default (large-v3-turbo) prominent — it's the best multilingual quality
# / speed trade-off for the typical KZ+RU+EN dictation user. For users
# whose dictation is predominantly Kazakh (especially pure-KZ utterances
# with diacritics Қ/Ң/Ө/Ү/Ұ/Һ/І), large-v3 noticeably outperforms turbo
# at the cost of ~3× decode time and ~2× VRAM. Notes target a Russian-
# speaking user picking between speed and recognition quality.
WHISPER_MODELS: tuple[WhisperModelPreset, ...] = (
    WhisperModelPreset(
        "large-v3-turbo",
        params="809M",
        note="рекомендую — ≈large-v3 по качеству для RU/EN, ~3× быстрее; KZ норм",
    ),
    WhisperModelPreset(
        "large-v3",
        params="1.55B",
        note="лучшее качество, особенно для KZ; тяжело без GPU",
    ),
    WhisperModelPreset(
        "medium",
        params="769M",
        note="компромисс — KZ заметно хуже, средне по скорости",
    ),
    WhisperModelPreset(
        "small",
        params="244M",
        note="быстро, KZ слабый — для смешанной диктовки не подходит",
    ),
)
```

- [ ] **Step 3: Verify imports + dropdown still work**

Run:
```
.venv/Scripts/python.exe -c "from soyle.core.transcriber import WHISPER_MODELS; [print(p.display_label) for p in WHISPER_MODELS]"
```

Expected: 4 lines printed, each containing model id + params + the updated note.

- [ ] **Step 4: Run full unit suite to confirm no test depended on exact note strings**

Run:
```
.venv/Scripts/pytest.exe tests/unit/ -q
```

Expected: same pass count as Task 1 (no regressions).

- [ ] **Step 5: Ruff + mypy**

Run:
```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/core/transcriber.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/core/transcriber.py
git commit -m "$(cat <<'EOF'
chore(transcriber): clarify WHISPER_MODELS notes for KZ users

Spell out the large-v3 vs large-v3-turbo trade-off in the dropdown
notes: turbo is fine for RU/EN-dominant users and "KZ норм", while
large-v3 is meaningfully better for KZ-heavy dictation at the cost
of 3× decode time. medium/small notes tightened to reflect their
KZ-degraded reality.

No behavior change — dropdown labels only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Settings UI — language dropdown hint label

**Files:**
- Modify: `src/soyle/ui/settings.py:247-253` (Whisper tab language section)

- [ ] **Step 1: Read the current language-dropdown block to confirm structure**

Lines 247-253 of `src/soyle/ui/settings.py`:

```python
        self._w_language = QComboBox()
        self._w_language.addItem("Авто (определять автоматически)", None)
        self._w_language.addItem("Русский", "ru")
        self._w_language.addItem("English", "en")
        idx = self._w_language.findData(self._cfg.whisper.language)
        self._w_language.setCurrentIndex(max(0, idx))
        layout.addRow("Язык:", self._w_language)
```

Note: `kk` is intentionally not in the dropdown (see the existing comment at lines 240-246 about GTX 16-series GPU hangs).

- [ ] **Step 2: Add the hint QLabel under the dropdown**

Replace the block above with:

```python
        self._w_language = QComboBox()
        self._w_language.addItem("Авто (определять автоматически)", None)
        self._w_language.addItem("Русский", "ru")
        self._w_language.addItem("English", "en")
        idx = self._w_language.findData(self._cfg.whisper.language)
        self._w_language.setCurrentIndex(max(0, idx))
        layout.addRow("Язык:", self._w_language)

        # Hint label — same muted styling as the Cloud Sync last-synced
        # subtitle. Auto-detect is the only viable path for KZ users
        # (kk is not in the dropdown by design — see comment above), and
        # forcing ru/en breaks code-switching for everyone else.
        self._w_language_hint = QLabel(
            "Auto-detect — рекомендуется для смешанной KZ+RU+EN речи. "
            "Принудительный выбор ru/en даёт лучше recognition "
            "строго-моноязычной диктовки, но ломает code-switching. "
            "Казахский всегда через Auto-detect (hardware-ограничение)."
        )
        self._w_language_hint.setStyleSheet("color: #888; font-size: 11px;")
        self._w_language_hint.setWordWrap(True)
        layout.addRow("", self._w_language_hint)
```

- [ ] **Step 3: Smoke-test imports and Qt construction**

Run:
```
.venv/Scripts/python.exe -c "from soyle.ui.settings import SettingsWindow; print('settings imports OK')"
```

Expected: `settings imports OK` printed, no Qt errors.

- [ ] **Step 4: Run full unit suite (settings has its own tests indirectly via floating_button etc.)**

Run:
```
.venv/Scripts/pytest.exe tests/unit/ -q
```

Expected: same pass count, no regressions.

- [ ] **Step 5: mypy + ruff**

Run:
```
.venv/Scripts/python.exe -m mypy src/
.venv/Scripts/ruff.exe check src/soyle/ui/settings.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

```
git add src/soyle/ui/settings.py
git commit -m "$(cat <<'EOF'
feat(settings): clarify language dropdown for code-switchers

Adds a muted hint label under the Whisper language dropdown explaining
auto-detect is the right choice for KZ+RU+EN mixed speech, that
forcing ru/en breaks code-switching, and that KZ must use auto-detect
due to the hardware constraint already documented in the surrounding
comment block (GTX 16-series CT2 hang).

No behavior change — UX guidance only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Rewrite `polish_v1.md` — KZ examples + tighten Rule 4

**Files:**
- Modify: `src/soyle/prompts/polish_v1.md` (lines 67-81 — the three draft KZ examples + the TODO comment block; also Rule 4 at lines 28-33)

- [ ] **Step 1: Read the file end-to-end to confirm current structure**

Open `src/soyle/prompts/polish_v1.md` and observe:
- Rules 1-8 (lines 9-46)
- Input/Output format spec (lines 48-54)
- Examples block (lines 56-84) with the `TODO(prompt-tuning)` HTML comment at lines 76-81 admitting the 3 KZ examples are drafts.

- [ ] **Step 2: Update Rule 4 to add the explicit anti-normalize anti-pattern**

Replace Rule 4 (lines 28-33 in the existing file) with:

```
4. Preserve code-switching across Kazakh, Russian, and English. If the speaker
   mixes languages within one sentence (e.g. "давай заdeployим", "маған keyboard
   керек", "бұл feature-ды pushting керек"), keep the mixing exactly. Do not
   translate either side. Do not add Kazakh suffixes to non-Kazakh stems unless
   the speaker did so. Do not strip Kazakh suffixes from non-Kazakh stems if the
   speaker added them (e.g. "deploy-тау керек" stays as written).

   ANTI-PATTERN: If the input is Kazakh, NEVER output Russian translation.
   "Бүгін кешке үйде боламын" must NOT become "Сегодня вечером буду дома."
   Same applies in reverse: KZ-dominant input with RU words must keep the
   RU words as RU, not retranslate them into KZ.
```

- [ ] **Step 3: Replace the three KZ examples + remove the TODO comment**

Replace lines 67-81 (the three KZ example blocks plus the `TODO(prompt-tuning)` HTML comment) with:

```
Input: {"language":"kk","text":"анау мынау бұл функцияда баг бар сонымен fix қылу керек ертеңге дейін"}
Output: Бұл функцияда баг бар, fix қылу керек ертеңге дейін.

Input: {"language":"kk","text":"ну сосын мен PR-ды open қылдым review жасап бересің ба"}
Output: Мен PR-ды open қылдым. Review жасап бересің бе?

Input: {"language":"kk","text":"бұл feature-ды staging-ке push етіп қойдым кеше"}
Output: Бұл feature-ды staging-ке push етіп қойдым кеше.
```

The replacement removes the HTML comment block entirely and substitutes three realistic KZ-dominant tech-speech examples that demonstrate: (a) filler stripping (`анау мынау`, `сонымен`, `ну сосын`), (b) KZ-suffix preservation on EN stems (`PR-ды`, `feature-ды`, `staging-ке`), (c) one example with no edits needed (model learns "don't fix what isn't broken").

- [ ] **Step 4: Sanity-load the prompt via PostProcess**

Run:
```
.venv/Scripts/python.exe -c "from soyle.core.postprocess import PostProcess; from soyle.core.config import PostProcessConfig; from pathlib import Path; pp = PostProcess(config=PostProcessConfig(), api_key=None, prompt_path=Path('src/soyle/prompts/polish_v1.md')); print('polish loaded, length:', len(pp._prompts['polish']))"
```

Expected: `polish loaded, length: <integer ≈ 2300-3000>`. No exceptions.

- [ ] **Step 5: Verify the TODO marker is gone**

Run:
```
.venv/Scripts/python.exe -c "import pathlib; assert 'TODO(prompt-tuning)' not in pathlib.Path('src/soyle/prompts/polish_v1.md').read_text(encoding='utf-8'); print('TODO marker removed')"
```

Expected: `TODO marker removed`.

- [ ] **Step 6: Run unit tests (no prompt-content assertions exist, so this is a safety net)**

Run:
```
.venv/Scripts/pytest.exe tests/unit/test_postprocess.py -q
```

Expected: all postprocess tests pass.

- [ ] **Step 7: Commit**

```
git add src/soyle/prompts/polish_v1.md
git commit -m "$(cat <<'EOF'
feat(prompts): rewrite polish KZ examples + tighten no-KZ-to-RU rule

Removes the TODO(prompt-tuning) marker and the three draft Kazakh
examples from polish_v1.md. New examples are realistic KZ-dominant
tech-speech patterns demonstrating filler stripping, KZ-suffix
preservation on English stems (PR-ды, feature-ды, staging-ке), and
one example with no changes needed (model learns when to leave alone).

Rule 4 gains an explicit anti-pattern: if input is Kazakh, NEVER
output Russian translation. Symmetric for KZ-dominant input with RU
words.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Audit `ai_prompt_v1.md` — add KZ example + tighten rule

**Files:**
- Modify: `src/soyle/prompts/ai_prompt_v1.md` (Rule 2 at lines 28-31; examples block at lines 67-91 — the TODO comment too)

- [ ] **Step 1: Tighten Rule 2 with the same anti-normalize anti-pattern**

Replace Rule 2 (current lines 28-31):

```
2. **Same language as input.** If the speaker spoke Russian, output Russian.
   Kazakh → Kazakh. English → English. Mixed → preserve the mixing exactly
   (e.g. "напиши function-ды Python-да" stays as written).

   ANTI-PATTERN: A Kazakh-dominant instruction must produce a Kazakh
   instruction. NEVER silently translate Kazakh to Russian when constructing
   the prompt. Mixed KZ+RU+EN instructions must stay mixed.
```

- [ ] **Step 2: Add a realistic KZ AI-prompt example and remove the TODO comment**

Replace lines 67-91 (the existing 3 EN/RU examples + the entire `TODO(prompt-tuning)` block) with:

```
EXAMPLES:

Input: {"language":"ru","text":"эээ ну я хочу чтобы ты написал функцию на питоне которая парсит csv ну и возвращает список словарей и ещё чтобы там был тайп хинт"}
Output: Напиши функцию на Python, которая парсит CSV и возвращает список словарей. Добавь type hints.

Input: {"language":"ru","text":"короче напиши мне промпт для клода чтобы он типа сделал code review одного pull request на гитхабе на русском"}
Output: Сделай code review этого pull request на GitHub. Ответ — на русском.

Input: {"language":"en","text":"um can you like explain how the react useeffect hook works i mean with examples and you know in simple terms"}
Output: Explain how the React useEffect hook works. Use simple terms and include code examples.

Input: {"language":"kk","text":"Claude-қа айтшы Python-да CSV-ды parse жасайтын функция жаз ну онда type hints болсын"}
Output: Python-да CSV-ды parse жасайтын функция жаз. Type hints қос.

Input: {"language":"kk","text":"осы файлды оқып шығып маған негізгі баг-тарды KZ-да жаз"}
Output: Осы файлды оқып шығып, негізгі баг-тарды KZ-да жаз.
```

The new KZ examples show: (a) instruction-mode conversion ("айтшы…жаз" → imperative "жаз"), (b) preserving English tokens (`CSV`, `Python`, `type hints`) with KZ suffixes intact (`-ды`, `-да`), (c) one example where the speaker explicitly demands KZ output ("KZ-да жаз") — the model must respect that, not silently default to RU.

- [ ] **Step 3: Sanity-load**

Run:
```
.venv/Scripts/python.exe -c "from pathlib import Path; t = Path('src/soyle/prompts/ai_prompt_v1.md').read_text(encoding='utf-8'); assert 'TODO(prompt-tuning)' not in t; assert 'KZ-да жаз' in t; print('ai_prompt OK')"
```

Expected: `ai_prompt OK`.

- [ ] **Step 4: Run postprocess unit tests**

Run:
```
.venv/Scripts/pytest.exe tests/unit/test_postprocess.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/soyle/prompts/ai_prompt_v1.md
git commit -m "$(cat <<'EOF'
feat(prompts): KZ examples + no-normalize rule for ai_prompt

Adds two realistic KZ-dominant AI-prompt examples to ai_prompt_v1.md:
imperative conversion with English token preservation (CSV/Python/
type hints with KZ -ды/-да suffixes), and an explicit "respond in KZ"
constraint that the model must respect. Rule 2 gains the anti-pattern
disallowing silent KZ→RU translation when constructing prompts.

TODO(prompt-tuning) marker removed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Audit `rewrite_v1.md` — strengthen KZ examples + tighten Rule 1

**Files:**
- Modify: `src/soyle/prompts/rewrite_v1.md` (Rule 1 at lines 18-21; examples + TODO at lines 83-97)

- [ ] **Step 1: Tighten Rule 1**

Replace Rule 1 (lines 18-21):

```
1. **Same language.** If the input is Russian, output Russian. If English,
   output English. If Kazakh, output Kazakh. If mixed, preserve the mixing
   naturally — keep each fragment in the language the speaker used. Never
   translate.

   ANTI-PATTERN: NEVER translate a Kazakh rewrite into Russian. If you
   reorder a KZ utterance for clarity, the rewritten version must remain
   in Kazakh — same vocabulary, just better structure.
```

- [ ] **Step 2: Replace the three KZ rewrite examples and remove the TODO comment**

Replace lines 83-97 (three KZ examples + the entire `TODO(prompt-tuning)` block) with:

```
Input: {"language":"kk","text":"анау мынау бүгін мен жұмыстан шықтым ну сосын досымды кездестірдім қазақша сөйлестік"}
Output: Бүгін жұмыстан шыққан соң досымды кездестірдім — қазақша сөйлестік.

Input: {"language":"kk","text":"маған механический keyboard керек ну такой shiny тұрсын столда жақсы"}
Output: Маған механический keyboard керек — столда жақсы тұратын shiny model.

Input: {"language":"kk","text":"ну сонымен ертең meeting боп жатыр ертеңге дейін deck-ті дайындау керек слайды біз talk through қыламыз"}
Output: Ертең meeting бар. Ертеңге дейін deck-ті дайындау керек — слайдтарды бірге talk through қыламыз.
```

The new examples demonstrate: (a) reordering preserves KZ-dominant flow + keeps EN/RU words in their original language (`механический`, `keyboard`, `meeting`, `deck`, `talk through`), (b) merging two fragments into one sentence without language collapse, (c) the third example explicitly stresses-tests the "rewrite" verb on a mixed KZ+EN string.

- [ ] **Step 3: Sanity-load**

Run:
```
.venv/Scripts/python.exe -c "from pathlib import Path; t = Path('src/soyle/prompts/rewrite_v1.md').read_text(encoding='utf-8'); assert 'TODO(prompt-tuning)' not in t; assert 'talk through қыламыз' in t; print('rewrite OK')"
```

Expected: `rewrite OK`.

- [ ] **Step 4: Run postprocess tests**

Run:
```
.venv/Scripts/pytest.exe tests/unit/test_postprocess.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/soyle/prompts/rewrite_v1.md
git commit -m "$(cat <<'EOF'
feat(prompts): strengthen rewrite KZ examples + tighten no-translate rule

Replaces the three draft KZ rewrite examples with realistic samples
demonstrating that reordering for clarity must preserve KZ-dominant
flow AND keep English/Russian fragments in their original language
(механический, keyboard, meeting, deck, talk through). Rule 1 gains
the anti-pattern banning silent KZ→RU rewrite translation.

TODO(prompt-tuning) marker removed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Audit `plain_text_v1.md` — KZ examples for prose mode

**Files:**
- Modify: `src/soyle/prompts/plain_text_v1.md` (Rule 1 at lines 22-23; examples + TODO at lines 72-95)

- [ ] **Step 1: Tighten Rule 1**

Replace Rule 1 (lines 22-23):

```
1. **Same language as input.** Russian → Russian. Kazakh → Kazakh. English →
   English. Mixed → preserve the mixing naturally. Never translate.

   ANTI-PATTERN: A Kazakh dictation must produce Kazakh prose, never
   Russian. Casual KZ chat-style messages stay KZ-casual; formal KZ
   document text stays KZ-formal. Never collapse mixed text into one
   language for "readability".
```

- [ ] **Step 2: Replace examples and remove the TODO comment**

Replace lines 72-95 (the existing 3 examples + the entire `TODO(prompt-tuning)` block) with:

```
EXAMPLES:

Input: {"language":"ru","text":"эээ ну привет коллеги короче я тут подумал что нам надо ну как бы пересмотреть планы на следующий квартал потому что ну рынок изменился сильно"}
Output: Привет, коллеги. Думаю, нам нужно пересмотреть планы на следующий квартал — рынок сильно изменился.

Input: {"language":"ru","text":"короче я сегодня типа на работе встретил андрея давно не виделись поговорили часик про новую работу его и про детей"}
Output: Сегодня на работе встретил Андрея — давно не виделись. Поговорили час про его новую работу и про детей.

Input: {"language":"en","text":"um so basically the meeting tomorrow is moved to three pm and you know i need everyone to bring like the q3 numbers"}
Output: The meeting tomorrow is moved to 3 PM. Please bring the Q3 numbers.

Input: {"language":"kk","text":"сәлем команда сосын біз бүгін стендапта айттық қой деплой staging-ке Сейфолла ну сосын testing қылып жатыр"}
Output: Сәлем, команда. Бүгін стендапта айттық — деплой staging-ке. Сейфолла testing қылып жатыр.

Input: {"language":"kk","text":"бұл хабарламаны Айгүлге де жібер ну және Серікке де керек болса"}
Output: Бұл хабарламаны Айгүлге де жібер; Серікке де керек болса жібер.
```

The new KZ examples demonstrate: (a) casual chat-message KZ that stays casual (Slack/Telegram tone), (b) merging fragmented KZ sentences with proper Kazakh-style punctuation (semicolon, em-dash), without translating English tokens (`staging`, `testing`).

- [ ] **Step 3: Sanity-load**

Run:
```
.venv/Scripts/python.exe -c "from pathlib import Path; t = Path('src/soyle/prompts/plain_text_v1.md').read_text(encoding='utf-8'); assert 'TODO(prompt-tuning)' not in t; assert 'Сәлем, команда' in t; print('plain_text OK')"
```

Expected: `plain_text OK`.

- [ ] **Step 4: Run tests**

```
.venv/Scripts/pytest.exe tests/unit/test_postprocess.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/soyle/prompts/plain_text_v1.md
git commit -m "$(cat <<'EOF'
feat(prompts): KZ prose examples + no-translate rule for plain_text

Two realistic KZ dictation-to-prose samples: a casual team-chat
message that stays casual, and a multi-sentence KZ fragment merged
with proper Kazakh-style punctuation. Both preserve English tokens
(staging, testing) verbatim. Rule 1 gains the explicit anti-pattern
forbidding "for readability" language collapse.

TODO(prompt-tuning) marker removed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Audit `task_v1.md` — KZ structured-task example + tighten Rule 1

**Files:**
- Modify: `src/soyle/prompts/task_v1.md` (Rule 1 at lines 23-25; examples + TODO at lines 126-151)

- [ ] **Step 1: Tighten Rule 1 (free-text fields stay in source language)**

Replace Rule 1 (lines 23-25):

```
1. **Same language for free-text fields.** "Задача" and "Описание" stay in
   the language(s) the speaker used. If the speech is mixed, preserve the
   mixing exactly. Never translate.

   ANTI-PATTERN: If the input was Kazakh, the "Задача" and "Описание"
   fields must contain Kazakh — NEVER silently translate them into
   Russian. The labels "Задача / Департамент / Приоритет / Описание"
   themselves are always Russian by spec (that's the tracker format),
   but the values they hold preserve the input's language.
```

- [ ] **Step 2: Add a KZ-dominant structured-task example, replace the TODO block**

Replace lines 126-151 (the last existing example + the TODO comment) with:

```
Input: {"language":"ru","text":"короче feature-ды staging-ке push қылып содан кейін деплой жасау керек на следующей неделе"}
Output:
Задача: Push feature-ды staging-ке и задеплоить

Департамент: Engineering

Приоритет: P1

Описание: Feature-ды staging-ке push қылып, содан кейін деплой жасау керек на следующей неделе.

Input: {"language":"kk","text":"шұғыл түрде production-да keep-alive-ды fix қылу керек юзерлердің сессиялары үзіліп жатыр Engineering команда"}
Output:
Задача: Fix keep-alive в production

Департамент: Engineering

Приоритет: P0

Описание: Юзерлердің сессиялары үзіліп жатыр production-да. Шұғыл түрде keep-alive-ды fix қылу керек.

Input: {"language":"kk","text":"жаңа лендинг үшін екі вариант дайындау керек дизайнерлермен талқылау керек жұмаға дейін маркетинг"}
Output:
Задача: Жаңа лендинг үшін екі вариант дайындау

Департамент: Маркетинг

Приоритет: P1

Описание: Жаңа лендинг үшін екі вариант дайындау. Дизайнерлермен талқылау керек жұмаға дейін.
```

The new KZ examples show: (a) KZ word "шұғыл" mapped to P0 (already in priority cues line 32), (b) KZ-dominant "Описание" stays KZ — labels stay RU, (c) priority and department inference work even when the cue word is Kazakh.

- [ ] **Step 3: Sanity-load**

Run:
```
.venv/Scripts/python.exe -c "from pathlib import Path; t = Path('src/soyle/prompts/task_v1.md').read_text(encoding='utf-8'); assert 'TODO(prompt-tuning)' not in t; assert 'Юзерлердің сессиялары' in t; print('task OK')"
```

Expected: `task OK`.

- [ ] **Step 4: Run tests**

```
.venv/Scripts/pytest.exe tests/unit/test_postprocess.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/soyle/prompts/task_v1.md
git commit -m "$(cat <<'EOF'
feat(prompts): KZ structured-task examples + no-translate rule for task

Two realistic KZ-dominant task examples: a production keep-alive
incident with шұғыл → P0 priority inference, and a marketing landing-
page task with Kazakh free-text fields. Rule 1 clarifies: "Задача"
and "Описание" stay in the input language; only the labels remain
Russian per tracker-format spec.

TODO(prompt-tuning) marker removed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: New "Code-switching и казахский" section in `MANUAL_TESTS.md`

**Files:**
- Modify: `docs/MANUAL_TESTS.md` (insert new section before existing "Stability" section)

- [ ] **Step 1: Insert the new section**

In `docs/MANUAL_TESTS.md`, immediately before the existing `## Cloud Sync (Phase 1)` heading (line ~58 — find it via grep), insert this new section:

```markdown
## Code-switching и казахский

Сценарии проверяют, что KZ-распознавание и KZ-сохранение работают
во всём пайплайне Whisper → LLM. Реальные аудио-фразы — лучше всего;
если нет, прогоняй текстовые варианты через Settings → LLM (mode = polish)
с подставленным `info.language` через debug-логирование.

### A. Pure KZ recognition (Whisper layer)

- [ ] Произнесите: "Бүгін кешке үйде боламын".
      Распознать должен: букву **Қ/Ң/Ө/Ү/Ұ/Һ/І** не теряя; никаких подстановок RU-фонетики.
- [ ] Произнесите: "Қазақстанда қаншама уақыт өмір сүрдің?"
      Должен сохранить вопросительную интонацию + KZ-буквы.
- [ ] Произнесите: "Алматыдан Астанаға поездбен жүрдім."
      Должен сохранить KZ-падежи (-дан ablative, -ға dative).

### B. KZ + English code-switching

- [ ] Произнесите: "Бұл feature-ды staging-ке push етеміз."
      Должен сохранить английские слова латиницей + KZ-суффиксы (-ды accusative, -ке dative).
- [ ] Произнесите: "Pull request жасадым, code review керек."
      Должен сохранить EN-имена существительные + KZ-глаголы.
- [ ] Произнесите: "GitHub-қа commit-ті push етіп жатырмын."
      Множественные EN-сущ + KZ-глаголы.

### C. KZ + Russian code-switching

- [ ] Произнесите: "Документке тапсырманы жазып қойдым."
      Должен сохранить RU-stem "документ" + KZ-падеж (-ке dative), не транскрибировать в KZ-фонетику.
- [ ] Произнесите: "Сосын совещаниеге барамын."
      RU-сущ "совещание" + KZ-падеж (-ге dative).

### D. LLM polish сохраняет KZ во всех 5 modes

Прогоните ОДИН и тот же KZ-доминантный input через каждый mode и проверьте,
что ни один не "нормализует" KZ → RU:

- [ ] Input: "анау мынау бұл функцияда баг бар сонымен fix қылу керек ертеңге дейін"
- [ ] **polish** → "Бұл функцияда баг бар, fix қылу керек ертеңге дейін." (filler-stripping, KZ stays KZ)
- [ ] **rewrite** → может реорганизовать, но остаётся KZ
- [ ] **ai_prompt** → должен превратить в KZ-инструкцию ("Fix қыл мына функцияны…")
- [ ] **plain_text** → KZ prose, не RU translation
- [ ] **task** → структурированный output, "Задача" и "Описание" в KZ

### E. Regression: pure-RU остался прежним

- [ ] Произнесите старую тестовую фразу: "Привет это тестовая фраза"
      Распознавание и polish должны быть так же хороши, как до изменений.
      (Это страховка от R1 — добавление KZ в initial_prompt не должно ухудшать pure-RU recognition.)

### F. Regression: pure-EN остался прежним

- [ ] Произнесите: "Hello world how are you doing today"
      Pure-EN recognition + polish без регрессий.
      (Если этот чек проседает — initial_prompt смещает auto-detect, нужно откатить
      `as_whisper_prompt()` к старому формату или поменять порядок Languages-списка.)

```

- [ ] **Step 2: Verify the section is in the right place**

Run:
```
.venv/Scripts/python.exe -c "import pathlib; t = pathlib.Path('docs/MANUAL_TESTS.md').read_text(encoding='utf-8'); a = t.index('Code-switching и казахский'); b = t.index('Cloud Sync (Phase 1)'); assert a < b, 'KZ section must precede Cloud Sync'; print('section order OK')"
```

Expected: `section order OK`.

- [ ] **Step 3: Commit**

```
git add docs/MANUAL_TESTS.md
git commit -m "$(cat <<'EOF'
docs(manual-tests): add Code-switching и казахский section

Six checklist sections (A-F) covering pure-KZ Whisper recognition,
KZ+EN and KZ+RU code-switching, KZ preservation across all 5 LLM
modes, plus explicit pure-RU and pure-EN regression guards. Section E
and F are the gates to run BEFORE merge — they catch the R1 risk
(KZ language hint biasing auto-detect away from pure-EN).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Final validation gates + push + open PR

**Files:** none directly — this is a verification + push task.

- [ ] **Step 1: Run the full unit suite**

```
.venv/Scripts/pytest.exe tests/unit/ -q
```

Expected: 247/247 pass (245 existing + 2 new in `test_dictionary.py`).

- [ ] **Step 2: Mypy clean across all source files**

```
.venv/Scripts/python.exe -m mypy src/
```

Expected: `Success: no issues found in 30 source files`.

- [ ] **Step 3: Ruff clean on the entire source tree**

```
.venv/Scripts/ruff.exe check src/ tests/
```

Expected: `All checks passed!`.

- [ ] **Step 4: Import smoke test**

```
.venv/Scripts/python.exe -c "from soyle.app import SoyleApp; from soyle.ui.settings import SettingsWindow; from soyle.core.dictionary import DictionaryStore; ds = DictionaryStore(); print('imports OK; sample whisper prompt:', repr(ds.as_whisper_prompt()))"
```

Expected: `imports OK; sample whisper prompt: 'Languages: Kazakh, Russian, English.'` (or similar — should at minimum start with `Languages:`).

- [ ] **Step 5: Run manual sections E + F locally (the pre-merge gate from spec)**

This is the explicit regression check from the spec for R1. Before pushing:
- Dictate "Привет это тестовая фраза" — verify Whisper still recognises pure-RU cleanly.
- Dictate "Hello world how are you doing today" — verify Whisper still recognises pure-EN cleanly.

If either regresses noticeably, STOP. Investigate before merging — likely root cause is that the `Languages:` prefix is biasing auto-detect too strongly. Mitigation options: re-order the hint (`English, Russian, Kazakh`), or make it conditional on dictionary content.

- [ ] **Step 6: Push the branch**

```
git push origin claude/kz-codeswitching-spec
```

Note: the branch already exists from the spec PR. This pushes the new commits on top.

- [ ] **Step 7: Open or update the PR**

If the spec PR (#22) is still open and unmerged, the new commits stack on top automatically — visible in the existing PR. Update the PR description to include the new commits.

If the spec PR was already merged separately, open a new PR:

```
gh pr create --head claude/kz-codeswitching-spec --base main \
  --title "feat(kz): code-switching reinforcement — KZ-first" \
  --body "$(cat <<'EOF'
## Summary
Implementation of the KZ-first code-switching spec at [docs/superpowers/specs/2026-05-21-kz-code-switching-design.md](docs/superpowers/specs/2026-05-21-kz-code-switching-design.md).

### Changes (10 files)
- 4 code: `dictionary.py` (Languages-hint prefix in initial_prompt), `transcriber.py` (WHISPER_MODELS notes), `settings.py` (language-dropdown hint label), `test_dictionary.py` (2 new tests + 2 updated assertions)
- 5 prompts: `polish`, `ai_prompt`, `rewrite`, `plain_text`, `task` — KZ examples replaced/added, "never KZ→RU normalize" anti-pattern added to each
- 1 doc: `MANUAL_TESTS.md` — new "Code-switching и казахский" section with A-F checklists

### Pre-merge validation
- [x] pytest 247/247 pass
- [x] mypy clean
- [x] ruff clean
- [x] imports OK
- [x] Manual section E (pure-RU regression) — passed locally
- [x] Manual section F (pure-EN regression) — passed locally

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for codex review + CI; address P1/P2 comments in a follow-up commit on the same branch**

Per the `codex_bot_feedback_pattern` memory: codex P2+ findings get a follow-up commit before the next plan task. For this plan there is no "next plan task" — the PR is the deliverable.

If codex finds nothing → user merges → branch deleted.

---

## Self-Review

After writing the plan above, I checked it against the spec.

**Spec coverage check:** every spec change has a task:

| Spec change | Task |
|-------------|------|
| `dictionary.py:as_whisper_prompt()` adds Languages prefix | Task 1 |
| `transcriber.py:WHISPER_MODELS` notes clarify KZ trade-off | Task 2 |
| `settings.py` language dropdown hint label | Task 3 |
| `tests/unit/test_dictionary.py` updated + 2 new tests | Task 1 (combined with code change for TDD cycle) |
| `polish_v1.md` rewrite | Task 4 |
| `ai_prompt_v1.md` audit | Task 5 |
| `rewrite_v1.md` audit | Task 6 |
| `plain_text_v1.md` audit | Task 7 |
| `task_v1.md` audit | Task 8 |
| `MANUAL_TESTS.md` new section | Task 9 |
| Pre-merge regression check (R1) | Task 10 Step 5 |
| PR open + review | Task 10 Step 7-8 |

✓ All 10 spec-defined files + the regression gate are mapped.

**Placeholder scan:** no TBD / TODO / fill-in-later patterns. All KZ phrases are concrete (best-effort, flagged at top for native-speaker sanity check during execution).

**Type / signature consistency:** `DictionaryStore.as_whisper_prompt() -> str` signature unchanged (only the return value's format changes). `WhisperModelPreset` schema unchanged. `SettingsWindow.__init__` signature unchanged (only adds a new private widget attribute `_w_language_hint`). All other files are prompts (no types) or docs.

✓ No inconsistencies found.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-21-kz-code-switching-implementation.md`.

Two execution options:

1. **Subagent-driven (recommended)** — fresh subagent per task, review between tasks. Best when the user wants asynchronous progress and explicit checkpoints.
2. **Inline execution** — execute tasks in the current session using `superpowers:executing-plans`. Faster, but the session context grows with each task.

User: which approach?
