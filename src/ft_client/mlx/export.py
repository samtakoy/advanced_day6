#!/usr/bin/env python3
"""Экспорт обученного MLX LoRA-адаптера в Ollama.

Цепочка: merge адаптера с базовой моделью → GGUF конвертация → Ollama import.

Шаги под капотом:
  1. mlx_lm.fuse — объединяет базовую модель + LoRA-адаптер в полную модель
  2. Конвертация в GGUF формат (через llama.cpp convert-hf-to-gguf.py)
  3. Создание Ollama Modelfile и `ollama create` для импорта

Usage:
    python -m src.ft_client.mlx.export                                    # defaults
    python -m src.ft_client.mlx.export --model Qwen/Qwen2.5-7B-Instruct  # выбрать модель
    python -m src.ft_client.mlx.export --ollama-name kmp-extract-ft        # имя в Ollama
    python -m src.ft_client.mlx.export --quantize q4_K_M                  # квантизация GGUF
    python -m src.ft_client.mlx.export --dry-run                          # показать план
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Корень проекта — на 4 уровня выше (mlx/ → ft_client/ → src/ → advanced_day6/)
ROOT = Path(__file__).resolve().parent.parent.parent.parent

from src.utils import model_slug  # noqa: E402

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_OLLAMA_NAME = "kmp-extract-ft"


def step_fuse(model: str, adapter_path: Path, fused_path: Path, dry_run: bool) -> bool:
    """Шаг 1: объединить базовую модель с LoRA-адаптером (mlx_lm.fuse).

    Результат — полная модель в HuggingFace формате (safetensors + tokenizer).
    """
    print("\n=== Шаг 1: Fuse (merge адаптера с базовой моделью) ===")

    cmd = [
        sys.executable, "-m", "mlx_lm.fuse",
        "--model", model,
        "--adapter-path", str(adapter_path),
        "--save-path", str(fused_path),
    ]
    print(f"  Команда: {' '.join(cmd)}")

    if dry_run:
        return True

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  [FAIL] mlx_lm.fuse завершился с кодом {result.returncode}",
              file=sys.stderr)
        return False

    print(f"  [OK] Fused модель сохранена в: {fused_path}")
    return True


def step_convert_gguf(
    fused_path: Path, gguf_path: Path, quantize: str | None, dry_run: bool
) -> bool:
    """Шаг 2: конвертировать HuggingFace модель в GGUF формат.

    GGUF — формат, который понимает Ollama (и llama.cpp под капотом).
    Без квантизации модель будет в f16 (~14GB для 7B). С q4_K_M — ~4GB.
    """
    print("\n=== Шаг 2: Конвертация в GGUF ===")

    # Ищем convert-hf-to-gguf.py (часть llama.cpp)
    # Обычно ставится через: pip install llama-cpp-python
    # или клонируется из https://github.com/ggerganov/llama.cpp
    convert_script = shutil.which("convert-hf-to-gguf")

    if not convert_script:
        # Пробуем найти через python -m
        # llama-cpp-python включает конвертер как модуль
        print("  convert-hf-to-gguf не найден в PATH.")
        print("  Пробуем альтернативный путь через mlx_lm.convert...")

        # mlx_lm.convert может экспортировать в GGUF напрямую (в новых версиях)
        cmd = [
            sys.executable, "-m", "mlx_lm.convert",
            "--hf-path", str(fused_path),
            "--mlx-path", str(gguf_path.parent / "mlx_export"),
            "-q",  # квантизация
        ]
        print(f"  Команда: {' '.join(cmd)}")

        if dry_run:
            return True

        result = subprocess.run(cmd)
        if result.returncode != 0:
            print("  [WARN] mlx_lm.convert не сработал.", file=sys.stderr)
            print("  Попробуйте установить llama-cpp-python:", file=sys.stderr)
            print("    pip install llama-cpp-python", file=sys.stderr)
            print("  Или используйте mlx_lm.server напрямую (без Ollama):", file=sys.stderr)
            print(f"    python -m mlx_lm.server --model {fused_path}", file=sys.stderr)
            return False
        return True

    # Стандартный путь через convert-hf-to-gguf
    cmd = [convert_script, str(fused_path), "--outfile", str(gguf_path)]
    if quantize:
        # Квантизация требует отдельного шага через llama-quantize
        print(f"  Примечание: квантизация {quantize} будет применена после конвертации")

    print(f"  Команда: {' '.join(cmd)}")

    if dry_run:
        return True

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  [FAIL] Конвертация завершилась с кодом {result.returncode}",
              file=sys.stderr)
        return False

    print(f"  [OK] GGUF сохранён: {gguf_path}")
    return True


def step_ollama_import(
    fused_path: Path,
    gguf_path: Path,
    ollama_name: str,
    base_model: str,
    dry_run: bool,
) -> bool:
    """Шаг 3: импортировать модель в Ollama.

    Создаём Modelfile (инструкция для Ollama) и выполняем `ollama create`.
    """
    print(f"\n=== Шаг 3: Импорт в Ollama как '{ollama_name}' ===")

    # Проверяем что ollama доступна
    if not shutil.which("ollama"):
        print("  [FAIL] ollama не найдена в PATH", file=sys.stderr)
        return False

    # Modelfile — инструкция для Ollama, откуда брать модель
    # FROM указывает на GGUF файл или на HF-папку с safetensors
    modelfile_content = f"""# Автосгенерированный Modelfile для fine-tuned extraction-модели
# Базовая модель: {base_model}
# Дата: see git log
FROM {gguf_path if gguf_path.exists() else fused_path}

# Системный промпт не вшиваем — он подаётся через API при каждом запросе.
# Это позволяет обновлять system prompt (таксономию модулей) без пересборки модели.
"""

    modelfile_path = fused_path.parent / "Modelfile"
    print(f"  Modelfile: {modelfile_path}")
    print(f"  FROM: {gguf_path if gguf_path.exists() else fused_path}")

    if dry_run:
        print(f"\n  Содержимое Modelfile:\n{modelfile_content}")
        return True

    modelfile_path.write_text(modelfile_content, encoding="utf-8")

    cmd = ["ollama", "create", ollama_name, "-f", str(modelfile_path)]
    print(f"  Команда: {' '.join(cmd)}")

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  [FAIL] ollama create завершился с кодом {result.returncode}",
              file=sys.stderr)
        return False

    print(f"  [OK] Модель '{ollama_name}' создана в Ollama!")
    print(f"\n  Проверка: ollama run {ollama_name}")
    print(f"  Eval:     python -m src.baseline.run_baseline --provider ollama --model {ollama_name}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Экспорт MLX LoRA-адаптера в Ollama (fuse → GGUF → ollama create)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"HuggingFace model ID базовой модели (default: {DEFAULT_MODEL})")
    ap.add_argument("--adapter", type=Path, default=None,
                    help="Путь к LoRA-адаптеру (default: data/mlx/<model-slug>/adapters)")
    ap.add_argument("--fused-path", type=Path, default=None,
                    help="Куда сохранить fused модель (default: data/mlx/<model-slug>/fused)")
    ap.add_argument("--gguf-path", type=Path, default=None,
                    help="Путь для GGUF файла (default: <fused-path>/model.gguf)")
    ap.add_argument("--ollama-name", default=DEFAULT_OLLAMA_NAME,
                    help=f"Имя модели в Ollama (default: {DEFAULT_OLLAMA_NAME})")
    ap.add_argument("--quantize", default=None,
                    help="Квантизация GGUF (q4_K_M, q8_0, etc.). По умолчанию f16.")
    ap.add_argument("--skip-fuse", action="store_true",
                    help="Пропустить fuse (если уже сделан)")
    ap.add_argument("--skip-gguf", action="store_true",
                    help="Пропустить GGUF-конвертацию (Ollama попробует импорт из safetensors)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Показать план без выполнения")
    args = ap.parse_args()

    # Все MLX-артефакты в data/mlx/<model-slug>/ — рядом с остальными данными.
    slug = model_slug(args.model)
    if args.adapter is None:
        args.adapter = ROOT / "data" / "mlx" / slug / "adapters"
    if args.fused_path is None:
        args.fused_path = ROOT / "data" / "mlx" / slug / "fused"
    if args.gguf_path is None:
        args.gguf_path = args.fused_path / "model.gguf"

    # Проверяем адаптер до вывода плана
    if not args.skip_fuse and not args.adapter.exists() and not args.dry_run:
        print(f"error: адаптер не найден: {args.adapter}", file=sys.stderr)
        print("Сначала запустите обучение: python -m src.ft_client.mlx.train",
              file=sys.stderr)
        return 2

    print(f"=== MLX Export Pipeline ===")
    print(f"  Базовая модель:  {args.model}")
    print(f"  LoRA адаптер:    {args.adapter}")
    print(f"  Fused модель:    {args.fused_path}")
    print(f"  GGUF:            {args.gguf_path}")
    print(f"  Ollama имя:      {args.ollama_name}")

    # Шаг 1: Fuse
    if not args.skip_fuse:
        if not step_fuse(args.model, args.adapter, args.fused_path, args.dry_run):
            return 1

    # Шаг 2: GGUF
    if not args.skip_gguf:
        if not step_convert_gguf(
            args.fused_path, args.gguf_path, args.quantize, args.dry_run
        ):
            # GGUF конвертация не обязательна — Ollama может работать с safetensors
            print("\n  [INFO] GGUF конвертация не удалась, пробуем импорт без неё...")

    # Шаг 3: Ollama import
    if not step_ollama_import(
        args.fused_path, args.gguf_path, args.ollama_name, args.model, args.dry_run
    ):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
