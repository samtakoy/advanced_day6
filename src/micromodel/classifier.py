"""Уровень 2 — Маленькая LLM с числовой уверенностью.

Вызывает маленькую модель (qwen2.5:3b через Ollama).
Модель возвращает extraction + confidence как число 0-1.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from src.baseline.run_baseline import call_api


@dataclass
class MicroResult:
    """Результат вызова маленькой LLM."""
    predicted: dict | None       # извлечённые поля (без modules)
    confidence: float            # 0-1, уверенность модели
    raw_content: str             # сырой ответ
    tokens_in: int
    tokens_out: int
    latency_ms: float


def _parse_micro_response(content: str) -> tuple[dict | None, float]:
    """Парсинг ответа модели. Возвращает (extraction, confidence).

    Ожидаемый формат: {"extraction": {...}, "confidence": 0.82}
    """
    parsed = None

    # Попытка 1: прямой JSON
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Попытка 2: JSON в markdown-блоке
        m = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # Попытка 3: подстрока между первой { и последней }
        if parsed is None:
            first = content.find("{")
            last = content.rfind("}")
            if first != -1 and last > first:
                try:
                    parsed = json.loads(content[first:last + 1])
                except json.JSONDecodeError:
                    pass

    if not isinstance(parsed, dict):
        return None, 0.0

    # Извлечь confidence
    confidence = 0.0
    raw_conf = parsed.get("confidence")
    if isinstance(raw_conf, (int, float)):
        confidence = max(0.0, min(1.0, float(raw_conf)))

    # Извлечь extraction
    if "extraction" in parsed and isinstance(parsed["extraction"], dict):
        return parsed["extraction"], confidence
    else:
        # Весь JSON и есть extraction (без обёртки)
        return parsed, confidence


def call_micro(
    client,
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    num_ctx: int | None = None,
) -> MicroResult:
    """Вызвать маленькую LLM, получить extraction + числовой confidence."""
    t0 = time.perf_counter()

    resp = call_api(client, model, messages, temperature, num_ctx=num_ctx)

    raw = resp.choices[0].message.content or ""
    predicted, confidence = _parse_micro_response(raw)
    latency = (time.perf_counter() - t0) * 1000

    return MicroResult(
        predicted=predicted,
        confidence=confidence,
        raw_content=raw,
        tokens_in=resp.usage.prompt_tokens,
        tokens_out=resp.usage.completion_tokens,
        latency_ms=round(latency, 1),
    )
