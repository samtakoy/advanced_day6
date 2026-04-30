"""Проксирование запросов в OpenAI / OpenRouter / Ollama.

Логика выбора провайдера:
  - OLLAMA_BASE_URL → Ollama (OpenAI-compatible API, http://localhost:11434/v1)
  - OPENROUTER_API_KEY → OpenRouter
  - Иначе → OpenAI напрямую (читает OPENAI_API_KEY)

Неизвестные поля из тела запроса передаются через extra_body — официальный
параметр OpenAI SDK для полей, которые SDK не валидирует сам.
Это позволяет проксировать произвольные расширения (reasoning, provider-routing
и т.д.) без whack-a-mole blacklist-а.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

load_dotenv()

_sync_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None


def _provider() -> str:
    if os.getenv("OLLAMA_BASE_URL"):
        return "ollama"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    return "openai"


def _client_kwargs() -> dict:
    p = _provider()
    if p == "ollama":
        return {
            "api_key": "ollama",  # Ollama ignores the key
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        }
    if p == "openrouter":
        return {
            "api_key": os.getenv("OPENROUTER_API_KEY"),
            "base_url": "https://openrouter.ai/api/v1",
        }
    return {}  # OpenAI direct: SDK picks up OPENAI_API_KEY from env


def get_client() -> OpenAI:
    global _sync_client
    if _sync_client is None:
        _sync_client = OpenAI(**_client_kwargs())
    return _sync_client


def get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(**_client_kwargs())
    return _async_client


def _normalize_model(model: str) -> str:
    """OpenRouter requires provider prefix. Ollama and OpenAI do not."""
    if _provider() == "openrouter" and "/" not in model:
        return f"openai/{model}"
    return model


def proxy_chat(
    messages: list[dict],
    model: str = "gpt-4o-mini",
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra_body: dict | None = None,
) -> object:
    """Отправить запрос в LLM, вернуть сырой ChatCompletion объект.

    extra_body пробрасывается через OpenAI SDK без валидации: tools, tool_choice,
    top_p, provider-routing, reasoning и любые другие поля.
    """
    kwargs: dict = {"model": _normalize_model(model), "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if extra_body:
        kwargs["extra_body"] = extra_body
    return get_client().chat.completions.create(**kwargs)


async def proxy_stream(
    messages: list[dict],
    model: str = "gpt-4o-mini",
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream_options: dict | None = None,
    extra_body: dict | None = None,
) -> AsyncIterator:
    """Async streaming запрос в LLM. Возвращает AsyncStream[ChatCompletionChunk].

    stream_options={"include_usage": True} — OpenRouter вернёт usage в последнем чанке.
    extra_body — произвольные поля, пробрасываются через SDK без валидации.
    """
    kwargs: dict = {
        "model": _normalize_model(model),
        "messages": messages,
        "stream": True,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if stream_options:
        kwargs["stream_options"] = stream_options
    if extra_body:
        kwargs["extra_body"] = extra_body
    return await get_async_client().chat.completions.create(**kwargs)
