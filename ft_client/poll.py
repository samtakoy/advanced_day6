#!/usr/bin/env python3
"""Poll OpenAI fine-tuning job status until terminal.

Usage:
    python -m ft_client.poll <job_id>
    python -m ft_client.poll                 # reads last_job.json
    python -m ft_client.poll --interval 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {"succeeded", "failed", "cancelled"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Poll an OpenAI fine-tune job")
    ap.add_argument("job_id", nargs="?", default=None)
    ap.add_argument("--interval", type=int, default=30,
                    help="Seconds between polls (default 30)")
    ap.add_argument("--job-file", type=Path,
                    default=ROOT / "ft_client" / "last_job.json")
    args = ap.parse_args()

    if load_dotenv:
        load_dotenv(ROOT / ".env")

    job_id = args.job_id
    if (not job_id) and args.job_file.is_file():
        job_id = json.loads(args.job_file.read_text(encoding="utf-8")).get("job_id")
    if not job_id:
        print("error: no job id (pass as arg or create job first)", file=sys.stderr)
        return 2

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
    print(f"Polling job {job_id} every {args.interval}s. Ctrl+C to stop.")
    last = None
    while True:
        job = client.fine_tuning.jobs.retrieve(job_id)
        status = job.status
        if status != last:
            print(f"[{time.strftime('%H:%M:%S')}] status={status}  "
                  f"trained_tokens={getattr(job, 'trained_tokens', None)}")
            last = status
        if status in TERMINAL:
            if status == "succeeded":
                print(f"\nFine-tuned model: {job.fine_tuned_model}")
            else:
                err = getattr(job, "error", None)
                print(f"\nJob ended as {status}. error={err}")
            return 0 if status == "succeeded" else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
