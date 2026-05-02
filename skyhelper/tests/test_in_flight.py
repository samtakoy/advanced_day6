"""Tests for /chat reject-if-busy lock (Session.in_flight).

Покрываем 4 инварианта:
1. Если in_flight=True — повторный /chat в ту же сессию отбивается 409.
2. На 409 история сессии НЕ загрязняется висячим user-сообщением.
3. После успешного запроса in_flight сброшен (release сработал).
4. На исключении из llm.chat in_flight всё равно сброшен (finally),
   иначе сессия залипает 409 навсегда.

Явный race-тест не пишем: в текущей архитектуре llm.chat синхронен и
блокирует event loop, поэтому два запроса физически не могут одновременно
дойти до check-and-set. Лок добавлен на будущее (миграция на
asyncio.to_thread / multi-worker), документировано в app.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from skyhelper.src import app as app_module
from skyhelper.src import sessions as sessions_module


@pytest.fixture
def client():
    # Изолируем словарь сессий между тестами.
    sessions_module._sessions.clear()
    return TestClient(app_module.app)


def _stub_llm_chat(reply: str = "ok"):
    """Заглушка llm.chat → (reply, added, calls, alerts)."""
    return (reply, [{"role": "assistant", "content": reply}], [], [])


def test_rejects_when_in_flight_already_set(client):
    sess = sessions_module.get_or_create("s1", user_id="U")
    sess.in_flight = True

    r = client.post("/chat", json={"session_id": "s1", "message": "hi"})

    assert r.status_code == 409
    assert "обрабатывается" in r.json()["detail"]


def test_409_does_not_pollute_history(client):
    sess = sessions_module.get_or_create("s1", user_id="U")
    sess.in_flight = True
    history_before = list(sess.history)

    client.post("/chat", json={"session_id": "s1", "message": "hi"})

    # ВАЖНО: на 409 ни user-сообщение, ни turn_count не меняются.
    # Иначе summarization потом увидит висячий user без assistant-ответа
    # и попадёт в кейсы из test_history.py (orphan tool / dangling tc).
    assert sess.history == history_before
    assert sess.turn_count == 0


def test_in_flight_reset_after_success(client):
    with patch("skyhelper.src.app.llm.chat", return_value=_stub_llm_chat()):
        r = client.post("/chat", json={"session_id": "s_ok", "message": "hi"})
    assert r.status_code == 200
    sess = sessions_module._sessions["s_ok"]
    assert sess.in_flight is False, "release не сработал — сессия залипнет"


def test_in_flight_reset_after_llm_exception(client):
    def boom(*a, **kw):
        raise RuntimeError("upstream down")

    with patch("skyhelper.src.app.llm.chat", side_effect=boom):
        # FastAPI вернёт 500, нам важен побочный эффект: in_flight снят.
        with pytest.raises(RuntimeError):
            client.post("/chat", json={"session_id": "s_err", "message": "hi"})

    sess = sessions_module._sessions["s_err"]
    assert sess.in_flight is False, (
        "finally не отработал на исключении — сессия залипнет 409 навсегда"
    )


def test_in_flight_is_set_during_llm_call(client):
    """Лок взведён ИМЕННО на время llm.chat (между set до вызова и release
    после). Если кто-то перенесёт `session.in_flight = True` ниже llm.chat,
    защита исчезнет — этот тест поймает."""
    captured: dict = {}

    def capture(session, **kw):
        captured["in_flight_during_call"] = session.in_flight
        return _stub_llm_chat()

    with patch("skyhelper.src.app.llm.chat", side_effect=capture):
        client.post("/chat", json={"session_id": "s_cap", "message": "hi"})

    assert captured["in_flight_during_call"] is True
