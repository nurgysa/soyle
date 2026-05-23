# KZ Detection Root Cause — Research Notes

**Date:** 2026-05-23
**Status:** Investigation complete, no fix applied (deferred by user decision).
**Author:** Investigation triggered during manual QA session, root cause confirmed via faster-whisper source code + web research.

---

## TL;DR

PR [`a0656c5 feat(dictionary): prepend Languages hint to Whisper initial_prompt`](https://github.com/nurgysa/soyle/commit/a0656c5) was an **architecturally misguided fix**. It added `"Languages: Kazakh, Russian, English."` to `initial_prompt` in `as_whisper_prompt()`, expecting it to bias Whisper's language auto-detection toward multilingual. **It does not, and cannot, do that** — `initial_prompt` is a decoder parameter, applied only **after** language detection has already chosen a language from mel-spectrogram features alone.

KZ-речь through `language=Auto-detect` therefore continues to be misdetected as `ar` / `az` / `ru`, and the user sees arabic / azerbaijani / russian text instead of Kazakh. On GTX 16xx hardware, the simple workaround (`language="kk"`) is blocked by a known CT2 hang.

This document captures the evidence so the next person (likely future-Claude or future-Nurgysa) doesn't repeat the same wrong assumption, and lays out the trade-off matrix for an actual fix when capacity allows.

---

## 1. Symptom

User dictates Kazakh into Söyle with `Settings → Whisper → Язык = Авто (определять автоматически)`. Visible output:

- Sometimes: arabic letters (e.g. `text_len=18`, `lang=ar`, `probability=0.22`)
- Sometimes: russian characters (transliteration of Kazakh phonetics)
- Sometimes: azerbaijani-like text (`lang=az`, `probability=0.35`)
- **Never**: actual Kazakh

Observed in `%APPDATA%/Soyle/logs/soyle.log` during manual QA session 2026-05-23 16:05–16:13 UTC.

Hardware: NVIDIA GTX 1650 Ti (Turing without Tensor Cores), 4 GB VRAM, Söyle running with `compute_type=int8`, `device=cuda` in Settings but `device=cpu` in logs (secondary bug — separate triage).

---

## 2. Root Cause — Hard Proof

### 2.1 faster-whisper source code

Söyle uses `WhisperModel.transcribe()` (not the batched `BatchedInferencePipeline`). All line references below are pinned to upstream tag **v1.2.1** — the version locked in `uv.lock` and installed in `.venv`.

**[`WhisperModel.transcribe()` lines 938–952](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L938-L952) — language detection happens FIRST, and takes ONLY mel-spectrogram features:**

```python
(
    language,
    language_probability,
    all_language_probs,
) = self.detect_language(
    features=features[..., seek:],          # ← ONLY mel features
    language_detection_segments=language_detection_segments,
    language_detection_threshold=language_detection_threshold,
)

self.logger.info(
    "Detected language '%s' with probability %.2f",
    language,
    language_probability,
)
```

**[Lines 963–968](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L963-L968) — the tokenizer is THEN built from the chosen language, locking the decoding alphabet:**

```python
tokenizer = Tokenizer(
    self.hf_tokenizer,
    self.model.is_multilingual,
    task=task,
    language=language,                       # ← locked to whatever detection chose
)
```

**[`WhisperModel.generate_segments()` lines 1143–1149](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L1143-L1149) — `initial_prompt` only enters here, encoded by the already-locked tokenizer:**

```python
if options.initial_prompt is not None:
    if isinstance(options.initial_prompt, str):
        initial_prompt = " " + options.initial_prompt.strip()
        initial_prompt_tokens = tokenizer.encode(initial_prompt)
        all_tokens.extend(initial_prompt_tokens)
    else:
        all_tokens.extend(options.initial_prompt)
```

The order is: **(1)** mel features → `detect_language()` picks a language; **(2)** `Tokenizer` is built using that language; **(3)** `initial_prompt` gets encoded via that tokenizer and prepended to the decoder's token stream. By the time `initial_prompt` enters the picture, the language decision is locked, AND the prompt text is being encoded into tokens of that language's alphabet. If detection picked `ar`, the phrase "Languages: Kazakh, Russian, English." becomes arabic-encoded tokens that further bias the decoder toward... still arabic.

### 2.2 Real-world log evidence

| Timestamp | audio | detected | probability | what user actually said |
|-----------|-------|----------|-------------|--------------------------|
| 16:05:31 | 5.6s | `ru` | (old log format, no prob field) | Kazakh phrase |
| 16:07:18 | 1.44s | **`ar`** | **0.22** | Kazakh phrase |
| 16:10:42 | 11.98s | `ru` | 0.98 | Kazakh phrase |
| 16:12:46 | 2.6s | **`az`** | **0.35** | Kazakh phrase |

User confirmed all four were Kazakh speech. Whisper detected `kk` **zero times**. Two out of four detections had probability below 0.4 (uncertain guess by Whisper's own metric).

### 2.3 Web research — KZ is a known weak spot for Whisper

Sources:
- [SYSTRAN/faster-whisper Issue #918 — auto-detect mixes multiple languages](https://github.com/SYSTRAN/faster-whisper/issues/918) — documented pattern of misclassification in multilingual auto-detect mode
- [HuggingFace akuzdeuov/whisper-base.kk](https://huggingface.co/akuzdeuov/whisper-base.kk) — community-fine-tuned KZ model that achieves **15.36% WER on KSC2**
- [arxiv 2408.05554 — Improving Whisper for Kazakh](https://arxiv.org/pdf/2408.05554) — documents that vanilla Whisper-large-v3 has **>40% WER on FLEURS Kazakh** and **>55% WER on KSC test set**, even with `language="kk"` forced

Translation: even when we DO manage to force `kk`, more than half the words are wrong. KZ is fundamentally low-resource for vanilla Whisper.

---

## 3. Why Our Previous Fix Did Not Work (Postmortem)

Commit message of `a0656c5`:

> feat(dictionary): prepend Languages hint to Whisper initial_prompt
>
> as_whisper_prompt() now always emits "Languages: Kazakh, Russian, English." — empty-dict users get multilingual bias too. When terms exist, the glossary clause is appended.

The intent ("multilingual bias") cannot be achieved through `initial_prompt` — that parameter has no path into the detection layer. The text gets encoded into tokens, those tokens are concatenated as "previous tokens" for the decoder, and the decoder then generates tokens **within the language the tokenizer was built for**. If the tokenizer was built for `ar`, the prompt about "Languages: Kazakh, Russian, English." becomes arabic-encoded tokens that further bias the decoder toward... still arabic.

The fix wasn't just ineffective — it may have been slightly **harmful**, because feeding multi-script hint text into a wrong-language tokenizer creates noisy decoder context. In practice the effect is likely negligible (12 tokens at most), but the architectural sin remains.

### Learning saved to user memory

`whisper_initial_prompt_scope.md` documents this trap so future sessions don't repeat the mistake.

---

## 4. Hardware Constraint Recap

GTX 16xx series (1650, 1650 Ti, 1660 Ti) is Turing architecture **without** Tensor Cores. CTranslate2 + faster-whisper checkpoints **hang** during segment iteration when given `language="kk"` on this hardware. Already documented in [`src/soyle/ui/settings.py:240-246`](../../src/soyle/ui/settings.py#L240).

This is why `kk` was intentionally removed from the language dropdown UI — not because the model can't speak Kazakh (large-v3 supports kk), but because forcing it deadlocks the GPU on common consumer hardware.

CPU + small model is the only safe fallback, but `small` has even worse KZ recognition than `large-v3`, so it's not a real workaround.

---

## 5. Mitigation Options — Trade-off Matrix

| # | Approach | Effort (CC) | KZ accuracy delta | Hardware risk (GTX 16xx) | Notes |
|---|---|---|---|---|---|
| **A** | Revert the misguided fix + add diagnostic logging | ~30 min | none | none | Remove `"Languages:"` prefix from `as_whisper_prompt()`. Log `info.all_language_probs` top-5 + warning when top-1 probability < 0.5. Update 2 tests we added in `test_dictionary.py`. Update `MANUAL_TESTS.md` KZ section to set realistic expectation. |
| **B** | A + re-expose `kk` in Settings dropdown with explicit hardware warning | ~1 hr | huge — IF user not on 16xx | user opt-in, takes the risk | Default stays Auto. `kk` option labeled "Казахский (может зависать на GTX 16xx)". |
| **C** | A + opt-in config flag for smart re-detect | ~3 hr | medium on non-16xx | flag default off → none | `whisper.kz_smart_detect = false`. When `true`: check `info.all_language_probs`, if `kk` in top-5 with probability > 0.10 → retry with `language="kk"`. Adds ~1× transcribe latency on retry path. |
| **D** | Dual-model strategy: large-v3 (multilingual) + `whisper-base.kk` (KZ-only) | ~1 day | **massive** — 55% → 15% WER | none — base model doesn't trigger 16xx hang | Load both. Routing: if detected lang ∈ {kk, az, tr, uz, ar with low conf} → switch transcribe to KZ-specific model. +290 MB disk, +VRAM if both loaded concurrently (can lazy-load). |
| **E** | Switch from CT2 to openai-whisper for KZ-mode only | ~1 week | good | none (different lib doesn't hang) | Major architectural shift, dual code paths. Slower than CT2. Likely overkill. |

---

## 6. Recommendation

**When capacity allows:**

1. **First PR (small)**: Option **A** — honest fix. Removes the architecturally wrong code, adds diagnostic logging, sets realistic expectations in docs. Closes the misconception, doesn't promise anything.

2. **Second PR (medium-large)**: Option **D** — dual-model. This is the real fix. WER 55% → 15% on Kazakh is the difference between "unusable" and "actually works". Worth the extra 290 MB on disk for users who actually dictate Kazakh.

**Do NOT** ship Option B without A. Re-exposing `kk` while leaving the misguided "Languages:" prefix in place would compound the confusion: user picks `kk` from dropdown, app hangs on their 16xx, and the misleading hint label was telling them to trust auto-detect.

**Skip C entirely** unless D is too expensive. C is a half-measure — it still requires `language="kk"` to actually transcribe Kazakh, which means GTX 16xx users still hit the hang. The dual-model approach in D sidesteps the hardware quirk entirely by using a different, smaller, non-CT2 model for the KZ path.

---

## 7. Out of scope for this research

- **Fix implementation** — user explicitly chose "research only" for this session. Any PR per options A–E is future work.
- **Secondary bug**: `Settings.device=cuda` but `logs.device=cpu`. Noted, separate investigation needed (probably config not being read, or CUDA init silently falling back).
- **Cloud Sync exception** `'str' object has no attribute 'get'` (cloud_sync_unhandled at 16:04:58) — separate bug, also surfaced during this QA session.
- **Manual QA blocks B/C/D/E** — paused pending fix decision on this bug; pure-RU and pure-EN regression checks (E/F in MANUAL_TESTS) are still runnable since they don't depend on KZ recognition.

---

## 8. Sources

### Source code (upstream faster-whisper, pinned to v1.2.1)
- [`faster_whisper/transcribe.py:938-952` (WhisperModel.transcribe)](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L938-L952) — `detect_language()` takes only mel features
- [`faster_whisper/transcribe.py:963-968` (WhisperModel.transcribe)](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L963-L968) — `Tokenizer` built from chosen language, locking decoding alphabet
- [`faster_whisper/transcribe.py:1143-1149` (WhisperModel.generate_segments)](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L1143-L1149) — `initial_prompt` encoded via that already-locked tokenizer

### In-repo source (this repo)
- [`src/soyle/core/transcriber.py:206-213`](../../src/soyle/core/transcriber.py#L206) — how we call `model.transcribe()`
- [`src/soyle/core/dictionary.py:113-128`](../../src/soyle/core/dictionary.py#L113) — `as_whisper_prompt()` with the now-known-wrong prefix
- [`src/soyle/ui/settings.py:240-246`](../../src/soyle/ui/settings.py#L240) — original `kk` exclusion comment (still accurate)

### External
- [SYSTRAN/faster-whisper Issue #918 — Auto-detect mixes multiple languages](https://github.com/SYSTRAN/faster-whisper/issues/918)
- [SYSTRAN/faster-whisper Issue #1245 — Detect language and transcribe in separate steps](https://github.com/SYSTRAN/faster-whisper/issues/1245)
- [HuggingFace: akuzdeuov/whisper-base.kk](https://huggingface.co/akuzdeuov/whisper-base.kk) — fine-tuned KZ model
- [arxiv 2408.05554 — Improving Whisper's Recognition Performance for Under-Represented Language Kazakh](https://arxiv.org/pdf/2408.05554)
- [Whisper Discussion #2167 — Language Detection using large-v3](https://github.com/openai/whisper/discussions/2167)

### In-repo references
- PR [`a0656c5`](https://github.com/nurgysa/soyle/commit/a0656c5) — the misguided fix being postmortemed
- Spec: [`docs/superpowers/specs/2026-05-21-kz-code-switching-design.md`](../superpowers/specs/2026-05-21-kz-code-switching-design.md) — original (now-known-flawed) intent of the KZ work
- Plan: [`docs/superpowers/plans/2026-05-21-kz-code-switching-implementation.md`](../superpowers/plans/2026-05-21-kz-code-switching-implementation.md) — implementation that shipped
- Manual checklist: [`docs/MANUAL_TESTS.md`](../MANUAL_TESTS.md) — KZ A/B/C/E/F sections that surface this bug in QA
