# KZ Dual-Model Design

**Date:** 2026-05-24
**Status:** Spec — awaiting implementation plan
**Brainstormed via:** `superpowers:brainstorming` (2026-05-24 session)
**Implements:** Variant D from [`docs/research/2026-05-23-kz-detection-root-cause.md`](../../research/2026-05-23-kz-detection-root-cause.md)

---

## 1. Context

[PR #40](https://github.com/nurgysa/soyle/pull/40) (Variant A) shipped 2026-05-24: removed the architecturally-incorrect `Languages: Kazakh, Russian, English.` prefix from `as_whisper_prompt()`, added diagnostic logging (`language_candidates`, `low_confidence_detection`), updated `MANUAL_TESTS.md` with an honest "KZ broken" disclaimer.

That cleaned up the lie but didn't fix the underlying problem: vanilla `whisper-large-v3` has **>55% WER on Kazakh** even with `language="kk"` forced (arxiv 2408.05554), and on GTX 16xx hardware the `language="kk"` argument deadlocks CTranslate2 entirely. Auto-detect mistakenly classifies Kazakh speech as `ar`/`az`/`ru` with low confidence, leading to arabic letters, azerbaijani text, or russian transliteration appearing in the output instead of Kazakh.

This spec describes **Variant D**: a second, KZ-fine-tuned Whisper model (`akuzdeuov/whisper-base.kk`, **15.36% WER on KSC2**) loaded lazily alongside the primary multilingual model. A router decides which model to use per-utterance based on detection signals from the primary model.

---

## 2. Goals

- KZ-dominant dictation produces Kazakh-script output (not arabic / azerbaijani / russian) **most of the time** when the speech contains diacritics (Қ Ң Ө Ү Ұ Һ І).
- Zero behaviour change for the 95% RU/EN dictation case.
- Zero startup cost for users who never dictate Kazakh.
- All routing decisions automatic — no Settings toggle, no hotkey modifier, no user knobs.
- Works on the existing GTX 1650 Ti hardware constraint (4 GB VRAM, Turing without Tensor Cores).

## 3. Non-goals

- **Not** a fix for high-confidence Kazakh→Russian misdetection (e.g. phrases without diacritics like "Бугин кешке уйде" instead of "Бүгін кешке үйде" — this is an accepted limitation of the heuristic router).
- **Not** support for other Turkic languages (uz, ky, tk) — those keep using `large-v3`. If a future user needs them, the architecture supports adding more secondary models, but it's premature to build the framework now.
- **Not** a generic multi-model registry / plugin system. One secondary model, one routing rule.
- **Not** real-time language switching mid-utterance (Whisper auto-detect already handles within-language code-switching adequately).
- **Not** a UX for fixing the `device=cuda` in Settings vs `device=cpu` in logs mismatch — that's a separate bug in `_ensure_loaded()`.

---

## 4. Decisions log

These six decisions came out of the brainstorming session and shape every section below.

| # | Decision | Chosen | Alternatives considered |
|---|---|---|---|
| 1 | Routing philosophy | **Automatic always** | Opt-in toggle / Mode dropdown |
| 2 | Routing scope | **KZ only** | KZ + ex-USSR / Generic multi-model registry |
| 3 | KZ model loading | **Lazy persistent** | Eager-on-startup / Lazy-ephemeral (swap) |
| 4 | Routing trigger | **Heuristic** (kk OR turkic+low-conf OR kk-in-top-5) | Always-parallel / Manual hotkey override |
| 5 | KZ model failure UX | **Toast first time + log** | Silent fallback / Persistent Settings warning |
| 6 | Distribution | **Pre-download script** | Auto-download on demand / Bundled with installer |

---

## 5. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       app.py                            │
│                                                         │
│   self._transcriber: KzAwareTranscriber                 │
│                       │                                 │
│                       │  .transcribe(audio, sr)         │
│                       ▼                                 │
└───────────────────────┼─────────────────────────────────┘
                        │
       ┌────────────────┼────────────────┐
       │                                  │
       ▼                                  ▼
┌──────────────────┐              ┌──────────────────────┐
│   Transcriber    │              │  KZ Transcriber      │
│   (primary)      │              │  (lazy via factory)  │
│                  │              │                      │
│  large-v3-turbo  │              │  whisper-base.kk-ct2 │
│  ~1.5 GB int8    │              │  ~75 MB int8         │
│  multilingual    │              │  KZ-only, lang=kk    │
└──────────────────┘              └──────────────────────┘
       ▲                                  ▲
       │ always loaded                    │ lazy: created on
       │ via warm_up()                    │ first KZ-route
```

**Composition:** `KzAwareTranscriber(primary: Transcriber, kz_factory: Callable[[], Transcriber])`.

- `primary` is the existing `Transcriber`, injected from `app.py` (current wiring).
- `kz_factory` is a callable that constructs a second `Transcriber` instance. Called once on first KZ routing decision; the returned instance is cached.

**Routing flow** (full sequence in Section 7):
1. `KzAwareTranscriber.transcribe()` always calls `primary.transcribe()` first → returns `TranscriptResult` with detection info.
2. Router consults `info.language`, `info.language_probability`, `info.all_language_probs`.
3. If route_to_kz: lazy-load KZ model via factory, re-transcribe same audio with `language="kk"` forced, return KZ result.
4. Otherwise return primary result unchanged.

**What stays the same:**

- `Transcriber` class — zero changes to its existing methods (one additive `TranscriptResult` field extension — see Section 6).
- Public API `transcribe(audio, sample_rate) -> TranscriptResult` — identical.
- `_InferenceJob` — zero changes (uses Transcriber-protocol via duck typing).

---

## 6. Components

### 6.1 New class: `KzAwareTranscriber`

**File:** `src/soyle/core/kz_aware_transcriber.py` (new).

```python
from collections.abc import Callable

import numpy as np
import structlog

from soyle.core.transcriber import TranscriptResult, Transcriber

_log = structlog.get_logger(__name__)

# Routing thresholds — hard-coded defaults. Promoted to config.toml
# only if real-world use shows per-user tuning is needed.
_TURKIC_FAMILY_LANGUAGES = frozenset({"az", "tr", "uz", "ky", "ar", "fa"})
_TURKIC_LOW_CONF_THRESHOLD = 0.6
_KZ_TOP5_MIN_PROB = 0.10


class KzAwareTranscriber:
    """Routes transcription between a multilingual primary model and a
    lazily-loaded KZ-specialised model, based on detection signals from
    the primary.

    Thread safety: relies on the project-wide invariant that exactly one
    _InferenceJob is active at a time. If that invariant changes, add a
    threading.Lock around _ensure_kz_loaded().

    See docs/superpowers/specs/2026-05-24-kz-dual-model-design.md.
    """

    def __init__(
        self,
        primary: Transcriber,
        kz_factory: Callable[[], Transcriber],
    ) -> None:
        self._primary = primary
        self._kz_factory = kz_factory
        self._kz: Transcriber | None = None
        self._kz_load_failed_once: bool = False  # toast suppression
        self._failure_toast_callback: Callable[[str], None] | None = None

    # ---- Public API (mirrors Transcriber duck-type) ----

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> TranscriptResult:
        """Run the routing flow. See Section 7 for full sequence."""
        ...

    def set_initial_prompt(self, prompt: str) -> None:
        """Forward to both models (KZ only if already loaded)."""
        self._primary.set_initial_prompt(prompt)
        if self._kz is not None:
            self._kz.set_initial_prompt(prompt)

    def set_language(self, language: str | None) -> None:
        """Forward only to primary. KZ model is always language='kk'."""
        self._primary.set_language(language)

    def warm_up(self) -> None:
        """Warm up only primary. KZ is lazy by design."""
        self._primary.warm_up()

    @property
    def device(self) -> str:
        return self._primary.device

    # ---- Wiring (called by app.py during setup) ----

    def set_failure_toast_callback(self, cb: Callable[[str], None]) -> None:
        """Called once per session if KZ model fails to load."""
        self._failure_toast_callback = cb

    # ---- Internal ----

    def _ensure_kz_loaded(self) -> Transcriber | None:
        """Returns Transcriber on success, None on failure (fallback path)."""
        ...

    def _should_route_to_kz(self, result: TranscriptResult) -> bool:
        """Routing heuristic — three OR-combined signals."""
        ...
```

### 6.2 Changes to `Transcriber`

Additive only — `TranscriptResult` gains two fields:

```python
@dataclass
class TranscriptResult:
    raw_text: str
    language: str
    duration_ms: int
    segments: list[dict[str, Any]]
    language_probability: float = 0.0                                # NEW
    all_language_probs: list[tuple[str, float]] | None = None        # NEW
```

`Transcriber.transcribe()` populates these from `info.language_probability` and `info.all_language_probs`. Default values preserve backward compat for any existing callers / tests that construct `TranscriptResult` manually.

### 6.3 Changes to `app.py`

```python
# Before (current main):
self._transcriber = Transcriber(
    model=self._cfg.whisper.model,
    device=self._cfg.whisper.device,
    compute_type=self._cfg.whisper.compute_type,
    language=self._cfg.whisper.language,
    initial_prompt=self._dict_store.as_whisper_prompt(),
)

# After:
primary = Transcriber(
    model=self._cfg.whisper.model,
    device=self._cfg.whisper.device,
    compute_type=self._cfg.whisper.compute_type,
    language=self._cfg.whisper.language,
    initial_prompt=self._dict_store.as_whisper_prompt(),
)

def _kz_factory() -> Transcriber:
    # KZ model uses int8 always (smaller, faster, identical quality
    # for base-size at this precision). Language forced to "kk".
    return Transcriber(
        model="soyle/whisper-base-kk-ct2",  # local CT2 path (Section 6.4)
        device=self._cfg.whisper.device,
        compute_type="int8",
        language="kk",
        initial_prompt=self._dict_store.as_whisper_prompt(),
    )

self._transcriber = KzAwareTranscriber(
    primary=primary,
    kz_factory=_kz_factory,
)
self._transcriber.set_failure_toast_callback(self._tray.show_action_failed)
```

The variable name `self._transcriber` stays — its declared type widens to `Transcriber | KzAwareTranscriber` via duck typing on the shared interface (`transcribe`, `set_initial_prompt`, `set_language`, `warm_up`, `device`).

### 6.4 Changes to `scripts/download_model.py`

Add `--model kz` flag. New code path:

1. Download `akuzdeuov/whisper-base.kk` via `huggingface_hub.snapshot_download`.
2. Run `ct2-transformers-converter` (programmatic API or subprocess) to convert HF Transformers → CT2 int8.
3. Save result at `~/.cache/huggingface/hub/models--soyle--whisper-base-kk-ct2/snapshots/main/` so `WhisperModel("soyle/whisper-base-kk-ct2")` resolves locally without HF lookup.
4. Print resolved path for user reference.

`ct2-transformers-converter` is a new dependency. Added to `pyproject.toml` under a setup-only optional group so it's installed by `uv sync --extra setup` but not pulled into the runtime app bundle.

---

## 7. Data flow

Full sequence of one dictation with routing:

```
User holds RightAlt, speaks Kazakh
        │
        ▼
Recorder produces (audio: np.ndarray, sr: int)
        │
        ▼
_InferenceJob.run() → self._transcriber.transcribe(audio, sr)
        │
        ▼ ─────────────────────────── KzAwareTranscriber.transcribe()
┌──────────────────────────────────────────────────────────┐
│ 1. result = self._primary.transcribe(audio, sr)          │
│    Existing Transcriber:                                 │
│      - mel features → detect_language()                  │
│      - full transcribe with detected lang                │
│      - returns TranscriptResult with new fields          │
│        (language, language_probability, all_language_    │
│        probs) populated from info                        │
│                                                          │
│ 2. route = self._should_route_to_kz(result)              │
│    Three OR-combined signals:                            │
│      (a) result.language == "kk"                         │
│      (b) result.language in TURKIC_FAMILY                │
│          AND result.language_probability < 0.6           │
│      (c) "kk" in result.all_language_probs with          │
│          prob >= 0.10                                    │
│                                                          │
│ 3. if not route:                                         │
│        _log.info("route_to_primary",                     │
│                  lang=result.language)                   │
│        return result                                     │
│                                                          │
│ 4. kz = self._ensure_kz_loaded()                         │
│    - cached self._kz if already loaded                   │
│    - else: factory() → warm_up() → cache → log           │
│    - on exception: log + toast(once) + return None       │
│                                                          │
│ 5. if kz is None:                                        │
│        _log.warning("kz_unavailable_fallback",           │
│                     original_lang=result.language)       │
│        return result   # primary's output (bad KZ)       │
│                                                          │
│ 6. kz_result = kz.transcribe(audio, sr)                  │
│    - kz Transcriber has language="kk" forced             │
│    - any exception here PROPAGATES (Section 8 #2)        │
│                                                          │
│ 7. _log.info("route_to_kz",                              │
│              primary_detected=result.language,           │
│              primary_prob=result.language_probability,   │
│              kz_chars=len(kz_result.raw_text))           │
│    return kz_result                                      │
└──────────────────────────────────────────────────────────┘
        │
        ▼
result.raw_text → PostProcess (polish / rewrite / ...)
        │
        ▼
LLM output injected via Ctrl+V into target window
```

### Performance characteristics

| Scenario | Cost |
|---|---|
| RU/EN dictation (95% of cases) | 1× transcribe = baseline |
| KZ dictation, KZ model already loaded | 2× transcribe (~+1-3 sec on CPU) |
| **First** KZ dictation in session | 2× transcribe + KZ model load (~+3-5 sec, once) |
| KZ model load failed | 1× transcribe + toast (once) + degraded output |

### Notable edge cases

- **User forces `language="ru"` in Settings**: `primary.set_language("ru")` makes `result.language` always `"ru"`, router never fires. KZ model never loads. Correct behaviour: user explicitly opted out of multilingual.
- **`detected == kk` but KZ model load failed**: silent fallback to primary's `kk` transcription, which has poor quality (>55% WER) but at least uses correct alphabet.
- **`detected == az` with `prob == 0.7`** (above threshold): not routed, user gets azerbaijani text. Accepted limitation — heuristic can't catch high-confidence false positives without per-utterance always-parallel transcription.

---

## 8. Error handling

Six failure modes, with detection point and behaviour.

| # | Failure | Detection | Behaviour | User-visible |
|---|---|---|---|---|
| 1 | KZ model not on disk (user skipped `download_model.py --model kz`) | `_ensure_kz_loaded` catches `WhisperModel(...)` exception | Set `_kz_load_failed_once = True`; log `kz_model_load_failed`; toast once; return None | Toast: "KZ recognition недоступен. Запустите `download_model.py --model kz`" |
| 2 | KZ model loaded but runtime crash (OOM, corrupted file) | `kz.transcribe()` raises `CudaOOMError` / `ModelNotLoadedError` | **Re-raise** — do not swallow | Existing `_InferenceJob` error toast |
| 3 | Primary returns `all_language_probs == None` | `_should_route_to_kz` defensive guard | Skip signal (c); signals (a) and (b) still evaluated | None |
| 4 | `_failure_toast_callback is None` (test path) | None check before invocation | Log only, no toast | None (degraded mode for tests) |
| 5 | KZ-route adds 2× transcribe latency | Accepted cost | Log `route_to_kz_total_sec` for observability | Latency only |
| 6 | Two concurrent transcribe calls | Domain invariant (single _InferenceJob at a time) | Safe without lock; documented in class docstring | n/a |

**Design principle:** load-time failures get silent fallback + visible toast (routine setup problem). Runtime failures re-raise (could be a real bug or hardware issue — silencing would mask the problem). This matches the existing `cloud_sync` style: network errors silent, schema mismatch loud.

---

## 9. Testing strategy

### 9.1 Unit tests

**New file:** `tests/unit/test_kz_aware_transcriber.py`

Mock `Transcriber` and `kz_factory` to test routing decisions in isolation, without loading real Whisper models. Pattern:

```python
class FakeInfo:
    def __init__(self, language, language_probability, all_language_probs):
        self.language = language
        self.language_probability = language_probability
        self.all_language_probs = all_language_probs

class FakeTranscriber:
    """Records calls; returns canned TranscriptResult."""
    def __init__(self, result_factory):
        self.result_factory = result_factory
        self.transcribe_calls = []
        self.warm_up_calls = 0
        self.initial_prompts = []
        self.languages = []
    def transcribe(self, audio, sample_rate):
        self.transcribe_calls.append((audio.shape, sample_rate))
        return self.result_factory()
    def warm_up(self): self.warm_up_calls += 1
    def set_initial_prompt(self, p): self.initial_prompts.append(p)
    def set_language(self, l): self.languages.append(l)
    @property
    def device(self): return "cpu"
```

**Minimum test coverage (15 cases):**

1. `test_route_to_primary_when_ru_detected` — `result.language="ru"`, prob=0.98, no kk in top-5 → factory NEVER called.
2. `test_route_to_kz_when_kk_detected` — `result.language="kk"` → factory called once, kz.transcribe called, return kz result.
3. `test_route_to_kz_when_turkic_low_conf` — `result.language="az"`, prob=0.35 → factory called, kz used.
4. `test_no_route_when_turkic_high_conf` — `result.language="az"`, prob=0.85 → primary result returned, kz NOT loaded.
5. `test_route_when_kk_in_top5` — `result.language="ar"`, prob=0.4, `all_language_probs=[("ar",0.4),("kk",0.15),...]` → routed.
6. `test_no_route_when_kk_top5_prob_too_low` — `kk` present with prob=0.05 (< 0.10) → not routed.
7. `test_lazy_load_only_first_time` — two consecutive KZ-routes → factory called once, cached.
8. `test_load_failure_invokes_toast_once` — factory raises on first attempt; two KZ-route attempts → toast callback called once, log called twice.
9. `test_load_failure_returns_primary_fallback` — factory raises → wrapper returns primary's result.
10. `test_set_initial_prompt_forwards_to_both_when_kz_loaded` — after kz lazy-load, `set_initial_prompt("X")` → primary gets "X", kz gets "X".
11. `test_set_initial_prompt_doesnt_force_kz_load` — `set_initial_prompt` called before any route → factory NOT called.
12. `test_set_language_only_forwards_to_primary` — `set_language("ru")` → primary gets "ru", kz.set_language never called.
13. `test_warm_up_only_primary` — `warm_up()` → primary.warm_up called, kz NOT warmed.
14. `test_concurrent_state_safe_under_single_thread` — documents the domain invariant (not an actual threading test).
15. `test_all_language_probs_none_skips_top5_signal` — defensive check, `all_language_probs=None` → routing decision based only on signals (a) and (b).

### 9.2 Existing tests untouched

- `tests/unit/test_dictionary.py` — zero changes (we don't touch `as_whisper_prompt()`).
- `tests/unit/test_transcriber.py` (if exists) — zero changes (we don't touch `Transcriber`'s methods, only extend `TranscriptResult` dataclass).
- All 342 current tests must still pass.

### 9.3 Manual checklist updates

`docs/MANUAL_TESTS.md` section "Code-switching и казахский" — remove the current disclaimer (added in PR #40 as honest stopgap) and replace with:

> **После shipping этого PR:** Запустите `uv run python scripts/download_model.py --model kz` ОДИН раз. KZ recognition должно стать reliable для фраз с диакритиками (Қ Ң Ө Ү Ұ Һ І). Фразы без диакритик (фонетически близкие к RU) могут проваливаться — это accepted limitation heuristic routing.

Add new checklist entries:
- A.1 prereq: `download_model.py --model kz` completes без ошибок.
- A.2 first KZ dictation: log shows `kz_model_loaded` exactly once.
- A.3 second KZ dictation: NO new `kz_model_loaded` (cached).
- New section C: rename KZ-model directory to simulate load failure → toast appears once, dictation continues with primary fallback, second KZ-attempt does NOT show another toast.

### 9.4 Integration test (manual only)

Real KZ recognition accuracy is integration-territory. Unit tests prove **router decisions are correct given hypothetical info**. Real ML quality is measured manually on real hardware per `MANUAL_TESTS.md`. Right boundary.

### 9.5 CI implications

- `pytest tests/unit/ -q` expected: 342 (current) + ~15 (new) = ~357 passed.
- `mypy src/` strict — must pass (new class needs full annotations).
- `ruff check src/ tests/` — must pass.
- No new runtime dependencies. `ct2-transformers-converter` is setup-only via `[tool.uv]` optional group.

---

## 10. Open questions / future work

These intentionally deferred:

- **Per-user threshold tuning:** if the heuristic misses a lot for some users, promote `_TURKIC_LOW_CONF_THRESHOLD` and `_KZ_TOP5_MIN_PROB` to `config.toml`. Wait for real-world feedback before adding the config field.
- **High-confidence Kazakh→Russian misdetect** (phrases without diacritics): accepted limitation for v1. If users complain, options are (a) document "use diacritics" as workaround, (b) ship `always-parallel` mode behind a feature flag.
- **Other Turkic languages** (uz, ky, tk): no current user demand. Architecture extensible — `KzAwareTranscriber` could become `MultiLangAwareTranscriber` with a `Dict[str, Callable[[], Transcriber]]` factory map. Not building until needed.
- **Secondary bug — `device=cuda` Settings vs `device=cpu` logs**: separate investigation. Not addressed in this spec.
- **CT2 conversion failure handling in `download_model.py`**: if `ct2-transformers-converter` fails, the user gets a traceback. Could wrap with friendlier message — minor polish for later.

---

## 11. References

### Source code (upstream faster-whisper v1.2.1)
- [`faster_whisper/transcribe.py:938-952`](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L938-L952) — `detect_language()` API used by `Transcriber`.
- [`faster_whisper/transcribe.py:1143-1149`](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L1143-L1149) — where `initial_prompt` enters the decoder.

### In-repo
- [`docs/research/2026-05-23-kz-detection-root-cause.md`](../../research/2026-05-23-kz-detection-root-cause.md) — root cause investigation, Variant D mitigation matrix entry.
- [`src/soyle/core/transcriber.py`](../../../src/soyle/core/transcriber.py) — existing `Transcriber` class.
- [`src/soyle/app.py`](../../../src/soyle/app.py) — wiring point for `self._transcriber`.
- [`scripts/download_model.py`](../../../scripts/download_model.py) — pattern for `--model` flag.

### External
- [HuggingFace: akuzdeuov/whisper-base.kk](https://huggingface.co/akuzdeuov/whisper-base.kk) — the fine-tuned KZ model (15.36% WER on KSC2).
- [arxiv 2408.05554 — Improving Whisper for Kazakh](https://arxiv.org/pdf/2408.05554) — academic baseline showing vanilla Whisper >55% WER even with `language="kk"`.
- [SYSTRAN/faster-whisper Issue #918](https://github.com/SYSTRAN/faster-whisper/issues/918) — documented auto-detect failure pattern.

### PRs in this saga
- [PR #38, #39](https://github.com/nurgysa/soyle/pull/38) — research postmortem.
- [PR #40](https://github.com/nurgysa/soyle/pull/40) — Variant A: revert misguided fix + diagnostic logging.
- **Next:** implementation plan + PR for this spec.
