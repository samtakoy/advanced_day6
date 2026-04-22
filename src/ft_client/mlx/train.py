#!/usr/bin/env python3
"""Локальное QLoRA-обучение через MLX (Apple Silicon).

Обёртка над mlx_lm.lora — готовит данные и запускает тренировку.
mlx_lm нативно поддерживает OpenAI chat format с tool_calls (v0.31+):
  - ключ "messages" в каждой JSONL-строке — стандартный chat format
  - ключ "tools" — список tool schemas, нужен для Qwen chat template

Скрипт автоматически добавляет "tools" из contracts/tool_schemas.json
в каждую строку датасета перед запуском обучения.

Usage:
    python -m src.ft_client.mlx.train                                    # defaults
    python -m src.ft_client.mlx.train --model Qwen/Qwen2.5-7B-Instruct  # выбрать модель
    python -m src.ft_client.mlx.train --iters 10 --dry-run               # smoke test
    python -m src.ft_client.mlx.train --iters 600 --lora-layers 16       # полное обучение
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Корень проекта — на 4 уровня выше (mlx/ → ft_client/ → src/ → advanced_day6/)
ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Модель по умолчанию — Qwen 2.5 7B Instruct.
# mlx_lm автоматически скачивает её с HuggingFace при первом запуске.
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

# Гиперпараметры по умолчанию (разумные для ~50 примеров на 7B модели):
#   iters=600   — ~12 эпох на 47 примерах (47 * 12 ≈ 564)
#   lora-layers=16 — количество слоёв для LoRA-адаптера
#   batch-size=1   — минимальный батч, экономит RAM
DEFAULT_ITERS = 600
DEFAULT_LORA_LAYERS = 16
DEFAULT_BATCH_SIZE = 1
DEFAULT_LEARNING_RATE = 1e-5


def load_tool_schemas(contracts_dir: Path) -> list[dict]:
    """Загрузить tool schemas из contracts/tool_schemas.json."""
    schemas_path = contracts_dir / "tool_schemas.json"
    with schemas_path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["tools"]


def prepare_data_dir(
    train_jsonl: Path,
    eval_jsonl: Path | None,
    tools: list[dict],
    out_dir: Path,
) -> Path:
    """Подготовить временную папку с данными для mlx_lm.

    mlx_lm ожидает папку с train.jsonl (и опционально valid.jsonl).
    Каждая строка должна содержать "messages" и "tools".
    Наш датасет уже содержит "messages", но "tools" нужно добавить —
    без этого Qwen chat template не вставит описания инструментов в промпт.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    def inject_tools_into_jsonl(src: Path, dst: Path) -> int:
        """Скопировать JSONL, добавив "tools" к каждой строке. Возвращает число строк."""
        count = 0
        with src.open(encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                example = json.loads(line)
                # Добавляем tools только если их ещё нет
                if "tools" not in example:
                    example["tools"] = tools
                fout.write(json.dumps(example, ensure_ascii=False) + "\n")
                count += 1
        return count

    n_train = inject_tools_into_jsonl(train_jsonl, out_dir / "train.jsonl")
    print(f"  train.jsonl: {n_train} примеров (tools injected)")

    if eval_jsonl and eval_jsonl.is_file():
        n_eval = inject_tools_into_jsonl(eval_jsonl, out_dir / "valid.jsonl")
        print(f"  valid.jsonl: {n_eval} примеров (tools injected)")

    return out_dir


def build_mlx_command(args: argparse.Namespace, data_dir: Path) -> list[str]:
    """Собрать команду для запуска mlx_lm.lora."""
    cmd = [
        sys.executable, "-m", "mlx_lm.lora",
        "--model", args.model,
        "--data", str(data_dir),
        "--train",
        # --mask-prompt: считать loss только по ответу модели (не по промпту).
        # Это стандартная практика для chat fine-tune — мы учим модель генерировать
        # правильные ответы, а не запоминать промпты.
        "--mask-prompt",
        "--iters", str(args.iters),
        "--num-layers", str(args.lora_layers),
        "--batch-size", str(args.batch_size),
        "--learning-rate", str(args.learning_rate),
        "--adapter-path", str(args.adapter_path),
    ]

    # Eval каждые 50 итераций (если есть valid.jsonl)
    if (data_dir / "valid.jsonl").exists():
        cmd += ["--val-batches", "5"]

    return cmd


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MLX QLoRA fine-tuning для KMP-агента (Apple Silicon)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"HuggingFace model ID (default: {DEFAULT_MODEL})")
    ap.add_argument("--train", type=Path,
                    default=ROOT / "data" / "out" / "train.jsonl",
                    help="Путь к train.jsonl")
    ap.add_argument("--eval", type=Path,
                    default=ROOT / "data" / "out" / "eval.jsonl",
                    help="Путь к eval.jsonl (для валидации во время обучения)")
    ap.add_argument("--contracts", type=Path,
                    default=ROOT / "data" / "contracts",
                    help="Папка с tool_schemas.json")
    ap.add_argument("--iters", type=int, default=DEFAULT_ITERS,
                    help=f"Число итераций обучения (default: {DEFAULT_ITERS})")
    ap.add_argument("--lora-layers", type=int, default=DEFAULT_LORA_LAYERS,
                    help=f"Число LoRA-слоёв (default: {DEFAULT_LORA_LAYERS})")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                    help=f"Размер батча (default: {DEFAULT_BATCH_SIZE})")
    ap.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE,
                    help=f"Learning rate (default: {DEFAULT_LEARNING_RATE})")
    ap.add_argument("--adapter-path", type=Path,
                    default=ROOT / "adapters",
                    help="Куда сохранить LoRA-адаптер (default: ./adapters)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Показать команду без запуска")
    args = ap.parse_args()

    # --- Проверки ---
    if not args.train.is_file():
        print(f"error: train файл не найден: {args.train}", file=sys.stderr)
        return 2

    # Проверяем что mlx_lm установлен
    try:
        import mlx_lm  # noqa: F401
    except ImportError:
        print("error: mlx_lm не установлен. Запустите: pip install mlx mlx-lm",
              file=sys.stderr)
        return 2

    # --- Подготовка данных ---
    # Создаём временную папку с данными, в которых к каждой строке добавлен "tools"
    print("=== Подготовка данных ===")
    tools = load_tool_schemas(args.contracts)
    print(f"  Загружено {len(tools)} tool schemas из {args.contracts}")

    # Используем папку рядом с адаптерами для подготовленных данных
    data_dir = args.adapter_path.parent / "mlx_data"
    prepare_data_dir(args.train, args.eval, tools, data_dir)

    # --- Сборка команды ---
    cmd = build_mlx_command(args, data_dir)

    print(f"\n=== MLX LoRA команда ===")
    print(" ".join(cmd))

    if args.dry_run:
        print("\nDRY RUN — обучение не запущено.")
        return 0

    # --- Запуск обучения ---
    print(f"\n=== Запуск обучения ({args.iters} итераций) ===")
    print(f"  Модель: {args.model}")
    print(f"  LoRA слоёв: {args.lora_layers}")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Адаптер будет сохранён в: {args.adapter_path}")
    print()

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print(f"\n[OK] Обучение завершено. Адаптер: {args.adapter_path}")
        print(f"Следующий шаг: python -m src.ft_client.mlx.export "
              f"--model {args.model} --adapter {args.adapter_path}")
    else:
        print(f"\n[FAIL] mlx_lm.lora завершился с кодом {result.returncode}",
              file=sys.stderr)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
