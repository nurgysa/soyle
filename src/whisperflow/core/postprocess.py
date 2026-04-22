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

# Curated list of OpenRouter models suitable for short-text polish/rewrite.
# Each entry: (model_id, short human-readable label shown in the UI).
# Ordered roughly cheapest/fastest → most capable.
POPULAR_MODELS: tuple[tuple[str, str], ...] = (
    ("google/gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite — fastest, cheapest"),
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash — balanced"),
    ("openai/gpt-4.1-nano", "GPT-4.1 Nano — OpenAI small"),
    ("openai/gpt-4.1-mini", "GPT-4.1 Mini — OpenAI balanced"),
    ("anthropic/claude-haiku-4-5", "Claude Haiku 4.5 — Anthropic fast"),
    ("anthropic/claude-sonnet-4-5", "Claude Sonnet 4.5 — Anthropic quality"),
    ("deepseek/deepseek-chat", "DeepSeek Chat — cheap, strong"),
    ("mistralai/mistral-small-latest", "Mistral Small — European"),
    ("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B — open-weights"),
    ("qwen/qwen-2.5-72b-instruct", "Qwen 2.5 72B — multilingual"),
)
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

        cost_usd = self._estimate_cost(tokens_in, tokens_out)
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
    def _estimate_cost(tokens_in: int, tokens_out: int) -> float:
        # Gemini 2.5 Flash Lite: $0.10/M input, $0.40/M output
        return (tokens_in / 1_000_000) * 0.10 + (tokens_out / 1_000_000) * 0.40

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
