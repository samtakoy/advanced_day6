#!/usr/bin/env python3
"""Day 9 — Run multi-stage inference decomposition.

Compares monolithic (single-prompt) vs multi-stage (analyze → classify → assemble)
extraction on eval examples.

Usage:
    python -m src.multistage.run_multistage --dry-run
    python -m src.multistage.run_multistage
    python -m src.multistage.run_multistage --provider ollama --model qwen2.5:7b-instruct
    python -m src.multistage.run_multistage --no-mono   # skip monolithic comparison
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.baseline.run_baseline import load_eval  # noqa: E402
from src.multistage.pipeline import MultistageResult, run_multistage  # noqa: E402
from src.utils import model_slug  # noqa: E402


def _save_results(results: list[MultistageResult], out_dir: Path,
                  model: str, provider: str, temperature: float) -> None:
    """Save per-example JSON, summary.json, and summary.md."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Per-example JSON ---
    for r in results:
        path = out_dir / f"{r.name}.json"
        data = {
            "name": r.name,
            "multistage": {
                "extraction": r.ms_extraction,
                "metrics": asdict(r.ms_metrics) if r.ms_metrics else None,
                "validation_errors": r.ms_validation_errors,
                "tokens_in": r.ms_tokens_in,
                "tokens_out": r.ms_tokens_out,
                "latency_ms": round(r.ms_latency_ms, 1),
                "error": r.ms_error,
                "stages": r.stages,
            },
            "monolithic": {
                "extraction": r.mono_extraction,
                "metrics": asdict(r.mono_metrics) if r.mono_metrics else None,
                "validation_errors": r.mono_validation_errors,
                "tokens_in": r.mono_tokens_in,
                "tokens_out": r.mono_tokens_out,
                "latency_ms": round(r.mono_latency_ms, 1),
                "raw": r.mono_raw,
                "error": r.mono_error,
            },
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # --- Aggregate ---
    n = len(results)

    def _avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _metrics_summary(label: str, get_metrics, get_verr, get_tin, get_tout, get_lat):
        valid = [(get_metrics(r), r) for r in results
                 if get_metrics(r) is not None and not get_metrics(r).error]
        return {
            "label": label,
            "count": len(valid),
            "errors": n - len(valid),
            "avg_modules_iou": round(_avg([m.modules_iou for m, _ in valid]), 3),
            "avg_new_modules_iou": round(_avg([m.new_modules_iou for m, _ in valid]), 3),
            "avg_depends_on_iou": round(_avg([m.depends_on_iou for m, _ in valid]), 3),
            "avg_ac_recall": round(_avg([m.ac_recall for m, _ in valid]), 3),
            "avg_oos_precision": round(_avg([m.oos_precision for m, _ in valid]), 3),
            "type_match_rate": round(
                sum(1 for m, _ in valid if m.type_match) / len(valid), 3
            ) if valid else 0,
            "block_match_rate": round(
                sum(1 for m, _ in valid if m.block_match) / len(valid), 3
            ) if valid else 0,
            "total_tokens_in": sum(get_tin(r) for r in results),
            "total_tokens_out": sum(get_tout(r) for r in results),
            "avg_latency_ms": round(_avg([get_lat(r) for r in results]), 1),
            "validation_errors_total": sum(len(get_verr(r)) for r in results),
        }

    ms_summary = _metrics_summary(
        "multi-stage",
        lambda r: r.ms_metrics, lambda r: r.ms_validation_errors,
        lambda r: r.ms_tokens_in, lambda r: r.ms_tokens_out, lambda r: r.ms_latency_ms,
    )
    mono_summary = _metrics_summary(
        "monolithic",
        lambda r: r.mono_metrics, lambda r: r.mono_validation_errors,
        lambda r: r.mono_tokens_in, lambda r: r.mono_tokens_out, lambda r: r.mono_latency_ms,
    )

    # Per-stage token breakdown
    stage_breakdown: dict[str, dict] = {}
    for r in results:
        for s in r.stages:
            sname = s.get("stage", "?")
            if sname not in stage_breakdown:
                stage_breakdown[sname] = {"tokens_in": 0, "tokens_out": 0,
                                          "latency_ms": 0, "errors": 0, "count": 0}
            stage_breakdown[sname]["tokens_in"] += s.get("tokens_in", 0)
            stage_breakdown[sname]["tokens_out"] += s.get("tokens_out", 0)
            stage_breakdown[sname]["latency_ms"] += s.get("latency_ms", 0)
            stage_breakdown[sname]["count"] += 1
            if s.get("error"):
                stage_breakdown[sname]["errors"] += 1

    summary = {
        "config": {
            "model": model,
            "provider": provider,
            "temperature": temperature,
            "examples": n,
        },
        "multistage": ms_summary,
        "monolithic": mono_summary,
        "stage_breakdown": stage_breakdown,
        "per_example": [
            {
                "name": r.name,
                "ms_modules_iou": r.ms_metrics.modules_iou if r.ms_metrics and not r.ms_metrics.error else None,
                "mono_modules_iou": r.mono_metrics.modules_iou if r.mono_metrics and not r.mono_metrics.error else None,
                "ms_type": r.ms_metrics.type_match if r.ms_metrics else None,
                "mono_type": r.mono_metrics.type_match if r.mono_metrics else None,
                "ms_block": r.ms_metrics.block_match if r.ms_metrics else None,
                "mono_block": r.mono_metrics.block_match if r.mono_metrics else None,
                "ms_tokens": r.ms_tokens_in + r.ms_tokens_out,
                "mono_tokens": r.mono_tokens_in + r.mono_tokens_out,
                "ms_latency": round(r.ms_latency_ms, 1),
                "mono_latency": round(r.mono_latency_ms, 1),
                "ms_error": r.ms_error,
            }
            for r in results
        ],
    }

    summary_path = out_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # --- summary.md ---
    md_path = out_dir / "summary.md"
    lines = [
        "# Day 9: Multi-stage Inference Decomposition",
        "",
        f"**Model:** {model}  |  **Provider:** {provider}  |  T={temperature}  |  Examples: {n}",
        "",
        "## Comparison: Monolithic vs Multi-stage",
        "",
        "| Metric | Monolithic | Multi-stage | Delta |",
        "|--------|-----------|-------------|-------|",
    ]

    def _delta(a: float, b: float) -> str:
        d = b - a
        sign = "+" if d > 0 else ""
        return f"{sign}{d:.3f}"

    for label, key in [
        ("modules IoU", "avg_modules_iou"),
        ("newModules IoU", "avg_new_modules_iou"),
        ("dependsOn IoU", "avg_depends_on_iou"),
        ("AC recall", "avg_ac_recall"),
        ("OoS precision", "avg_oos_precision"),
        ("type match", "type_match_rate"),
        ("block match", "block_match_rate"),
    ]:
        mv = mono_summary[key]
        msv = ms_summary[key]
        lines.append(f"| {label} | {mv:.3f} | {msv:.3f} | {_delta(mv, msv)} |")

    lines.extend([
        "",
        "## Cost & Latency",
        "",
        "| Metric | Monolithic | Multi-stage | Delta |",
        "|--------|-----------|-------------|-------|",
        f"| Tokens in | {mono_summary['total_tokens_in']} | {ms_summary['total_tokens_in']} | {ms_summary['total_tokens_in'] - mono_summary['total_tokens_in']:+d} |",
        f"| Tokens out | {mono_summary['total_tokens_out']} | {ms_summary['total_tokens_out']} | {ms_summary['total_tokens_out'] - mono_summary['total_tokens_out']:+d} |",
        f"| Avg latency (ms) | {mono_summary['avg_latency_ms']:.0f} | {ms_summary['avg_latency_ms']:.0f} | {ms_summary['avg_latency_ms'] - mono_summary['avg_latency_ms']:+.0f} |",
        f"| Validation errors | {mono_summary['validation_errors_total']} | {ms_summary['validation_errors_total']} | {ms_summary['validation_errors_total'] - mono_summary['validation_errors_total']:+d} |",
        "",
    ])

    # Stage breakdown
    if stage_breakdown:
        lines.extend([
            "## Per-stage Breakdown",
            "",
            "| Stage | Calls | Errors | Tokens in | Tokens out | Avg latency (ms) |",
            "|-------|-------|--------|-----------|------------|-------------------|",
        ])
        for sname, sdata in stage_breakdown.items():
            avg_lat = sdata["latency_ms"] / sdata["count"] if sdata["count"] else 0
            lines.append(
                f"| {sname} | {sdata['count']} | {sdata['errors']} | "
                f"{sdata['tokens_in']} | {sdata['tokens_out']} | {avg_lat:.0f} |"
            )
        lines.append("")

    # Per-example table
    lines.extend([
        "## Per-example Results",
        "",
        "| # | mono modules_iou | ms modules_iou | mono type | ms type | mono block | ms block | mono tokens | ms tokens | ms error |",
        "|---|-----------------|----------------|-----------|---------|------------|----------|-------------|-----------|----------|",
    ])
    for r in results:
        mm = r.mono_metrics
        msm = r.ms_metrics

        def _fmt_iou(m):
            if m and not m.error:
                return f"{m.modules_iou:.2f}"
            return "ERR"

        def _fmt_bool(m, attr):
            if m and not m.error:
                return "ok" if getattr(m, attr) else "MISS"
            return "ERR"

        mono_tok = r.mono_tokens_in + r.mono_tokens_out
        ms_tok = r.ms_tokens_in + r.ms_tokens_out
        err = r.ms_error or "-"
        if len(err) > 30:
            err = err[:30] + "..."

        lines.append(
            f"| {r.name} | {_fmt_iou(mm)} | {_fmt_iou(msm)} | "
            f"{_fmt_bool(mm, 'type_match')} | {_fmt_bool(msm, 'type_match')} | "
            f"{_fmt_bool(mm, 'block_match')} | {_fmt_bool(msm, 'block_match')} | "
            f"{mono_tok} | {ms_tok} | {err} |"
        )
    lines.append("")

    with md_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n  summary.json -> {summary_path}")
    print(f"  summary.md   -> {md_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Day 9: Multi-stage inference decomposition")
    ap.add_argument("--from-jsonl", type=Path,
                    default=ROOT / "data" / "out" / "eval.jsonl",
                    help="Eval JSONL file")
    ap.add_argument("--out-dir", type=Path,
                    default=ROOT / "data" / "multistage")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--provider", choices=["auto", "openai", "openrouter", "ollama"],
                    default="auto")
    ap.add_argument("--num-ctx", type=int, default=None,
                    help="Context window size (Ollama only)")
    ap.add_argument("--no-mono", action="store_true",
                    help="Skip monolithic comparison run")
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

    slug = model_slug(args.model)
    out_dir = args.out_dir / slug
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

    print(f"Day 9: Multi-stage Inference Decomposition")
    print(f"  Model: {model}  Provider: {provider}  T={args.temperature}")
    print(f"  Examples: {len(examples)}  Monolithic comparison: {'yes' if not args.no_mono else 'no'}")
    print(f"  Output: {out_dir}")

    if args.dry_run:
        for name, messages in examples:
            gold = json.loads(messages[2]["content"])
            print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")
            print(f"  would run: analyze → classify → extract → assemble")
            if not args.no_mono:
                print(f"  + monolithic comparison")
        print("\n(dry run — no API calls made)")
        return 0

    from openai import OpenAI
    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)

    results: list[MultistageResult] = []

    for name, messages in examples:
        system_content = messages[0]["content"]
        user_text = messages[1]["content"]
        gold = json.loads(messages[2]["content"])

        print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")

        r = run_multistage(
            name, system_content, user_text, gold,
            client, model, args.temperature,
            num_ctx=args.num_ctx,
            run_mono=not args.no_mono,
        )
        results.append(r)

        # Console output
        for s in r.stages:
            err = f" ERROR: {s['error']}" if s.get("error") else ""
            tin = s.get('tokens_in', 0)
            tout = s.get('tokens_out', 0)
            print(f"  stage.{s['stage']}: tokens={tin}+{tout}  "
                  f"latency={s['latency_ms']:.0f}ms{err}")

        if r.ms_metrics and not r.ms_metrics.error:
            m = r.ms_metrics
            print(f"  [multi-stage] type={'ok' if m.type_match else 'MISS'}  "
                  f"block={'ok' if m.block_match else 'MISS'}  "
                  f"modules_iou={m.modules_iou:.2f}  deps_iou={m.depends_on_iou:.2f}")
        elif r.ms_error:
            print(f"  [multi-stage] ERROR: {r.ms_error}")

        if not args.no_mono and r.mono_metrics and not r.mono_metrics.error:
            m = r.mono_metrics
            print(f"  [monolithic]  type={'ok' if m.type_match else 'MISS'}  "
                  f"block={'ok' if m.block_match else 'MISS'}  "
                  f"modules_iou={m.modules_iou:.2f}  deps_iou={m.depends_on_iou:.2f}")
        elif not args.no_mono and r.mono_error:
            print(f"  [monolithic]  ERROR: {r.mono_error}")

        ms_tok = r.ms_tokens_in + r.ms_tokens_out
        mono_tok = r.mono_tokens_in + r.mono_tokens_out
        print(f"  tokens: ms={ms_tok}  mono={mono_tok}  "
              f"latency: ms={r.ms_latency_ms:.0f}ms  mono={r.mono_latency_ms:.0f}ms")

    # --- Summary ---
    n = len(results)
    ms_valid = [r for r in results if r.ms_metrics and not r.ms_metrics.error]
    mono_valid = [r for r in results if r.mono_metrics and not r.mono_metrics.error]

    print(f"\n=== Summary ===")
    print(f"  examples: {n}")
    if ms_valid:
        avg_ms = sum(r.ms_metrics.modules_iou for r in ms_valid) / len(ms_valid)
        print(f"  [multi-stage] avg modules_iou: {avg_ms:.3f}  "
              f"valid: {len(ms_valid)}/{n}  "
              f"tokens: in={sum(r.ms_tokens_in for r in results)} "
              f"out={sum(r.ms_tokens_out for r in results)}")
    if mono_valid:
        avg_mono = sum(r.mono_metrics.modules_iou for r in mono_valid) / len(mono_valid)
        print(f"  [monolithic]  avg modules_iou: {avg_mono:.3f}  "
              f"valid: {len(mono_valid)}/{n}  "
              f"tokens: in={sum(r.mono_tokens_in for r in results)} "
              f"out={sum(r.mono_tokens_out for r in results)}")

    _save_results(results, out_dir, model, provider, args.temperature)

    return 0


if __name__ == "__main__":
    sys.exit(main())
