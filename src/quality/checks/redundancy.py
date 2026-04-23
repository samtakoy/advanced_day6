"""Redundancy check — run N inferences and measure consensus.

Same input is sent N times at higher temperature. Results are compared
field-by-field. Disagreement signals low confidence.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter

from src.quality.models import CheckVerdict


def _parse_json(content: str) -> dict | None:
    """Try to parse JSON from response, with markdown code block fallback."""
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


def _iou(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def _majority_vote_value(values: list):
    """Return the most common value from a list."""
    counter = Counter(str(v) for v in values)
    most_common_str = counter.most_common(1)[0][0]
    # Return the original value (not stringified)
    for v in values:
        if str(v) == most_common_str:
            return v
    return values[0]


def _majority_vote_list(lists: list[list]) -> list:
    """For list fields, return the list that appears most often (by content)."""
    serialized = [json.dumps(sorted(lst) if lst else [], ensure_ascii=False) for lst in lists]
    counter = Counter(serialized)
    best_str = counter.most_common(1)[0][0]
    for lst, s in zip(lists, serialized):
        if s == best_str:
            return lst
    return lists[0]


def _compute_consensus(extractions: list[dict]) -> tuple[float, dict]:
    """Compute field-by-field consensus across N extractions.

    Returns (consensus_score, majority_extraction).
    """
    n = len(extractions)
    if n <= 1:
        return 1.0, extractions[0] if extractions else {}

    fields_agree = 0
    total_fields = 0
    majority = {}

    # Scalar fields: exact match
    for field in ("title", "type", "block"):
        total_fields += 1
        values = [e.get(field) for e in extractions]
        if len(set(str(v) for v in values)) == 1:
            fields_agree += 1
        majority[field] = _majority_vote_value(values)

    # List fields: IoU-based agreement
    for field in ("modules", "newModules", "dependsOn", "acceptanceCriteria", "outOfScope"):
        total_fields += 1
        lists = [e.get(field, []) for e in extractions]

        # Check pairwise IoU — all pairs must agree
        all_agree = True
        for i in range(n):
            for j in range(i + 1, n):
                s_i = set(str(x) for x in lists[i])
                s_j = set(str(x) for x in lists[j])
                if _iou(s_i, s_j) < 0.8:
                    all_agree = False
                    break
            if not all_agree:
                break

        if all_agree:
            fields_agree += 1
        majority[field] = _majority_vote_list(lists)

    consensus = fields_agree / total_fields if total_fields else 1.0
    return consensus, majority


def run(extraction: dict, *, client, model: str, messages: list[dict],
        temperature: float = 0.7, n: int = 3, num_ctx: int | None = None,
        **_kwargs) -> CheckVerdict:
    """Run redundancy check: call LLM N-1 more times and compare.

    Args:
        extraction: The initial extraction (already obtained).
        client: OpenAI-compatible client.
        model: Model name.
        messages: [system, user] messages.
        temperature: Temperature for redundancy calls (higher = more diversity).
        n: Total number of extractions to compare (including the initial one).
        num_ctx: Context window size (Ollama only).
    """
    t0 = time.perf_counter()
    extra_calls = 0
    extra_tokens_in = 0
    extra_tokens_out = 0

    extractions = [extraction]

    kwargs: dict = dict(model=model, messages=messages, temperature=temperature)
    if num_ctx is not None:
        kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}}

    for _ in range(n - 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            extra_calls += 1
            if resp.usage:
                extra_tokens_in += resp.usage.prompt_tokens
                extra_tokens_out += resp.usage.completion_tokens

            content = resp.choices[0].message.content or ""
            parsed = _parse_json(content)
            if parsed and isinstance(parsed, dict):
                extractions.append(parsed)
        except Exception as e:
            # If API call fails, still proceed with what we have
            print(f"  [redundancy] API error: {e}")

    latency = (time.perf_counter() - t0) * 1000

    if len(extractions) < 2:
        return CheckVerdict(
            check_name="redundancy",
            status="UNSURE",
            details={"reason": "only 1 valid extraction obtained",
                     "n_valid": len(extractions)},
            latency_ms=latency,
            extra_calls=extra_calls,
            extra_tokens_in=extra_tokens_in,
            extra_tokens_out=extra_tokens_out,
        )

    consensus, majority = _compute_consensus(extractions)

    # Check type/block unanimity
    types = [e.get("type") for e in extractions]
    blocks = [e.get("block") for e in extractions]
    type_unanimous = len(set(types)) == 1
    block_unanimous = len(set(blocks)) == 1

    if consensus >= 0.85 and type_unanimous and block_unanimous:
        status = "OK"
    elif consensus >= 0.6:
        status = "UNSURE"
    else:
        status = "FAIL"

    return CheckVerdict(
        check_name="redundancy",
        status=status,
        details={
            "consensus": round(consensus, 3),
            "n_valid": len(extractions),
            "n_requested": n,
            "type_unanimous": type_unanimous,
            "block_unanimous": block_unanimous,
            "majority_extraction": majority,
        },
        latency_ms=latency,
        extra_calls=extra_calls,
        extra_tokens_in=extra_tokens_in,
        extra_tokens_out=extra_tokens_out,
    )
