#!/usr/bin/env python3
"""Synthetic-example generator.

Calls an OpenAI-compatible endpoint (OpenRouter by default) with one of the
meta-prompts from prompts/meta_*.md, validates the response via the validator
module, and writes passing examples to dataset/synthetic/<slug>.json.

Usage:
    python -m dataset.gen_synthetic --count 3 --mode agent --type refactor
    python -m dataset.gen_synthetic --count 30                  # distribute per default quota
    python -m dataset.gen_synthetic --count 5 --model anthropic/claude-3.5-sonnet

The script is idempotent: each example gets a unique filename; re-runs add more.
Invalid generations are retried up to --max-retries with error feedback injected
into a follow-up message. Hard failures are logged to generation_log.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validator.validate import (  # noqa: E402
    check_semantic,
    check_structural,
    detect_mode,
    load_tool_schemas,
)
from dataset.scenarios import (  # noqa: E402
    DEVELOP, REFACTOR, BUGFIX, RESEARCH, TESTS,
    QUESTION_AXES, PLAIN_TOPICS,
    pick_variation,
)


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

# Default distribution for the "auto" mode (matches the plan)
DEFAULT_QUOTAS = {
    "develop":  12,
    "refactor": 6,
    "bugfix":   6,
    "research": 8,
    "tests":    3,
    "question": 8,
    "plain":    7,
}

# Which type already has one or more hand-crafted seeds — deduct from quota
SEED_TYPE_COUNTS = {
    "develop":  2,  # golden_01, golden_02
    "refactor": 1,  # refactor_01
    "bugfix":   1,  # bugfix_01
    "research": 1,  # research_01
    "tests":    1,  # tests_01
    "question": 1,  # golden_03
    "plain":    1,  # plain_01
}

AGENT_TYPES = {"develop", "refactor", "bugfix", "research", "tests"}


# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------

@dataclass
class GenAttempt:
    attempt: int
    duration_s: float
    tokens_in: int = 0
    tokens_out: int = 0
    errors: list[str] = field(default_factory=list)
    ok: bool = False


@dataclass
class GenRecord:
    slug: str
    mode: str
    type: str | None
    model: str
    provider: str
    attempts: list[GenAttempt] = field(default_factory=list)
    status: str = "pending"  # ok | fail
    out_path: str = ""
    scenario_seed: str = ""


# ------------------------------------------------------------------
# Prompt assembly
# ------------------------------------------------------------------

PROMPTS_DIR = ROOT / "prompts"
SEEDS_DIR = ROOT / "dataset" / "seeds"


def _compact_seed_for_reference(seed_path: Path, max_chars: int = 8000) -> str:
    """Load a seed, strip _meta, pretty-print JSON but cap length."""
    with seed_path.open(encoding="utf-8") as f:
        ex = json.load(f)
    ex.pop("_meta", None)
    txt = json.dumps(ex, ensure_ascii=False, indent=2)
    if len(txt) > max_chars:
        # for very large replan seeds, trim to the first N chars and note truncation
        txt = txt[:max_chars] + "\n...<truncated for prompt size>..."
    return txt


def _find_seed_for_type(task_type: str, rng: random.Random) -> Path:
    """Pick a hand-crafted seed that matches the requested type."""
    candidates: list[Path] = []
    for p in sorted(SEEDS_DIR.glob("*.json")):
        with p.open(encoding="utf-8") as f:
            m = (json.load(f).get("_meta") or {})
        if m.get("type") == task_type:
            candidates.append(p)
    if not candidates:
        # fallback: first develop seed
        for p in sorted(SEEDS_DIR.glob("*.json")):
            with p.open(encoding="utf-8") as f:
                m = (json.load(f).get("_meta") or {})
            if m.get("type") == "develop":
                candidates.append(p)
                break
    if not candidates:
        raise RuntimeError(f"No seed found for type={task_type}")
    return rng.choice(candidates)


def _find_seed_for_mode(mode: str, rng: random.Random) -> Path:
    for p in sorted(SEEDS_DIR.glob("*.json")):
        with p.open(encoding="utf-8") as f:
            m = (json.load(f).get("_meta") or {})
        if m.get("mode") == mode:
            return p
    raise RuntimeError(f"No seed found for mode={mode}")


def _load_meta_prompt(mode: str) -> str:
    fname = {
        "agent": "meta_agent.md",
        "agent_question": "meta_question.md",
        "plain": "meta_plain.md",
    }[mode]
    return (PROMPTS_DIR / fname).read_text(encoding="utf-8")


def _make_task_id(rng: random.Random) -> str:
    return f"t-{rng.randint(1000, 9999)}"


def _fill_agent_prompt(template: str, *, task_type: str, task_id: str, scenario: str,
                       variation: str, include_replan: bool, reference: str) -> str:
    return (template
            .replace("<<TASK_TYPE>>", task_type)
            .replace("<<TASK_ID>>", task_id)
            .replace("<<SCENARIO>>", scenario)
            .replace("<<VARIATION>>", variation)
            .replace("<<INCLUDE_REPLAN>>", "true" if include_replan else "false")
            .replace("<<REFERENCE_EXAMPLE>>", reference))


def _fill_question_prompt(template: str, *, task_id: str, ambiguity_axis: str,
                          variation: str, reference: str) -> str:
    return (template
            .replace("<<TASK_ID>>", task_id)
            .replace("<<AMBIGUITY_AXIS>>", ambiguity_axis)
            .replace("<<VARIATION>>", variation)
            .replace("<<REFERENCE_EXAMPLE>>", reference))


def _fill_plain_prompt(template: str, *, topic: str, angle: str,
                       reference: str) -> str:
    return (template
            .replace("<<TOPIC>>", topic)
            .replace("<<ANGLE>>", angle)
            .replace("<<REFERENCE_EXAMPLE>>", reference))


# ------------------------------------------------------------------
# Provider / API
# ------------------------------------------------------------------

def _resolve_provider(explicit: str, model: str) -> tuple[str, str, str | None, str]:
    """Return (provider, resolved_model, base_url, api_key)."""
    provider = explicit
    if provider == "auto":
        provider = "openrouter" if os.getenv("OPENROUTER_API_KEY") else "openai"

    if provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY") or ""
        base_url = "https://openrouter.ai/api/v1"
        resolved_model = model if "/" in model else f"openai/{model}"
    else:
        api_key = os.getenv("OPENAI_API_KEY") or ""
        base_url = None
        resolved_model = model
    return provider, resolved_model, base_url, api_key


def _call_llm(client, model: str, prompt: str, temperature: float,
              retries: int = 3) -> tuple[str, int, int]:
    last_exc = None
    # For anthropic/* models, skip the Google Vertex route — it 403s Russian
    # KMP prompts. `ignore` is safer than `order`+`allow_fallbacks:false`
    # because direct Anthropic access isn't guaranteed on every account.
    extra_body: dict = {}
    if model.startswith("anthropic/"):
        extra_body = {"provider": {"ignore": ["google-vertex"]}}
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=16000,
                **({"extra_body": extra_body} if extra_body else {}),
            )
            return (resp.choices[0].message.content or "",
                    resp.usage.prompt_tokens,
                    resp.usage.completion_tokens)
        except Exception as e:
            last_exc = e
            wait = 2 ** attempt
            print(f"    transport error (attempt {attempt+1}/{retries}): {e}; "
                  f"retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


# ------------------------------------------------------------------
# Post-processing and validation
# ------------------------------------------------------------------

SYSTEM_PROMPT_AGENT = (PROMPTS_DIR / "system_agent.md").read_text(encoding="utf-8")
SYSTEM_PROMPT_PLAIN = (PROMPTS_DIR / "system_plain.md").read_text(encoding="utf-8")


def _strip_code_fence(txt: str) -> str:
    """If the LLM wrapped output in ```json ... ``` or ``` ... ```, unwrap it."""
    txt = txt.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", txt, flags=re.DOTALL)
    if m:
        return m.group(1).strip()
    return txt


def _parse_and_substitute(raw_text: str, task_id: str | None) -> dict:
    """Parse the LLM response as a JSON example and substitute system-prompt placeholders."""
    obj = json.loads(_strip_code_fence(raw_text))

    msgs = obj.get("messages") or []
    for i, m in enumerate(msgs):
        if m.get("role") != "system":
            continue
        content = m.get("content") or ""
        if "<<SYSTEM_PROMPT_AGENT>>" in content:
            sp = SYSTEM_PROMPT_AGENT.replace("<<TASK_ID>>", task_id or "t-0000")
            msgs[i]["content"] = content.replace("<<SYSTEM_PROMPT_AGENT>>", sp)
        elif "<<SYSTEM_PROMPT_PLAIN>>" in content:
            msgs[i]["content"] = content.replace("<<SYSTEM_PROMPT_PLAIN>>", SYSTEM_PROMPT_PLAIN)

    obj["messages"] = msgs
    return obj


def _validate(example: dict, tools_by_name: dict) -> list[str]:
    issues = check_structural(example) + check_semantic(example, tools_by_name)
    errs = [i for i in issues if i.severity == "error"]
    return [f"{e.code}{' @ ' + e.path if e.path else ''}: {e.message}" for e in errs]


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len] or "example"


# ------------------------------------------------------------------
# One shot
# ------------------------------------------------------------------

def _generate_one(*, client, model: str, mode: str, task_type: str | None,
                  rng: random.Random, tools_by_name: dict, out_dir: Path,
                  include_replan: bool, max_retries: int, temperature: float) -> GenRecord:
    # Pick scenario + reference per mode
    if mode == "agent":
        assert task_type
        scenario_pool = {
            "develop": DEVELOP, "refactor": REFACTOR, "bugfix": BUGFIX,
            "research": RESEARCH, "tests": TESTS,
        }[task_type]
        scenario = rng.choice(scenario_pool)
        variation = pick_variation(rng)
        task_id = _make_task_id(rng)
        reference_path = _find_seed_for_type(task_type, rng)
        reference = _compact_seed_for_reference(reference_path)

        template = _load_meta_prompt("agent")
        prompt = _fill_agent_prompt(template, task_type=task_type, task_id=task_id,
                                    scenario=scenario, variation=variation,
                                    include_replan=include_replan, reference=reference)
        scenario_seed = scenario

    elif mode == "agent_question":
        ambiguity_axis, scenario = rng.choice(QUESTION_AXES)
        variation = pick_variation(rng)
        task_id = _make_task_id(rng)
        reference_path = _find_seed_for_mode("agent_question", rng)
        reference = _compact_seed_for_reference(reference_path)
        template = _load_meta_prompt("agent_question")
        prompt = _fill_question_prompt(template, task_id=task_id,
                                       ambiguity_axis=ambiguity_axis,
                                       variation=variation, reference=reference)
        scenario_seed = scenario
        task_type = None

    elif mode == "plain":
        topic, angle = rng.choice(PLAIN_TOPICS)
        reference_path = _find_seed_for_mode("plain", rng)
        reference = _compact_seed_for_reference(reference_path)
        template = _load_meta_prompt("plain")
        prompt = _fill_plain_prompt(template, topic=topic, angle=angle,
                                    reference=reference)
        task_id = None
        scenario_seed = f"{topic}: {angle}"
        task_type = None
    else:
        raise ValueError(f"Unknown mode {mode}")

    slug_base = _slugify(scenario_seed, max_len=40)
    slug = f"{mode}_{task_type or 'none'}_{slug_base}_{uuid.uuid4().hex[:6]}"
    record = GenRecord(slug=slug, mode=mode, type=task_type, model=model,
                       provider="", scenario_seed=scenario_seed)

    follow_up_errors: list[str] = []
    current_prompt = prompt
    for attempt in range(1, max_retries + 2):  # initial + retries
        att = GenAttempt(attempt=attempt, duration_s=0.0)
        t0 = time.time()
        try:
            if follow_up_errors:
                current_prompt = (
                    prompt +
                    "\n\n---\n\n## Previous attempt was invalid. Fix these errors:\n\n"
                    + "\n".join(f"- {e}" for e in follow_up_errors)
                    + "\n\nProduce a corrected example now. Same rules apply."
                )
            raw, tin, tout = _call_llm(client, model, current_prompt, temperature)
            att.tokens_in = tin
            att.tokens_out = tout

            # Parse & substitute
            obj = _parse_and_substitute(raw, task_id)

            # Inject _meta if missing
            if "_meta" not in obj:
                obj["_meta"] = {}
            obj["_meta"].setdefault("mode", mode)
            if task_type:
                obj["_meta"].setdefault("type", task_type)
            if task_id:
                obj["_meta"].setdefault("task_id", task_id)
            obj["_meta"].setdefault("generated_by", model)
            obj["_meta"].setdefault("scenario_seed", scenario_seed[:160])

            # Validate
            errs = _validate(obj, tools_by_name)
            if errs:
                att.errors = errs
                follow_up_errors = errs
                att.ok = False
                att.duration_s = time.time() - t0
                record.attempts.append(att)
                print(f"    attempt {attempt}: {len(errs)} validation error(s)")
                for e in errs[:5]:
                    print(f"      - {e[:140]}")
                continue

            # Save
            out_path = out_dir / f"{slug}.json"
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            att.ok = True
            att.duration_s = time.time() - t0
            record.attempts.append(att)
            record.status = "ok"
            record.out_path = str(out_path.relative_to(ROOT))
            print(f"    attempt {attempt}: OK -> {out_path.name} "
                  f"(tokens in={tin} out={tout}, {att.duration_s:.1f}s)")
            return record

        except json.JSONDecodeError as e:
            att.errors = [f"JSON parse: {e}"]
            follow_up_errors = att.errors
            att.duration_s = time.time() - t0
            record.attempts.append(att)
            print(f"    attempt {attempt}: could not parse JSON — {e}")
        except Exception as e:  # transport or other
            att.errors = [f"Transport/runtime: {e}"]
            att.duration_s = time.time() - t0
            record.attempts.append(att)
            print(f"    attempt {attempt}: runtime error — {e}")

    record.status = "fail"
    return record


# ------------------------------------------------------------------
# Distribution planner
# ------------------------------------------------------------------

def _plan_distribution(count: int, explicit_type: str | None,
                       rng: random.Random) -> list[tuple[str, str | None]]:
    """Return a list of (mode, task_type_or_None) tuples of length `count`."""
    if explicit_type:
        if explicit_type == "question":
            return [("agent_question", None)] * count
        if explicit_type == "plain":
            return [("plain", None)] * count
        if explicit_type in AGENT_TYPES:
            return [("agent", explicit_type)] * count
        raise ValueError(f"Unknown type: {explicit_type}")

    # Auto distribution matching plan quotas, minus what seeds already cover
    remaining = {t: max(0, q - SEED_TYPE_COUNTS.get(t, 0))
                 for t, q in DEFAULT_QUOTAS.items()}
    total = sum(remaining.values())
    if total == 0:
        raise RuntimeError("All quotas already covered by seeds")
    scale = count / total
    scaled = {t: max(0, int(round(n * scale))) for t, n in remaining.items()}
    # Fix rounding drift
    drift = count - sum(scaled.values())
    if drift != 0:
        # add/subtract to the biggest bucket
        biggest = max(scaled, key=scaled.get)  # type: ignore[arg-type]
        scaled[biggest] = max(0, scaled[biggest] + drift)

    out: list[tuple[str, str | None]] = []
    for t, n in scaled.items():
        for _ in range(n):
            if t == "question":
                out.append(("agent_question", None))
            elif t == "plain":
                out.append(("plain", None))
            else:
                out.append(("agent", t))
    rng.shuffle(out)
    return out


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic training examples")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--type", choices=sorted(list(AGENT_TYPES) + ["question", "plain"]),
                    help="Pin all generations to this type; otherwise distribute per quota")
    ap.add_argument("--model", default="openai/gpt-4o",
                    help="Model name. For direct OpenAI, 'gpt-4o'; for OpenRouter use vendor/model "
                         "(e.g. anthropic/claude-3.5-sonnet)")
    ap.add_argument("--provider", choices=["auto", "openai", "openrouter"], default="auto")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "dataset" / "synthetic")
    ap.add_argument("--contracts", type=Path, default=ROOT / "contracts")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument("--include-replan-ratio", type=float, default=0.25,
                    help="Fraction of agent examples that must include the NEEDS_REPLAN branch")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show the distribution plan and example prompts, no API calls")
    args = ap.parse_args()

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    provider, model, base_url, api_key = _resolve_provider(args.provider, args.model)
    if not args.dry_run and not api_key:
        env_var = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
        print(f"error: {env_var} not set", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed) if args.seed is not None else random.Random()

    tools_by_name = load_tool_schemas(args.contracts)

    dist = _plan_distribution(args.count, args.type, rng)
    replan_count = int(len([d for d in dist if d[0] == "agent"]) * args.include_replan_ratio)
    replan_positions = set(rng.sample([i for i, d in enumerate(dist) if d[0] == "agent"],
                                       min(replan_count,
                                           len([d for d in dist if d[0] == "agent"]))))

    print(f"Provider: {provider}  model: {model}")
    print(f"Output:   {args.out_dir}")
    print(f"Plan:     {len(dist)} examples")
    for i, (m, t) in enumerate(dist):
        replan_marker = " +replan" if i in replan_positions else ""
        print(f"   {i+1:3d}. mode={m:14s} type={t or '—':10s}{replan_marker}")

    if args.dry_run:
        return 0

    from openai import OpenAI
    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)

    log_path = args.out_dir / "generation_log.jsonl"
    records: list[GenRecord] = []
    total_tin = 0
    total_tout = 0

    for i, (m, t) in enumerate(dist):
        print(f"\n[{i+1}/{len(dist)}] mode={m}  type={t}")
        include_replan = (i in replan_positions) and (m == "agent")
        rec = _generate_one(
            client=client, model=model, mode=m, task_type=t,
            rng=rng, tools_by_name=tools_by_name, out_dir=args.out_dir,
            include_replan=include_replan, max_retries=args.max_retries,
            temperature=args.temperature,
        )
        rec.provider = provider
        records.append(rec)
        for att in rec.attempts:
            total_tin += att.tokens_in
            total_tout += att.tokens_out
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

    ok_count = sum(1 for r in records if r.status == "ok")
    print("\n=== Generation summary ===")
    print(f"  planned:  {len(dist)}")
    print(f"  ok:       {ok_count}")
    print(f"  failed:   {len(records) - ok_count}")
    print(f"  tokens:   in={total_tin} out={total_tout}")
    print(f"  log:      {log_path}")

    return 0 if ok_count == len(dist) else 1


if __name__ == "__main__":
    sys.exit(main())
