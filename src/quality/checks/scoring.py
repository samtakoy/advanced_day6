"""Scoring check — LLM self-assessment of extraction quality.

A second LLM call asks the model to evaluate its own extraction
against the original input, returning per-field confidence.
"""

from __future__ import annotations

import json
import re
import time

from src.quality.models import CheckVerdict

SELF_ASSESSMENT_PROMPT = """\
Ты — аудитор извлечения задач. Тебе дан оригинальный текст задачи и результат извлечения (JSON).

Оцени качество извлечения по каждому полю. Для каждого поля верни статус:
- "OK" — поле извлечено корректно
- "UNSURE" — возможны ошибки, неоднозначность
- "FAIL" — явная ошибка

Верни JSON строго в формате (без markdown, без пояснений вне JSON):
{
  "overall": "OK" | "UNSURE" | "FAIL",
  "field_confidence": {
    "title": "OK" | "UNSURE" | "FAIL",
    "type": "OK" | "UNSURE" | "FAIL",
    "block": "OK" | "UNSURE" | "FAIL",
    "modules": "OK" | "UNSURE" | "FAIL",
    "newModules": "OK" | "UNSURE" | "FAIL",
    "dependsOn": "OK" | "UNSURE" | "FAIL",
    "acceptanceCriteria": "OK" | "UNSURE" | "FAIL",
    "outOfScope": "OK" | "UNSURE" | "FAIL"
  },
  "reasoning": "краткое пояснение (1-2 предложения)"
}

## Оригинальный текст задачи:
{user_text}

## Результат извлечения:
{extraction_json}
"""


def _parse_json(content: str) -> dict | None:
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass
    if content:
        m = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return None


def run(extraction: dict, *, client, model: str, messages: list[dict],
        temperature: float = 0.0, num_ctx: int | None = None,
        **_kwargs) -> CheckVerdict:
    """Run scoring check: ask the model to self-assess its extraction.

    Args:
        extraction: The extraction to evaluate.
        client: OpenAI-compatible client.
        model: Model name.
        messages: Original [system, user] messages.
        temperature: Temperature for self-assessment (0 = deterministic).
        num_ctx: Context window size (Ollama only).
    """
    t0 = time.perf_counter()

    user_text = messages[1]["content"] if len(messages) > 1 else ""
    extraction_json = json.dumps(extraction, ensure_ascii=False, indent=2)

    prompt = SELF_ASSESSMENT_PROMPT.format(
        user_text=user_text,
        extraction_json=extraction_json,
    )

    assessment_messages = [
        {"role": "system", "content": "Ты — аудитор качества извлечения данных. Отвечай только валидным JSON."},
        {"role": "user", "content": prompt},
    ]

    kwargs: dict = dict(
        model=model,
        messages=assessment_messages,
        temperature=temperature,
    )
    if num_ctx is not None:
        kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}}

    extra_calls = 0
    extra_tokens_in = 0
    extra_tokens_out = 0

    try:
        resp = client.chat.completions.create(**kwargs)
        extra_calls = 1
        if resp.usage:
            extra_tokens_in = resp.usage.prompt_tokens
            extra_tokens_out = resp.usage.completion_tokens

        content = resp.choices[0].message.content or ""
        assessment = _parse_json(content)
    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000
        return CheckVerdict(
            check_name="scoring",
            status="UNSURE",
            details={"error": str(e)},
            latency_ms=latency,
            extra_calls=extra_calls,
            extra_tokens_in=extra_tokens_in,
            extra_tokens_out=extra_tokens_out,
        )

    latency = (time.perf_counter() - t0) * 1000

    if not assessment or "overall" not in assessment:
        return CheckVerdict(
            check_name="scoring",
            status="UNSURE",
            details={"error": "failed to parse self-assessment",
                     "raw_response": content[:500]},
            latency_ms=latency,
            extra_calls=extra_calls,
            extra_tokens_in=extra_tokens_in,
            extra_tokens_out=extra_tokens_out,
        )

    overall = assessment.get("overall", "UNSURE").upper()
    if overall not in ("OK", "UNSURE", "FAIL"):
        overall = "UNSURE"

    return CheckVerdict(
        check_name="scoring",
        status=overall,
        details={
            "field_confidence": assessment.get("field_confidence", {}),
            "reasoning": assessment.get("reasoning", ""),
        },
        latency_ms=latency,
        extra_calls=extra_calls,
        extra_tokens_in=extra_tokens_in,
        extra_tokens_out=extra_tokens_out,
    )
