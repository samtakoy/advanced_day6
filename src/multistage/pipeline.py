"""Multi-stage pipeline orchestrator.

Chains: analyze → classify → extract → assemble (deterministic).
Compares with monolithic (single-prompt) baseline.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from src.baseline.run_baseline import (
    ExampleMetrics,
    call_api,
    parse_response,
    score,
)
from src.multistage.stages import (
    StageResult,
    assemble,
    run_analyze,
    run_classify,
    run_extract,
)
from src.validator.validate import validate_gold


SUFFIX_BASE = (
    '\n\nВерни ответ в формате JSON с корневым полем "extraction", '
    'содержащим JSON по схеме выше.'
)


@dataclass
class MultistageResult:
    name: str
    # Multi-stage outputs
    stages: list[dict] = field(default_factory=list)
    ms_extraction: dict | None = None
    ms_metrics: ExampleMetrics | None = None
    ms_validation_errors: list[str] = field(default_factory=list)
    ms_tokens_in: int = 0
    ms_tokens_out: int = 0
    ms_latency_ms: float = 0.0
    ms_error: str | None = None
    # Monolithic outputs
    mono_extraction: dict | None = None
    mono_metrics: ExampleMetrics | None = None
    mono_validation_errors: list[str] = field(default_factory=list)
    mono_tokens_in: int = 0
    mono_tokens_out: int = 0
    mono_latency_ms: float = 0.0
    mono_raw: str = ""
    mono_error: str | None = None


def run_monolithic(
    name: str,
    system_content: str,
    user_text: str,
    gold: dict,
    client,
    model: str,
    temperature: float,
    num_ctx: int | None = None,
) -> tuple[dict | None, ExampleMetrics, list[str], int, int, float, str]:
    """Run single-prompt (monolithic) extraction."""
    t0 = time.perf_counter()

    system_prompt = system_content + SUFFIX_BASE
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    resp = call_api(client, model, messages, temperature, num_ctx=num_ctx)
    raw = resp.choices[0].message.content or ""
    predicted, _, _ = parse_response(raw)

    latency = (time.perf_counter() - t0) * 1000

    if predicted is not None:
        m = score(gold, predicted)
        m.name = name
        verr = validate_gold(predicted, name)
    else:
        m = ExampleMetrics(name=name, gold=gold, error="JSON parse failed")
        verr = ["JSON parse failed"]

    m.tokens_in = resp.usage.prompt_tokens
    m.tokens_out = resp.usage.completion_tokens

    return predicted, m, verr, resp.usage.prompt_tokens, resp.usage.completion_tokens, latency, raw


def _add_stage(result: MultistageResult, sr: StageResult) -> None:
    """Append stage result and accumulate tokens/latency."""
    result.stages.append(asdict(sr))
    result.ms_tokens_in += sr.tokens_in
    result.ms_tokens_out += sr.tokens_out
    result.ms_latency_ms += sr.latency_ms


def run_multistage(
    name: str,
    system_content: str,
    user_text: str,
    gold: dict,
    client,
    model: str,
    temperature: float = 0.3,
    num_ctx: int | None = None,
    run_mono: bool = True,
) -> MultistageResult:
    """Run full multi-stage pipeline + optional monolithic comparison."""
    result = MultistageResult(name=name)

    # ── Stage 1: Analyze (modules, deps) ──
    s1 = run_analyze(user_text, client, model, temperature=temperature, num_ctx=num_ctx)
    _add_stage(result, s1)

    if s1.error or s1.output is None:
        result.ms_error = f"stage analyze failed: {s1.error}"
        if run_mono:
            _run_mono_into(result, name, system_content, user_text, gold,
                           client, model, temperature, num_ctx)
        return result

    # ── Stage 2: Classify (type, block) ──
    s2 = run_classify(user_text, client, model, temperature=temperature, num_ctx=num_ctx)
    _add_stage(result, s2)

    if s2.error or s2.output is None:
        result.ms_error = f"stage classify failed: {s2.error}"
        if run_mono:
            _run_mono_into(result, name, system_content, user_text, gold,
                           client, model, temperature, num_ctx)
        return result

    # ── Stage 3: Extract (title, acceptanceCriteria, outOfScope) ──
    s3 = run_extract(user_text, client, model, temperature=temperature, num_ctx=num_ctx)
    _add_stage(result, s3)

    if s3.error or s3.output is None:
        result.ms_error = f"stage extract failed: {s3.error}"
        if run_mono:
            _run_mono_into(result, name, system_content, user_text, gold,
                           client, model, temperature, num_ctx)
        return result

    # ── Stage 4: Assemble (deterministic merge, no LLM) ──
    t0 = time.perf_counter()
    extraction = assemble(s1.output, s2.output, s3.output)
    assemble_ms = (time.perf_counter() - t0) * 1000
    result.stages.append({"stage": "assemble", "latency_ms": assemble_ms})
    result.ms_latency_ms += assemble_ms

    result.ms_extraction = extraction
    m = score(gold, extraction)
    m.name = name
    m.tokens_in = result.ms_tokens_in
    m.tokens_out = result.ms_tokens_out
    result.ms_metrics = m
    result.ms_validation_errors = validate_gold(extraction, name)

    # ── Monolithic for comparison ──
    if run_mono:
        _run_mono_into(result, name, system_content, user_text, gold,
                       client, model, temperature, num_ctx)

    return result


def _run_mono_into(
    result: MultistageResult,
    name: str,
    system_content: str,
    user_text: str,
    gold: dict,
    client,
    model: str,
    temperature: float,
    num_ctx: int | None,
) -> None:
    """Run monolithic inference and populate result fields."""
    try:
        pred, m, verr, tin, tout, lat, raw = run_monolithic(
            name, system_content, user_text, gold, client, model, temperature, num_ctx)
        result.mono_extraction = pred
        result.mono_metrics = m
        result.mono_validation_errors = verr
        result.mono_tokens_in = tin
        result.mono_tokens_out = tout
        result.mono_latency_ms = lat
        result.mono_raw = raw
    except Exception as e:
        result.mono_error = str(e)
