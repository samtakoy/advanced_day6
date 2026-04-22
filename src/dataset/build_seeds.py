#!/usr/bin/env python3
"""Build a JSONL from seed JSON files.

Reads dataset/seeds/*.json (pretty-printed, each with _meta + messages),
validates each through validator checks, strips _meta, writes one compact
JSON per line to the output JSONL file.

Usage:
    python -m src.dataset.build_seeds                    # defaults
    python -m src.dataset.build_seeds --out out.jsonl
    python -m src.dataset.build_seeds --skip-validate    # trust the sources

Exits 1 if any seed is invalid or unparseable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Корень проекта — на 3 уровня выше (dataset/ → src/ → advanced_day6/)
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.validator.validate import (  # noqa: E402
    check_semantic,
    check_structural,
    detect_mode,
    load_tool_schemas,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Flatten seed .json files into JSONL")
    ap.add_argument(
        "--in", dest="input_dir", type=Path,
        default=ROOT / "data" / "seeds",
        help="Directory with *.json seed files",
    )
    ap.add_argument(
        "--out", type=Path,
        default=ROOT / "data" / "out" / "seeds.jsonl",
        help="Output JSONL path",
    )
    ap.add_argument(
        "--contracts", type=Path,
        default=ROOT / "data" / "contracts",
        help="Path to contracts directory",
    )
    ap.add_argument("--skip-validate", action="store_true",
                    help="Skip structural + semantic validation (not recommended)")
    args = ap.parse_args()

    if not args.input_dir.is_dir():
        print(f"error: input dir not found: {args.input_dir}", file=sys.stderr)
        return 2

    tools_by_name = {} if args.skip_validate else load_tool_schemas(args.contracts)

    mode_counts: dict[str, int] = {}
    written = 0
    failed = 0

    with args.out.open("w", encoding="utf-8") as out_f:
        for path in sorted(args.input_dir.glob("*.json")):
            try:
                with path.open(encoding="utf-8") as f:
                    ex = json.load(f)
            except json.JSONDecodeError as e:
                print(f"[FAIL] {path.name}: bad JSON: {e}", file=sys.stderr)
                failed += 1
                continue

            if not args.skip_validate:
                issues = check_structural(ex) + check_semantic(ex, tools_by_name)
                errs = [i for i in issues if i.severity == "error"]
                if errs:
                    print(f"[FAIL] {path.name}: {len(errs)} validation error(s):",
                          file=sys.stderr)
                    for i in errs:
                        loc = f" @ {i.path}" if i.path else ""
                        print(f"    {i.code}{loc}: {i.message}", file=sys.stderr)
                    failed += 1
                    continue

            mode = detect_mode(ex)
            mode_counts[mode] = mode_counts.get(mode, 0) + 1

            # strip _meta (OpenAI fine-tune rejects unknown top-level keys)
            ex.pop("_meta", None)

            # compact one-liner, preserve non-ASCII (Cyrillic)
            line = json.dumps(ex, ensure_ascii=False, separators=(",", ":"))
            out_f.write(line + "\n")
            written += 1
            print(f"[OK  ] {path.name}  mode={mode}")

    print()
    print(f"Written {written} line(s) to {args.out}")
    print(f"By mode: {mode_counts}")
    if failed:
        print(f"Failed:  {failed} file(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
