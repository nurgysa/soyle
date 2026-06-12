"""Routes transcription between a multilingual primary model and a
lazily-loaded KZ-specialised model, based on detection signals from
the primary.

See docs/superpowers/specs/2026-05-24-kz-dual-model-design.md for the
architecture and decisions log.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import structlog

from soyle.core.transcriber import Transcriber, TranscriptResult

_log = structlog.get_logger(__name__)

# Routing thresholds — hard-coded defaults. Promoted to config.toml only
# if real-world use shows per-user tuning is needed. See spec Section 10
# (Open questions) for the deferral reasoning.
# Includes non-Turkic ar/fa: Whisper empirically misdetects Kazakh as
# them (see docs/research/2026-05-23-kz-detection-root-cause.md).
_TURKIC_FAMILY_LANGUAGES: frozenset[str] = frozenset({"az", "tr", "uz", "ky", "ar", "fa"})
_TURKIC_LOW_CONF_THRESHOLD: float = 0.6
_KZ_TOP5_MIN_PROB: float = 0.10


class KzAwareTranscriber:
    """Routes transcription between a multilingual primary model and a
    lazily-loaded KZ-specialised model.

    Thread safety: this class relies on the project-wide invariant that
    exactly one _InferenceJob is active at a time (single QThread
    consumer of the recorder). If that invariant changes, add a
    threading.Lock around _ensure_kz_loaded() — without one, two
    concurrent KZ-routes would call the factory twice and leak a model.
    """

    def __init__(
        self,
        primary: Transcriber,
        kz_factory: Callable[[], Transcriber],
    ) -> None:
        self._primary = primary
        self._kz_factory = kz_factory
        self._kz: Transcriber | None = None
        self._kz_load_failed_once: bool = False
        self._failure_toast_callback: Callable[[str], None] | None = None

    # ---- Public API (mirrors Transcriber duck-type) ----

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> TranscriptResult:
        primary_result = self._primary.transcribe(audio, sample_rate)
        reason = self._route_reason(primary_result)
        if reason is None:
            _log.info(
                "route_to_primary",
                lang=primary_result.language,
                prob=primary_result.language_probability,
            )
            return primary_result
        kz = self._ensure_kz_loaded()
        if kz is None:
            _log.warning(
                "kz_unavailable_fallback",
                original_lang=primary_result.language,
            )
            return primary_result
        kz_result = kz.transcribe(audio, sample_rate)
        _log.info(
            "route_to_kz",
            primary_detected=primary_result.language,
            primary_prob=primary_result.language_probability,
            kz_chars=len(kz_result.raw_text),
            reason=reason,
        )
        return kz_result

    def set_initial_prompt(self, prompt: str) -> None:
        self._primary.set_initial_prompt(prompt)
        if self._kz is not None:
            self._kz.set_initial_prompt(prompt)

    def set_language(self, language: str | None) -> None:
        # KZ model is always language="kk" — only forward to primary.
        self._primary.set_language(language)

    def warm_up(self) -> None:
        # KZ model NOT warmed up here — lazy by design.
        self._primary.warm_up()

    @property
    def device(self) -> str:
        return self._primary.device

    # ---- Wiring (called once at construction time by app.py) ----

    def set_failure_toast_callback(self, cb: Callable[[str], None]) -> None:
        """Register a callback fired once per session if KZ load fails.

        THREADING CONTRACT: the callback is invoked synchronously from
        whatever thread calls transcribe() — in the app that is an
        _InferenceJob QRunnable worker, NOT the Qt main thread. The
        registrant must marshal to the UI thread itself (emit a Qt
        Signal — see the _inference_done pattern in app.py). Passing a
        direct UI call like tray.toast here would touch
        QSystemTrayIcon off the main thread (codex P2 on PR #45).
        """
        self._failure_toast_callback = cb

    # ---- Internal ----

    def _ensure_kz_loaded(self) -> Transcriber | None:
        if self._kz is not None:
            return self._kz
        if self._kz_load_failed_once:
            return None
        try:
            self._kz = self._kz_factory()
            self._kz.warm_up()
            _log.info("kz_model_loaded")
            return self._kz
        # Broad catch is intentional: load failure is a routine setup
        # problem (model not downloaded, disk full, corrupt file) handled
        # by fallback + one-time toast. Runtime transcribe() failures are
        # NOT caught here — they re-raise (spec Section 8 #1 vs #2).
        except Exception as exc:
            # factory may have assigned before warm_up raised — reset so
            # the next call does not short-circuit via `if self._kz is not None`.
            self._kz = None
            self._kz_load_failed_once = True
            _log.error("kz_model_load_failed", error=str(exc), exc_info=True)
            if self._failure_toast_callback is not None:
                self._failure_toast_callback(
                    "KZ recognition недоступен (модель не загрузилась). "
                    "Откат на основную модель — KZ распознавание ненадёжно. "
                    "Запустите: scripts/download_model.py --model kz"
                )
            return None

    def _route_reason(self, result: TranscriptResult) -> str | None:
        """Return which signal fired, or None if KZ routing is not needed.

        Return values: "kk" | "turkic_low_conf" | "kk_in_top5" | None.
        The literal is logged as ``reason`` on the route_to_kz event —
        groundwork for threshold-tuning decisions deferred in spec Section 10.
        """
        if result.language == "kk":
            return "kk"
        if (
            result.language in _TURKIC_FAMILY_LANGUAGES
            and result.language_probability < _TURKIC_LOW_CONF_THRESHOLD
        ):
            return "turkic_low_conf"
        if result.all_language_probs is not None:
            # all_language_probs is the FULL candidate list (~99 languages),
            # not pre-sliced — sort and take the actual top five before
            # applying the threshold, per the documented heuristic
            # (codex P2 on PR #45).
            top5 = sorted(result.all_language_probs, key=lambda x: -x[1])[:5]
            for cand_lang, cand_prob in top5:
                if cand_lang == "kk" and cand_prob >= _KZ_TOP5_MIN_PROB:
                    return "kk_in_top5"
        return None
