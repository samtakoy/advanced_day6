"""LLM Gateway — FastAPI proxy между клиентом и LLM (OpenAI / OpenRouter / Ollama).

Шаг 4+: streaming поддержка через AsyncOpenAI.
"""
from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from gateway.src import audit, cost_tracker, input_guard, output_guard, proxy, rate_limiter

logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Gateway", version="0.5.0")

# Поля из тела запроса, которые обрабатываются явно или не поддерживаются OpenAI SDK.

@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    """Логируем тело 422 — иначе uvicorn показывает только статус."""
    body_bytes = await request.body()
    body_preview = body_bytes[:500].decode("utf-8", errors="replace")
    logger.error("422 validation error | errors=%s | body_preview=%s", exc.errors(), body_preview)
    return JSONResponse({"detail": exc.errors()}, status_code=422)


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    # content может быть str, list[dict] (content parts для tool-calls/images) или None.
    # Pydantic с str | None падает с 422 когда pi присылает список.
    content: str | list | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "gpt-4o-mini"
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = None
    # Все остальные поля (tools, tool_choice, top_p, stop, n, seed, stream, ...)
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

    # --- Request received ---
    is_stream_early = bool((request.model_extra or {}).get("stream"))
    logger.info(
        "REQUEST model=%s messages=%d stream=%s ip=%s",
        request.model, len(request.messages), is_stream_early, client_ip,
    )

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

    # --- Stream detection ---
    is_stream = bool((request.model_extra or {}).get("stream"))
    if is_stream:
        return await _stream_response(
            request=request,
            messages=messages,
            all_input_findings=all_input_findings,
            mode=mode,
            client_ip=client_ip,
        )

    # --- Proxy (non-streaming) ---
    # Всё из model_extra кроме 'stream' идёт в extra_body — SDK пробросит без валидации.
    extra_body = {k: v for k, v in (request.model_extra or {}).items() if k != "stream"}
    logger.info("UPSTREAM_SEND model=%s (non-stream)", request.model)
    try:
        response = proxy.proxy_chat(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            extra_body=extra_body or None,
        )
    except Exception as exc:
        logger.error("UPSTREAM_ERROR model=%s error=%s", request.model, exc)
        return JSONResponse(
            {"error": {"message": str(exc), "type": "proxy_error"}},
            status_code=502,
        )
    logger.info("UPSTREAM_DONE model=%s", request.model)

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


async def _stream_response(
    request: ChatCompletionRequest,
    messages: list[dict],
    all_input_findings: list[dict],
    mode: str,
    client_ip: str,
):
    """Обработать streaming запрос через AsyncOpenAI.

    Открываем стрим ДО StreamingResponse — чтобы early-ошибки
    (нет ключа, провайдер недоступен) возвращались как 502 JSON,
    а не как 200 OK с SSE-error внутри.
    """
    # 'stream' и 'stream_options' передаём явно; остальное — в extra_body без валидации SDK.
    extra_body = {k: v for k, v in (request.model_extra or {}).items()
                  if k not in ("stream", "stream_options")}

    logger.info("UPSTREAM_SEND model=%s (stream)", request.model)
    try:
        stream = await proxy.proxy_stream(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream_options={"include_usage": True},
            extra_body=extra_body or None,
        )
    except Exception as exc:
        logger.error("UPSTREAM_ERROR model=%s error=%s", request.model, exc)
        return JSONResponse(
            {"error": {"message": str(exc), "type": "proxy_error"}},
            status_code=502,
        )
    logger.info("UPSTREAM_STREAM_OPEN model=%s", request.model)

    async def generate():
        full_text: list[str] = []
        final_usage: dict[str, int] | None = None

        try:
            async for chunk in stream:
                # Накапливаем text-content для post-stream guard/audit.
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        full_text.append(delta.content)

                # Usage приходит в последнем чанке (OpenRouter/OpenAI со stream_options).
                # Ollama тихо игнорирует stream_options — usage останется None.
                if getattr(chunk, "usage", None):
                    u = chunk.usage
                    final_usage = {
                        "prompt_tokens": u.prompt_tokens or 0,
                        "completion_tokens": u.completion_tokens or 0,
                        "total_tokens": u.total_tokens or 0,
                    }

                # Форвардим весь чанк 1-в-1: сохраняем delta.tool_calls,
                # delta.role, delta.refusal, finish_reason и пр.
                # Без этого coding agent потеряет вызовы инструментов.
                yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"

        except Exception as exc:
            # Ошибка в середине стрима — HTTP-статус уже 200, шлём SSE-event.
            err = json.dumps({"error": {"message": str(exc), "type": "stream_error"}})
            yield f"data: {err}\n\n"
            return

        yield "data: [DONE]\n\n"
        logger.info("UPSTREAM_STREAM_DONE model=%s tokens=%s", request.model, final_usage)

        # --- Post-stream: output guard (alert-only) + cost + audit ---
        complete_text = "".join(full_text)

        output_result = output_guard.check(complete_text)
        output_alerts: list[str] = []
        if output_result["secrets"]:
            # Маскировать уже отправленные чанки нельзя — только фиксируем.
            output_alerts.append("output_secrets_in_stream")
        output_alerts.extend(output_result["prompt_leak"])
        output_alerts.extend(output_result["suspicious_urls"])
        output_alerts.extend(output_result["suspicious_commands"])

        cost_usd = 0.0
        cost_source = "unknown"
        if final_usage:
            cost_usd, cost_source = cost_tracker.extract_cost_from_usage(
                request.model, final_usage
            )
            cost_tracker.record(request.model, final_usage, cost_usd)

        audit.log_request(
            client_ip=client_ip,
            model=request.model,
            input_guard_result={
                "mode": mode,
                "secrets_found": list({f["type"] for f in all_input_findings}),
                "count": len(all_input_findings),
                "action": "masked" if mode == "mask" else (
                    "blocked" if all_input_findings else "passed"
                ),
            },
            output_guard_result={
                "alerts": output_alerts,
                "secrets_masked": 0,  # streaming: маскирование невозможно
            },
            usage={**(final_usage or {}), "cost_usd": cost_usd, "cost_source": cost_source},
            messages=messages,
            response_text=complete_text,
        )

    headers: dict[str, str] = {}
    if all_input_findings:
        headers["X-Gateway-Input-Secrets"] = str(len(all_input_findings))
    # X-Gateway-Output-Alerts и X-Gateway-Cost-USD недоступны в streaming:
    # заголовки уходят до завершения генерации — данные видны только в audit log.

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=headers,
    )
