"""OpenRouter client for post-transcription polish."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from whisperflow.core.config import PostProcessConfig

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Curated list of Google-hosted OpenRouter models suitable for polish/rewrite.
# Prices are USD per 1 million tokens. Check openrouter.ai/models for up-to-date
# figures — we use these both for the UI label and for the cost estimate.


@dataclass(frozen=True)
class ModelPreset:
    model_id: str
    label: str
    price_in_per_m: float
    price_out_per_m: float

    @property
    def display_label(self) -> str:
        return (
            f"{self.model_id}  ·  {self.label}  ·  "
            f"${self.price_in_per_m:.2f} / ${self.price_out_per_m:.2f} per M"
        )


POPULAR_MODELS: tuple[ModelPreset, ...] = (
    ModelPreset(
        "google/gemma-4-31b:free",
        "Gemma 4 31B (free)",
        price_in_per_m=0.0,
        price_out_per_m=0.0,
    ),
    ModelPreset(
        "google/gemma-4-31b",
        "Gemma 4 31B",
        price_in_per_m=0.10,
        price_out_per_m=0.30,
    ),
    ModelPreset(
        "google/gemini-2.5-flash-lite-preview-09-2025",
        "Gemini 2.5 Flash Lite Preview 09-2025",
        price_in_per_m=0.10,
        price_out_per_m=0.40,
    ),
    ModelPreset(
        "google/gemini-2.5-flash-lite",
        "Gemini 2.5 Flash Lite",
        price_in_per_m=0.10,
        price_out_per_m=0.40,
    ),
)


def model_pricing(model_id: str) -> tuple[float, float]:
    """Return (input_price, output_price) per 1M tokens for the given model.

    Falls back to Gemini 2.5 Flash Lite pricing if the model isn't in our
    curated list. Callers (cost estimator) can treat this as a rough hint.
    """
    for preset in POPULAR_MODELS:
        if preset.model_id == model_id:
            return preset.price_in_per_m, preset.price_out_per_m
    return 0.10, 0.40
REFUSAL_MARKERS = (
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "я не могу помочь",
    "я не могу ответить",
    "as an ai",
)
MAX_LENGTH_RATIO = 3.0  # output char estimate / input char estimate must be ≤ this


@dataclass
class PolishResult:
    text: str
    fallback: bool
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


class PostProcess:
    """
    Async OpenRouter wrapper with retry + graceful fallback.

    - Never raises: on any failure, returns raw input with fallback=True.
    - 5xx → exponential backoff (0.5s, 1s, 2s).
    - 401/403 → immediate fallback.
    - 429 → retries with backoff.
    - Timeout/connect error → fallback after retries exhausted.
    - LLM output that looks refused or significantly longer than input → fallback.
    """

    def __init__(
        self,
        config: PostProcessConfig,
        api_key: str | None,
        prompt_path: Path,
        dictionary_hint: str = "",
        rewrite_prompt_path: Path | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._polish_prompt = (
            prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        )
        if rewrite_prompt_path is not None and rewrite_prompt_path.exists():
            self._rewrite_prompt = rewrite_prompt_path.read_text(encoding="utf-8")
        else:
            # Fallback: if rewrite prompt missing, rewrite mode behaves like polish.
            self._rewrite_prompt = self._polish_prompt
        self._dictionary_hint = dictionary_hint

    def set_dictionary_hint(self, hint: str) -> None:
        """Update the per-user glossary clause appended to the system prompt."""
        self._dictionary_hint = hint

    @property
    def _base_prompt(self) -> str:
        return self._rewrite_prompt if self._config.mode == "rewrite" else self._polish_prompt

    @property
    def _system_prompt(self) -> str:
        base = self._base_prompt
        if not self._dictionary_hint:
            return base
        return f"{base}\n\nADDITIONAL GLOSSARY:\n{self._dictionary_hint}"

    async def polish(self, raw_text: str, language: str) -> PolishResult:
        if not self._api_key or not raw_text.strip():
            reason = "no_api_key" if not self._api_key else "empty_input"
            return self._fallback(raw_text, reason=reason)

        user_payload = json.dumps(
            {"language": language, "text": raw_text}, ensure_ascii=False
        )

        body: dict[str, object] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "temperature": self._config.temperature,
            "max_tokens": min(len(raw_text) * 2, 1024),
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/nurgisa/whisperflow",
            "X-Title": "WhisperFlow",
        }

        start = time.monotonic()
        reply, tokens_in, tokens_out = await self._call_with_retry(body, headers)
        latency_ms = int((time.monotonic() - start) * 1000)

        if reply is None:
            return self._fallback(raw_text, reason="api_failed", latency_ms=latency_ms)

        cleaned = reply.strip()
        if self._looks_refused(cleaned) or self._too_long(raw_text, cleaned):
            return self._fallback(
                raw_text, reason="refused_or_hallucinated", latency_ms=latency_ms
            )

        cost_usd = self._estimate_cost(tokens_in, tokens_out, self._config.model)
        return PolishResult(
            text=cleaned,
            fallback=False,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )

    async def _call_with_retry(
        self, body: dict[str, object], headers: dict[str, str]
    ) -> tuple[str | None, int, int]:
        delays = [0.5, 1.0, 2.0]
        # `retries` is the number of retry attempts *after* the initial call,
        # so total attempts = retries + 1.
        attempts = max(1, self._config.retries + 1)

        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            for attempt in range(attempts):
                try:
                    resp = await client.post(API_URL, json=body, headers=headers)
                except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
                    if attempt + 1 < attempts:
                        await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                        continue
                    return None, 0, 0

                if resp.status_code == 200:
                    data = resp.json()
                    msg = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    return (
                        msg,
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                    )

                if resp.status_code in (401, 403):
                    return None, 0, 0

                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                        continue
                    return None, 0, 0

                return None, 0, 0

        return None, 0, 0

    @staticmethod
    def _looks_refused(text: str) -> bool:
        low = text.lower()
        return any(marker in low for marker in REFUSAL_MARKERS)

    @staticmethod
    def _too_long(raw: str, reply: str) -> bool:
        if len(raw) == 0:
            return False
        return len(reply) / max(len(raw), 1) > MAX_LENGTH_RATIO

    @staticmethod
    def _estimate_cost(tokens_in: int, tokens_out: int, model_id: str) -> float:
        """Cost in USD based on the selected model's per-million pricing."""
        in_per_m, out_per_m = model_pricing(model_id)
        return (tokens_in / 1_000_000) * in_per_m + (tokens_out / 1_000_000) * out_per_m

    @staticmethod
    def _fallback(raw: str, reason: str, latency_ms: int = 0) -> PolishResult:
        return PolishResult(
            text=raw,
            fallback=True,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=latency_ms,
        )
