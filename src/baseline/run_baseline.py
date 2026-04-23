#!/usr/bin/env python3
"""Run baseline evaluation for extraction fine-tune dataset.

Sends system+user from eval.jsonl to the model, parses the JSON response,
and computes per-field metrics against gold answers.

Metrics:
    - type:     exact match (0 or 1)
    - block:    exact match (0 or 1)
    - modules:  IoU (Jaccard similarity of sets)
    - dependsOn: IoU (Jaccard similarity of sets)
    - acceptanceCriteria: recall (semantic — count of gold items covered)
    - outOfScope: precision (no hallucinated items)
    - JSON parse: success/fail

Usage:
    python -m src.baseline.run_baseline --dry-run
    python -m src.baseline.run_baseline
    python -m src.baseline.run_baseline --provider ollama --model qwen2.5:14b-instruct
    python -m src.baseline.run_baseline --limit 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils import model_slug  # noqa: E402
from src.validator.validate import validate_gold  # noqa: E402


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

    # acceptanceCriteria recall: fraction of gold items present in prediction (exact match)
    gold_ac = gold.get("acceptanceCriteria", [])
    pred_ac = predicted.get("acceptanceCriteria", [])
    if gold_ac:
        matched = sum(1 for g in gold_ac if g in pred_ac)
        m.ac_recall = matched / len(gold_ac)
    else:
        m.ac_recall = 1.0 if not pred_ac else 0.0

    # outOfScope precision: fraction of predicted items that are in gold
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
        # Ollama OpenAI-compat API принимает extra_body для специфичных параметров
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
                    help="Context window size (Ollama only). Default: model's default (~32K). "
                         "For extraction 4096 is enough.")
    args = ap.parse_args()

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

    # Output dir: data/baseline/eval/<model-slug>/
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

    metrics_list: list[ExampleMetrics] = []

    for name, messages in examples:
        # Extract system + user (first 2 messages), gold from assistant (3rd)
        prompt_msgs = [
            {"role": messages[0]["role"], "content": messages[0]["content"]},
            {"role": messages[1]["role"], "content": messages[1]["content"]},
        ]
        gold = json.loads(messages[2]["content"])

        print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")

        if args.dry_run:
            print(f"  would call {model} via {provider}, temperature={args.temperature}")
            continue

        try:
            resp = call_api(client, model, prompt_msgs, args.temperature,
                           num_ctx=args.num_ctx)
        except Exception as e:
            print(f"  [ERROR] {e}", file=sys.stderr)
            m = ExampleMetrics(name=name, error=str(e))
            metrics_list.append(m)
            continue

        choice = resp.choices[0]
        content = choice.message.content or ""

        # Try to parse JSON from response
        predicted = None
        try:
            predicted = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            import re
            json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
            if json_match:
                try:
                    predicted = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

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

        # Save raw response
        raw_path = out_dir / f"{name}.json"
        with raw_path.open("w", encoding="utf-8") as f:
            json.dump({
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
            }, f, ensure_ascii=False, indent=2)

        print(f"  json_valid={m.json_valid}  type={m.type_match}  block={m.block_match}")
        print(f"  modules_iou={m.modules_iou:.2f}  new_modules_iou={m.new_modules_iou:.2f}  deps_iou={m.depends_on_iou:.2f}")
        print(f"  ac_recall={m.ac_recall:.2f}  oos_precision={m.oos_precision:.2f}")
        print(f"  validation_errors={len(m.validation_errors)}")
        if m.validation_errors:
            for ve in m.validation_errors[:5]:
                print(f"    - {ve}")
        print(f"  tokens in={m.tokens_in} out={m.tokens_out}")

    if args.dry_run:
        print("\n(dry run — no outputs written)")
        return 0

    # Aggregate summary
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

    tot_in = sum(m.tokens_in for m in metrics_list)
    tot_out = sum(m.tokens_out for m in metrics_list)
    print(f"  total tokens: in={tot_in} out={tot_out}")

    # Save summary
    summary = out_dir / "summary.json"
    with summary.open("w", encoding="utf-8") as f:
        json.dump([asdict(m) for m in metrics_list], f, ensure_ascii=False, indent=2)
    print(f"\n  summary.json -> {summary}")

    # Markdown summary
    summary_md = out_dir / "summary.md"
    lines = [
        f"# Extraction Baseline (provider={provider}, model={model}, T={args.temperature})",
        "",
        f"Examples: **{n}**  |  errors: **{n - nv}**  |  tokens: in={tot_in}, out={tot_out}",
        "",
        "| # | type | block | modules IoU | deps IoU | AC recall | OoS prec | json |",
        "|---|------|-------|-------------|----------|-----------|----------|------|",
    ]
    for m in metrics_list:
        lines.append(
            f"| {m.name} | {'ok' if m.type_match else 'MISS'} | "
            f"{'ok' if m.block_match else 'MISS'} | "
            f"{m.modules_iou:.2f} | {m.depends_on_iou:.2f} | "
            f"{m.ac_recall:.2f} | {m.oos_precision:.2f} | "
            f"{'ok' if m.json_valid else 'FAIL'} |"
        )
    if nv:
        lines.extend([
            "",
            "## Averages",
            f"- modules IoU: **{sum(m.modules_iou for m in valid)/nv:.3f}**",
            f"- dependsOn IoU: **{sum(m.depends_on_iou for m in valid)/nv:.3f}**",
            f"- AC recall: **{sum(m.ac_recall for m in valid)/nv:.3f}**",
            f"- OoS precision: **{sum(m.oos_precision for m in valid)/nv:.3f}**",
        ])
    with summary_md.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  summary.md   -> {summary_md}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
