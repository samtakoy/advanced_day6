"""Audit Log — JSONL-запись каждого запроса/ответа для post-mortem анализа."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
AUDIT_LOG = LOGS_DIR / "audit.jsonl"

# Если GATEWAY_LOG_FULL=true — логируем полные тексты промптов и ответов
_LOG_FULL = os.getenv("GATEWAY_LOG_FULL", "false").lower() == "true"


def log_request(
    client_ip: str,
    model: str,
    input_guard_result: dict,
    output_guard_result: dict,
    usage: dict | None,
    messages: list[dict],
    response_text: str,
) -> None:
    """Записать одну строку в audit.jsonl."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Preview первых 100 символов user-сообщения
    user_content = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    messages_preview = (user_content or "")[:100]
    response_preview = (response_text or "")[:100]

    record: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "client_ip": client_ip,
        "model": model,
        "input_guard": input_guard_result,
        "output_guard": output_guard_result,
        "usage": usage,
        "messages_preview": messages_preview,
        "response_preview": response_preview,
    }

    if _LOG_FULL:
        record["messages_full"] = messages
        record["response_full"] = response_text

    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
