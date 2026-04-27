"""Тонкая обёртка над OpenAI-совместимым API. Slice 1: без тулов.

Auto-detect провайдера: если задан OPENROUTER_API_KEY — идём через OpenRouter,
иначе — прямо в OpenAI. Та же логика, что и в src/baseline/run_baseline.py.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"


def _provider() -> str:
    return "openrouter" if os.getenv("OPENROUTER_API_KEY") else "openai"


def _resolve_model() -> str:
    raw = os.getenv("SKYHELPER_MODEL", "gpt-4o-mini")
    if _provider() == "openrouter" and "/" not in raw:
        return f"openai/{raw}"
    return raw


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if _provider() == "openrouter":
            _client = OpenAI(
                api_key=os.getenv("OPENROUTER_API_KEY"),
                base_url="https://openrouter.ai/api/v1",
            )
        else:
            _client = OpenAI()  # читает OPENAI_API_KEY
    return _client


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def chat(history: list[dict]) -> str:
    """Отправить историю в LLM и получить ответ ассистента."""
    messages = [{"role": "system", "content": load_system_prompt()}] + history
    response = _get_client().chat.completions.create(
        model=_resolve_model(),
        messages=messages,
        temperature=0.3,
    )
    return response.choices[0].message.content or ""
