#!/usr/bin/env python3
"""Mix seeds + synthetic into train/eval JSONL (stratified 80/20).

Reads seed .json files from dataset/seeds/ and synthetic .json files from
dataset/synthetic/, validates each, strips _meta (OpenAI FT rejects unknown
top-level keys), then emits two files:

- dataset/train.jsonl
- dataset/eval.jsonl

Stratified split keeps per-mode proportions (agent / agent_question / plain)
balanced in both splits.

Usage:
    python -m dataset.mix_and_split
    python -m dataset.mix_and_split --eval-ratio 0.2 --seed 42
    python -m dataset.mix_and_split --skip-validate   # trust inputs
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
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


def load_examples(
    dir_path: Path,
    tools_by_name: dict,
    skip_validate: bool,
    label: str,
) -> tuple[list[dict], int]:
    """Load, validate, and tag examples from a directory."""
    out: list[dict] = []
    failed = 0
    for path in sorted(dir_path.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                ex = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[FAIL {label}] {path.name}: bad JSON: {e}", file=sys.stderr)
            failed += 1
            continue

        if not skip_validate:
            issues = check_structural(ex) + check_semantic(ex, tools_by_name)
            errs = [i for i in issues if i.severity == "error"]
            if errs:
                print(f"[FAIL {label}] {path.name}: {len(errs)} error(s):",
                      file=sys.stderr)
                for i in errs[:3]:
                    loc = f" @ {i.path}" if i.path else ""
                    print(f"    {i.code}{loc}: {i.message}", file=sys.stderr)
                failed += 1
                continue

        ex["_mode"] = detect_mode(ex)
        ex["_source"] = label
        ex["_filename"] = path.name
        out.append(ex)
    return out, failed


def stratified_split(
    examples: list[dict],
    eval_ratio: float,
    rng: random.Random,
) -> tuple[list[dict], list[dict]]:
    """Per-mode 80/20 split; ensures each mode appears in eval."""
    by_mode: dict[str, list[dict]] = defaultdict(list)
    for ex in examples:
        by_mode[ex["_mode"]].append(ex)

    train: list[dict] = []
    eval_: list[dict] = []
    for mode, items in by_mode.items():
        rng.shuffle(items)
        n_eval = max(1, round(len(items) * eval_ratio))
        # never eval more than half
        n_eval = min(n_eval, max(1, len(items) // 2))
        eval_.extend(items[:n_eval])
        train.extend(items[n_eval:])

    rng.shuffle(train)
    rng.shuffle(eval_)
    return train, eval_


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            clean.pop("_meta", None)
            line = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
            f.write(line + "\n")


def summarize(rows: list[dict], label: str) -> None:
    counts: dict[str, int] = defaultdict(int)
    src: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["_mode"]] += 1
        src[r["_source"]] += 1
    total = len(rows) or 1
    pct = {m: f"{100 * n / total:.0f}%" for m, n in counts.items()}
    print(f"{label}: n={len(rows)}  modes={dict(counts)}  pct={pct}  source={dict(src)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Mix seeds+synthetic and split 80/20")
    ap.add_argument("--seeds-dir", type=Path,
                    default=Path(__file__).resolve().parent / "seeds")
    ap.add_argument("--synthetic-dir", type=Path,
                    default=Path(__file__).resolve().parent / "synthetic")
    ap.add_argument("--out-train", type=Path,
                    default=Path(__file__).resolve().parent / "train.jsonl")
    ap.add_argument("--out-eval", type=Path,
                    default=Path(__file__).resolve().parent / "eval.jsonl")
    ap.add_argument("--contracts", type=Path, default=ROOT / "contracts")
    ap.add_argument("--eval-ratio", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-validate", action="store_true")
    args = ap.parse_args()

    if not args.seeds_dir.is_dir():
        print(f"error: seeds dir not found: {args.seeds_dir}", file=sys.stderr)
        return 2

    tools_by_name = {} if args.skip_validate else load_tool_schemas(args.contracts)

    seeds, f1 = load_examples(args.seeds_dir, tools_by_name,
                              args.skip_validate, "seed")
    synth, f2 = load_examples(args.synthetic_dir, tools_by_name,
                              args.skip_validate, "synthetic") \
        if args.synthetic_dir.is_dir() else ([], 0)

    if f1 or f2:
        print(f"validation failed: seeds={f1} synthetic={f2}", file=sys.stderr)
        return 1

    all_ex = seeds + synth
    print(f"Loaded: seeds={len(seeds)} synthetic={len(synth)} total={len(all_ex)}")

    rng = random.Random(args.seed)
    train, eval_ = stratified_split(all_ex, args.eval_ratio, rng)

    write_jsonl(args.out_train, train)
    write_jsonl(args.out_eval, eval_)

    print()
    summarize(train, "train")
    summarize(eval_,  "eval ")
    print()
    print(f"Wrote {args.out_train}  ({len(train)} rows)")
    print(f"Wrote {args.out_eval}   ({len(eval_)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
