"""Двухуровневый инференс: rules (модули) + LLM (остальное).

Rules всегда извлекают modules через regex — бесплатно и точно.
Маленькая LLM извлекает 7 оставшихся полей + возвращает confidence 0-1.
Если confidence < порога — вместо маленькой LLM берём результат большой.
Modules всегда от rules, независимо от уровня.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.baseline.run_baseline import (
    ExampleMetrics,
    call_api,
    parse_response,
    score,
)
from src.micromodel.classifier import MicroResult, call_micro
from src.micromodel.rules import extract_modules
from src.validator.validate import validate_gold

# Суффикс к системному промпту: просим 7 полей (без modules) + confidence
SUFFIX_MICRO = (
    '\n\nВерни ответ в формате JSON:'
    '\n{"extraction": {"title": "...", "type": "...", "block": "...", '
    '"newModules": [...], "dependsOn": [...], '
    '"acceptanceCriteria": [...], "outOfScope": [...]}, '
    '"confidence": 0.85}'
    '\nconfidence — число от 0 до 1, твоя уверенность в правильности ответа.'
)


@dataclass
class PipelineResult:
    """Результат прогона одного примера через пайплайн."""
    name: str
    # Модули от rules
    rules_modules: list[str] = field(default_factory=list)
    # Результат маленькой LLM
    micro_result: MicroResult | None = None
    # Результат большой LLM (только если micro не прошла порог)
    big_extraction: dict | None = None
    big_raw: str = ""
    big_tokens_in: int = 0
    big_tokens_out: int = 0
    big_latency_ms: float = 0.0
    # Итог
    escalated: bool = False       # ушло ли на большую LLM
    final_extraction: dict | None = None
    metrics: ExampleMetrics | None = None
    validation_errors: list[str] = field(default_factory=list)
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_latency_ms: float = 0.0


def run_pipeline(
    name: str,
    messages: list[dict],
    gold: dict,
    micro_client,
    big_client,
    micro_model: str,
    big_model: str,
    threshold: float = 0.95,
    temperature: float = 0.3,
    micro_num_ctx: int | None = None,
    big_num_ctx: int | None = None,
) -> PipelineResult:
    """Прогнать один пример через пайплайн.

    1. Rules извлекают modules (regex, 0 токенов).
    2. Маленькая LLM извлекает остальные 7 полей + confidence.
    3. Если confidence >= порога — берём результат micro.
       Иначе — вызываем большую LLM (fallback).
    4. В любом случае modules подставляются от rules.
    """
    t0 = time.perf_counter()
    result = PipelineResult(name=name)

    system_content = messages[0]["content"]
    user_text = messages[1]["content"]

    # --- Rules: извлекаем модули ---
    result.rules_modules = extract_modules(user_text)

    # --- Промпт для LLM (без modules) ---
    system_prompt = system_content + SUFFIX_MICRO
    prompt_msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    # --- Маленькая LLM ---
    micro = call_micro(
        micro_client, micro_model, prompt_msgs,
        temperature=temperature, num_ctx=micro_num_ctx,
    )
    result.micro_result = micro
    result.total_tokens_in += micro.tokens_in
    result.total_tokens_out += micro.tokens_out

    if micro.confidence >= threshold and micro.predicted is not None:
        # Micro уверена — берём её результат, подставляем modules от rules
        extraction = dict(micro.predicted)
        extraction["modules"] = result.rules_modules
        result.final_extraction = extraction
        result.metrics = score(gold, extraction)
        result.metrics.name = name
        result.validation_errors = validate_gold(extraction, name)
        result.total_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return result

    # --- Большая LLM (fallback) ---
    result.escalated = True
    t_big = time.perf_counter()
    resp = call_api(big_client, big_model, prompt_msgs, temperature, num_ctx=big_num_ctx)
    big_raw = resp.choices[0].message.content or ""
    big_predicted, _, _ = parse_response(big_raw)

    result.big_raw = big_raw
    result.big_tokens_in = resp.usage.prompt_tokens
    result.big_tokens_out = resp.usage.completion_tokens
    result.big_latency_ms = round((time.perf_counter() - t_big) * 1000, 1)
    result.total_tokens_in += result.big_tokens_in
    result.total_tokens_out += result.big_tokens_out

    if big_predicted is not None:
        # Подставляем modules от rules и в результат большой LLM
        extraction = dict(big_predicted)
        extraction["modules"] = result.rules_modules
        result.big_extraction = big_predicted
        result.final_extraction = extraction
        result.metrics = score(gold, extraction)
        result.metrics.name = name
        result.validation_errors = validate_gold(extraction, name)
    else:
        result.final_extraction = None
        result.metrics = ExampleMetrics(name=name, error="JSON parse failed on big model")

    result.total_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    return result
