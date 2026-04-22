#!/usr/bin/env python3
"""Create a fine-tuning job on OpenAI.

Gated behind `--confirm` because fine-tune costs real money. By default runs
dry-run, prints what it would create, and exits.

Usage:
    python -m src.ft_client.openai.create_job                       # dry-run
    python -m src.ft_client.openai.create_job --confirm             # really submit
    python -m src.ft_client.openai.create_job --model gpt-4o-mini-2024-07-18
    python -m src.ft_client.openai.create_job --epochs 3 --suffix kmp-agent
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
DEFAULT_MODEL = "gpt-4o-mini-2024-07-18"

from src.utils import model_slug  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Create an OpenAI fine-tuning job")
    ap.add_argument("--ids-file", type=Path, default=None,
                    help="JSON file with training_file / validation_file ids "
                         "(default: last_upload_<model-slug>.json)")
    ap.add_argument("--training-file", default=None,
                    help="Override training_file id")
    ap.add_argument("--validation-file", default=None,
                    help="Override validation_file id")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--epochs", default="auto",
                    help="`auto` or an integer")
    ap.add_argument("--suffix", default="kmp-agent",
                    help="Suffix for the resulting model name")
    ap.add_argument("--confirm", action="store_true",
                    help="Actually submit the job (costs money). "
                         "Without --confirm, runs dry-run.")
    args = ap.parse_args()

    if load_dotenv:
        load_dotenv(ROOT / ".env")

    # Дефолтный путь к ids-файлу включает slug модели — согласован с upload.py.
    slug = model_slug(args.model)
    if args.ids_file is None:
        args.ids_file = ROOT / "src" / "ft_client" / f"last_upload_{slug}.json"

    train_id = args.training_file
    val_id = args.validation_file
    if (not train_id) and args.ids_file.is_file():
        data = json.loads(args.ids_file.read_text(encoding="utf-8"))
        train_id = train_id or data.get("training_file")
        val_id = val_id or data.get("validation_file")

    if not train_id:
        print("error: no training_file id (run upload.py first or pass "
              "--training-file)", file=sys.stderr)
        return 2

    hp: dict[str, object] = {}
    if args.epochs != "auto":
        try:
            hp["n_epochs"] = int(args.epochs)
        except ValueError:
            print(f"error: --epochs must be int or 'auto'", file=sys.stderr)
            return 2

    spec = {
        "training_file": train_id,
        "validation_file": val_id,
        "model": args.model,
        "suffix": args.suffix,
        "hyperparameters": hp or {"n_epochs": "auto"},
    }

    print("=== fine-tuning job spec ===")
    print(json.dumps(spec, indent=2))

    if not args.confirm:
        print("\nDRY RUN (no --confirm). Nothing submitted.")
        print("To actually create the job, re-run with --confirm.")
        return 0

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("error: OPENAI_API_KEY not set", file=sys.stderr)
        return 2
    try:
        from openai import OpenAI
    except ImportError:
        print("error: `openai` package missing", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key)
    kwargs = {k: v for k, v in spec.items() if v is not None}
    job = client.fine_tuning.jobs.create(**kwargs)

    print(f"\n[OK] created job: {job.id}")
    print(f"     status: {job.status}")
    print(f"     model: {job.model} -> suffix={args.suffix}")
    print(f"\nTrack with: python -m src.ft_client.openai.poll {job.id}")

    # persist job id for convenience (slug модели в имени — чтобы job'ы разных моделей не терялись)
    out = ROOT / "src" / "ft_client" / f"last_job_{slug}.json"
    out.write_text(json.dumps({"job_id": job.id, "status": job.status}, indent=2),
                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
