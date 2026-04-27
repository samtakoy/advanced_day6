"""FastAPI-приложение SkyHelper.

Slice 4.5: возвращаем tool_calls в ChatResponse и пишем per-session audit-лог.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from skyhelper.src import audit, llm, policies, sessions

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="SkyHelper", version="0.4.5")


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ToolCallRecord(BaseModel):
    name: str
    args: str  # JSON-строка от модели
    result: str  # JSON-строка от диспетчера


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: list[ToolCallRecord] = []


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "chat.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session = sessions.get_or_create(request.session_id)
    session.turn_count += 1
    policies.check_pending_timeout(session)
    session.history.append({"role": "user", "content": request.message})
    reply, added, calls = llm.chat(session.history, session)
    session.history.extend(added)
    audit.log_turn(
        session_id=session.session_id,
        turn=session.turn_count,
        user_message=request.message,
        tool_calls=calls,
        assistant_reply=reply,
    )
    return ChatResponse(
        session_id=session.session_id,
        reply=reply,
        tool_calls=[ToolCallRecord(**c) for c in calls],
    )
