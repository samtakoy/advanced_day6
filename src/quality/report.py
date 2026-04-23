"""Report generation — aggregate metrics, JSON + markdown output."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from src.quality.models import PipelineResult


def aggregate(results: list[PipelineResult]) -> dict:
    """Compute aggregate metrics across all pipeline results."""
    n = len(results)
    if n == 0:
        return {}

    accepted = [r for r in results if r.status == "ACCEPTED"]
    warnings = [r for r in results if r.status == "ACCEPTED_WITH_WARNINGS"]
    rejected = [r for r in results if r.status == "REJECTED"]

    agg = {
        "total": n,
        "accepted": len(accepted),
        "accepted_with_warnings": len(warnings),
        "rejected": len(rejected),
        "acceptance_rate": round(len(accepted) / n, 3),
        "warning_rate": round(len(warnings) / n, 3),
        "rejection_rate": round(len(rejected) / n, 3),
        "avg_attempts": round(sum(r.attempts for r in results) / n, 2),
        "avg_api_calls": round(sum(r.total_api_calls for r in results) / n, 2),
        "avg_latency_ms": round(sum(r.total_latency_ms for r in results) / n, 1),
        "total_tokens_in": sum(r.total_tokens_in for r in results),
        "total_tokens_out": sum(r.total_tokens_out for r in results),
    }

    # Accuracy on accepted (if gold available)
    accepted_all = accepted + warnings
    with_metrics = [r for r in accepted_all if r.baseline_metrics]
    if with_metrics:
        agg["accuracy_on_accepted"] = {
            "count": len(with_metrics),
            "avg_modules_iou": round(
                sum(r.baseline_metrics.get("modules_iou", 0) for r in with_metrics) / len(with_metrics), 3),
            "avg_type_match": round(
                sum(1 for r in with_metrics if r.baseline_metrics.get("type_match")) / len(with_metrics), 3),
            "avg_block_match": round(
                sum(1 for r in with_metrics if r.baseline_metrics.get("block_match")) / len(with_metrics), 3),
        }

    # False reject rate (rejected but gold score was good)
    rejected_with_metrics = [r for r in rejected if r.baseline_metrics]
    if rejected_with_metrics:
        false_rejects = sum(
            1 for r in rejected_with_metrics
            if r.baseline_metrics.get("modules_iou", 0) >= 0.8
            and r.baseline_metrics.get("type_match")
            and r.baseline_metrics.get("block_match")
        )
        agg["false_reject_rate"] = round(false_rejects / len(rejected), 3) if rejected else 0

    # Per-check breakdown
    check_stats: dict[str, dict] = {}
    for r in results:
        for v in r.verdicts:
            if v.check_name not in check_stats:
                check_stats[v.check_name] = {"OK": 0, "UNSURE": 0, "FAIL": 0, "total": 0}
            check_stats[v.check_name][v.status] = check_stats[v.check_name].get(v.status, 0) + 1
            check_stats[v.check_name]["total"] += 1
    agg["per_check"] = check_stats

    return agg


def save_json(results: list[PipelineResult], agg: dict, out_dir: Path,
              meta: dict | None = None) -> Path:
    """Save detailed results + summary as JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-example details
    for r in results:
        detail_path = out_dir / f"{r.name}.json"
        data = asdict(r)
        if meta:
            data["meta"] = meta
        with detail_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Summary
    summary_path = out_dir / "summary.json"
    summary = {"meta": meta or {}, "aggregate": agg,
               "results": [asdict(r) for r in results]}
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary_path


def save_markdown(results: list[PipelineResult], agg: dict, out_dir: Path,
                  meta: dict | None = None) -> Path:
    """Save human-readable markdown summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "summary.md"

    meta = meta or {}
    lines = [
        f"# Quality Pipeline Report",
        f"",
        f"**Model:** {meta.get('model', '?')}  |  "
        f"**Provider:** {meta.get('provider', '?')}  |  "
        f"**Checks:** {', '.join(meta.get('checks', []))}",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total examples | {agg.get('total', 0)} |",
        f"| Accepted | {agg.get('accepted', 0)} |",
        f"| Accepted with warnings | {agg.get('accepted_with_warnings', 0)} |",
        f"| Rejected | {agg.get('rejected', 0)} |",
        f"| Acceptance rate | {agg.get('acceptance_rate', 0):.1%} |",
        f"| Warning rate | {agg.get('warning_rate', 0):.1%} |",
        f"| Rejection rate | {agg.get('rejection_rate', 0):.1%} |",
        f"| Avg attempts | {agg.get('avg_attempts', 0)} |",
        f"| Avg API calls | {agg.get('avg_api_calls', 0)} |",
        f"| Avg latency (ms) | {agg.get('avg_latency_ms', 0):.0f} |",
        f"| Total tokens in | {agg.get('total_tokens_in', 0)} |",
        f"| Total tokens out | {agg.get('total_tokens_out', 0)} |",
        f"",
    ]

    if "false_reject_rate" in agg:
        lines.append(f"**False reject rate:** {agg['false_reject_rate']:.1%}")
        lines.append("")

    # Per-check breakdown
    per_check = agg.get("per_check", {})
    if per_check:
        lines.extend([
            "## Per-check breakdown",
            "",
            "| Check | OK | UNSURE | FAIL | Total |",
            "|-------|-----|--------|------|-------|",
        ])
        for check_name, stats in per_check.items():
            lines.append(
                f"| {check_name} | {stats.get('OK', 0)} | "
                f"{stats.get('UNSURE', 0)} | {stats.get('FAIL', 0)} | "
                f"{stats.get('total', 0)} |"
            )
        lines.append("")

    # Accuracy on accepted
    acc = agg.get("accuracy_on_accepted")
    if acc:
        lines.extend([
            "## Accuracy on accepted",
            "",
            f"- Examples with gold: **{acc['count']}**",
            f"- Avg modules IoU: **{acc['avg_modules_iou']:.3f}**",
            f"- Avg type match: **{acc['avg_type_match']:.3f}**",
            f"- Avg block match: **{acc['avg_block_match']:.3f}**",
            "",
        ])

    # Per-example table
    lines.extend([
        "## Per-example results",
        "",
        "| # | Status | Attempts | API calls | Latency (ms) | Checks |",
        "|---|--------|----------|-----------|-------------|--------|",
    ])
    for r in results:
        checks_summary = ", ".join(f"{v.check_name}={v.status}" for v in r.verdicts)
        lines.append(
            f"| {r.name} | {r.status} | {r.attempts} | "
            f"{r.total_api_calls} | {r.total_latency_ms:.0f} | "
            f"{checks_summary} |"
        )

    with md_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return md_path
