#!/usr/bin/env python3
"""Run the base gpt-4o-mini (no fine-tune) on seed tasks to capture baseline behavior.

For each selected seed:
  1. Extract the (system + first-user) prefix — i.e., the agent has NOT yet responded.
  2. Call gpt-4o-mini with those messages + all 8 tools from contracts/tool_schemas.json.
  3. Save the raw response to baseline/outputs/<seed_stem>.json.
  4. Score a few universal metrics (first_tool, THOUGHT, SELF-CHECK, task_id-in-args, tool-name validity).
  5. Write aggregated summary.json and summary.md.

This is the point-of-reference we compare against AFTER fine-tune.

Usage:
    python -m src.baseline.run_baseline --dry-run      # no API calls, show plan
    python -m src.baseline.run_baseline                # hits OpenAI, requires OPENAI_API_KEY
    python -m src.baseline.run_baseline --limit 3      # only first 3 seeds
    python -m src.baseline.run_baseline --modes agent  # filter modes (agent,agent_question,plain)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


# Корень проекта — на 3 уровня выше (baseline/ → src/ → advanced_day6/)
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.validator.validate import ALLOWED_TOOL_NAMES, detect_mode  # noqa: E402


@dataclass
class SeedMetrics:
    seed: str
    mode: str
    first_tool: str | None = None
    all_tools: list[str] = field(default_factory=list)
    tool_names_valid: bool = True
    has_thought: bool = False
    has_self_check: bool = False
    has_task_id_in_state_args: bool = False
    content_preview: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None


def load_seeds(seeds_dir: Path, modes: set[str]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for p in sorted(seeds_dir.glob("*.json")):
        with p.open(encoding="utf-8") as f:
            ex = json.load(f)
        mode = detect_mode(ex)
        if mode in modes:
            out.append((p.stem, ex))
    return out


def load_jsonl(jsonl_path: Path, modes: set[str]) -> list[tuple[str, dict]]:
    """Load examples from a JSONL file (e.g. eval.jsonl after mix_and_split).

    Each line is an example. Since mix_and_split strips _meta, we detect
    mode from structure. Names are index-based: eval_01, eval_02, ...
    """
    out: list[tuple[str, dict]] = []
    with jsonl_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            ex = json.loads(line)
            mode = detect_mode(ex)
            if mode in modes:
                name = f"{jsonl_path.stem}_{i:02d}_{mode}"
                out.append((name, ex))
    return out


def extract_prompt(messages: list[dict]) -> list[dict]:
    """Take system + first user (up to and including the first user turn)."""
    out: list[dict] = []
    for m in messages:
        out.append({"role": m["role"], "content": m.get("content") or ""})
        if m["role"] == "user":
            break
    return out


def load_tools(contracts_dir: Path) -> list[dict]:
    with (contracts_dir / "tool_schemas.json").open(encoding="utf-8") as f:
        return json.load(f)["tools"]


STATE_TOOLS_SET = {"plan_write", "step_read", "step_update_result",
                   "task_status", "plan_revise"}


def analyze_response(mode: str, content: str | None, tool_calls: list) -> SeedMetrics:
    content = content or ""
    m = SeedMetrics(seed="", mode=mode)
    m.has_thought = "THOUGHT:" in content
    m.has_self_check = "SELF-CHECK:" in content
    m.content_preview = content[:200].replace("\n", " ")
    if tool_calls:
        names = [tc.function.name for tc in tool_calls]
        m.first_tool = names[0]
        m.all_tools = names
        m.tool_names_valid = all(n in ALLOWED_TOOL_NAMES for n in names)
        # Check task_id presence in state-tool args
        task_id_ok = False
        for tc in tool_calls:
            if tc.function.name in STATE_TOOLS_SET:
                try:
                    args = json.loads(tc.function.arguments)
                    if "task_id" in args and args.get("task_id"):
                        task_id_ok = True
                        break
                except json.JSONDecodeError:
                    pass
        m.has_task_id_in_state_args = task_id_ok
    return m


def call_api(client, model: str, messages: list[dict], tools: list[dict],
             temperature: float, retries: int = 3):
    last_err = None
    for attempt in range(retries):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                temperature=temperature,
            )
        except Exception as e:
            last_err = e
            # crude backoff
            wait = 2 ** attempt
            print(f"  API error (attempt {attempt+1}/{retries}): {e}; retrying in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    raise last_err  # type: ignore[misc]


def main() -> int:
    ap = argparse.ArgumentParser(description="Run gpt-4o-mini baseline on seeds")
    ap.add_argument("--seeds", type=Path, default=ROOT / "data" / "seeds")
    ap.add_argument("--from-jsonl", type=Path, default=None,
                    help="Load examples from a JSONL file (e.g. dataset/eval.jsonl). "
                         "Overrides --seeds when given.")
    ap.add_argument("--contracts", type=Path, default=ROOT / "data" / "contracts")
    ap.add_argument("--out-dir", type=Path,
                    default=Path(__file__).resolve().parent / "outputs")
    ap.add_argument("--model", default="gpt-4o-mini",
                    help="Model name. For OpenRouter the 'openai/' prefix is auto-added if missing.")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--modes", default="agent,agent_question,plain",
                    help="Comma-separated modes to include")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only run on the first N seeds (after mode filter)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Do not hit the API; just print what would be sent")
    ap.add_argument("--provider", choices=["auto", "openai", "openrouter", "ollama"], default="auto",
                    help="Which provider to use. 'auto' picks OpenRouter if OPENROUTER_API_KEY "
                         "is set, else OpenAI. 'ollama' uses local Ollama on localhost:11434.")
    args = ap.parse_args()

    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    # Resolve provider, key, base_url, and adjusted model name
    # Поддерживаемые провайдеры:
    #   openai     — напрямую через OpenAI API
    #   openrouter — через OpenRouter (единый ключ на все модели)
    #   ollama     — локальная модель через Ollama (OpenAI-compat API на localhost:11434)
    #   auto       — openrouter если есть ключ, иначе openai
    provider = args.provider
    if provider == "auto":
        provider = "openrouter" if os.getenv("OPENROUTER_API_KEY") else "openai"

    if provider == "ollama":
        # Ollama предоставляет OpenAI-совместимый API на localhost:11434/v1.
        # API key не нужен — ставим заглушку, т.к. openai SDK требует непустую строку.
        api_key = "ollama"
        base_url = "http://localhost:11434/v1"
        model = args.model
    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = "https://openrouter.ai/api/v1"
        # OpenRouter requires a vendor prefix in the model name
        model = args.model if "/" in args.model else f"openai/{args.model}"
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = None  # SDK default
        model = args.model

    if not args.dry_run and not api_key:
        env_var = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
        print(f"error: {env_var} not set — populate .env or export it",
              file=sys.stderr)
        return 2

    # Auto-switch output dir if reading eval.jsonl and default out-dir is untouched
    default_out = Path(__file__).resolve().parent / "outputs"
    if args.from_jsonl and args.out_dir == default_out:
        args.out_dir = Path(__file__).resolve().parent / f"outputs_{args.from_jsonl.stem}"
    args.out_dir.mkdir(parents=True, exist_ok=True)

    modes = {m.strip() for m in args.modes.split(",") if m.strip()}
    if args.from_jsonl:
        if not args.from_jsonl.is_file():
            print(f"error: --from-jsonl file not found: {args.from_jsonl}",
                  file=sys.stderr)
            return 2
        seeds = load_jsonl(args.from_jsonl, modes)
        source_label = str(args.from_jsonl)
    else:
        seeds = load_seeds(args.seeds, modes)
        source_label = str(args.seeds)
    if args.limit:
        seeds = seeds[: args.limit]

    if not seeds:
        print(f"error: no examples matched modes={modes} in {source_label}", file=sys.stderr)
        return 1

    tools = load_tools(args.contracts)

    client = None
    if not args.dry_run:
        from openai import OpenAI
        if base_url:
            client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            client = OpenAI(api_key=api_key)
        print(f"Provider: {provider}  model: {model}")

    metrics_list: list[SeedMetrics] = []

    for seed_name, ex in seeds:
        mode = detect_mode(ex)
        prompt_msgs = extract_prompt(ex["messages"])
        print(f"\n--- {seed_name}  mode={mode}  n_prompt_msgs={len(prompt_msgs)} ---")

        if args.dry_run:
            resolved_model = args.model if ("/" in args.model or provider in ("openai", "ollama")) else f"openai/{args.model}"
            print(f"  would call {resolved_model} via {provider} with {len(tools)} tools, "
                  f"system+user prefix, temperature={args.temperature}")
            continue

        try:
            resp = call_api(client, model, prompt_msgs, tools, args.temperature)
        except Exception as e:
            print(f"  [ERROR] {e}", file=sys.stderr)
            m = SeedMetrics(seed=seed_name, mode=mode, error=str(e))
            metrics_list.append(m)
            continue

        choice = resp.choices[0]
        msg = choice.message
        tool_calls = msg.tool_calls or []

        # Persist raw response for later inspection
        raw_path = args.out_dir / f"{seed_name}.json"
        with raw_path.open("w", encoding="utf-8") as f:
            json.dump({
                "seed": seed_name,
                "mode": mode,
                "provider": provider,
                "model": model,
                "temperature": args.temperature,
                "input_messages": prompt_msgs,
                "response": {
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        } for tc in tool_calls
                    ],
                    "finish_reason": choice.finish_reason,
                },
                "usage": {
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                    "total_tokens": resp.usage.total_tokens,
                },
            }, f, ensure_ascii=False, indent=2)

        m = analyze_response(mode, msg.content, tool_calls)
        m.seed = seed_name
        m.tokens_in = resp.usage.prompt_tokens
        m.tokens_out = resp.usage.completion_tokens
        metrics_list.append(m)

        print(f"  first_tool={m.first_tool}  all_tools={m.all_tools}")
        print(f"  THOUGHT={m.has_thought}  SELF-CHECK={m.has_self_check}  "
              f"task_id_in_state_args={m.has_task_id_in_state_args}  "
              f"tool_names_valid={m.tool_names_valid}")
        print(f"  tokens in={m.tokens_in} out={m.tokens_out}")
        if m.content_preview:
            print(f"  content: {m.content_preview[:150]}...")

    if args.dry_run:
        print("\n(dry run — no outputs written)")
        return 0

    # Aggregate
    print("\n=== Summary ===")
    n = len(metrics_list)
    if n == 0:
        return 0

    def pct(cond) -> str:
        cnt = sum(1 for x in metrics_list if cond(x))
        return f"{cnt}/{n}"

    agent_ms = [x for x in metrics_list if x.mode == "agent" and not x.error]
    print(f"  seeds run: {n} (errors: {sum(1 for x in metrics_list if x.error)})")
    if agent_ms:
        na = len(agent_ms)
        pw = sum(1 for x in agent_ms if x.first_tool == "plan_write")
        th = sum(1 for x in agent_ms if x.has_thought)
        sc = sum(1 for x in agent_ms if x.has_self_check)
        tid = sum(1 for x in agent_ms if x.has_task_id_in_state_args)
        tv = sum(1 for x in agent_ms if x.tool_names_valid)
        print(f"  agent seeds ({na}):")
        print(f"    first_tool == plan_write:           {pw}/{na}")
        print(f"    THOUGHT present:                    {th}/{na}")
        print(f"    SELF-CHECK present:                 {sc}/{na}")
        print(f"    task_id in state-tool args:         {tid}/{na}")
        print(f"    all tool names valid (from set):    {tv}/{na}")

    tot_in = sum(x.tokens_in for x in metrics_list)
    tot_out = sum(x.tokens_out for x in metrics_list)
    print(f"  total tokens: in={tot_in} out={tot_out}")

    # Save JSON summary
    summary_json = args.out_dir / "summary.json"
    with summary_json.open("w", encoding="utf-8") as f:
        json.dump([asdict(x) for x in metrics_list], f, ensure_ascii=False, indent=2)
    print(f"\n  summary.json -> {summary_json}")

    # Also render a short Markdown summary
    summary_md = args.out_dir / "summary.md"
    lines = [
        f"# Baseline (provider={provider}, model={model}, T={args.temperature})",
        "",
        f"Seeds: **{n}**  |  errors: **{sum(1 for x in metrics_list if x.error)}**  |  "
        f"tokens: in={tot_in}, out={tot_out}",
        "",
        "| Seed | Mode | First tool | ToolsValid | THOUGHT | SELF-CHECK | task_id | tokens in/out |",
        "|------|------|------------|------------|---------|------------|---------|---------------|",
    ]
    for x in metrics_list:
        lines.append(
            f"| {x.seed} | {x.mode} | {x.first_tool or '—'} | "
            f"{'✓' if x.tool_names_valid else '✗'} | "
            f"{'✓' if x.has_thought else '✗'} | "
            f"{'✓' if x.has_self_check else '✗'} | "
            f"{'✓' if x.has_task_id_in_state_args else '✗'} | "
            f"{x.tokens_in}/{x.tokens_out} |"
        )
    with summary_md.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  summary.md   -> {summary_md}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
