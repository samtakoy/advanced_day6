"""Тонкая обёртка над OpenAI-совместимым API с поддержкой native tool-calling.

Slice 6: добавлены canary-токен (генерируется при импорте), рендер
системного промпта с {{canary}} placeholder, output guard на финальный
ассистент-текст (canary leak → refusal).

Auto-detect провайдера: если задан OPENROUTER_API_KEY — идём через OpenRouter,
иначе — прямо в OpenAI.
"""
from __future__ import annotations

import json
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

# Инструменты, которые возвращают retrieved-контент и подлежат output validation.
_CONTENT_TOOLS = {"read_flight_alert", "fetch_url", "fetch_fare_rules"}


def _find_last_content_tool(
    tool_calls_log: list[dict],
) -> tuple[str, str] | tuple[None, None]:
    """Вернуть (name, result_json) последнего content-retrieval tool call."""
    for entry in reversed(tool_calls_log):
        if entry["name"] in _CONTENT_TOOLS:
            return entry["name"], entry["result"]
    return None, None


def _get_visible_content(tool_name: str, result_json: str) -> str:
    """Извлечь и санитизировать контент из result тула.

    Всегда применяет sanitization независимо от session.sanitize —
    validator сравнивает ответ с ground-truth visible content,
    работает как backstop даже когда sanitize=off.
    """
    try:
        result = json.loads(result_json)
    except Exception:  # noqa: BLE001
        return ""
    raw = result.get("content", "")
    if not raw:
        return ""
    if tool_name in ("read_flight_alert", "fetch_url"):
        return guards.strip_hidden_html(raw)
    if tool_name == "fetch_fare_rules":
        return guards.strip_zero_width(raw)
    return raw


def _safe_fallback(tool_name: str) -> str:
    if tool_name == "read_flight_alert":
        return (
            "Не удалось безопасно суммировать уведомление. "
            "Подтверждённые детали: рейс задержан, новое время указано в уведомлении."
        )
    if tool_name == "fetch_fare_rules":
        return (
            "Не могу подтвердить эту информацию из документа. "
            "Обратитесь к официальному тарифному листу."
        )
    return "Страница не содержит подтверждения этой информации."


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

            # Guard 1: canary leak
            if guards.contains_canary(final_text, CANARY):
                guard_alerts.append("canary_leak")
                final_text = guards.CANARY_LEAK_REFUSAL
                assistant_dict["content"] = final_text

            # Guard 2: LLM-based output validation — backstop независимо от sanitize
            last_tool, last_result = _find_last_content_tool(tool_calls_log)
            if last_tool and last_result:
                visible = _get_visible_content(last_tool, last_result)
                violations = guards.validate_output(
                    final_text, visible, _get_client(), _resolve_model(),
                )
                if violations:
                    guard_alerts.append(f"output_validation_failed:{violations}")
                    final_text = _safe_fallback(last_tool)
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
