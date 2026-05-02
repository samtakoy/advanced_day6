"""History windowing: determines what goes to the LLM vs. what stays in the audit trail.

session.history  — full audit trail, never trimmed.
session.summarized_count — index boundary: everything before it is already summarized.
session.summary  — rolling summary string, injected as a synthetic user/assistant pair.
"""
from __future__ import annotations

from skyhelper.src.sessions import Session

WINDOW_SIZE = 30        # max user/assistant messages in the live window (tool msgs free)
SUMMARIZE_CHUNK = 10    # user/assistant messages to summarize per summarization call


def _ua_count(messages: list[dict]) -> int:
    return sum(1 for m in messages if m["role"] in ("user", "assistant"))


def get_live_window(session: Session) -> list[dict]:
    """Messages not yet summarized — these are sent to the LLM."""
    return session.history[session.summarized_count:]


def needs_summarization(session: Session) -> bool:
    return _ua_count(get_live_window(session)) >= WINDOW_SIZE


def pop_chunk(session: Session) -> list[dict]:
    """Extract the oldest SUMMARIZE_CHUNK user/assistant messages (plus their tool messages)
    from the live window and advance summarized_count. Returns the extracted slice.

    Граница чанка должна попадать только в "безопасную" точку — туда, где нет
    незакрытых tool_call_id. Иначе либо live window начнётся с осиротевшего
    tool-сообщения (граница после assistant(tool_calls), tool-ответ позже),
    либо саммари съест assistant(tool_calls), у которого ответ ещё в полёте
    (медленный тул, конкурентная запись истории) — и пришедший позже tool
    станет осиротевшим.

    Стратегия: идём вперёд, запоминаем последний safe-индекс (pending пуст);
    после набора SUMMARIZE_CHUNK UA продолжаем тянуть, пока pending не
    закроется или история не кончится; если до конца истории pending так и
    не закрылся (dangling tool_calls) — откатываемся к последнему safe-индексу.
    """
    pending_tool_call_ids: set[str] = set()
    ua_seen = 0
    i = session.summarized_count
    last_safe_i = i

    def _absorb(msg: dict) -> None:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                pending_tool_call_ids.add(tc["id"])
        elif msg["role"] == "tool":
            pending_tool_call_ids.discard(msg.get("tool_call_id"))

    while i < len(session.history) and ua_seen < SUMMARIZE_CHUNK:
        msg = session.history[i]
        _absorb(msg)
        if msg["role"] in ("user", "assistant"):
            ua_seen += 1
        i += 1
        if not pending_tool_call_ids:
            last_safe_i = i

    while i < len(session.history) and pending_tool_call_ids:
        msg = session.history[i]
        _absorb(msg)
        i += 1
        if not pending_tool_call_ids:
            last_safe_i = i

    if pending_tool_call_ids:
        # Dangling tool_calls без tool-ответа в истории: откат к safe-границе,
        # чтобы assistant(tool_calls) остался в live window и встретился со
        # своим tool-ответом, когда тот наконец придёт.
        i = last_safe_i

    chunk = session.history[session.summarized_count:i]
    session.summarized_count = i
    return chunk


def build_messages(
    system_content: str,
    summary: str | None,
    live_window: list[dict],
) -> list[dict]:
    """Assemble the final messages list for the LLM.

    Structure:
      [system]
      [user: context marker] + [assistant: summary]  — only when summary exists
      *live_window
    """
    messages: list[dict] = [{"role": "system", "content": system_content}]
    if summary:
        messages.append({"role": "user", "content": "[Контекст предыдущего диалога]"})
        messages.append({"role": "assistant", "content": summary})
    messages.extend(live_window)
    return messages
