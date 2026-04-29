"""LLM Gateway — FastAPI proxy между клиентом и LLM (OpenAI / OpenRouter).

Шаг 1: скелет — healthcheck + stub endpoint.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="LLM Gateway", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions():
    return JSONResponse({"error": "not implemented"}, status_code=501)
