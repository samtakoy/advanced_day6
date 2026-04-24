#!/usr/bin/env python3
"""Run quality control pipeline — confidence estimation for extraction inference.

Runs selected checks (constraint, redundancy, scoring) on eval examples
and produces a detailed report with acceptance/rejection statistics.

Usage:
    python -m src.quality.run_quality --dry-run
    python -m src.quality.run_quality
    python -m src.quality.run_quality --provider ollama --model qwen2.5:14b-instruct
    python -m src.quality.run_quality --checks constraint,scoring
    python -m src.quality.run_quality --input-set edge_cases
    python -m src.quality.run_quality --input-set all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.baseline.run_baseline import load_eval, score  # noqa: E402
from src.quality.models import PipelineConfig  # noqa: E402
from src.quality.pipeline import run_pipeline  # noqa: E402
from src.quality.report import aggregate, save_json, save_markdown  # noqa: E402
from src.utils import model_slug  # noqa: E402


INPUT_SETS = {
    "eval": ROOT / "data" / "out" / "eval.jsonl",
    "edge_cases": ROOT / "data" / "quality" / "inputs" / "edge_cases.jsonl",
    "noisy": ROOT / "data" / "quality" / "inputs" / "noisy.jsonl",
}
VALID_CHECKS = {"constraint", "redundancy", "scoring", "scoring_cot"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Run quality control pipeline")
    ap.add_argument("--from-jsonl", type=Path, default=None,
                    help="Explicit JSONL file to evaluate")
    ap.add_argument("--input-set", default="eval",
                    help="Input set: eval, edge_cases, noisy, all (default: eval)")
    ap.add_argument("--out-dir", type=Path,
                    default=ROOT / "data" / "quality")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--provider", choices=["auto", "openai", "openrouter", "ollama"],
                    default="auto")
    ap.add_argument("--num-ctx", type=int, default=None,
                    help="Context window (Ollama only)")
    ap.add_argument("--checks", default="constraint,redundancy,scoring,scoring_cot",
                    help="Comma-separated checks to run (default: all)")
    ap.add_argument("--redundancy-n", type=int, default=3,
                    help="Number of total calls for redundancy check (default: 3)")
    ap.add_argument("--max-retries", type=int, default=2,
                    help="Max retries on constraint failure (default: 2)")
    ap.add_argument("--redundancy-temperature", type=float, default=0.7,
                    help="Temperature for redundancy calls (default: 0.7)")
    ap.add_argument("--no-run-all", action="store_true",
                    help="Stop pipeline early on FAIL (default: run all checks)")
    args = ap.parse_args()

    # Parse checks
    checks = [c.strip() for c in args.checks.split(",")]
    for c in checks:
        if c not in VALID_CHECKS:
            print(f"error: unknown check '{c}'. Valid: {sorted(VALID_CHECKS)}",
                  file=sys.stderr)
            return 2

    config = PipelineConfig(
        checks=checks,
        max_retries=args.max_retries,
        redundancy_n=args.redundancy_n,
        redundancy_temperature=args.redundancy_temperature,
        run_all_checks=not args.no_run_all,
    )

    # Load env
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    # Provider setup
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

    # Determine input files
    if args.from_jsonl:
        input_files = [(args.from_jsonl.stem, args.from_jsonl)]
    elif args.input_set == "all":
        input_files = [(name, path) for name, path in INPUT_SETS.items()]
    elif args.input_set in INPUT_SETS:
        input_files = [(args.input_set, INPUT_SETS[args.input_set])]
    else:
        print(f"error: unknown input-set '{args.input_set}'. "
              f"Valid: {list(INPUT_SETS.keys()) + ['all']}", file=sys.stderr)
        return 2

    # Validate input files exist
    for set_name, fpath in input_files:
        if not fpath.is_file():
            print(f"error: {fpath} not found", file=sys.stderr)
            return 2

    # Setup client
    client = None
    needs_api = any(c in checks for c in ("redundancy", "scoring"))
    if not args.dry_run:
        from openai import OpenAI
        if base_url:
            client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            client = OpenAI(api_key=api_key)
        print(f"Provider: {provider}  model: {model}")
        print(f"Checks: {checks}")
        print(f"Config: retries={config.max_retries}, redundancy_n={config.redundancy_n}")

    meta = {
        "provider": provider,
        "model": args.model,
        "temperature": args.temperature,
        "checks": checks,
        "redundancy_n": config.redundancy_n,
        "max_retries": config.max_retries,
    }

    for set_name, fpath in input_files:
        print(f"\n{'='*60}")
        print(f"Input set: {set_name} ({fpath})")
        print(f"{'='*60}")

        examples = load_eval(fpath)
        # Override names with set prefix
        examples = [(f"{set_name}_{i:02d}", msgs) for i, (_, msgs) in enumerate(examples, 1)]

        if args.limit:
            examples = examples[:args.limit]

        if not examples:
            print("  no examples loaded", file=sys.stderr)
            continue

        if args.dry_run:
            for name, msgs in examples:
                gold = json.loads(msgs[2]["content"])
                print(f"  {name}: would run pipeline on '{gold.get('title', '?')[:50]}'")
            continue

        results = []
        for name, msgs in examples:
            prompt_msgs = [
                {"role": msgs[0]["role"], "content": msgs[0]["content"]},
                {"role": msgs[1]["role"], "content": msgs[1]["content"]},
            ]
            gold = json.loads(msgs[2]["content"])

            print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")

            r = run_pipeline(
                name=name,
                messages=prompt_msgs,
                client=client,
                model=model,
                temperature=args.temperature,
                config=config,
                gold=gold,
                num_ctx=args.num_ctx,
                score_fn=score,
            )
            results.append(r)

            # Print per-example summary
            print(f"  status: {r.status}  attempts: {r.attempts}  "
                  f"api_calls: {r.total_api_calls}  latency: {r.total_latency_ms:.0f}ms")
            for v in r.verdicts:
                if v.check_name == "constraint":
                    errs = v.details.get("schema_errors", [])
                    warns = v.details.get("invariant_warnings", [])
                    print(f"    constraint: {v.status}  errors={len(errs)} warnings={len(warns)}")
                elif v.check_name == "redundancy":
                    attempts = v.details.get("attempts", [])
                    n_passed = v.details.get("n_passed", "?")
                    n_total = v.details.get("n_total", "?")
                    print(f"    redundancy: {v.status}  passed={n_passed}/{n_total}")
                    for a in attempts:
                        temp = a.get("temperature", "?")
                        if not a.get("parsed"):
                            print(f"      T={temp}: JSON parse failed")
                            continue
                        passed = "PASS" if a.get("pass") else "FAIL"
                        valid = "yes" if a.get("valid") else "NO"
                        vs_gold = a.get("vs_gold", {})
                        gold_str = ""
                        if vs_gold:
                            gold_str = (f" modules_iou={vs_gold.get('modules_iou', 0):.2f}"
                                        f" type={'ok' if vs_gold.get('type_match') else 'MISS'}"
                                        f" block={'ok' if vs_gold.get('block_match') else 'MISS'}")
                        failed = a.get("failed_fields", [])
                        fail_str = f"  [{', '.join(failed)}]" if failed else ""
                        print(f"      T={temp}: {passed}  schema={valid}{gold_str}{fail_str}")
                elif v.check_name == "scoring":
                    fc = v.details.get("field_confidence", {})
                    fields_str = " ".join(f"{k}={fv}" for k, fv in fc.items() if fv != "OK")
                    reasoning = v.details.get("reasoning", "")
                    print(f"    scoring: {v.status}  {fields_str or 'all fields OK'}")
                    if reasoning:
                        print(f"      reasoning: {reasoning}")
                elif v.check_name == "scoring_cot":
                    fc = v.details.get("field_confidence", {})
                    fr = v.details.get("field_reasoning", {})
                    fields_str = " ".join(f"{k}={fv}" for k, fv in fc.items() if fv != "OK")
                    print(f"    scoring_cot: {v.status}  {fields_str or 'all fields OK'}")
                    summary = v.details.get("summary", "")
                    if summary:
                        print(f"      summary: {summary}")
                    for field_name, reason in fr.items():
                        verdict = fc.get(field_name, "?")
                        if verdict != "OK" and reason:
                            print(f"      {field_name} ({verdict}): {reason}")

            if r.baseline_metrics:
                bm = r.baseline_metrics
                print(f"  vs gold: modules_iou={bm.get('modules_iou', 0):.2f} "
                      f"type={'ok' if bm.get('type_match') else 'MISS'} "
                      f"block={'ok' if bm.get('block_match') else 'MISS'}")

        # Aggregate and save
        agg = aggregate(results)
        slug = model_slug(args.model)
        out = args.out_dir / "eval" / slug / set_name
        meta_with_set = {**meta, "input_set": set_name, "input_file": str(fpath)}

        json_path = save_json(results, agg, out, meta_with_set)
        md_path = save_markdown(results, agg, out, meta_with_set)

        print(f"\n=== {set_name} Summary ===")
        print(f"  accepted: {agg.get('accepted', 0)}  "
              f"warnings: {agg.get('accepted_with_warnings', 0)}  "
              f"rejected: {agg.get('rejected', 0)}")
        print(f"  avg attempts: {agg.get('avg_attempts', 0)}  "
              f"avg api calls: {agg.get('avg_api_calls', 0)}")
        print(f"  total tokens: in={agg.get('total_tokens_in', 0)} "
              f"out={agg.get('total_tokens_out', 0)}")
        print(f"  summary.json -> {json_path}")
        print(f"  summary.md   -> {md_path}")

    if args.dry_run:
        print("\n(dry run — no API calls made)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
