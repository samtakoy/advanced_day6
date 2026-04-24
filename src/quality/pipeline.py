"""Pipeline orchestrator — runs selected checks with retry logic.

Flow:
    Input → LLM call → Extraction JSON
      ↓
    1. Constraint check (free, catches structural errors)
       FAIL → retry up to max_retries → all FAIL → REJECTED
      ↓
    2. Redundancy check (N-1 extra calls)
       FAIL → REJECTED
      ↓
    3. Scoring check (1 extra call)
       FAIL → ACCEPTED_WITH_WARNINGS
      ↓
    Final: ACCEPTED / ACCEPTED_WITH_WARNINGS / REJECTED
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict

from src.quality.models import CheckVerdict, PipelineConfig, PipelineResult
from src.quality.checks import constraint, redundancy, scoring, scoring_cot


def _parse_json(content: str) -> dict | None:
    if not content:
        return None
    try:
        obj = json.loads(content)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, TypeError):
        pass
    # Closed markdown block: ```json ... ```
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    # First { to last }
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


def _call_llm(client, model: str, messages: list[dict],
              temperature: float, num_ctx: int | None = None) -> tuple[dict | None, int, int, str]:
    """Call LLM and return (parsed_json, tokens_in, tokens_out, raw_content)."""
    kwargs: dict = dict(model=model, messages=messages, temperature=temperature)
    if num_ctx is not None:
        kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}}

    resp = client.chat.completions.create(**kwargs)
    tokens_in = resp.usage.prompt_tokens if resp.usage else 0
    tokens_out = resp.usage.completion_tokens if resp.usage else 0
    content = resp.choices[0].message.content or ""
    parsed = _parse_json(content)
    if parsed and not isinstance(parsed, dict):
        parsed = None
    return parsed, tokens_in, tokens_out, content


def run_pipeline(
    name: str,
    messages: list[dict],
    client,
    model: str,
    temperature: float,
    config: PipelineConfig,
    gold: dict | None = None,
    num_ctx: int | None = None,
    score_fn=None,
) -> PipelineResult:
    """Run the full quality pipeline for one example.

    Args:
        name: Example identifier.
        messages: [system, user] messages to send to the model.
        client: OpenAI-compatible API client.
        model: Model name.
        temperature: Base temperature for initial call.
        config: Pipeline configuration.
        gold: Optional gold extraction for scoring against.
        num_ctx: Context window size (Ollama only).
        score_fn: Optional scoring function (gold, predicted) -> metrics dict.
    """
    t0 = time.perf_counter()
    result = PipelineResult(name=name)

    # --- Initial LLM call ---
    extraction = None
    attempt = 0
    max_attempts = config.max_retries + 1

    all_verdicts: list[CheckVerdict] = []
    total_calls = 0
    total_tok_in = 0
    total_tok_out = 0

    while attempt < max_attempts:
        attempt += 1
        result.attempts = attempt

        try:
            extraction, tok_in, tok_out, raw = _call_llm(
                client, model, messages, temperature, num_ctx)
            total_calls += 1
            total_tok_in += tok_in
            total_tok_out += tok_out
        except Exception as e:
            result.error = f"LLM call failed: {e}"
            result.status = "REJECTED"
            break

        if extraction is None:
            # JSON parse failed — try to get a useful error message
            parse_error = "JSON parse failed"
            try:
                # Try to extract JSON substring to get specific error
                first_brace = raw.find("{")
                last_brace = raw.rfind("}")
                if first_brace != -1 and last_brace > first_brace:
                    json.loads(raw[first_brace:last_brace + 1])
            except json.JSONDecodeError as e:
                parse_error = f"JSON parse failed: {e.msg} (pos {e.pos})"

            if "constraint" in config.checks:
                v = CheckVerdict(
                    check_name="constraint", status="FAIL",
                    details={"schema_errors": [parse_error],
                             "invariant_warnings": []})
                all_verdicts.append(v)
                print(f"  [{name}] attempt {attempt}: {parse_error}\n"
                      f"    raw response (first 300): {raw[:300]}")
                continue
            else:
                result.error = "JSON parse failed"
                result.status = "REJECTED"
                break

        # --- Constraint check ---
        if "constraint" in config.checks:
            v = constraint.run(extraction)
            all_verdicts.append(v)

            if v.status == "FAIL":
                print(f"  [{name}] attempt {attempt}: constraint FAIL, retrying...")
                extraction = None
                continue
            # UNSURE or OK — proceed to next checks
        break  # No constraint FAIL, exit retry loop

    if extraction is None and result.status != "REJECTED":
        result.status = "REJECTED"
        result.error = result.error or "All attempts failed constraint check"

    if extraction is not None:
        result.final_extraction = extraction

        # --- Redundancy check ---
        if "redundancy" in config.checks and client:
            from src.validator.validate import validate_gold as _validate_gold
            v = redundancy.run(
                extraction,
                client=client,
                model=model,
                messages=messages,
                temperature=config.redundancy_temperature,
                n=config.redundancy_n,
                num_ctx=num_ctx,
                gold=gold,
                validate_fn=_validate_gold,
                score_fn=score_fn,
            )
            all_verdicts.append(v)
            total_calls += v.extra_calls
            total_tok_in += v.extra_tokens_in
            total_tok_out += v.extra_tokens_out

            # Use majority extraction if available
            if v.details.get("majority_extraction"):
                result.final_extraction = v.details["majority_extraction"]

            if v.status == "FAIL":
                result.status = "REJECTED"

        # --- Scoring check ---
        if "scoring" in config.checks and client and (config.run_all_checks or result.status != "REJECTED"):
            v = scoring.run(
                result.final_extraction,
                client=client,
                model=model,
                messages=messages,
                temperature=config.scoring_temperature,
                num_ctx=num_ctx,
            )
            all_verdicts.append(v)
            total_calls += v.extra_calls
            total_tok_in += v.extra_tokens_in
            total_tok_out += v.extra_tokens_out

        # --- Scoring COT check ---
        if "scoring_cot" in config.checks and client and (config.run_all_checks or result.status != "REJECTED"):
            v = scoring_cot.run(
                result.final_extraction,
                client=client,
                model=model,
                messages=messages,
                temperature=config.scoring_temperature,
                num_ctx=num_ctx,
            )
            all_verdicts.append(v)
            total_calls += v.extra_calls
            total_tok_in += v.extra_tokens_in
            total_tok_out += v.extra_tokens_out

        # --- Determine final status ---
        if result.status != "REJECTED":
            statuses = [v.status for v in all_verdicts]
            if "FAIL" in statuses:
                result.status = "REJECTED"
            elif "UNSURE" in statuses:
                result.status = "ACCEPTED_WITH_WARNINGS"
            else:
                result.status = "ACCEPTED"

    # --- Score against gold if available ---
    if gold and result.final_extraction and score_fn:
        metrics = score_fn(gold, result.final_extraction)
        result.baseline_metrics = asdict(metrics) if hasattr(metrics, '__dataclass_fields__') else metrics

    result.verdicts = all_verdicts
    result.total_api_calls = total_calls
    result.total_tokens_in = total_tok_in
    result.total_tokens_out = total_tok_out
    result.total_latency_ms = (time.perf_counter() - t0) * 1000

    return result
