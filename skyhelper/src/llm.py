"""Тонкая обёртка над OpenAI-совместимым API с поддержкой native tool-calling.

Slice 6: добавлены canary-токен (генерируется при импорте), рендер
системного промпта с {{canary}} placeholder, output guard на финальный
ассистент-текст (canary leak → refusal).

Auto-detect провайдера: если задан OPENROUTER_API_KEY — идём через OpenRouter,
иначе — прямо в OpenAI.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from skyhelper.src import guards, tools
from skyhelper.src.sessions import Session

load_dotenv()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_PATHS = {
    "naive": PROMPTS_DIR / "system_naive.md",
    "hardened": PROMPTS_DIR / "system_hardened.md",
}
DEFAULT_PROMPT_MODE = "hardened"

MAX_TOOL_LOOP_ITERATIONS = 10

# Canary генерируется один раз при старте процесса. Output guard ищет
# точное вхождение в каждом финальном ответе. В naive-промпте canary
# не вшит — guard в этом режиме никогда не сработает (демо-режим: пусть
# промпт уплывает в ответ как есть).
CANARY = guards.generate_canary()


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


def load_system_prompt(mode: str = DEFAULT_PROMPT_MODE) -> str:
    path = SYSTEM_PROMPT_PATHS.get(mode, SYSTEM_PROMPT_PATHS[DEFAULT_PROMPT_MODE])
    template = path.read_text(encoding="utf-8")
    return (
        template
        .replace("{{canary}}", CANARY)
        .replace("{{today}}", date.today().isoformat())
    )


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


def chat(
    history: list[dict],
    session: Session,
    prompt_mode: str = DEFAULT_PROMPT_MODE,
) -> tuple[str, list[dict], list[dict], list[str]]:
    """Отправить историю в LLM, выполнить все tool-calls, вернуть финальный ответ.

    Returns:
        (final_assistant_text, messages_added_this_turn, tool_calls_log, guard_alerts)
        guard_alerts — список сработавших защит (например, ["canary_leak"]).
    """
    messages = [{"role": "system", "content": load_system_prompt(prompt_mode)}] + history
    tool_schemas = tools.build_tool_schemas()
    added_this_turn: list[dict] = []
    tool_calls_log: list[dict] = []
    guard_alerts: list[str] = []

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
            final_text = msg.content or ""
            # Output guard: canary leak → редактируем и уведомляем
            if guards.contains_canary(final_text, CANARY):
                guard_alerts.append("canary_leak")
                final_text = guards.CANARY_LEAK_REFUSAL
                # Перезаписываем и в истории, чтобы следующий турн не цитировал утечку.
                assistant_dict["content"] = final_text
            return final_text, added_this_turn, tool_calls_log, guard_alerts

        for tool_call in msg.tool_calls:
            tool_result = tools.dispatch(
                tool_call.function.name,
                tool_call.function.arguments,
                session,
            )
            tool_calls_log.append({
                "name": tool_call.function.name,
                "args": tool_call.function.arguments,
                "result": tool_result,
            })
            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result,
            }
            messages.append(tool_msg)
            added_this_turn.append(tool_msg)

    # Лимит итераций исчерпан — не падаем 500-й, а возвращаем вежливый
    # фоллбек. Защита от self-DoS-цикла (например, «найди на любые даты»),
    # плюс backstop против намеренного abuse.
    fallback = (
        "Не получилось собрать ответ за разумное число попыток. "
        "Уточните, пожалуйста, маршрут и конкретный месяц — "
        "я найду варианты по ним."
    )
    fallback_dict = {"role": "assistant", "content": fallback}
    added_this_turn.append(fallback_dict)
    guard_alerts.append("tool_loop_limit")
    return fallback, added_this_turn, tool_calls_log, guard_alerts
