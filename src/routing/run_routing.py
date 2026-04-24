#!/usr/bin/env python3
"""Day 8 — Run model routing evaluation.

Routes eval examples through cheap model first, escalates to strong model
when confidence is low.

Usage:
    python -m src.routing.run_routing --dry-run
    python -m src.routing.run_routing --provider ollama
    python -m src.routing.run_routing --provider ollama --self-score
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
from src.routing.router import RouterConfig, RoutingResult, route_example  # noqa: E402
from src.utils import model_slug  # noqa: E402


def _build_run_slug(config: RouterConfig) -> str:
    """Build output directory name from config."""
    parts = [model_slug(config.cheap_model), "to", model_slug(config.strong_model)]
    if config.use_self_score:
        parts.append("selfscore")
    return "_".join(parts)


def _save_results(results: list[RoutingResult], out_dir: Path,
                  config: RouterConfig, provider: str) -> None:
    """Save per-example JSON, summary.json, and summary.md."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Per-example JSON ---
    for r in results:
        path = out_dir / f"{r.name}.json"
        data = {
            "name": r.name,
            "routed_to": r.routed_to,
            "escalation_reasons": r.escalation_reasons,
            "extraction": r.extraction,
            "metrics": asdict(r.metrics) if r.metrics else None,
            "cheap_raw": r.cheap_raw,
            "strong_raw": r.strong_raw,
            "tokens": {
                "cheap_in": r.cheap_tokens_in,
                "cheap_out": r.cheap_tokens_out,
                "strong_in": r.strong_tokens_in,
                "strong_out": r.strong_tokens_out,
                "total_in": r.tokens_in,
                "total_out": r.tokens_out,
            },
            "latency_ms": round(r.latency_ms, 1),
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # --- Aggregate ---
    n = len(results)
    cheap_results = [r for r in results if r.routed_to == "cheap"]
    strong_results = [r for r in results if r.routed_to == "strong"]

    def _avg_metric(subset: list[RoutingResult], attr: str) -> float:
        vals = [getattr(r.metrics, attr, 0) for r in subset if r.metrics and not r.metrics.error]
        return sum(vals) / len(vals) if vals else 0.0

    valid_results = [r for r in results if r.metrics and not r.metrics.error]

    agg = {
        "total": n,
        "on_cheap": len(cheap_results),
        "on_strong": len(strong_results),
        "escalation_rate": round(len(strong_results) / n, 3) if n else 0,
        "overall": {
            "avg_modules_iou": round(_avg_metric(valid_results, "modules_iou"), 3),
            "avg_type_match": round(
                sum(1 for r in valid_results if r.metrics.type_match) / len(valid_results), 3
            ) if valid_results else 0,
            "avg_block_match": round(
                sum(1 for r in valid_results if r.metrics.block_match) / len(valid_results), 3
            ) if valid_results else 0,
        },
        "cheap_subset": {
            "count": len(cheap_results),
            "avg_modules_iou": round(_avg_metric(cheap_results, "modules_iou"), 3),
        },
        "strong_subset": {
            "count": len(strong_results),
            "avg_modules_iou": round(_avg_metric(strong_results, "modules_iou"), 3),
        },
        "tokens": {
            "total_in": sum(r.tokens_in for r in results),
            "total_out": sum(r.tokens_out for r in results),
        },
        "avg_latency_ms": round(sum(r.latency_ms for r in results) / n, 1) if n else 0,
        "escalation_reasons_breakdown": {},
    }

    # Count escalation reasons
    reason_counts: dict[str, int] = {}
    for r in results:
        for reason in r.escalation_reasons:
            # Normalize: strip details after ':'
            key = reason.split(":")[0]
            reason_counts[key] = reason_counts.get(key, 0) + 1
    agg["escalation_reasons_breakdown"] = reason_counts

    # --- summary.json ---
    summary_path = out_dir / "summary.json"
    summary = {
        "config": {
            "cheap_model": config.cheap_model,
            "strong_model": config.strong_model,
            "temperature": config.temperature,
            "use_self_score": config.use_self_score,
            "provider": provider,
        },
        "aggregate": agg,
        "results": [
            {
                "name": r.name,
                "routed_to": r.routed_to,
                "escalation_reasons": r.escalation_reasons,
                "modules_iou": r.metrics.modules_iou if r.metrics else None,
                "type_match": r.metrics.type_match if r.metrics else None,
                "block_match": r.metrics.block_match if r.metrics else None,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "latency_ms": round(r.latency_ms, 1),
            }
            for r in results
        ],
    }
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # --- summary.md ---
    md_path = out_dir / "summary.md"
    flags = []
    if config.use_self_score:
        flags.append("self-score")
    flags_str = f"  |  Flags: {', '.join(flags)}" if flags else ""

    lines = [
        f"# Day 8: Model Routing",
        f"",
        f"**Cheap:** {config.cheap_model}  |  **Strong:** {config.strong_model}  |  "
        f"**Provider:** {provider}  |  T={config.temperature}{flags_str}",
        f"",
        f"## Routing Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total examples | {n} |",
        f"| Stayed on cheap | {len(cheap_results)} |",
        f"| Escalated to strong | {len(strong_results)} |",
        f"| Escalation rate | {agg['escalation_rate']:.1%} |",
        f"| Avg latency | {agg['avg_latency_ms']:.0f} ms |",
        f"| Total tokens in | {agg['tokens']['total_in']} |",
        f"| Total tokens out | {agg['tokens']['total_out']} |",
        f"",
    ]

    # Escalation reasons
    if reason_counts:
        lines.extend([
            "## Escalation Reasons",
            "",
            "| Reason | Count |",
            "|--------|-------|",
        ])
        for reason, count in sorted(reason_counts.items()):
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    # Accuracy comparison
    lines.extend([
        "## Accuracy",
        "",
        "| Subset | Count | Avg modules IoU | Type match | Block match |",
        "|--------|-------|-----------------|------------|-------------|",
    ])

    for label, subset in [("Overall", valid_results), ("Cheap only", cheap_results), ("Strong only", strong_results)]:
        valid = [r for r in subset if r.metrics and not r.metrics.error]
        if valid:
            m_iou = sum(r.metrics.modules_iou for r in valid) / len(valid)
            t_match = sum(1 for r in valid if r.metrics.type_match) / len(valid)
            b_match = sum(1 for r in valid if r.metrics.block_match) / len(valid)
            lines.append(f"| {label} | {len(valid)} | {m_iou:.3f} | {t_match:.1%} | {b_match:.1%} |")
        else:
            lines.append(f"| {label} | 0 | - | - | - |")
    lines.append("")

    # Per-example table
    lines.extend([
        "## Per-example Results",
        "",
        "| # | routed_to | reasons | type | block | modules_iou | deps_iou | latency |",
        "|---|-----------|---------|------|-------|-------------|----------|---------|",
    ])
    for r in results:
        m = r.metrics
        reasons_str = ", ".join(r.split(":")[0] for r in r.escalation_reasons) if r.escalation_reasons else "-"
        if m and not m.error:
            lines.append(
                f"| {r.name} | {r.routed_to} | {reasons_str} | "
                f"{'ok' if m.type_match else 'MISS'} | "
                f"{'ok' if m.block_match else 'MISS'} | "
                f"{m.modules_iou:.2f} | {m.depends_on_iou:.2f} | "
                f"{r.latency_ms:.0f}ms |"
            )
        else:
            error = m.error if m else "no metrics"
            lines.append(
                f"| {r.name} | {r.routed_to} | {reasons_str} | "
                f"ERR | ERR | - | - | {r.latency_ms:.0f}ms |"
            )
    lines.append("")

    with md_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n  summary.json -> {summary_path}")
    print(f"  summary.md   -> {md_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Day 8: Model routing evaluation")
    ap.add_argument("--from-jsonl", type=Path,
                    default=ROOT / "data" / "out" / "eval.jsonl",
                    help="Eval JSONL file")
    ap.add_argument("--out-dir", type=Path,
                    default=ROOT / "data" / "routing")
    ap.add_argument("--cheap-model", default="qwen2.5:7b-instruct")
    ap.add_argument("--strong-model", default="gpt-oss:20b")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--provider", choices=["auto", "openai", "openrouter", "ollama"],
                    default="auto")
    ap.add_argument("--num-ctx", type=int, default=None,
                    help="Context window size (Ollama only)")
    ap.add_argument("--self-score", action="store_true",
                    help="Enable self-score confidence heuristic")
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
    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = None

    if not args.dry_run and not api_key:
        env_var = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
        print(f"error: {env_var} not set", file=sys.stderr)
        return 2

    config = RouterConfig(
        cheap_model=args.cheap_model,
        strong_model=args.strong_model,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        use_self_score=args.self_score,
    )

    run_slug = _build_run_slug(config)
    out_dir = args.out_dir / run_slug
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

    print(f"Day 8: Model Routing")
    print(f"  Cheap:  {config.cheap_model}")
    print(f"  Strong: {config.strong_model}")
    print(f"  Provider: {provider}  T={config.temperature}")
    if config.use_self_score:
        print(f"  Self-score: enabled")
    print(f"  Examples: {len(examples)}")
    print(f"  Output: {out_dir}")

    if args.dry_run:
        for name, messages in examples:
            gold = json.loads(messages[2]["content"])
            print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")
            print(f"  would route through {config.cheap_model} → (maybe) {config.strong_model}")
        print("\n(dry run — no API calls made)")
        return 0

    client = None
    from openai import OpenAI
    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)

    results: list[RoutingResult] = []
    for name, messages in examples:
        gold = json.loads(messages[2]["content"])
        print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")

        r = route_example(name, messages, gold, client, config)
        results.append(r)

        # Console output
        m = r.metrics
        print(f"  routed_to: {r.routed_to}")
        if r.escalation_reasons:
            for reason in r.escalation_reasons:
                print(f"    reason: {reason}")
        if m and not m.error:
            print(f"  type={'ok' if m.type_match else 'MISS'}  block={'ok' if m.block_match else 'MISS'}  "
                  f"modules_iou={m.modules_iou:.2f}  deps_iou={m.depends_on_iou:.2f}")
        elif m and m.error:
            print(f"  ERROR: {m.error}")
        print(f"  tokens: in={r.tokens_in} out={r.tokens_out}  latency={r.latency_ms:.0f}ms")

    # --- Summary ---
    n = len(results)
    n_cheap = sum(1 for r in results if r.routed_to == "cheap")
    n_strong = sum(1 for r in results if r.routed_to == "strong")
    valid = [r for r in results if r.metrics and not r.metrics.error]

    print(f"\n=== Routing Summary ===")
    print(f"  on cheap:  {n_cheap}/{n}")
    print(f"  on strong: {n_strong}/{n}")
    if valid:
        avg_iou = sum(r.metrics.modules_iou for r in valid) / len(valid)
        print(f"  avg modules_iou: {avg_iou:.3f}")
    print(f"  total tokens: in={sum(r.tokens_in for r in results)} out={sum(r.tokens_out for r in results)}")
    print(f"  avg latency: {sum(r.latency_ms for r in results) / n:.0f}ms")

    _save_results(results, out_dir, config, provider)

    return 0


if __name__ == "__main__":
    sys.exit(main())
