"""Тонкая обёртка над OpenAI-совместимым API с поддержкой native tool-calling.

Auto-detect провайдера: если задан OPENROUTER_API_KEY — идём через OpenRouter,
иначе — прямо в OpenAI. Та же логика, что и в src/baseline/run_baseline.py.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from skyhelper.src import tools
from skyhelper.src.sessions import Session

load_dotenv()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"

MAX_TOOL_LOOP_ITERATIONS = 10


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


def _assistant_msg_to_dict(msg) -> dict:
    """Сериализовать assistant-сообщение из OpenAI SDK в plain dict для session-истории."""
    result: dict = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return result


def chat(history: list[dict], session: Session) -> tuple[str, list[dict]]:
    """Отправить историю в LLM, выполнить все tool-calls, вернуть финальный ответ.

    Session передаётся в диспетчер тулов — нужен для propose_booking
    (запись pending_booking) и book_flight (HITL-policy check).

    Returns:
        (final_assistant_text, messages_added_this_turn)
    """
    messages = [{"role": "system", "content": load_system_prompt()}] + history
    tool_schemas = tools.build_tool_schemas()
    added_this_turn: list[dict] = []

    for _ in range(MAX_TOOL_LOOP_ITERATIONS):
        response = _get_client().chat.completions.create(
            model=_resolve_model(),
            messages=messages,
            tools=tool_schemas,
            temperature=0.3,
        )
        msg = response.choices[0].message
        assistant_dict = _assistant_msg_to_dict(msg)
        messages.append(assistant_dict)
        added_this_turn.append(assistant_dict)

        if not msg.tool_calls:
            return msg.content or "", added_this_turn

        for tool_call in msg.tool_calls:
            tool_result = tools.dispatch(
                tool_call.function.name,
                tool_call.function.arguments,
                session,
            )
            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result,
            }
            messages.append(tool_msg)
            added_this_turn.append(tool_msg)

    raise RuntimeError(
        f"Tool-call loop exceeded {MAX_TOOL_LOOP_ITERATIONS} iterations"
    )
