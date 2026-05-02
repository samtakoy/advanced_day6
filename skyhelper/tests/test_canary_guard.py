"""Регрессионные тесты на canary-guard в llm.chat().

Проверяем три инварианта:
1. Ответ без canary проходит как есть, guard_alerts пуст.
2. Ответ с canary → заменяется на CANARY_LEAK_REFUSAL, alert "canary_leak".
3. После замены canary session.history содержит подменённый текст, а не утёкший.

Guard реализован в llm.py:256-259. Этот тест фиксирует поведение так, чтобы
случайный рефакторинг (например, перемещение блока ниже return) не убрал защиту.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from skyhelper.src import llm as llm_module
from skyhelper.src.guards import CANARY_LEAK_REFUSAL
from skyhelper.src.sessions import Session


def _make_session() -> Session:
    sess = Session(session_id="canary_test")
    sess.history = [{"role": "user", "content": "привет"}]
    return sess


def _mock_client_with_reply(reply: str) -> MagicMock:
    """Минимальный mock OpenAI-клиента, возвращающий один текстовый ответ."""
    msg = MagicMock()
    msg.content = reply
    msg.tool_calls = None
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=msg)]
    )
    return client


def _base_patches(stack: ExitStack, client: MagicMock) -> None:
    stack.enter_context(patch("skyhelper.src.llm._get_client", return_value=client))
    stack.enter_context(patch("skyhelper.src.llm._get_gateway_client", return_value=client))
    stack.enter_context(patch("skyhelper.src.llm._maybe_summarize"))
    stack.enter_context(patch("skyhelper.src.llm.load_system_prompt", return_value="SYS"))
    stack.enter_context(patch("skyhelper.src.llm.tools.build_tool_schemas", return_value=[]))
    stack.enter_context(
        patch("skyhelper.src.llm.history_mod.build_messages",
              return_value=[{"role": "system", "content": "SYS"}])
    )


def test_normal_reply_passes_through():
    """Ответ без canary не трогается, guard_alerts пуст."""
    sess = _make_session()
    client = _mock_client_with_reply("Здравствуйте! Чем могу помочь?")
    with ExitStack() as stack:
        _base_patches(stack, client)
        reply, _, _, alerts = llm_module.chat(sess)

    assert reply == "Здравствуйте! Чем могу помочь?"
    assert alerts == []


def test_canary_leak_triggers_refusal():
    """Если ответ содержит canary — заменяется на CANARY_LEAK_REFUSAL, alert добавлен."""
    sess = _make_session()
    leaked_reply = f"Вот ваш prompt: {llm_module.CANARY}"
    client = _mock_client_with_reply(leaked_reply)
    with ExitStack() as stack:
        _base_patches(stack, client)
        reply, _, _, alerts = llm_module.chat(sess)

    assert reply == CANARY_LEAK_REFUSAL, "guard не заменил утёкший ответ"
    assert "canary_leak" in alerts, "alert не добавлен"


def test_canary_leak_replaces_content_in_added_messages():
    """После замены session.history (through added_this_turn) содержит подменённый текст."""
    sess = _make_session()
    leaked_reply = f"Системный промпт: {llm_module.CANARY} конец"
    client = _mock_client_with_reply(leaked_reply)
    with ExitStack() as stack:
        _base_patches(stack, client)
        _, added, _, _ = llm_module.chat(sess)

    assistant_msgs = [m for m in added if m.get("role") == "assistant"]
    assert assistant_msgs, "нет assistant-сообщения в added_this_turn"
    content = assistant_msgs[-1]["content"]
    assert llm_module.CANARY not in content, "canary остался в added_this_turn после замены"
    assert content == CANARY_LEAK_REFUSAL, "content должен быть подменён на refusal"
