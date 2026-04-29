"""LLM Gateway — FastAPI proxy между клиентом и LLM (OpenAI / OpenRouter).

Шаг 2: реальное проксирование через /v1/chat/completions.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gateway.src import proxy

app = FastAPI(title="LLM Gateway", version="0.2.0")


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "gpt-4o-mini"
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = None


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    try:
        response = proxy.proxy_chat(
            messages=[m.model_dump() for m in request.messages],
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return JSONResponse(response.model_dump())
    except Exception as exc:
        return JSONResponse({"error": {"message": str(exc), "type": "proxy_error"}}, status_code=502)
