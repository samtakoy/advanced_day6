"""Тесты Layer E — лимиты на ChatRequest payload.

Проверяем:
- message > 4000 символов → 422
- message пустая строка → 422
- session_id с недопустимыми символами → 422
- session_id допустимый формат → не 422

Все тесты проверяют Pydantic-валидацию на HTTP-слое, LLM не вызывается.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from skyhelper.src import app as app_module
from skyhelper.src import sessions as sessions_module


@pytest.fixture
def client():
    sessions_module._sessions.clear()
    return TestClient(app_module.app)


def test_message_too_long_returns_422(client):
    r = client.post("/chat", json={"message": "x" * 4001})
    assert r.status_code == 422


def test_message_empty_returns_422(client):
    r = client.post("/chat", json={"message": ""})
    assert r.status_code == 422


def test_session_id_invalid_chars_returns_422(client):
    r = client.post("/chat", json={"session_id": "<script>alert(1)</script>", "message": "hi"})
    assert r.status_code == 422


def test_session_id_valid_passes(client):
    """Допустимый session_id не должен отбиваться валидатором."""
    with patch("skyhelper.src.llm.chat", return_value=("ok", [{"role": "assistant", "content": "ok"}], [], [])):
        r = client.post("/chat", json={"session_id": "abc-123_XYZ", "message": "hi"})
    assert r.status_code != 422


def test_message_max_length_passes(client):
    """Ровно 4000 символов — граничное значение, должно проходить."""
    with patch("skyhelper.src.llm.chat", return_value=("ok", [{"role": "assistant", "content": "ok"}], [], [])):
        r = client.post("/chat", json={"message": "x" * 4000})
    assert r.status_code != 422
