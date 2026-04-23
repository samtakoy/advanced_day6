#!/usr/bin/env python3
"""Локальное QLoRA-обучение через MLX (Apple Silicon).

Обёртка над mlx_lm.lora — готовит данные и запускает тренировку.
Датасет — single-turn extraction (system + user → assistant JSON),
формат OpenAI chat messages. Tool calling не используется.

Usage:
    python -m src.ft_client.mlx.train                                    # defaults
    python -m src.ft_client.mlx.train --model Qwen/Qwen2.5-7B-Instruct  # выбрать модель
    python -m src.ft_client.mlx.train --iters 10 --dry-run               # smoke test
    python -m src.ft_client.mlx.train --iters 600 --lora-layers 16       # полное обучение
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Корень проекта — на 4 уровня выше (mlx/ → ft_client/ → src/ → advanced_day6/)
ROOT = Path(__file__).resolve().parent.parent.parent.parent

from src.utils import model_slug  # noqa: E402

# Модель по умолчанию — Qwen 2.5 7B Instruct.
# mlx_lm автоматически скачивает её с HuggingFace при первом запуске.
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

# Гиперпараметры по умолчанию (разумные для ~50 примеров на 7B модели):
#   iters=600   — ~13 эпох на 45 примерах (45 * 13 ≈ 585)
#   lora-layers=8 — экономит ~6GB RAM (16 + max-seq-length 4096 → OOM на 48GB Mac)
#   batch-size=1  — минимальный батч, экономит RAM
DEFAULT_ITERS = 600
DEFAULT_LORA_LAYERS = 8
DEFAULT_BATCH_SIZE = 1
DEFAULT_LEARNING_RATE = 1e-5
# Extraction-примеры короткие (~1300-1800 токенов), 4096 с запасом.
DEFAULT_MAX_SEQ_LENGTH = 4096


def prepare_data_dir(
    train_jsonl: Path,
    eval_jsonl: Path | None,
    out_dir: Path,
) -> Path:
    """Подготовить папку с данными для mlx_lm.

    mlx_lm ожидает папку с train.jsonl (и опционально valid.jsonl).
    Наш датасет уже в формате OpenAI chat messages — просто копируем.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    def copy_jsonl(src: Path, dst: Path) -> int:
        count = 0
        with src.open(encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                fout.write(line + "\n")
                count += 1
        return count

    n_train = copy_jsonl(train_jsonl, out_dir / "train.jsonl")
    print(f"  train.jsonl: {n_train} примеров")

    if eval_jsonl and eval_jsonl.is_file():
        n_eval = copy_jsonl(eval_jsonl, out_dir / "valid.jsonl")
        print(f"  valid.jsonl: {n_eval} примеров")

    return out_dir


def build_mlx_command(args: argparse.Namespace, data_dir: Path) -> list[str]:
    """Собрать команду для запуска mlx_lm.lora."""
    cmd = [
        sys.executable, "-m", "mlx_lm.lora",
        "--model", args.model,
        "--data", str(data_dir),
        "--train",
        # --mask-prompt: считать loss только по assistant-ответу (не по system+user).
        # Single-turn extraction — mask-prompt работает корректно.
        "--mask-prompt",
        "--iters", str(args.iters),
        "--num-layers", str(args.lora_layers),
        "--batch-size", str(args.batch_size),
        "--learning-rate", str(args.learning_rate),
        "--adapter-path", str(args.adapter_path),
        "--max-seq-length", str(args.max_seq_length),
    ]

    # Gradient accumulation и checkpointing
    if args.grad_accum_steps > 1:
        cmd += ["--grad-accumulation-steps", str(args.grad_accum_steps)]
    if args.grad_checkpoint:
        cmd += ["--grad-checkpoint"]

    cmd += ["--save-every", str(args.save_every),
            "--steps-per-eval", str(args.steps_per_eval)]
    if (data_dir / "valid.jsonl").exists():
        cmd += ["--val-batches", str(args.val_batches)]

    return cmd


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MLX QLoRA fine-tuning для extraction-модели (Apple Silicon)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"HuggingFace model ID (default: {DEFAULT_MODEL})")
    ap.add_argument("--train", type=Path,
                    default=ROOT / "data" / "out" / "train.jsonl",
                    help="Путь к train.jsonl")
    ap.add_argument("--eval", type=Path,
                    default=ROOT / "data" / "out" / "eval.jsonl",
                    help="Путь к eval.jsonl (для валидации во время обучения)")
    ap.add_argument("--iters", type=int, default=DEFAULT_ITERS,
                    help=f"Число итераций обучения (default: {DEFAULT_ITERS})")
    ap.add_argument("--lora-layers", type=int, default=DEFAULT_LORA_LAYERS,
                    help=f"Число LoRA-слоёв (default: {DEFAULT_LORA_LAYERS})")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                    help=f"Размер батча (default: {DEFAULT_BATCH_SIZE})")
    ap.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE,
                    help=f"Learning rate (default: {DEFAULT_LEARNING_RATE})")
    ap.add_argument("--max-seq-length", type=int, default=DEFAULT_MAX_SEQ_LENGTH,
                    help=f"Макс. длина последовательности в токенах (default: {DEFAULT_MAX_SEQ_LENGTH})")
    ap.add_argument("--grad-accum-steps", type=int, default=1,
                    help="Gradient accumulation: симулирует больший batch без роста RAM (default: 1)")
    ap.add_argument("--grad-checkpoint", action="store_true",
                    help="Gradient checkpointing: экономит ~40%% RAM, замедляет ~20%%")
    ap.add_argument("--save-every", type=int, default=50,
                    help="Сохранять checkpoint каждые N итераций (default: 50)")
    ap.add_argument("--steps-per-eval", type=int, default=50,
                    help="Считать val loss каждые N итераций (default: 50)")
    ap.add_argument("--val-batches", type=int, default=11,
                    help="Число eval-примеров для val loss (default: 11 — весь eval)")
    ap.add_argument("--adapter-path", type=Path, default=None,
                    help="Куда сохранить LoRA-адаптер (default: data/mlx/<model-slug>/adapters)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Показать команду без запуска")
    args = ap.parse_args()

    # Все MLX-артефакты в data/mlx/<model-slug>/ — рядом с остальными данными.
    # Пример: data/mlx/qwen2.5-7b-instruct/adapters/
    slug = model_slug(args.model)
    if args.adapter_path is None:
        args.adapter_path = ROOT / "data" / "mlx" / slug / "adapters"

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
    print("=== Подготовка данных ===")

    # Подготовленные данные рядом с адаптером: data/mlx/<slug>/mlx_data/
    data_dir = args.adapter_path.parent / "mlx_data"
    prepare_data_dir(args.train, args.eval, data_dir)

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
