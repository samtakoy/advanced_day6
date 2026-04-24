"""Model routing — cheap model first, escalate to strong on low confidence.

Escalation heuristics:
  1. JSON parse failed (free)
  2. Constraint check FAIL — schema / domain errors (free)
  3. Self-check confidence — model explains reasoning + scores itself (embedded in prompt)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.baseline.run_baseline import (
    ExampleMetrics,
    build_system_prompt,
    call_api,
    parse_response,
    score,
)
from src.quality.checks.constraint import run as constraint_run


@dataclass
class RouterConfig:
    cheap_model: str = "qwen2.5:7b-instruct"
    strong_model: str = "gpt-oss:20b"
    temperature: float = 0.3
    num_ctx: int | None = None
    use_self_check: bool = False


@dataclass
class RoutingResult:
    name: str
    routed_to: str = "cheap"                       # "cheap" | "strong"
    escalation_reasons: list[str] = field(default_factory=list)
    extraction: dict | None = None
    metrics: ExampleMetrics | None = None
    cheap_raw: str | None = None
    strong_raw: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    cheap_tokens_in: int = 0
    cheap_tokens_out: int = 0
    strong_tokens_in: int = 0
    strong_tokens_out: int = 0


def route_example(
    name: str,
    messages: list[dict],
    gold: dict,
    client,
    config: RouterConfig,
) -> RoutingResult:
    """Route a single example through cheap → (maybe) strong model.

    Args:
        name: Example identifier.
        messages: [system_msg, user_msg] — raw from eval.jsonl.
        gold: Gold extraction dict.
        client: OpenAI-compatible client.
        config: Router configuration.

    Returns:
        RoutingResult with routing decision, extraction, and metrics.
    """
    t0 = time.perf_counter()
    result = RoutingResult(name=name)
    reasons: list[str] = []

    # --- Build system prompt ---
    system_content = messages[0]["content"]
    system_prompt = build_system_prompt(
        system_content, self_score=False, self_explain=config.use_self_check)

    prompt_msgs = [
        {"role": "system", "content": system_prompt},
        {"role": messages[1]["role"], "content": messages[1]["content"]},
    ]

    # --- Step 1: Call cheap model ---
    resp = call_api(client, config.cheap_model, prompt_msgs, config.temperature,
                    num_ctx=config.num_ctx)

    cheap_content = resp.choices[0].message.content or ""
    result.cheap_raw = cheap_content
    result.cheap_tokens_in = resp.usage.prompt_tokens
    result.cheap_tokens_out = resp.usage.completion_tokens

    predicted, confidence, _reasoning = parse_response(cheap_content)

    # --- Step 2: Escalation heuristics ---

    # Heuristic 1: JSON parse failed
    if predicted is None:
        reasons.append("json_parse_failed")

    # Heuristic 2: Constraint check
    if predicted is not None:
        verdict = constraint_run(predicted)
        if verdict.status in ("FAIL", "UNSURE"):
            reasons.append(f"constraint_{verdict.status.lower()}: {verdict.details.get('schema_errors', []) or verdict.details.get('invariant_warnings', [])}")

    # Heuristic 3: Self-check confidence
    if config.use_self_check and predicted is not None and confidence is not None:
        conf_upper = str(confidence).upper()
        if conf_upper in ("UNSURE", "FAIL"):
            reasons.append(f"self_check_{conf_upper.lower()}")

    # --- Step 3: Escalate or accept ---
    if reasons:
        result.routed_to = "strong"
        result.escalation_reasons = reasons

        # Strong model always gets self_explain for better chain-of-thought
        strong_system = build_system_prompt(system_content, self_score=False, self_explain=True)
        strong_msgs = [
            {"role": "system", "content": strong_system},
            {"role": messages[1]["role"], "content": messages[1]["content"]},
        ]

        resp_strong = call_api(client, config.strong_model, strong_msgs, config.temperature,
                               num_ctx=config.num_ctx)
        strong_content = resp_strong.choices[0].message.content or ""
        result.strong_raw = strong_content
        result.strong_tokens_in = resp_strong.usage.prompt_tokens
        result.strong_tokens_out = resp_strong.usage.completion_tokens

        predicted_strong, _conf, _reas = parse_response(strong_content)
        if predicted_strong is not None:
            predicted = predicted_strong
        # If strong also fails to parse, keep cheap result (or None)

    # --- Step 4: Score vs gold ---
    if predicted is not None:
        result.extraction = predicted
        result.metrics = score(gold, predicted)
        result.metrics.name = name
    else:
        result.extraction = None
        result.metrics = ExampleMetrics(name=name, error="JSON parse failed on both models")

    # --- Totals ---
    result.tokens_in = result.cheap_tokens_in + result.strong_tokens_in
    result.tokens_out = result.cheap_tokens_out + result.strong_tokens_out
    result.latency_ms = (time.perf_counter() - t0) * 1000

    return result
