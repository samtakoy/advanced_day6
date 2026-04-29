"""LLM Gateway — FastAPI proxy между клиентом и LLM (OpenAI / OpenRouter).

Шаг 4: Output Guard — проверка ответа модели перед отдачей клиенту.
"""
from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from gateway.src import audit, cost_tracker, input_guard, output_guard, proxy, rate_limiter

app = FastAPI(title="LLM Gateway", version="0.4.0")


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: str | None = None  # None у tool-result и assistant с tool_calls


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "gpt-4o-mini"
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = None
    # Все остальные поля (tools, tool_choice, top_p, stop, n, seed, ...)
    # попадают в model_extra и пробрасываются в upstream.


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/stats")
async def stats() -> dict:
    return cost_tracker.get_stats()


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    req: Request,
    x_gateway_mode: str = Header(default="mask", alias="X-Gateway-Mode"),
):
    client_ip = req.client.host if req.client else "unknown"

    # --- Rate Limiter ---
    if not rate_limiter.limiter.check(client_ip):
        return JSONResponse(
            {
                "error": {
                    "message": (
                        f"Rate limit exceeded: max {rate_limiter.RATE_LIMIT} "
                        f"requests per {rate_limiter.RATE_WINDOW}s"
                    ),
                    "type": "rate_limit_exceeded",
                }
            },
            status_code=429,
            headers={"Retry-After": str(rate_limiter.RATE_WINDOW)},
        )

    messages = [m.model_dump() for m in request.messages]
    mode = x_gateway_mode.lower()

    # --- Input Guard ---
    # mask_messages применяет разную политику по ролям:
    #   user/system — маскируем секреты
    #   tool        — только фиксируем (retrieved контент не трогаем)
    #   assistant   — пропускаем
    # Вызываем всегда, чтобы собрать findings для аудита и block-проверки.
    messages, all_input_findings = input_guard.mask_messages(messages)

    if mode == "block":
        # Блокируем только по секретам из user/system — tool-секреты не повод
        # отказывать: это retrieved контент, который уже попал в систему.
        blockable = [f for f in all_input_findings if f.get("masked") is not False]
        if blockable:
            secret_types = list({f["type"] for f in blockable})
            return JSONResponse(
                {
                    "error": {
                        "message": "Request blocked: secrets detected in input",
                        "type": "input_guard_violation",
                        "secrets_found": secret_types,
                        "count": len(blockable),
                    }
                },
                status_code=400,
                headers={"X-Gateway-Input-Secrets": str(len(blockable))},
            )

    # --- Proxy ---
    extra = {k: v for k, v in (request.model_extra or {}).items() if k != "stream"}
    if (request.model_extra or {}).get("stream"):
        return JSONResponse(
            {"error": {"message": "Streaming is not supported by this gateway", "type": "unsupported_feature"}},
            status_code=400,
        )
    try:
        response = proxy.proxy_chat(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            **extra,
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

    # --- Cost Tracker ---
    cost_usd, cost_source = cost_tracker.extract_cost(response)
    headers["X-Gateway-Cost-USD"] = str(cost_usd)

    usage_dict = None
    if response.usage:
        usage_dict = {
            k: v for k, v in response.usage.model_dump().items()
            if v is not None
        }
    cost_tracker.record(request.model, usage_dict, cost_usd)

    # --- Audit Log ---

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
        usage={**(usage_dict or {}), "cost_usd": cost_usd, "cost_source": cost_source},
        messages=messages,
        response_text=reply_text,
    )

    return JSONResponse(response_dict, headers=headers)
