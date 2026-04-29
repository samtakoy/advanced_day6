"""Проксирование запросов в OpenAI / OpenRouter.

Логика выбора провайдера:
  - Если задан OPENROUTER_API_KEY — OpenRouter (base_url openrouter.ai/api/v1)
  - Иначе — OpenAI напрямую (читает OPENAI_API_KEY)
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: OpenAI | None = None


def _provider() -> str:
    return "openrouter" if os.getenv("OPENROUTER_API_KEY") else "openai"


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if _provider() == "openrouter":
            _client = OpenAI(
                api_key=os.getenv("OPENROUTER_API_KEY"),
                base_url="https://openrouter.ai/api/v1",
            )
        else:
            _client = OpenAI()
    return _client


def proxy_chat(
    messages: list[dict],
    model: str = "gpt-4o-mini",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> object:
    """Отправить запрос в LLM, вернуть сырой ChatCompletion объект."""
    # OpenRouter требует префикс провайдера если не задан
    if _provider() == "openrouter" and "/" not in model:
        model = f"openai/{model}"

    kwargs: dict = {"model": model, "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    return get_client().chat.completions.create(**kwargs)
