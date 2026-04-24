#!/usr/bin/env python3
"""Run baseline evaluation for extraction fine-tune dataset.

Day 6 mode: sends system+user from eval.jsonl, parses JSON, scores vs gold.
Day 7 mode: adds confidence estimation via --self-score, --self-explain,
            and external checks via --checks constraint,redundancy.

Usage:
    # Day 6 baseline
    python -m src.baseline.run_baseline --dry-run
    python -m src.baseline.run_baseline
    python -m src.baseline.run_baseline --provider ollama --model qwen2.5:14b-instruct

    # Day 7 — self-score
    python -m src.baseline.run_baseline --self-score
    python -m src.baseline.run_baseline --self-explain

    # Day 7 — with external checks
    python -m src.baseline.run_baseline --self-score --checks constraint,redundancy
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils import model_slug  # noqa: E402
from src.validator.validate import validate_gold  # noqa: E402

VALID_CHECKS = {"constraint", "redundancy"}

# --- Prompt suffixes for Day 7 modes ---

SUFFIX_BASE = (
    '\n\nВерни ответ в формате JSON с корневым полем "extraction", '
    'содержащим JSON по схеме выше.'
)

SUFFIX_SELF_SCORE = (
    '\nВерни ответ строго в таком формате:\n'
    '{\n'
    '  "extraction": { ...8 полей по схеме... },\n'
    '  "confidence": "OK"\n'
    '}\n'
    'confidence — оценка уверенности:\n'
    '- OK — все поля извлечены однозначно из текста, правила соблюдены.\n'
    '- UNSURE — есть сомнения в каком-либо поле.\n'
    '- FAIL — описание слишком короткое или непонятное для извлечения.'
)

SUFFIX_SELF_EXPLAIN = (
    '\nВерни ответ строго в таком формате:\n'
    '{\n'
    '  "extraction": { ...8 полей по схеме... },\n'
    '  "reasoning": "...",\n'
    '  "confidence": "OK | UNSURE | FAIL"\n'
    '}\n'
    'Подумай, насколько хорошо твоё решение. В поле reasoning положи объяснение '
    'логики своего решения, какие поля вызывают сомнения, '
    'и почему ты выбрал такую оценку confidence.\n'
    'В поле confidence положи оценку своей уверенности в правильности ответа:\n'
    '- OK — все поля извлечены однозначно из текста, правила соблюдены.\n'
    '- UNSURE — есть сомнения в каком-либо поле.\n'
    '- FAIL — описание слишком короткое или непонятное для извлечения.'
)


# --- Data classes ---

@dataclass
class ExampleMetrics:
    name: str
    json_valid: bool = False
    type_match: bool = False
    block_match: bool = False
    modules_iou: float = 0.0
    new_modules_iou: float = 0.0
    depends_on_iou: float = 0.0
    ac_recall: float = 0.0
    oos_precision: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    validation_errors: list[str] = field(default_factory=list)
    error: str | None = None
    gold: dict = field(default_factory=dict)
    predicted: dict = field(default_factory=dict)


# --- Helpers ---

def iou(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 1.0


def load_eval(jsonl_path: Path) -> list[tuple[str, list[dict]]]:
    """Load examples from eval JSONL. Returns [(name, messages)]."""
    out = []
    with jsonl_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            ex = json.loads(line)
            out.append((f"eval_{i:02d}", ex["messages"]))
    return out


def score(gold: dict, predicted: dict) -> ExampleMetrics:
    m = ExampleMetrics(name="")
    m.json_valid = True
    m.gold = gold
    m.predicted = predicted

    m.type_match = gold.get("type") == predicted.get("type")
    m.block_match = gold.get("block") == predicted.get("block")

    gold_modules = set(gold.get("modules", []))
    pred_modules = set(predicted.get("modules", []))
    m.modules_iou = iou(gold_modules, pred_modules)

    gold_new = set(gold.get("newModules", []))
    pred_new = set(predicted.get("newModules", []))
    m.new_modules_iou = iou(gold_new, pred_new)

    gold_deps = set(gold.get("dependsOn", []))
    pred_deps = set(predicted.get("dependsOn", []))
    m.depends_on_iou = iou(gold_deps, pred_deps)

    gold_ac = gold.get("acceptanceCriteria", [])
    pred_ac = predicted.get("acceptanceCriteria", [])
    if gold_ac:
        matched = sum(1 for g in gold_ac if g in pred_ac)
        m.ac_recall = matched / len(gold_ac)
    else:
        m.ac_recall = 1.0 if not pred_ac else 0.0

    gold_oos = set(predicted.get("outOfScope", []))
    pred_oos_list = predicted.get("outOfScope", [])
    if pred_oos_list:
        correct = sum(1 for p in pred_oos_list if p in gold.get("outOfScope", []))
        m.oos_precision = correct / len(pred_oos_list)
    else:
        m.oos_precision = 1.0

    return m


def call_api(client, model: str, messages: list[dict],
             temperature: float, num_ctx: int | None = None,
             retries: int = 3):
    last_err = None
    kwargs: dict = dict(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    if num_ctx is not None:
        kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}}
    for attempt in range(retries):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            print(f"  API error (attempt {attempt+1}/{retries}): {e}; retrying in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    raise last_err  # type: ignore[misc]


def parse_response(content: str) -> tuple[dict | None, str | None, str | None]:
    """Parse model response. Returns (predicted, confidence, reasoning).

    Always looks for 'extraction' wrapper. Falls back to raw JSON.
    """
    parsed = None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        if parsed is None:
            first = content.find("{")
            last = content.rfind("}")
            if first != -1 and last > first:
                try:
                    parsed = json.loads(content[first:last + 1])
                except json.JSONDecodeError:
                    pass

    if parsed is None or not isinstance(parsed, dict):
        return None, None, None

    if "extraction" in parsed and isinstance(parsed["extraction"], dict):
        predicted = parsed["extraction"]
        confidence = parsed.get("confidence")
        reasoning = parsed.get("reasoning")
    else:
        predicted = parsed
        confidence = None
        reasoning = None

    return predicted, confidence, reasoning


def build_system_prompt(base_content: str, self_score: bool, self_explain: bool) -> str:
    """Append Day 7 suffixes to the base system prompt."""
    prompt = base_content + SUFFIX_BASE
    if self_score:
        prompt += SUFFIX_SELF_SCORE
    if self_explain:
        prompt += SUFFIX_SELF_EXPLAIN
    return prompt


# --- Main ---

def main() -> int:
    ap = argparse.ArgumentParser(description="Run extraction baseline evaluation")
    ap.add_argument("--from-jsonl", type=Path,
                    default=ROOT / "data" / "out" / "eval.jsonl",
                    help="Eval JSONL file")
    ap.add_argument("--out-dir", type=Path,
                    default=ROOT / "data" / "baseline")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--provider", choices=["auto", "openai", "openrouter", "ollama"],
                    default="auto")
    ap.add_argument("--num-ctx", type=int, default=None,
                    help="Context window size (Ollama only).")
    # Day 7 flags
    ap.add_argument("--self-score", action="store_true",
                    help="Ask model to return confidence (OK/UNSURE/FAIL) with extraction")
    ap.add_argument("--self-explain", action="store_true",
                    help="Ask model to explain reasoning with extraction")
    ap.add_argument("--checks", default=None,
                    help="External checks: constraint,redundancy (comma-separated)")
    args = ap.parse_args()

    # Parse checks
    checks: list[str] = []
    if args.checks:
        checks = [c.strip() for c in args.checks.split(",")]
        for c in checks:
            if c not in VALID_CHECKS:
                print(f"error: unknown check '{c}'. Valid: {sorted(VALID_CHECKS)}",
                      file=sys.stderr)
                return 2

    day7_mode = args.self_score or args.self_explain or bool(checks)

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    provider = args.provider
    if provider == "auto":
        provider = "openrouter" if os.getenv("OPENROUTER_API_KEY") else "openai"

    if provider == "ollama":
        api_key = "ollama"
        base_url = "http://localhost:11434/v1"
        model = args.model
    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
        model = args.model if "/" in args.model else f"openai/{args.model}"
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = None
        model = args.model

    if not args.dry_run and not api_key:
        env_var = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
        print(f"error: {env_var} not set", file=sys.stderr)
        return 2

    source = args.from_jsonl.stem
    out_dir = args.out_dir / source / model_slug(args.model)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.from_jsonl.is_file():
        print(f"error: {args.from_jsonl} not found — run build_dataset.py first",
              file=sys.stderr)
        return 2

    examples = load_eval(args.from_jsonl)
    if args.limit:
        examples = examples[:args.limit]

    if not examples:
        print("error: no examples loaded", file=sys.stderr)
        return 1

    client = None
    if not args.dry_run:
        from openai import OpenAI
        if base_url:
            client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            client = OpenAI(api_key=api_key)
        print(f"Provider: {provider}  model: {model}")
        if day7_mode:
            flags = []
            if args.self_score:
                flags.append("self-score")
            if args.self_explain:
                flags.append("self-explain")
            if checks:
                flags.append(f"checks={','.join(checks)}")
            print(f"Day 7 mode: {', '.join(flags)}")

    metrics_list: list[ExampleMetrics] = []
    # Day 7 extras stored per-example
    confidence_list: list[str | None] = []
    reasoning_list: list[str | None] = []
    checks_list: list[dict | None] = []
    rejected_list: list[bool] = []
    retried_list: list[bool] = []
    latency_list: list[float] = []  # ms per example

    for name, messages in examples:
        prompt_msgs = [
            {"role": messages[0]["role"], "content": messages[0]["content"]},
            {"role": messages[1]["role"], "content": messages[1]["content"]},
        ]
        gold = json.loads(messages[2]["content"])

        # Build system prompt with Day 7 suffixes
        if day7_mode:
            prompt_msgs[0] = {
                "role": "system",
                "content": build_system_prompt(
                    messages[0]["content"], args.self_score, args.self_explain),
            }

        print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")

        t_start = time.perf_counter()

        if args.dry_run:
            print(f"  would call {model} via {provider}, temperature={args.temperature}")
            confidence_list.append(None)
            reasoning_list.append(None)
            checks_list.append(None)
            rejected_list.append(False)
            retried_list.append(False)
            latency_list.append(0)
            continue

        try:
            resp = call_api(client, model, prompt_msgs, args.temperature,
                           num_ctx=args.num_ctx)
        except Exception as e:
            print(f"  [ERROR] {e}", file=sys.stderr)
            m = ExampleMetrics(name=name, error=str(e))
            metrics_list.append(m)
            confidence_list.append(None)
            reasoning_list.append(None)
            checks_list.append(None)
            rejected_list.append(True)
            retried_list.append(False)
            latency_list.append((time.perf_counter() - t_start) * 1000)
            continue

        content = resp.choices[0].message.content or ""
        predicted, confidence, reasoning = parse_response(content)

        if predicted is not None and isinstance(predicted, dict):
            m = score(gold, predicted)
            m.validation_errors = validate_gold(predicted, name)
        else:
            m = ExampleMetrics(name=name, gold=gold)
            m.error = "JSON parse failed"
            m.validation_errors = ["JSON parse failed"]

        m.name = name
        m.tokens_in = resp.usage.prompt_tokens
        m.tokens_out = resp.usage.completion_tokens
        metrics_list.append(m)
        confidence_list.append(confidence)
        reasoning_list.append(reasoning)

        # --- External checks ---
        check_results: dict = {}
        rejected = False
        retried = False

        if predicted is not None and "constraint" in checks:
            from src.quality.checks.constraint import run as constraint_run
            cv = constraint_run(predicted)
            check_results["constraint"] = asdict(cv)
            if cv.status == "FAIL":
                rejected = True

        # Redundancy: only if validation failed (retry to get a better answer)
        if "redundancy" in checks:
            needs_retry = (
                predicted is None
                or bool(m.validation_errors)
                or not m.json_valid
            )

            if needs_retry:
                retried = True
                from src.quality.checks.redundancy import run as redundancy_run

                rv = redundancy_run(
                    predicted,
                    client=client,
                    model=model,
                    messages=prompt_msgs,
                    temperature=args.temperature,
                    gold=gold,
                    validate_fn=validate_gold,
                    score_fn=score,
                    num_ctx=args.num_ctx,
                )
                check_results["redundancy"] = asdict(rv)

                # Pick the best valid attempt if it improves on the original
                best_predicted = predicted
                best_iou = m.modules_iou if m.json_valid else -1.0
                upgraded = False
                for attempt in rv.details.get("attempts", []):
                    if not attempt.get("valid") or not attempt.get("parsed"):
                        continue
                    vs = attempt.get("vs_gold", {})
                    attempt_iou = vs.get("modules_iou", 0)
                    if attempt_iou > best_iou:
                        best_iou = attempt_iou
                        best_predicted = attempt.get("extraction")
                        upgraded = True

                if upgraded and best_predicted:
                    m_new = score(gold, best_predicted)
                    m_new.name = m.name
                    m_new.tokens_in = m.tokens_in
                    m_new.tokens_out = m.tokens_out
                    m_new.validation_errors = validate_gold(best_predicted, name)
                    check_results["redundancy_upgrade"] = {
                        "original_modules_iou": m.modules_iou,
                        "upgraded_modules_iou": m_new.modules_iou,
                    }
                    metrics_list[-1] = m_new
                    m = m_new
                    predicted = best_predicted
                    rejected = False  # upgrade saved it
            else:
                check_results["redundancy"] = {"skipped": True, "reason": "validation passed"}

        checks_list.append(check_results if check_results else None)
        latency_ms = (time.perf_counter() - t_start) * 1000
        latency_list.append(latency_ms)
        rejected_list.append(rejected)
        retried_list.append(retried)

        # --- Console output ---
        print(f"  json_valid={m.json_valid}  type={m.type_match}  block={m.block_match}")
        print(f"  modules_iou={m.modules_iou:.2f}  new_modules_iou={m.new_modules_iou:.2f}  deps_iou={m.depends_on_iou:.2f}")
        print(f"  ac_recall={m.ac_recall:.2f}  oos_precision={m.oos_precision:.2f}")
        if m.validation_errors:
            print(f"  validation_errors={len(m.validation_errors)}")
            for ve in m.validation_errors[:5]:
                print(f"    - {ve}")
        if confidence is not None:
            print(f"  self-confidence: {confidence}")
        if reasoning is not None:
            r_str = reasoning if isinstance(reasoning, str) else json.dumps(reasoning, ensure_ascii=False)
            print(f"  self-reasoning: {r_str[:200]}")
        if check_results:
            for ck_name, ck_data in check_results.items():
                status = ck_data.get("status", "?")
                if ck_name == "constraint":
                    errs = ck_data.get("details", {}).get("schema_errors", [])
                    warns = ck_data.get("details", {}).get("invariant_warnings", [])
                    print(f"  check.constraint: {status}  errors={len(errs)} warnings={len(warns)}")
                elif ck_name == "redundancy":
                    details = ck_data.get("details", {})
                    n_passed = details.get("n_passed", "?")
                    n_total = details.get("n_total", "?")
                    print(f"  check.redundancy: {status}  passed={n_passed}/{n_total}")
                    for a in details.get("attempts", []):
                        temp = a.get("temperature", "?")
                        if not a.get("parsed"):
                            print(f"    T={temp}: JSON parse failed")
                            continue
                        passed = "PASS" if a.get("pass") else "FAIL"
                        vs = a.get("vs_gold", {})
                        gold_str = ""
                        if vs:
                            gold_str = (f" modules_iou={vs.get('modules_iou', 0):.2f}"
                                        f" type={'ok' if vs.get('type_match') else 'MISS'}"
                                        f" block={'ok' if vs.get('block_match') else 'MISS'}")
                        failed = a.get("failed_fields", [])
                        fail_str = f"  [{', '.join(failed)}]" if failed else ""
                        print(f"    T={temp}: {passed}  schema={'yes' if a.get('valid') else 'NO'}"
                              f"{gold_str}{fail_str}")
                elif ck_name == "redundancy_upgrade":
                    orig = ck_data.get("original_modules_iou", 0)
                    upgraded = ck_data.get("upgraded_modules_iou", 0)
                    print(f"  >> redundancy upgrade: modules_iou {orig:.2f} → {upgraded:.2f}")
        if rejected:
            print(f"  REJECTED")
        if retried:
            print(f"  retried via redundancy")
        print(f"  tokens in={m.tokens_in} out={m.tokens_out}  latency={latency_ms:.0f}ms")

        # Save per-example JSON
        raw_path = out_dir / f"{name}.json"
        example_data: dict = {
            "name": name,
            "provider": provider,
            "model": model,
            "temperature": args.temperature,
            "input_messages": prompt_msgs,
            "response_content": content,
            "gold": gold,
            "predicted": predicted,
            "metrics": {
                "json_valid": m.json_valid,
                "type_match": m.type_match,
                "block_match": m.block_match,
                "modules_iou": m.modules_iou,
                "new_modules_iou": m.new_modules_iou,
                "depends_on_iou": m.depends_on_iou,
                "ac_recall": m.ac_recall,
                "oos_precision": m.oos_precision,
            },
            "validation_errors": m.validation_errors,
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            },
        }
        if confidence is not None:
            example_data["confidence"] = confidence
        if reasoning is not None:
            example_data["reasoning"] = reasoning
        if check_results:
            example_data["checks"] = check_results
        with raw_path.open("w", encoding="utf-8") as f:
            json.dump(example_data, f, ensure_ascii=False, indent=2)

    if args.dry_run:
        print("\n(dry run — no outputs written)")
        return 0

    # --- Aggregate summary ---
    if not metrics_list:
        return 0

    n = len(metrics_list)
    valid = [m for m in metrics_list if not m.error]
    nv = len(valid)

    print("\n=== Summary ===")
    print(f"  examples: {n}  (errors: {n - nv})")
    if nv:
        print(f"  JSON parse:   {sum(1 for m in valid if m.json_valid)}/{nv}")
        print(f"  type match:   {sum(1 for m in valid if m.type_match)}/{nv}")
        print(f"  block match:  {sum(1 for m in valid if m.block_match)}/{nv}")
        print(f"  modules IoU:  {sum(m.modules_iou for m in valid)/nv:.3f} (avg)")
        print(f"  newMods IoU:  {sum(m.new_modules_iou for m in valid)/nv:.3f} (avg)")
        print(f"  deps IoU:     {sum(m.depends_on_iou for m in valid)/nv:.3f} (avg)")
        print(f"  AC recall:    {sum(m.ac_recall for m in valid)/nv:.3f} (avg)")
        print(f"  OoS precision:{sum(m.oos_precision for m in valid)/nv:.3f} (avg)")
        schema_ok = sum(1 for m in metrics_list if not m.validation_errors)
        total_ve = sum(len(m.validation_errors) for m in metrics_list)
        print(f"  schema valid: {schema_ok}/{n}")
        print(f"  validation errors total: {total_ve}")

    # Day 7 quality metrics
    n_rejected = sum(rejected_list)
    n_retried = sum(retried_list)
    avg_latency = sum(latency_list) / len(latency_list) if latency_list else 0
    print(f"\n  rejected: {n_rejected}/{n}")
    print(f"  retried (redundancy): {n_retried}/{n}")
    print(f"  avg latency: {avg_latency:.0f}ms")

    # Day 7 confidence summary
    conf_values = [c for c in confidence_list if c is not None]
    if conf_values:
        print(f"\n  Self-confidence:")
        for status in ("OK", "UNSURE", "FAIL"):
            cnt = sum(1 for c in conf_values if str(c).upper() == status)
            if cnt:
                print(f"    {status}: {cnt}/{len(conf_values)}")

    tot_in = sum(m.tokens_in for m in metrics_list)
    tot_out = sum(m.tokens_out for m in metrics_list)
    # Add tokens from external checks (redundancy extra calls)
    for ck_data in checks_list:
        if not ck_data:
            continue
        for ck_name, ck in ck_data.items():
            if isinstance(ck, dict):
                tot_in += ck.get("extra_tokens_in", 0)
                tot_out += ck.get("extra_tokens_out", 0)
    print(f"  total tokens: in={tot_in} out={tot_out}")

    # Save summary JSON
    summary = out_dir / "summary.json"
    with summary.open("w", encoding="utf-8") as f:
        json.dump([asdict(m) for m in metrics_list], f, ensure_ascii=False, indent=2)
    print(f"\n  summary.json -> {summary}")

    # Markdown summary
    summary_md = out_dir / "summary.md"
    mode_str = ""
    if day7_mode:
        flags = []
        if args.self_score:
            flags.append("self-score")
        if args.self_explain:
            flags.append("self-explain")
        if checks:
            flags.append(f"checks={','.join(checks)}")
        mode_str = f"  |  Day 7: {', '.join(flags)}"

    lines = [
        f"# Extraction Baseline (provider={provider}, model={model}, T={args.temperature}{mode_str})",
        "",
        f"Examples: **{n}**  |  errors: **{n - nv}**  |  tokens: in={tot_in}, out={tot_out}",
        "",
    ]

    # Table header
    header = "| # | type | block | modules IoU | deps IoU | AC recall | OoS prec | json"
    sep = "|---|------|-------|-------------|----------|-----------|----------|-----"
    if args.self_score:
        header += " | self"
        sep += "|------"
    if checks:
        for ck in checks:
            header += f" | {ck}"
            sep += "|------"
    header += " |"
    sep += "|"
    lines.extend([header, sep])

    for i, m in enumerate(metrics_list):
        row = (
            f"| {m.name} | {'ok' if m.type_match else 'MISS'} | "
            f"{'ok' if m.block_match else 'MISS'} | "
            f"{m.modules_iou:.2f} | {m.depends_on_iou:.2f} | "
            f"{m.ac_recall:.2f} | {m.oos_precision:.2f} | "
            f"{'ok' if m.json_valid else 'FAIL'}"
        )
        if args.self_score:
            c = confidence_list[i] if i < len(confidence_list) else None
            row += f" | {c or '-'}"
        if checks:
            ck_data = checks_list[i] if i < len(checks_list) else None
            for ck in checks:
                if ck_data and ck in ck_data:
                    row += f" | {ck_data[ck].get('status', '?')}"
                else:
                    row += " | -"
        row += " |"
        lines.append(row)

    if nv:
        lines.extend([
            "",
            "## Averages",
            f"- modules IoU: **{sum(m.modules_iou for m in valid)/nv:.3f}**",
            f"- dependsOn IoU: **{sum(m.depends_on_iou for m in valid)/nv:.3f}**",
            f"- AC recall: **{sum(m.ac_recall for m in valid)/nv:.3f}**",
            f"- OoS precision: **{sum(m.oos_precision for m in valid)/nv:.3f}**",
        ])

    if conf_values:
        lines.extend(["", "## Self-confidence"])
        for status in ("OK", "UNSURE", "FAIL"):
            cnt = sum(1 for c in conf_values if str(c).upper() == status)
            if cnt:
                lines.append(f"- {status}: **{cnt}/{len(conf_values)}**")

    if any(r for r in reasoning_list if r):
        lines.extend(["", "## Self-reasoning (per example)"])
        for i, r in enumerate(reasoning_list):
            if r and i < len(metrics_list):
                lines.append(f"- **{metrics_list[i].name}**: {r[:200]}")

    with summary_md.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  summary.md   -> {summary_md}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
