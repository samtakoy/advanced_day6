"""LLM Gateway — FastAPI proxy между клиентом и LLM (OpenAI / OpenRouter).

Шаг 3: Input Guard — детекция и маскирование секретов во входящем промпте.

Хедер X-Gateway-Mode: block | mask (дефолт: mask)
"""
from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gateway.src import input_guard, proxy

app = FastAPI(title="LLM Gateway", version="0.3.0")


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
async def chat_completions(
    request: ChatCompletionRequest,
    x_gateway_mode: str = Header(default="mask", alias="X-Gateway-Mode"),
):
    messages = [m.model_dump() for m in request.messages]
    mode = x_gateway_mode.lower()

    # --- Input Guard ---
    all_findings: list[dict] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            findings = input_guard.scan(content)
            findings += input_guard.scan_base64(content)
            all_findings.extend(findings)

    if all_findings and mode == "block":
        secret_types = list({f["type"] for f in all_findings})
        return JSONResponse(
            {
                "error": {
                    "message": "Request blocked: secrets detected in input",
                    "type": "input_guard_violation",
                    "secrets_found": secret_types,
                    "count": len(all_findings),
                }
            },
            status_code=400,
            headers={"X-Gateway-Input-Secrets": str(len(all_findings))},
        )

    if mode == "mask":
        messages, all_findings = input_guard.mask_messages(messages)

    # --- Proxy ---
    try:
        response = proxy.proxy_chat(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except Exception as exc:
        return JSONResponse(
            {"error": {"message": str(exc), "type": "proxy_error"}},
            status_code=502,
        )

    headers = {}
    if all_findings:
        headers["X-Gateway-Input-Secrets"] = str(len(all_findings))

    return JSONResponse(response.model_dump(), headers=headers)
