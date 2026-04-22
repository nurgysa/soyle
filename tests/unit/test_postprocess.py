"""Tests for PostProcess — OpenRouter client with fallback behavior."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from whisperflow.core.config import PostProcessConfig
from whisperflow.core.postprocess import (
    POPULAR_MODELS,
    ModelPreset,
    PostProcess,
    model_pricing,
)

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        },
    )


@pytest.fixture
def prompt_file(tmp_path: Path) -> Path:
    p = tmp_path / "prompt.md"
    p.write_text("You are a cleanup assistant. Just polish the text.", encoding="utf-8")
    return p


@pytest.fixture
def pp_config() -> PostProcessConfig:
    return PostProcessConfig(timeout_seconds=2.0, retries=2)


@pytest.mark.asyncio
@respx.mock
async def test_polish_success(prompt_file: Path, pp_config: PostProcessConfig) -> None:
    respx.post(API_URL).mock(return_value=_ok_response("Привет, как дела?"))

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    result = await pp.polish("эээ привет ну как дела", language="ru")

    assert result.text == "Привет, как дела?"
    assert result.fallback is False
    assert result.tokens_in == 10
    assert result.tokens_out == 8


@pytest.mark.asyncio
@respx.mock
async def test_polish_falls_back_on_401(prompt_file: Path, pp_config: PostProcessConfig) -> None:
    respx.post(API_URL).mock(return_value=httpx.Response(401, json={"error": "bad key"}))

    pp = PostProcess(config=pp_config, api_key="sk-bad", prompt_path=prompt_file)
    raw = "эээ привет"
    result = await pp.polish(raw, language="ru")

    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
@respx.mock
async def test_polish_retries_on_5xx(prompt_file: Path, pp_config: PostProcessConfig) -> None:
    route = respx.post(API_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            _ok_response("Clean text."),
        ]
    )

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    result = await pp.polish("um raw text", language="en")

    assert result.fallback is False
    assert result.text == "Clean text."
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_polish_falls_back_on_timeout(
    prompt_file: Path, pp_config: PostProcessConfig
) -> None:
    respx.post(API_URL).mock(side_effect=httpx.TimeoutException("slow"))

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    raw = "hi there"
    result = await pp.polish(raw, language="en")

    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
@respx.mock
async def test_polish_detects_refusal(
    prompt_file: Path, pp_config: PostProcessConfig
) -> None:
    respx.post(API_URL).mock(
        return_value=_ok_response("I can't help with that request.")
    )

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    raw = "hello test"
    result = await pp.polish(raw, language="en")

    # Refusal detection → fallback to raw
    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
@respx.mock
async def test_polish_detects_hallucination_length_mismatch(
    prompt_file: Path, pp_config: PostProcessConfig
) -> None:
    # LLM returned 5x longer text — probably hallucinated
    raw = "hi"
    long_reply = "Well actually it is very interesting that you said hi because there are many."
    respx.post(API_URL).mock(return_value=_ok_response(long_reply))

    pp = PostProcess(config=pp_config, api_key="sk-test", prompt_path=prompt_file)
    result = await pp.polish(raw, language="en")

    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
async def test_polish_fallback_without_api_key(
    prompt_file: Path, pp_config: PostProcessConfig
) -> None:
    pp = PostProcess(config=pp_config, api_key=None, prompt_path=prompt_file)
    raw = "some text"
    result = await pp.polish(raw, language="en")
    assert result.fallback is True
    assert result.text == raw


@pytest.mark.asyncio
@respx.mock
async def test_mode_polish_uses_polish_prompt(
    tmp_path: Path, pp_config: PostProcessConfig
) -> None:
    polish_path = tmp_path / "polish.md"
    polish_path.write_text("POLISH-INSTRUCTIONS", encoding="utf-8")
    rewrite_path = tmp_path / "rewrite.md"
    rewrite_path.write_text("REWRITE-INSTRUCTIONS", encoding="utf-8")

    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        seen["system"] = body["messages"][0]["content"]
        return _ok_response("cleaned")

    respx.post(API_URL).mock(side_effect=capture)

    pp_config.mode = "polish"
    pp = PostProcess(
        config=pp_config,
        api_key="sk-test",
        prompt_path=polish_path,
        rewrite_prompt_path=rewrite_path,
    )
    await pp.polish("raw text", language="en")
    assert "POLISH-INSTRUCTIONS" in seen["system"]
    assert "REWRITE-INSTRUCTIONS" not in seen["system"]


@pytest.mark.asyncio
@respx.mock
async def test_mode_rewrite_uses_rewrite_prompt(
    tmp_path: Path, pp_config: PostProcessConfig
) -> None:
    polish_path = tmp_path / "polish.md"
    polish_path.write_text("POLISH-INSTRUCTIONS", encoding="utf-8")
    rewrite_path = tmp_path / "rewrite.md"
    rewrite_path.write_text("REWRITE-INSTRUCTIONS", encoding="utf-8")

    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        seen["system"] = body["messages"][0]["content"]
        return _ok_response("rewritten")

    respx.post(API_URL).mock(side_effect=capture)

    pp_config.mode = "rewrite"
    pp = PostProcess(
        config=pp_config,
        api_key="sk-test",
        prompt_path=polish_path,
        rewrite_prompt_path=rewrite_path,
    )
    await pp.polish("raw text", language="en")
    assert "REWRITE-INSTRUCTIONS" in seen["system"]
    assert "POLISH-INSTRUCTIONS" not in seen["system"]


# ---- Model presets + pricing ----

def test_popular_models_is_curated_google_entries() -> None:
    # Curated list: Gemini 2.5 Flash Lite + Gemma 4 31B IT (both Google).
    assert len(POPULAR_MODELS) == 2
    ids = {p.model_id for p in POPULAR_MODELS}
    assert ids == {"google/gemini-2.5-flash-lite", "google/gemma-4-31b-it"}
    for preset in POPULAR_MODELS:
        assert isinstance(preset, ModelPreset)
        assert preset.model_id.startswith("google/")


def test_model_pricing_known_model() -> None:
    in_p, out_p = model_pricing("google/gemini-2.5-flash-lite")
    assert in_p == 0.10
    assert out_p == 0.40


def test_model_pricing_gemma_4_31b_it() -> None:
    in_p, out_p = model_pricing("google/gemma-4-31b-it")
    assert in_p == 0.10
    assert out_p == 0.30


def test_model_pricing_unknown_falls_back() -> None:
    in_p, out_p = model_pricing("unknown/model-xyz")
    # Falls back to Gemini 2.5 Flash Lite defaults.
    assert in_p == 0.10
    assert out_p == 0.40


def test_display_label_contains_id_label_and_prices() -> None:
    preset = ModelPreset("x/y", "My Model", price_in_per_m=1.0, price_out_per_m=2.5)
    label = preset.display_label
    assert "x/y" in label
    assert "My Model" in label
    assert "$1.00" in label
    assert "$2.50" in label


def test_estimate_cost_uses_selected_model() -> None:
    # Gemma 4 31B IT: 100/1M * 0.10 + 100/1M * 0.30 = 0.00004
    gemma_cost = PostProcess._estimate_cost(100, 100, "google/gemma-4-31b-it")
    assert gemma_cost == pytest.approx(0.00004)
    # Gemini Flash Lite: 100/1M * 0.10 + 100/1M * 0.40 = 0.00005
    cost = PostProcess._estimate_cost(100, 100, "google/gemini-2.5-flash-lite")
    assert cost == pytest.approx(0.00005)
