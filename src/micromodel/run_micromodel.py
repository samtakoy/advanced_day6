#!/usr/bin/env python3
"""День 10 — Micro-model пайплайн: rules (модули) + LLM (остальное).

Использование:
    python -m src.micromodel.run_micromodel --dry-run
    python -m src.micromodel.run_micromodel --limit 1
    python -m src.micromodel.run_micromodel --threshold 0.95
    python -m src.micromodel.run_micromodel --sweep
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

from src.baseline.run_baseline import ExampleMetrics, call_api, load_eval, parse_response, score  # noqa: E402
from src.micromodel.classifier import MicroResult, call_micro  # noqa: E402
from src.micromodel.pipeline import PipelineResult, run_pipeline, SUFFIX_MICRO  # noqa: E402
from src.micromodel.rules import extract_modules  # noqa: E402
from src.utils import model_slug  # noqa: E402


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_client(provider: str):
    """Создать OpenAI-совместимый клиент для провайдера."""
    from openai import OpenAI
    if provider == "ollama":
        return OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")
    elif provider == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            print("error: OPENROUTER_API_KEY not set", file=sys.stderr)
            sys.exit(2)
        return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")
    else:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            print("error: OPENAI_API_KEY not set", file=sys.stderr)
            sys.exit(2)
        return OpenAI(api_key=key)


def _resolve_model(model: str, provider: str) -> str:
    """Добавить префикс провайдера для OpenRouter."""
    if provider == "openrouter" and "/" not in model:
        return f"openai/{model}"
    return model


def _print_result(r: PipelineResult) -> None:
    """Вывести результат одного примера в консоль."""
    level = "micro" if not r.escalated else "big (fallback)"
    print(f"  resolved: {level}")
    print(f"  rules modules: {r.rules_modules}")

    if r.micro_result:
        mi = r.micro_result
        print(f"  micro: conf={mi.confidence:.2f}  "
              f"tokens={mi.tokens_in}+{mi.tokens_out}  ({mi.latency_ms:.0f}ms)")

    if r.escalated:
        print(f"  big: tokens={r.big_tokens_in}+{r.big_tokens_out}  ({r.big_latency_ms:.0f}ms)")

    m = r.metrics
    if m and not m.error:
        print(f"  type={'ok' if m.type_match else 'MISS'}  "
              f"block={'ok' if m.block_match else 'MISS'}  "
              f"modules_iou={m.modules_iou:.2f}  deps_iou={m.depends_on_iou:.2f}")
    elif m and m.error:
        print(f"  ERROR: {m.error}")

    print(f"  total: tokens={r.total_tokens_in}+{r.total_tokens_out}  "
          f"latency={r.total_latency_ms:.0f}ms")


# ---------------------------------------------------------------------------
# Сохранение результатов
# ---------------------------------------------------------------------------

def _save_results(results: list[PipelineResult], out_dir: Path,
                  micro_model: str, big_model: str, threshold: float) -> None:
    """Сохранить per-example JSON, summary.json и summary.md."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-example JSON
    for r in results:
        path = out_dir / f"{r.name}.json"
        data = {
            "name": r.name,
            "escalated": r.escalated,
            "rules_modules": r.rules_modules,
            "micro": {
                "confidence": r.micro_result.confidence,
                "predicted": r.micro_result.predicted,
                "tokens_in": r.micro_result.tokens_in,
                "tokens_out": r.micro_result.tokens_out,
                "latency_ms": r.micro_result.latency_ms,
            } if r.micro_result else None,
            "big": {
                "predicted": r.big_extraction,
                "tokens_in": r.big_tokens_in,
                "tokens_out": r.big_tokens_out,
                "latency_ms": r.big_latency_ms,
            } if r.escalated else None,
            "final_extraction": r.final_extraction,
            "metrics": asdict(r.metrics) if r.metrics else None,
            "total_tokens_in": r.total_tokens_in,
            "total_tokens_out": r.total_tokens_out,
            "total_latency_ms": r.total_latency_ms,
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Агрегированная статистика
    n = len(results)
    valid = [r for r in results if r.metrics and not r.metrics.error]
    n_esc = sum(1 for r in results if r.escalated)

    agg: dict = {
        "config": {"micro_model": micro_model, "big_model": big_model, "threshold": threshold},
        "total": n,
        "on_micro": n - n_esc,
        "escalated": n_esc,
    }
    if valid:
        agg["metrics"] = {
            "avg_modules_iou": round(sum(r.metrics.modules_iou for r in valid) / len(valid), 3),
            "type_match_rate": round(sum(1 for r in valid if r.metrics.type_match) / len(valid), 3),
            "block_match_rate": round(sum(1 for r in valid if r.metrics.block_match) / len(valid), 3),
            "avg_depends_on_iou": round(sum(r.metrics.depends_on_iou for r in valid) / len(valid), 3),
            "avg_ac_recall": round(sum(r.metrics.ac_recall for r in valid) / len(valid), 3),
            "avg_oos_precision": round(sum(r.metrics.oos_precision for r in valid) / len(valid), 3),
        }
    agg["tokens"] = {
        "total_in": sum(r.total_tokens_in for r in results),
        "total_out": sum(r.total_tokens_out for r in results),
    }
    agg["avg_latency_ms"] = round(sum(r.total_latency_ms for r in results) / n, 1) if n else 0

    # summary.json
    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(agg, f, ensure_ascii=False, indent=2)

    # summary.md
    lines = [
        f"# Day 10: Micro-model Pipeline",
        f"",
        f"**Micro:** {micro_model}  |  **Big:** {big_model}  |  **Threshold:** {threshold}",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| On micro | {n - n_esc}/{n} ({(n-n_esc)/n:.0%}) |",
        f"| Escalated to big | {n_esc}/{n} ({n_esc/n:.0%}) |",
    ]
    if valid:
        m = agg["metrics"]
        lines.extend([
            f"| modules IoU | {m['avg_modules_iou']:.3f} |",
            f"| type match | {m['type_match_rate']:.1%} |",
            f"| block match | {m['block_match_rate']:.1%} |",
            f"| dependsOn IoU | {m['avg_depends_on_iou']:.3f} |",
            f"| AC recall | {m['avg_ac_recall']:.3f} |",
            f"| OoS precision | {m['avg_oos_precision']:.3f} |",
        ])
    lines.extend([
        f"| Tokens in | {agg['tokens']['total_in']} |",
        f"| Tokens out | {agg['tokens']['total_out']} |",
        f"| Avg latency | {agg['avg_latency_ms']:.0f}ms |",
        f"",
        f"## Per-example",
        f"",
        f"| # | escalated | micro_conf | type | block | modules_iou | latency |",
        f"|---|-----------|------------|------|-------|-------------|---------|",
    ])
    for r in results:
        m = r.metrics
        mc = f"{r.micro_result.confidence:.2f}" if r.micro_result else "-"
        esc = "yes" if r.escalated else "no"
        if m and not m.error:
            lines.append(
                f"| {r.name} | {esc} | {mc} | "
                f"{'ok' if m.type_match else 'MISS'} | "
                f"{'ok' if m.block_match else 'MISS'} | "
                f"{m.modules_iou:.2f} | {r.total_latency_ms:.0f}ms |"
            )
        else:
            lines.append(f"| {r.name} | {esc} | {mc} | ERR | ERR | - | {r.total_latency_ms:.0f}ms |")

    with (out_dir / "summary.md").open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n  summary.json -> {out_dir / 'summary.json'}")
    print(f"  summary.md   -> {out_dir / 'summary.md'}")


# ---------------------------------------------------------------------------
# Sweep — подбор порога
# ---------------------------------------------------------------------------

def run_sweep(examples, micro_client, big_client, micro_model, big_model,
              temperature, micro_num_ctx, big_num_ctx, out_dir):
    """Прогнать все примеры через micro и big один раз,
    затем симулировать разные пороги без дополнительных вызовов API."""
    n = len(examples)
    print(f"\n=== Sweep Mode ({n} examples) ===")

    # Фаза 1: Rules — извлекаем модули (0 API-вызовов)
    print(f"\n--- Фаза 1: Rules ---")
    all_modules: list[list[str]] = []
    for name, messages in examples:
        mods = extract_modules(messages[1]["content"])
        all_modules.append(mods)
        print(f"  {name}: {mods}")

    # Фаза 2: Маленькая LLM на всех примерах
    print(f"\n--- Фаза 2: Micro ({micro_model}) ---")
    system_prompt = examples[0][1][0]["content"] + SUFFIX_MICRO
    micro_results: list[MicroResult] = []
    for name, messages in examples:
        prompt_msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": messages[1]["content"]},
        ]
        mi = call_micro(micro_client, micro_model, prompt_msgs,
                        temperature=temperature, num_ctx=micro_num_ctx)
        micro_results.append(mi)
        print(f"  {name}: conf={mi.confidence:.2f}  "
              f"tokens={mi.tokens_in}+{mi.tokens_out}  ({mi.latency_ms:.0f}ms)")

    # Фаза 3: Большая LLM на всех примерах
    print(f"\n--- Фаза 3: Big ({big_model}) ---")
    big_results: list[tuple[dict | None, int, int, float]] = []
    for name, messages in examples:
        prompt_msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": messages[1]["content"]},
        ]
        import time
        t0 = time.perf_counter()
        resp = call_api(big_client, big_model, prompt_msgs, temperature, num_ctx=big_num_ctx)
        raw = resp.choices[0].message.content or ""
        predicted, _, _ = parse_response(raw)
        latency = (time.perf_counter() - t0) * 1000
        big_results.append((predicted, resp.usage.prompt_tokens, resp.usage.completion_tokens, latency))
        print(f"  {name}: tokens={resp.usage.prompt_tokens}+{resp.usage.completion_tokens}  "
              f"({latency:.0f}ms)")

    # Фаза 4: Симуляция порогов (без API-вызовов)
    golds = [json.loads(msgs[2]["content"]) for _, msgs in examples]
    big_total_tokens = sum(tin + tout for _, tin, tout, _ in big_results)

    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    sweep_rows: list[dict] = []

    for t in thresholds:
        n_micro = 0
        n_big = 0
        total_tokens = 0
        iou_sum = 0.0
        type_ok = 0
        block_ok = 0

        for i in range(n):
            mods = all_modules[i]
            micro = micro_results[i]
            big_pred, big_tin, big_tout, _ = big_results[i]

            if micro.confidence >= t and micro.predicted is not None:
                # Micro прошла порог — берём её результат
                n_micro += 1
                pred = dict(micro.predicted)
                pred["modules"] = mods
                total_tokens += micro.tokens_in + micro.tokens_out
            else:
                # Micro не прошла — берём big
                n_big += 1
                pred = dict(big_pred) if big_pred else {}
                pred["modules"] = mods
                total_tokens += micro.tokens_in + micro.tokens_out + big_tin + big_tout

            m = score(golds[i], pred)
            iou_sum += m.modules_iou
            if m.type_match:
                type_ok += 1
            if m.block_match:
                block_ok += 1

        tokens_saved = 1.0 - (total_tokens / big_total_tokens) if big_total_tokens else 0
        sweep_rows.append({
            "threshold": t,
            "pct_micro": round(n_micro / n, 3),
            "pct_big": round(n_big / n, 3),
            "modules_iou": round(iou_sum / n, 3),
            "type_match": round(type_ok / n, 3),
            "block_match": round(block_ok / n, 3),
            "tokens_saved": round(tokens_saved, 3),
        })

    # Вывод таблицы
    print(f"\n| threshold | % micro | % big | modules_iou | type | block | tokens_saved |")
    print(f"|-----------|---------|-------|-------------|------|-------|--------------|")
    for row in sweep_rows:
        print(f"| {row['threshold']:.2f}      | {row['pct_micro']:.0%}     | {row['pct_big']:.0%}   | "
              f"{row['modules_iou']:.3f}       | {row['type_match']:.0%}  | "
              f"{row['block_match']:.0%}   | {row['tokens_saved']:.0%}            |")

    # Сохранение
    sweep_dir = out_dir / "sweep"
    sweep_dir.mkdir(parents=True, exist_ok=True)

    with (sweep_dir / "sweep.json").open("w", encoding="utf-8") as f:
        json.dump({
            "config": {"micro_model": micro_model, "big_model": big_model, "examples": n},
            "micro_confidences": [m.confidence for m in micro_results],
            "sweep": sweep_rows,
        }, f, ensure_ascii=False, indent=2)

    lines = [
        f"# Day 10: Threshold Sweep",
        f"",
        f"**Micro:** {micro_model}  |  **Big:** {big_model}  |  N={n}",
        f"",
        f"| threshold | % micro | % big | modules_iou | type | block | tokens_saved |",
        f"|-----------|---------|-------|-------------|------|-------|--------------|",
    ]
    for row in sweep_rows:
        lines.append(
            f"| {row['threshold']:.2f} | {row['pct_micro']:.0%} | {row['pct_big']:.0%} | "
            f"{row['modules_iou']:.3f} | {row['type_match']:.0%} | "
            f"{row['block_match']:.0%} | {row['tokens_saved']:.0%} |"
        )

    with (sweep_dir / "sweep.md").open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n  sweep.json -> {sweep_dir / 'sweep.json'}")
    print(f"  sweep.md   -> {sweep_dir / 'sweep.md'}")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="День 10: Micro-model пайплайн")
    ap.add_argument("--from-jsonl", type=Path, default=ROOT / "data" / "out" / "eval.jsonl")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data" / "micromodel")
    ap.add_argument("--micro-model", default="qwen2.5:3b")
    ap.add_argument("--big-model", default="gpt-4o-mini")
    ap.add_argument("--micro-provider", default="ollama", choices=["ollama"])
    ap.add_argument("--big-provider", default="auto", choices=["auto", "openai", "openrouter", "ollama"])
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--micro-num-ctx", type=int, default=None)
    ap.add_argument("--big-num-ctx", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sweep", action="store_true",
                    help="Подбор порога: прогнать micro+big по одному разу, симулировать пороги")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    # Определяем провайдер для большой модели
    big_provider = args.big_provider
    if big_provider == "auto":
        big_provider = "openrouter" if os.getenv("OPENROUTER_API_KEY") else "openai"
    big_model = _resolve_model(args.big_model, big_provider)

    slug = f"{model_slug(args.micro_model)}_to_{model_slug(args.big_model)}"
    out_dir = args.out_dir / slug

    if not args.from_jsonl.is_file():
        print(f"error: {args.from_jsonl} not found", file=sys.stderr)
        return 2

    examples = load_eval(args.from_jsonl)
    if args.limit:
        examples = examples[:args.limit]
    if not examples:
        print("error: no examples loaded", file=sys.stderr)
        return 1

    print(f"Day 10: Micro-model Pipeline")
    print(f"  Micro: {args.micro_model} ({args.micro_provider})")
    print(f"  Big:   {big_model} ({big_provider})")
    print(f"  Threshold: {args.threshold}")
    print(f"  Examples: {len(examples)}")

    # Dry-run: показать что будет без API-вызовов
    if args.dry_run:
        for name, messages in examples:
            gold = json.loads(messages[2]["content"])
            mods = extract_modules(messages[1]["content"])
            print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")
            print(f"  rules modules: {mods}")
            print(f"  -> micro ({args.micro_model}) извлекает остальное; "
                  f"big ({big_model}) как fallback")
        print("\n(dry run)")
        return 0

    # Создаём клиенты
    micro_client = _make_client(args.micro_provider)
    big_client = _make_client(big_provider)

    # Sweep: подбор порога
    if args.sweep:
        run_sweep(examples, micro_client, big_client, args.micro_model, big_model,
                  args.temperature, args.micro_num_ctx, args.big_num_ctx, out_dir)
        return 0

    # Обычный прогон
    results: list[PipelineResult] = []
    for name, messages in examples:
        gold = json.loads(messages[2]["content"])
        print(f"\n--- {name} (gold.title={gold.get('title', '?')[:50]}) ---")
        r = run_pipeline(name, messages, gold, micro_client, big_client,
                         args.micro_model, big_model, threshold=args.threshold,
                         temperature=args.temperature, micro_num_ctx=args.micro_num_ctx,
                         big_num_ctx=args.big_num_ctx)
        results.append(r)
        _print_result(r)

    # Сводка
    n = len(results)
    n_esc = sum(1 for r in results if r.escalated)
    valid = [r for r in results if r.metrics and not r.metrics.error]

    print(f"\n=== Сводка ===")
    print(f"  На micro: {n - n_esc}/{n} ({(n-n_esc)/n:.0%})")
    print(f"  Escalated: {n_esc}/{n} ({n_esc/n:.0%})")
    if valid:
        print(f"  modules_iou: {sum(r.metrics.modules_iou for r in valid)/len(valid):.3f}")
        print(f"  type match: {sum(1 for r in valid if r.metrics.type_match)/len(valid):.1%}")
        print(f"  block match: {sum(1 for r in valid if r.metrics.block_match)/len(valid):.1%}")
    print(f"  tokens: in={sum(r.total_tokens_in for r in results)} "
          f"out={sum(r.total_tokens_out for r in results)}")
    print(f"  avg latency: {sum(r.total_latency_ms for r in results)/n:.0f}ms")

    _save_results(results, out_dir, args.micro_model, big_model, args.threshold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
