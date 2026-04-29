"""LLM Gateway — FastAPI proxy между клиентом и LLM (OpenAI / OpenRouter).

Шаг 4: Output Guard — проверка ответа модели перед отдачей клиенту.
"""
from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gateway.src import audit, input_guard, output_guard, proxy

app = FastAPI(title="LLM Gateway", version="0.4.0")


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
    req: Request = None,
    x_gateway_mode: str = Header(default="mask", alias="X-Gateway-Mode"),
):
    messages = [m.model_dump() for m in request.messages]
    mode = x_gateway_mode.lower()

    # --- Input Guard ---
    all_input_findings: list[dict] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            all_input_findings.extend(input_guard.scan(content))
            all_input_findings.extend(input_guard.scan_base64(content))

    if all_input_findings and mode == "block":
        secret_types = list({f["type"] for f in all_input_findings})
        return JSONResponse(
            {
                "error": {
                    "message": "Request blocked: secrets detected in input",
                    "type": "input_guard_violation",
                    "secrets_found": secret_types,
                    "count": len(all_input_findings),
                }
            },
            status_code=400,
            headers={"X-Gateway-Input-Secrets": str(len(all_input_findings))},
        )

    if mode == "mask":
        messages, all_input_findings = input_guard.mask_messages(messages)

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

    # --- Output Guard ---
    reply_text = ""
    if response.choices:
        reply_text = response.choices[0].message.content or ""

    output_result = output_guard.check(reply_text)
    output_alerts: list[str] = []

    if output_result["secrets"]:
        # Маскируем секреты в ответе
        reply_text, _ = output_guard.mask_secrets(reply_text)
        # Патчим в response dict
        output_alerts.append("output_secrets_masked")

    output_alerts.extend(output_result["prompt_leak"])
    output_alerts.extend(output_result["suspicious_urls"])
    output_alerts.extend(output_result["suspicious_commands"])

    # Собираем ответ
    response_dict = response.model_dump()
    if output_result["secrets"] and response_dict.get("choices"):
        response_dict["choices"][0]["message"]["content"] = reply_text

    # Response headers
    headers: dict[str, str] = {}
    if all_input_findings:
        headers["X-Gateway-Input-Secrets"] = str(len(all_input_findings))
    if output_alerts:
        headers["X-Gateway-Output-Alerts"] = ",".join(output_alerts)

    # --- Audit Log ---
    usage_dict = None
    if response.usage:
        usage_dict = {
            k: v for k, v in response.usage.model_dump().items()
            if v is not None
        }

    client_ip = req.client.host if req and req.client else "unknown"
    audit.log_request(
        client_ip=client_ip,
        model=request.model,
        input_guard_result={
            "mode": mode,
            "secrets_found": list({f["type"] for f in all_input_findings}),
            "count": len(all_input_findings),
            "action": "masked" if mode == "mask" else ("blocked" if all_input_findings else "passed"),
        },
        output_guard_result={
            "alerts": output_alerts,
            "secrets_masked": len(output_result["secrets"]),
        },
        usage=usage_dict,
        messages=messages,
        response_text=reply_text,
    )

    return JSONResponse(response_dict, headers=headers)
