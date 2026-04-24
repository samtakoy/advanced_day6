"""Redundancy check — run inferences at different temperatures, evaluate each against gold.

Three requests at temperatures 0, 0.35, 0.7. Each response is validated
(schema) and scored against gold (day 6 metrics). The report shows which
attempts passed and which fields failed.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict

from src.quality.models import CheckVerdict

TEMPERATURES = [0.0, 0.35, 0.7]


def _parse_json(content: str) -> dict | None:
    """Try to parse JSON from response, with markdown code block fallback."""
    if not content:
        return None
    try:
        obj = json.loads(content)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    first = content.find("{")
    last = content.rfind("}")
    if first != -1 and last > first:
        try:
            obj = json.loads(content[first:last + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _evaluate(extraction: dict | None, gold: dict | None,
              temperature: float, validate_fn, score_fn) -> dict:
    """Evaluate a single extraction: validate schema + score against gold."""
    result: dict = {"temperature": temperature}

    if extraction is None:
        result["parsed"] = False
        result["valid"] = False
        result["pass"] = False
        return result

    result["parsed"] = True
    result["extraction"] = extraction

    # Schema validation
    errors = validate_fn(extraction, "redundancy") if validate_fn else []
    result["valid"] = len(errors) == 0
    result["validation_errors"] = errors

    # Score against gold
    if gold and score_fn:
        metrics = score_fn(gold, extraction)
        if hasattr(metrics, '__dataclass_fields__'):
            m = asdict(metrics)
        elif hasattr(metrics, '__dict__'):
            m = {k: v for k, v in metrics.__dict__.items() if not k.startswith("_")}
        else:
            m = metrics

        vs_gold = {
            "type_match": m.get("type_match", False),
            "block_match": m.get("block_match", False),
            "modules_iou": round(m.get("modules_iou", 0), 3),
            "new_modules_iou": round(m.get("new_modules_iou", 0), 3),
            "depends_on_iou": round(m.get("depends_on_iou", 0), 3),
            "ac_recall": round(m.get("ac_recall", 0), 3),
            "oos_precision": round(m.get("oos_precision", 0), 3),
        }
        result["vs_gold"] = vs_gold

        # Determine which fields failed
        failed_fields = []
        if not vs_gold["type_match"]:
            failed_fields.append(f"type={extraction.get('type')}≠{gold.get('type')}")
        if not vs_gold["block_match"]:
            failed_fields.append(f"block={extraction.get('block')}≠{gold.get('block')}")
        if vs_gold["modules_iou"] < 1.0:
            failed_fields.append(f"modules_iou={vs_gold['modules_iou']}")
        if vs_gold["depends_on_iou"] < 1.0:
            failed_fields.append(f"depends_on_iou={vs_gold['depends_on_iou']}")
        result["failed_fields"] = failed_fields

        # Pass = valid schema + key metrics OK
        result["pass"] = (
            result["valid"]
            and vs_gold["type_match"]
            and vs_gold["block_match"]
            and vs_gold["modules_iou"] >= 0.8
        )
    else:
        result["pass"] = result["valid"]

    return result


def run(extraction: dict, *, client, model: str, messages: list[dict],
        temperature: float = 0.7, n: int = 3, num_ctx: int | None = None,
        gold: dict | None = None, validate_fn=None, score_fn=None,
        **_kwargs) -> CheckVerdict:
    """Run redundancy check: call LLM at different temperatures, evaluate each.

    The initial extraction (temperature from main pipeline) is included as
    the first attempt. Two additional calls are made at different temperatures.
    Each response is validated and scored against gold.

    Args:
        extraction: The initial extraction (already obtained).
        client: OpenAI-compatible client.
        model: Model name.
        messages: [system, user] messages.
        temperature: Not used (temperatures are fixed: 0, 0.35, 0.7).
        n: Not used (always 3 temperatures).
        num_ctx: Context window size (Ollama only).
        gold: Gold extraction to score each attempt against.
        validate_fn: Validation function (dict, prefix) -> list[str].
        score_fn: Scoring function (gold, predicted) -> metrics.
    """
    t0 = time.perf_counter()
    extra_calls = 0
    extra_tokens_in = 0
    extra_tokens_out = 0

    # Evaluate the initial extraction (from the main pipeline call)
    # We don't know its exact temperature, but it's the "base" attempt
    attempts = []

    # First attempt = initial extraction at pipeline temperature
    attempts.append(_evaluate(extraction, gold, 0.0, validate_fn, score_fn))

    # Additional calls at remaining temperatures
    for temp in TEMPERATURES[1:]:
        kwargs: dict = dict(model=model, messages=messages, temperature=temp)
        if num_ctx is not None:
            kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}}

        parsed = None
        try:
            resp = client.chat.completions.create(**kwargs)
            extra_calls += 1
            if resp.usage:
                extra_tokens_in += resp.usage.prompt_tokens
                extra_tokens_out += resp.usage.completion_tokens

            content = resp.choices[0].message.content or ""
            parsed = _parse_json(content)
            if parsed and not isinstance(parsed, dict):
                parsed = None
        except Exception as e:
            print(f"  [redundancy] API error at T={temp}: {e}")

        attempts.append(_evaluate(parsed, gold, temp, validate_fn, score_fn))

    latency = (time.perf_counter() - t0) * 1000

    # Determine status based on how many attempts passed
    n_passed = sum(1 for a in attempts if a.get("pass"))
    n_valid = sum(1 for a in attempts if a.get("valid"))
    n_parsed = sum(1 for a in attempts if a.get("parsed"))

    if n_passed == len(attempts):
        status = "OK"
    elif n_passed >= 1:
        status = "UNSURE"
    else:
        status = "FAIL"

    return CheckVerdict(
        check_name="redundancy",
        status=status,
        details={
            "n_passed": n_passed,
            "n_valid": n_valid,
            "n_parsed": n_parsed,
            "n_total": len(attempts),
            "attempts": attempts,
        },
        latency_ms=latency,
        extra_calls=extra_calls,
        extra_tokens_in=extra_tokens_in,
        extra_tokens_out=extra_tokens_out,
    )
