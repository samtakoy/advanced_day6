"""Scoring COT check — LLM self-assessment with chain-of-thought explanation.

Same as scoring, but the model is explicitly asked to explain its reasoning
for each field BEFORE giving the assessment. The hypothesis: requiring
detailed justification may improve assessment quality.
"""

from __future__ import annotations

import json
import re
import time

from src.quality.models import CheckVerdict

_COT_EXAMPLE = (
    '{"field_analysis": {'
    '"title": {"verdict": "OK", "reasoning": "Название точно отражает суть задачи"}, '
    '"type": {"verdict": "UNSURE", "reasoning": "Описание содержит и refactor и feat элементы"}, '
    '"block": {"verdict": "OK", "reasoning": "Задача явно относится к workspace_foundation"}, '
    '"modules": {"verdict": "FAIL", "reasoning": "В тексте упомянут db, но в extraction его нет"}, '
    '"newModules": {"verdict": "OK", "reasoning": "Новые модули корректно указаны"}, '
    '"dependsOn": {"verdict": "OK", "reasoning": "Зависимости совпадают с описанием"}, '
    '"acceptanceCriteria": {"verdict": "OK", "reasoning": "Критерии взяты из текста"}, '
    '"outOfScope": {"verdict": "OK", "reasoning": "Out of scope совпадает с явно указанным"}}, '
    '"overall": "FAIL", '
    '"summary": "Пропущен модуль db, остальное корректно"}'
)


def _build_cot_prompt(user_text: str, extraction_json: str) -> str:
    return (
        'Ты — аудитор извлечения задач. Тебе дан оригинальный текст задачи '
        'и результат извлечения (JSON).\n\n'
        'Проанализируй КАЖДОЕ поле по отдельности. Для каждого поля:\n'
        '1. Сравни значение в extraction с оригинальным текстом\n'
        '2. Объясни, почему считаешь поле корректным или нет\n'
        '3. Дай вердикт: OK, UNSURE или FAIL\n\n'
        'Затем дай общую оценку (overall) и краткое резюме.\n\n'
        'Верни JSON строго в формате (без markdown, без текста вне JSON):\n'
        + _COT_EXAMPLE + '\n\n'
        'Правила вердикта:\n'
        '- OK — поле извлечено корректно, совпадает с текстом\n'
        '- UNSURE — неоднозначность, можно трактовать по-разному\n'
        '- FAIL — явная ошибка: пропущено, добавлено лишнее, неправильное значение\n'
        '- overall = FAIL если хоть одно поле FAIL, UNSURE если есть UNSURE, иначе OK\n\n'
        '## Оригинальный текст задачи:\n' + user_text + '\n\n'
        '## Результат извлечения:\n' + extraction_json
    )


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
        first = content.find("{")
        last = content.rfind("}")
        if first != -1 and last > first:
            try:
                return json.loads(content[first:last + 1])
            except json.JSONDecodeError:
                pass
    return None


def run(extraction: dict, *, client, model: str, messages: list[dict],
        temperature: float = 0.0, num_ctx: int | None = None,
        **_kwargs) -> CheckVerdict:
    """Run scoring COT check: self-assessment with chain-of-thought.

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

    prompt = _build_cot_prompt(user_text, extraction_json)

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
            check_name="scoring_cot",
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
            check_name="scoring_cot",
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

    # Extract per-field verdicts and reasoning from field_analysis
    field_analysis = assessment.get("field_analysis", {})
    field_confidence = {}
    field_reasoning = {}
    for field_name, data in field_analysis.items():
        if isinstance(data, dict):
            field_confidence[field_name] = data.get("verdict", "UNSURE")
            field_reasoning[field_name] = data.get("reasoning", "")

    return CheckVerdict(
        check_name="scoring_cot",
        status=overall,
        details={
            "field_confidence": field_confidence,
            "field_reasoning": field_reasoning,
            "summary": assessment.get("summary", ""),
        },
        latency_ms=latency,
        extra_calls=extra_calls,
        extra_tokens_in=extra_tokens_in,
        extra_tokens_out=extra_tokens_out,
    )
