"""FastAPI-приложение SkyHelper. Slice 2: добавлен tool-call loop для search_flights."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from skyhelper.src import llm, policies, sessions

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="SkyHelper", version="0.3.0")


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


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
    reply, added = llm.chat(session.history, session)
    session.history.extend(added)
    return ChatResponse(session_id=session.session_id, reply=reply)
