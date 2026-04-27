"""FastAPI-приложение SkyHelper.

Slice 5: header X-User-Id для multi-user threat model + seed-загрузка
bookings из data/travel/seed_bookings.json при первом старте.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel

from skyhelper.src import audit, llm, policies, sessions, tools

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    tools.maybe_seed_bookings()
    yield


app = FastAPI(title="SkyHelper", version="0.6.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ToolCallRecord(BaseModel):
    name: str
    args: str
    result: str


class ChatResponse(BaseModel):
    session_id: str
    user_id: str
    reply: str
    tool_calls: list[ToolCallRecord] = []
    guard_alerts: list[str] = []


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "chat.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> ChatResponse:
    user_id = x_user_id or "ANON"
    session = sessions.get_or_create(request.session_id, user_id=user_id)
    session.turn_count += 1
    policies.check_pending_timeout(session)
    session.history.append({"role": "user", "content": request.message})
    reply, added, calls, alerts = llm.chat(session.history, session)
    session.history.extend(added)
    audit.log_turn(
        session_id=session.session_id,
        turn=session.turn_count,
        user_message=request.message,
        tool_calls=calls,
        assistant_reply=reply,
        user_id=session.user_id,
        guard_alerts=alerts,
    )
    return ChatResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        reply=reply,
        tool_calls=[ToolCallRecord(**c) for c in calls],
        guard_alerts=alerts,
    )
