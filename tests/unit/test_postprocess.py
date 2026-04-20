"""Tests for PostProcess — OpenRouter client with fallback behavior."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from whisperflow.core.config import PostProcessConfig
from whisperflow.core.postprocess import PostProcess

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
