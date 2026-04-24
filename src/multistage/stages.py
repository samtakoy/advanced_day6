"""Individual stage functions for multi-stage extraction inference."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from src.baseline.run_baseline import call_api
from src.multistage.prompts import STAGE1_ANALYZE, STAGE2_CLASSIFY, STAGE3_EXTRACT


@dataclass
class StageResult:
    stage: str
    output: dict | None = None
    raw: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    error: str | None = None


def _parse_json(text: str) -> dict | None:
    """Extract JSON from LLM response (raw, markdown-fenced, or substring)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    md = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if md:
        try:
            return json.loads(md.group(1))
        except json.JSONDecodeError:
            pass

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass

    return None


def _call_stage(
    stage_name: str,
    system_prompt: str,
    user_content: str,
    client,
    model: str,
    temperature: float,
    num_ctx: int | None = None,
) -> StageResult:
    """Generic: call LLM, parse JSON, return StageResult."""
    t0 = time.perf_counter()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        resp = call_api(client, model, messages, temperature, num_ctx=num_ctx)
    except Exception as e:
        return StageResult(stage=stage_name, error=str(e),
                           latency_ms=(time.perf_counter() - t0) * 1000)

    raw = resp.choices[0].message.content or ""
    parsed = _parse_json(raw)

    return StageResult(
        stage=stage_name,
        output=parsed,
        raw=raw,
        tokens_in=resp.usage.prompt_tokens,
        tokens_out=resp.usage.completion_tokens,
        latency_ms=(time.perf_counter() - t0) * 1000,
        error=None if parsed else "JSON parse failed",
    )


# ---------------------------------------------------------------------------
# Stage 1 — Analyze & Normalize
# ---------------------------------------------------------------------------

def run_analyze(user_text: str, client, model: str,
                temperature: float = 0.2, num_ctx: int | None = None) -> StageResult:
    return _call_stage("analyze", STAGE1_ANALYZE, user_text,
                       client, model, temperature, num_ctx)


# ---------------------------------------------------------------------------
# Stage 2 — Classify (type + block)
# ---------------------------------------------------------------------------

def run_classify(user_text: str, client, model: str,
                 temperature: float = 0.1, num_ctx: int | None = None) -> StageResult:
    return _call_stage("classify", STAGE2_CLASSIFY, user_text,
                       client, model, temperature, num_ctx)


# ---------------------------------------------------------------------------
# Stage 3 — Extract details (title, acceptanceCriteria, outOfScope)
# ---------------------------------------------------------------------------

def run_extract(user_text: str, client, model: str,
                temperature: float = 0.2, num_ctx: int | None = None) -> StageResult:
    return _call_stage("extract", STAGE3_EXTRACT, user_text,
                       client, model, temperature, num_ctx)


# ---------------------------------------------------------------------------
# Stage 4 — Assemble (deterministic merge, no LLM)
# ---------------------------------------------------------------------------

def assemble(analysis: dict, classification: dict, details: dict) -> dict:
    """Merge stage outputs into final 8-field extraction JSON. No LLM call."""
    return {
        "title": details.get("title", ""),
        "type": classification.get("type", ""),
        "block": classification.get("block", ""),
        "modules": analysis.get("modules", []),
        "newModules": analysis.get("newModules", []),
        "dependsOn": analysis.get("dependsOn", []),
        "acceptanceCriteria": details.get("acceptanceCriteria", []),
        "outOfScope": details.get("outOfScope", []),
    }
