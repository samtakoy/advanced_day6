#!/usr/bin/env python3
"""Print a one-page summary of train.jsonl + eval.jsonl.

Useful as the final "is the dataset ready?" check before fine-tune.

Usage:
    python -m dataset.summarize
    python -m dataset.summarize --train dataset/train.jsonl --eval dataset/eval.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _detect_mode(ex: dict) -> str:
    """Guess mode from messages structure (no _meta in final JSONL)."""
    msgs = ex.get("messages", [])
    # last assistant message determines mode
    last_asst = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
    has_tc = any(m.get("tool_calls") for m in msgs if m.get("role") == "assistant")
    if has_tc:
        return "agent"
    if last_asst and "QUESTION:" in (last_asst.get("content") or ""):
        return "agent_question"
    return "plain"


def summarize_file(path: Path) -> dict:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    modes = Counter(_detect_mode(r) for r in rows)

    # message counts per example
    msg_counts = [len(r.get("messages", [])) for r in rows]

    # tool call counts
    tool_names: Counter = Counter()
    for r in rows:
        for m in r.get("messages", []):
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls") or []:
                    tool_names[tc.get("function", {}).get("name")] += 1

    return {
        "n": len(rows),
        "modes": dict(modes),
        "msg_avg": sum(msg_counts) / max(1, len(msg_counts)),
        "msg_max": max(msg_counts) if msg_counts else 0,
        "tool_calls": dict(tool_names),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=Path,
                    default=Path(__file__).resolve().parent / "train.jsonl")
    ap.add_argument("--eval", type=Path,
                    default=Path(__file__).resolve().parent / "eval.jsonl")
    args = ap.parse_args()

    for label, p in (("TRAIN", args.train), ("EVAL", args.eval)):
        if not p.is_file():
            print(f"{label}: missing at {p}")
            continue
        s = summarize_file(p)
        print(f"\n=== {label}: {p.name} ===")
        print(f"  n:           {s['n']}")
        print(f"  modes:       {s['modes']}")
        pct = {k: f"{100 * v / s['n']:.0f}%" for k, v in s['modes'].items()}
        print(f"  mode-pct:    {pct}")
        print(f"  msgs avg:    {s['msg_avg']:.1f}")
        print(f"  msgs max:    {s['msg_max']}")
        print(f"  tool calls:  {s['tool_calls']}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
