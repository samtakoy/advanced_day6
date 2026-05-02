"""FastAPI-приложение SkyHelper.

Slice 7: добавлены Bearer-token auth и rate limit (per-token + per-userId)
через middleware. Auth выключен, если SKYHELPER_BEARER_TOKEN не задан
(dev-режим, лог-предупреждение при старте).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Literal

# Заморозить настройки безопасности: всегда hardened/sanitize=on/validate=on.
# Установить SKYHELPER_LOCK_SETTINGS=true чтобы включить.
LOCK_SETTINGS = os.getenv("SKYHELPER_LOCK_SETTINGS", "true").lower() == "true"

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from skyhelper.src import audit, llm, policies, security, sessions, tools

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

logger = logging.getLogger("skyhelper")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tools.maybe_seed_bookings()
    if not security.auth_enabled():
        logger.warning(
            "SKYHELPER_BEARER_TOKEN не задан — auth выключен (dev-режим). "
            "Перед публичной экспозицией обязательно задать токен."
        )
    yield


app = FastAPI(title="SkyHelper", version="0.7.0", lifespan=lifespan)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Rate limit + auth на /chat. Остальные маршруты (UI, healthz) — открытые.

    Порядок: сначала rate limit (по присланному токену, даже невалидному),
    потом auth. Иначе атакующий мог бы спамить невалидными токенами без
    счётчика и нагружать сервер auth-проверками.
    """
    if request.url.path != "/chat":
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    token_key = security.extract_token(auth_header)
    user_id = request.headers.get("X-User-Id", "ANON")

    if not security.token_limiter.check(token_key):
        return JSONResponse(
            {
                "detail": (
                    f"Rate limit exceeded (per token): "
                    f"{security.PER_TOKEN_LIMIT} requests / {security.WINDOW_SEC}s"
                )
            },
            status_code=429,
        )
    if not security.user_limiter.check(user_id):
        return JSONResponse(
            {
                "detail": (
                    f"Rate limit exceeded (per user): "
                    f"{security.PER_USER_LIMIT} requests / {security.WINDOW_SEC}s"
                )
            },
            status_code=429,
        )

    if err := security.check_bearer(auth_header):
        return JSONResponse({"detail": err}, status_code=401)

    return await call_next(request)


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=4000)
    prompt_mode: Literal["naive", "hardened"] = "hardened"
    sanitize: bool = True
    validate_output: bool = True
    use_gateway: bool = False  # если True — запросы идут через LLM Gateway


class ToolCallRecord(BaseModel):
    name: str
    args: str
    result: str


class ChatResponse(BaseModel):
    session_id: str
    user_id: str
    prompt_mode: str
    reply: str
    tool_calls: list[ToolCallRecord] = []
    guard_alerts: list[str] = []


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "chat.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "auth_enabled": security.auth_enabled(), "lock_settings": LOCK_SETTINGS}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> ChatResponse:
    user_id = x_user_id or "ANON"
    session = sessions.get_or_create(request.session_id, user_id=user_id)

    # Reject-if-busy. Должно быть САМОЙ ПЕРВОЙ операцией на сессии — раньше,
    # чем history.append, policies-чек, изменение настроек. Иначе при 409 в
    # session.history останется висячее user-сообщение без assistant-ответа,
    # что сломает summarization (см. test_history.py:test_does_not_eat_dangling
    # _assistant_tool_calls и связанные кейсы).
    #
    # Атомарность: check (`if session.in_flight`) и set (`session.in_flight =
    # True`) — две сихронные строки без await между ними. На single-thread
    # asyncio это атомарно. ВНИМАНИЕ: если кто-то впихнёт `await` между
    # ними — гонка вернётся. Для multi-worker раскладки этого мало:
    # `_sessions` — dict процесс-локальный, разные воркеры увидят разные
    # `Session` под одним id. В таком сетапе нужен общий лок (Redis SETNX
    # с TTL, PG advisory lock) и общее хранилище сессий.
    if session.in_flight:
        return JSONResponse(
            {"detail": "Предыдущее сообщение ещё обрабатывается. Попробуйте позже."},
            status_code=409,
        )
    session.in_flight = True
    try:
        if LOCK_SETTINGS:
            session.sanitize = True
            session.validate_output = True
            session.prompt_mode = "hardened"
        else:
            session.sanitize = request.sanitize
            session.validate_output = request.validate_output
            session.prompt_mode = request.prompt_mode
        session.turn_count += 1
        policies.check_pending_timeout(session)
        session.history.append({"role": "user", "content": request.message})
        reply, added, calls, alerts = llm.chat(
            session,
            prompt_mode=session.prompt_mode,
            use_gateway=request.use_gateway,
        )
        session.history.extend(added)
        audit.log_turn(
            session_id=session.session_id,
            turn=session.turn_count,
            user_message=request.message,
            tool_calls=calls,
            assistant_reply=reply,
            user_id=session.user_id,
            guard_alerts=alerts,
            prompt_mode=session.prompt_mode,
        )
        return ChatResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            prompt_mode=session.prompt_mode,
            reply=reply,
            tool_calls=[ToolCallRecord(**c) for c in calls],
            guard_alerts=alerts,
        )
    finally:
        # Снимаем флаг даже на исключении из llm.chat — иначе сессия
        # залипнет навсегда (in_flight=True, все будущие /chat → 409).
        # Висячее user-сообщение в session.history после такого крэша
        # лечит rollback в history.pop_chunk (last_safe_i).
        session.in_flight = False
