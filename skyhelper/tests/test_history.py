"""Unit tests for history windowing logic (skyhelper.src.history).

Тестируем чистые функции без I/O. Отдельная группа — _maybe_summarize из llm.py
с замоканным _call_summarizer и _get_client.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from skyhelper.src import history as h
from skyhelper.src.sessions import Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(*roles: str) -> Session:
    sess = Session(session_id="test")
    sess.history = [{"role": r, "content": f"msg{i}"} for i, r in enumerate(roles)]
    return sess


def _ua_roles(n: int) -> list[str]:
    """n alternating user/assistant roles."""
    return ["user" if i % 2 == 0 else "assistant" for i in range(n)]


# ---------------------------------------------------------------------------
# get_live_window
# ---------------------------------------------------------------------------

class TestGetLiveWindow:
    def test_empty_session(self):
        sess = Session(session_id="t")
        assert h.get_live_window(sess) == []

    def test_full_history_no_offset(self):
        sess = _make_session("user", "assistant", "user")
        assert len(h.get_live_window(sess)) == 3

    def test_with_summarized_offset(self):
        sess = _make_session("user", "assistant", "user", "assistant")
        sess.summarized_count = 2
        window = h.get_live_window(sess)
        assert len(window) == 2
        assert window[0]["content"] == "msg2"

    def test_fully_summarized_is_empty(self):
        sess = _make_session("user", "assistant")
        sess.summarized_count = 2
        assert h.get_live_window(sess) == []


# ---------------------------------------------------------------------------
# needs_summarization
# ---------------------------------------------------------------------------

class TestNeedsSummarization:
    def test_false_when_empty(self):
        assert not h.needs_summarization(Session(session_id="t"))

    def test_false_one_below_threshold(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE - 1))
        assert not h.needs_summarization(sess)

    def test_true_at_threshold(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE))
        assert h.needs_summarization(sess)

    def test_true_above_threshold(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE + 5))
        assert h.needs_summarization(sess)

    def test_tool_messages_not_counted(self):
        # WINDOW_SIZE-1 u/a + 100 tool msgs — should NOT trigger
        roles = _ua_roles(h.WINDOW_SIZE - 1) + ["tool"] * 100
        sess = _make_session(*roles)
        assert not h.needs_summarization(sess)

    def test_tool_messages_do_not_block_trigger(self):
        # WINDOW_SIZE u/a + many tool msgs — SHOULD trigger
        roles = _ua_roles(h.WINDOW_SIZE) + ["tool"] * 50
        sess = _make_session(*roles)
        assert h.needs_summarization(sess)

    def test_respects_summarized_count(self):
        # 30 u/a messages but 20 already summarized → only 10 live → no trigger
        sess = _make_session(*_ua_roles(30))
        sess.summarized_count = 20
        assert not h.needs_summarization(sess)


# ---------------------------------------------------------------------------
# pop_chunk
# ---------------------------------------------------------------------------

class TestPopChunk:
    def test_advances_pointer_by_summarize_chunk(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE))
        chunk = h.pop_chunk(sess)
        ua_in_chunk = sum(1 for m in chunk if m["role"] in ("user", "assistant"))
        assert ua_in_chunk == h.SUMMARIZE_CHUNK
        assert sess.summarized_count == h.SUMMARIZE_CHUNK

    def test_includes_tool_messages_in_range(self):
        # user → tool → assistant: tool travels with its pair
        sess = Session(session_id="t")
        sess.history = [
            {"role": "user", "content": "q"},
            {"role": "tool", "content": "tool-result"},
            {"role": "assistant", "content": "a"},
        ]
        chunk = h.pop_chunk(sess)
        roles = [m["role"] for m in chunk]
        assert roles == ["user", "tool", "assistant"]
        assert sess.summarized_count == 3

    def test_stops_after_summarize_chunk_ua_messages(self):
        # 20 u/a messages — pop_chunk should stop after SUMMARIZE_CHUNK (10)
        sess = _make_session(*_ua_roles(20))
        h.pop_chunk(sess)
        remaining_ua = sum(
            1 for m in h.get_live_window(sess)
            if m["role"] in ("user", "assistant")
        )
        assert remaining_ua == 20 - h.SUMMARIZE_CHUNK

    def test_handles_history_shorter_than_chunk(self):
        sess = _make_session("user", "assistant")
        chunk = h.pop_chunk(sess)
        assert len(chunk) == 2
        assert sess.summarized_count == 2
        assert h.get_live_window(sess) == []

    def test_empty_history_returns_empty(self):
        sess = Session(session_id="t")
        chunk = h.pop_chunk(sess)
        assert chunk == []
        assert sess.summarized_count == 0

    def test_does_not_overlap_on_second_call(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE))
        chunk1 = h.pop_chunk(sess)
        chunk2 = h.pop_chunk(sess)
        contents1 = {m["content"] for m in chunk1}
        contents2 = {m["content"] for m in chunk2}
        assert contents1.isdisjoint(contents2)

    def test_does_not_orphan_tool_messages_at_chunk_boundary(self):
        # Если 10-я UA в чанке — assistant(tool_calls), его tool-ответ
        # обязан уехать в чанк вместе с ним. Иначе live window начнётся
        # с осиротевшего tool-сообщения, и OpenAI API отвергнет запрос
        # ("tool message must follow assistant with matching tool_call_id").
        sess = Session(session_id="t")
        history: list[dict] = []
        for i in range(4):
            history.append({"role": "user", "content": f"u{i}"})
            history.append({"role": "assistant", "content": f"a{i}"})
        history.append({"role": "user", "content": "u_call"})
        history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "foo", "arguments": "{}"},
            }],
        })
        history.append({"role": "tool", "tool_call_id": "call_1", "content": "ok"})
        history.append({"role": "assistant", "content": "final"})
        history.append({"role": "user", "content": "u_next"})
        history.append({"role": "assistant", "content": "a_next"})
        sess.history = history

        h.pop_chunk(sess)
        live = h.get_live_window(sess)
        live_call_ids = {
            tc["id"]
            for m in live
            if m.get("role") == "assistant"
            for tc in (m.get("tool_calls") or [])
        }
        orphans = [
            m for m in live
            if m.get("role") == "tool"
            and m.get("tool_call_id") not in live_call_ids
        ]
        assert not orphans, f"live window has orphan tool messages: {orphans}"

    def test_does_not_eat_dangling_assistant_tool_calls(self):
        # Race: тул долгий, пользователь успел набить 30 сообщений.
        # session.history оказывается с assistant(tool_calls), у которого
        # tool-ответа ещё нет. pop_chunk не должен жадно сожрать всю
        # историю до конца — иначе assistant(tool_calls) уезжает в саммари,
        # а когда tool-ответ наконец придёт и будет добавлен в конец
        # истории, он станет осиротевшим в live window.
        sess = Session(session_id="t")
        history: list[dict] = []
        for i in range(4):
            history.append({"role": "user", "content": f"u{i}"})
            history.append({"role": "assistant", "content": f"a{i}"})
        history.append({"role": "user", "content": "u_in_flight"})
        history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "DANGLING",
                "type": "function",
                "function": {"name": "slow_tool", "arguments": "{}"},
            }],
        })
        # tool-ответа нет: in-flight ещё работает.
        # А пользователь успел набить кучу сообщений.
        for i in range(20):
            history.append({"role": "user", "content": f"spam_{i}"})
        sess.history = history

        h.pop_chunk(sess)
        live = h.get_live_window(sess)

        # dangling assistant(tool_calls) должен ОСТАТЬСЯ в live window —
        # иначе пришедший позже tool-ответ окажется без своей пары.
        has_dangling_tc = any(
            m.get("role") == "assistant"
            and any(tc.get("id") == "DANGLING" for tc in (m.get("tool_calls") or []))
            for m in live
        )
        assert has_dangling_tc, (
            "pop_chunk съел dangling assistant(tool_calls): "
            "когда tool-ответ наконец придёт, он будет осиротевшим"
        )

    def test_does_not_orphan_multiple_parallel_tool_calls(self):
        # Несколько параллельных tool_calls в одном assistant-сообщении —
        # все соответствующие tool-ответы должны уехать с ним.
        sess = Session(session_id="t")
        history: list[dict] = []
        for i in range(4):
            history.append({"role": "user", "content": f"u{i}"})
            history.append({"role": "assistant", "content": f"a{i}"})
        history.append({"role": "user", "content": "u_call"})
        history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "foo", "arguments": "{}"}},
                {"id": "c2", "type": "function",
                 "function": {"name": "bar", "arguments": "{}"}},
            ],
        })
        history.append({"role": "tool", "tool_call_id": "c1", "content": "r1"})
        history.append({"role": "tool", "tool_call_id": "c2", "content": "r2"})
        history.append({"role": "assistant", "content": "final"})
        sess.history = history

        h.pop_chunk(sess)
        live = h.get_live_window(sess)
        live_call_ids = {
            tc["id"]
            for m in live
            if m.get("role") == "assistant"
            for tc in (m.get("tool_calls") or [])
        }
        orphans = [
            m for m in live
            if m.get("role") == "tool"
            and m.get("tool_call_id") not in live_call_ids
        ]
        assert not orphans, f"live window has orphan tool messages: {orphans}"


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_no_summary_structure(self):
        window = [{"role": "user", "content": "hello"}]
        msgs = h.build_messages("SYS", None, window)
        assert msgs == [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "hello"},
        ]

    def test_with_summary_injects_synthetic_pair(self):
        window = [{"role": "user", "content": "hello"}]
        msgs = h.build_messages("SYS", "ключевые факты", window)
        assert msgs[0] == {"role": "system", "content": "SYS"}
        assert msgs[1] == {"role": "user", "content": "[Контекст предыдущего диалога]"}
        assert msgs[2] == {"role": "assistant", "content": "ключевые факты"}
        assert msgs[3] == {"role": "user", "content": "hello"}
        assert len(msgs) == 4

    def test_system_always_first(self):
        msgs = h.build_messages("SYS", "summary", [{"role": "user", "content": "x"}])
        assert msgs[0]["role"] == "system"

    def test_empty_window_no_summary(self):
        msgs = h.build_messages("SYS", None, [])
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"

    def test_empty_window_with_summary(self):
        msgs = h.build_messages("SYS", "summary", [])
        assert len(msgs) == 3
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[2]["role"] == "assistant"

    def test_does_not_mutate_window(self):
        window = [{"role": "user", "content": "x"}]
        original = list(window)
        h.build_messages("SYS", "summary", window)
        assert window == original


# ---------------------------------------------------------------------------
# _maybe_summarize (llm.py) — mocked _call_summarizer + _get_client
# ---------------------------------------------------------------------------

from skyhelper.src.llm import _maybe_summarize  # noqa: E402


class TestMaybeSummarize:
    def _patched(self, return_value="саммари"):
        return (
            patch("skyhelper.src.llm._call_summarizer", return_value=return_value),
            patch("skyhelper.src.llm._get_client", return_value=None),
        )

    def test_no_op_below_threshold(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE - 1))
        with patch("skyhelper.src.llm._call_summarizer") as mock_summ:
            _maybe_summarize(sess, client=None)
            mock_summ.assert_not_called()
        assert sess.summary is None
        assert sess.summarized_count == 0

    def test_calls_summarizer_at_threshold(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE))
        with patch("skyhelper.src.llm._call_summarizer", return_value="факты") as mock_summ:
            _maybe_summarize(sess, client=None)
            mock_summ.assert_called_once()
        assert sess.summary == "факты"
        assert sess.summarized_count == h.SUMMARIZE_CHUNK

    def test_passes_existing_summary_to_summarizer(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE))
        sess.summary = "старое саммари"
        captured: dict = {}

        def fake(chunk, existing, client, model):
            captured["existing"] = existing
            return "новое саммари"

        with patch("skyhelper.src.llm._call_summarizer", side_effect=fake):
            _maybe_summarize(sess, client=None)

        assert captured["existing"] == "старое саммари"
        assert sess.summary == "новое саммари"

    def test_summary_updates_after_pointer_advance(self):
        sess = _make_session(*_ua_roles(h.WINDOW_SIZE))
        with patch("skyhelper.src.llm._call_summarizer", return_value="s"):
            _maybe_summarize(sess, client=None)

        remaining_ua = sum(
            1 for m in h.get_live_window(sess)
            if m["role"] in ("user", "assistant")
        )
        assert remaining_ua == h.WINDOW_SIZE - h.SUMMARIZE_CHUNK
