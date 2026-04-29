"""Cost Tracker — подсчёт стоимости запросов.

Стратегия двухуровневая:
  1. OpenRouter возвращает usage.cost напрямую → берём его (поле в model_dump()).
  2. OpenAI direct (или если cost отсутствует) → считаем из токенов по таблице PRICING.

GET /stats возвращает кумулятивную статистику (in-memory).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# $/1M tokens — fallback таблица для OpenAI direct
PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini":  {"input": 0.15,  "output": 0.60},
    "gpt-4o":       {"input": 2.50,  "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40,  "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10,  "output": 0.40},
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-5":         {"input": 3.00,  "output": 15.00},
}

_FALLBACK_PRICING = PRICING["gpt-4o-mini"]


def extract_cost(response) -> tuple[float, str]:
    """Извлечь стоимость из ответа API.

    Returns:
        (cost_usd, source) где source = "provider" | "calculated"
    """
    usage = response.usage
    if usage is None:
        return 0.0, "unknown"

    # OpenRouter возвращает cost как extra field — доступен через model_dump()
    usage_dict = usage.model_dump()
    provider_cost = usage_dict.get("cost")
    if provider_cost is not None:
        return round(float(provider_cost), 8), "provider"

    # Fallback: считаем сами
    model = (response.model or "")
    # OpenRouter добавляет префикс "openai/" — нормализуем
    model_key = model.split("/")[-1] if "/" in model else model

    prompt_tokens = usage.prompt_tokens or 0
    completion_tokens = usage.completion_tokens or 0
    cost = _calculate(model_key, prompt_tokens, completion_tokens)
    return cost, "calculated"


def _calculate(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = PRICING.get(model, _FALLBACK_PRICING)
    cost = (prompt_tokens * prices["input"] + completion_tokens * prices["output"]) / 1_000_000
    return round(cost, 8)


# ---------------------------------------------------------------------------
# In-memory cumulative stats
# ---------------------------------------------------------------------------

@dataclass
class ModelStats:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class GlobalStats:
    total_requests: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    by_model: dict[str, ModelStats] = field(default_factory=dict)


_stats = GlobalStats()


def record(model: str, usage_dict: dict | None, cost_usd: float) -> None:
    """Обновить кумулятивную статистику."""
    _stats.total_requests += 1
    _stats.total_cost_usd = round(_stats.total_cost_usd + cost_usd, 8)

    if usage_dict:
        total = usage_dict.get("total_tokens", 0) or 0
        _stats.total_tokens += total

    if model not in _stats.by_model:
        _stats.by_model[model] = ModelStats()
    ms = _stats.by_model[model]
    ms.requests += 1
    ms.cost_usd = round(ms.cost_usd + cost_usd, 8)
    if usage_dict:
        ms.prompt_tokens += usage_dict.get("prompt_tokens", 0) or 0
        ms.completion_tokens += usage_dict.get("completion_tokens", 0) or 0


def get_stats() -> dict:
    """Вернуть текущую статистику в виде dict (для /stats endpoint)."""
    return {
        "total_requests": _stats.total_requests,
        "total_tokens": _stats.total_tokens,
        "total_cost_usd": _stats.total_cost_usd,
        "by_model": {
            m: {
                "requests": s.requests,
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "cost_usd": s.cost_usd,
            }
            for m, s in _stats.by_model.items()
        },
    }
