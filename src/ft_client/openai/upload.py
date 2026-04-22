#!/usr/bin/env python3
"""Upload train.jsonl to OpenAI Files API (purpose=fine-tune).

Logs the resulting file_id; pipe into create_job.py.

Usage:
    python -m src.ft_client.openai.upload                    # default: data/out/train.jsonl
    python -m src.ft_client.openai.upload --file <path>
    python -m src.ft_client.openai.upload --validation <path>   # also upload eval.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# Корень проекта — на 4 уровня выше (openai/ → ft_client/ → src/ → advanced_day6/)
ROOT = Path(__file__).resolve().parent.parent.parent.parent


def upload_one(client, path: Path, purpose: str) -> str:
    print(f"Uploading {path} ({path.stat().st_size} bytes)...")
    with path.open("rb") as f:
        result = client.files.create(file=f, purpose=purpose)
    print(f"  -> file_id = {result.id}  status={result.status}")
    return result.id


def main() -> int:
    ap = argparse.ArgumentParser(description="Upload JSONL to OpenAI Files API")
    ap.add_argument("--file", type=Path,
                    default=ROOT / "data" / "out" / "train.jsonl",
                    help="Path to training JSONL")
    ap.add_argument("--validation", type=Path, default=None,
                    help="Optional validation JSONL (eval.jsonl)")
    ap.add_argument("--purpose", default="fine-tune")
    ap.add_argument("--save-ids", type=Path,
                    default=ROOT / "src" / "ft_client" / "last_upload.json",
                    help="Where to persist file_ids for create_job.py")
    args = ap.parse_args()

    if load_dotenv:
        load_dotenv(ROOT / ".env")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("error: OPENAI_API_KEY not set. Fine-tuning goes through OpenAI "
              "directly, not OpenRouter.", file=sys.stderr)
        return 2

    if not args.file.is_file():
        print(f"error: not found: {args.file}", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI
    except ImportError:
        print("error: `openai` package missing. `pip install openai`", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key)

    train_id = upload_one(client, args.file, args.purpose)

    val_id = None
    if args.validation:
        if not args.validation.is_file():
            print(f"warn: validation file not found: {args.validation}",
                  file=sys.stderr)
        else:
            val_id = upload_one(client, args.validation, args.purpose)

    payload = {"training_file": train_id, "validation_file": val_id}
    args.save_ids.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved ids -> {args.save_ids}")
    print("Next: python -m src.ft_client.openai.create_job --confirm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
