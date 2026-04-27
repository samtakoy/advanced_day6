"""FastAPI-приложение SkyHelper. Slice 1: walking skeleton без тулов."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from skyhelper.src import llm, sessions

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="SkyHelper", version="0.1.0")


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
    session.history.append({"role": "user", "content": request.message})
    reply = llm.chat(session.history)
    session.history.append({"role": "assistant", "content": reply})
    return ChatResponse(session_id=session.session_id, reply=reply)
