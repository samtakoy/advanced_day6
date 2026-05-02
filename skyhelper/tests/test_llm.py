"""Tests for llm.chat() — order and client-routing guarantees.

Проверяем три инварианта:
1. _maybe_summarize вызывается ДО build_messages (иначе summary устаревшее).
2. Без gateway: прямой клиент передаётся и в summarize, и в LLM-вызов.
3. С use_gateway=True: gateway-клиент передаётся и в summarize, и в LLM-вызов.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from skyhelper.src.llm import chat
from skyhelper.src.sessions import Session


def _make_session(*roles: str) -> Session:
    sess = Session(session_id="test")
    sess.history = [{"role": r, "content": f"msg{i}"} for i, r in enumerate(roles)]
    return sess


def _mock_client(reply: str = "ok") -> MagicMock:
    """Минимальный mock OpenAI-клиента: возвращает один текстовый ответ без tool_calls."""
    msg = MagicMock()
    msg.content = reply
    msg.tool_calls = None
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=msg)]
    )
    return client


def _enter_base_patches(stack: ExitStack, direct: MagicMock, gateway: MagicMock | None = None) -> None:
    stack.enter_context(patch("skyhelper.src.llm._get_client", return_value=direct))
    stack.enter_context(patch("skyhelper.src.llm.load_system_prompt", return_value="SYS"))
    stack.enter_context(patch("skyhelper.src.llm.tools.build_tool_schemas", return_value=[]))
    if gateway is not None:
        stack.enter_context(patch("skyhelper.src.llm._get_gateway_client", return_value=gateway))


class TestChatOrder:
    def test_summarize_before_build_messages(self):
        """build_messages должен видеть summary, обновлённое _maybe_summarize."""
        sess = _make_session("user", "assistant")
        call_order = []

        def fake_summarize(session, client):
            call_order.append("summarize")
            session.summary = "fresh_summary"

        def fake_build(system, summary, window):
            call_order.append(("build_messages", summary))
            return [{"role": "system", "content": system}]

        direct = _mock_client()
        with ExitStack() as stack:
            stack.enter_context(patch("skyhelper.src.llm._maybe_summarize", side_effect=fake_summarize))
            stack.enter_context(patch("skyhelper.src.llm.history_mod.build_messages", side_effect=fake_build))
            _enter_base_patches(stack, direct)
            chat(sess)

        assert call_order[0] == "summarize", "_maybe_summarize должен идти первым"
        assert call_order[1][0] == "build_messages", "build_messages должен идти вторым"
        assert call_order[1][1] == "fresh_summary", "build_messages должен видеть обновлённое summary"

    def test_direct_client_passed_to_summarize(self):
        """Без gateway: _maybe_summarize получает тот же прямой клиент что и LLM-вызов."""
        sess = _make_session("user")
        clients_seen = []

        def fake_summarize(session, client):
            clients_seen.append(client)

        direct = _mock_client()
        gateway = _mock_client()

        with ExitStack() as stack:
            stack.enter_context(patch("skyhelper.src.llm._maybe_summarize", side_effect=fake_summarize))
            stack.enter_context(patch("skyhelper.src.llm.history_mod.build_messages",
                                      return_value=[{"role": "system", "content": "SYS"}]))
            _enter_base_patches(stack, direct, gateway)
            chat(sess, use_gateway=False)

        assert clients_seen[0] is direct
        assert direct.chat.completions.create.called
        assert not gateway.chat.completions.create.called

    def test_gateway_client_passed_to_summarize(self):
        """С use_gateway=True: _maybe_summarize получает gateway-клиент, не прямой."""
        sess = _make_session("user")
        clients_seen = []

        def fake_summarize(session, client):
            clients_seen.append(client)

        direct = _mock_client()
        gateway = _mock_client()

        with ExitStack() as stack:
            stack.enter_context(patch("skyhelper.src.llm._maybe_summarize", side_effect=fake_summarize))
            stack.enter_context(patch("skyhelper.src.llm.history_mod.build_messages",
                                      return_value=[{"role": "system", "content": "SYS"}]))
            _enter_base_patches(stack, direct, gateway)
            chat(sess, use_gateway=True)

        assert clients_seen[0] is gateway
        assert gateway.chat.completions.create.called
        assert not direct.chat.completions.create.called


# ---------------------------------------------------------------------------
# Layer D: summarizer system prompt объявляет untrusted-поля
# ---------------------------------------------------------------------------

class TestSummarizerUntrustedPrompt:
    """Контрактные тесты: summarizer получает промпт с перечислением untrusted-полей."""

    def _capture_summarizer_system(self, existing_summary: str = "") -> str:
        """Запустить _call_summarizer с мок-клиентом, вернуть system-промпт."""
        from skyhelper.src.llm import _call_summarizer

        mock_client = _mock_client("summary text")
        # signature: _call_summarizer(chunk, existing_summary, client, model)
        _call_summarizer([], existing_summary, mock_client, "gpt-4o-mini")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else [])
        system_msg = next(m for m in messages if m["role"] == "system")
        return system_msg["content"]

    def test_summarizer_prompt_mentions_passengers(self):
        system = self._capture_summarizer_system()
        assert "passengers" in system, "summarizer prompt должен называть поле passengers"

    def test_summarizer_prompt_mentions_arguments(self):
        system = self._capture_summarizer_system()
        assert "arguments" in system, "summarizer prompt должен называть tool_calls arguments"

    def test_summarizer_prompt_mentions_untrusted(self):
        system = self._capture_summarizer_system()
        assert "untrusted" in system.lower(), "summarizer prompt должен содержать слово untrusted"

    def test_summarizer_prompt_mentions_voucher_code(self):
        system = self._capture_summarizer_system()
        assert "voucher_code" in system, "summarizer prompt должен называть поле voucher_code"
