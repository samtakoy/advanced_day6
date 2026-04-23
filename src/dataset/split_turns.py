#!/usr/bin/env python3
"""Разбивка multi-turn примеров на single-turn для корректного --mask-prompt.

⚠️  ЭКСПЕРИМЕНТ НЕ ДАЛА ОЖИДАЕМОГО УЛУЧШЕНИЯ.
Модели, обученные на split-данных (402 примера), не показали прироста качества
по сравнению с обучением на оригинальных multi-turn примерах (47 примеров).
Точная причина не установлена. Скрипт оставлен для истории, но в текущем
пайплайне НЕ ИСПОЛЬЗУЕТСЯ. По умолчанию обучение идёт на оригинальных данных
из data/seeds/ и data/synthetic/.

---

Проблема: при multi-turn диалоге (11-18 ходов assistant) флаг --mask-prompt
в mlx_lm.lora маскирует ВСЕ кроме последнего assistant-сообщения.
Модель не учится на plan_write, step_read и т.д. — только на финальный ход.

Решение (теоретическое): каждый пример разрезается на N single-turn примеров,
где N — количество assistant-сообщений. Turn K содержит:
  - system (тот же)
  - все сообщения до K-го assistant включительно
  - tool-ответ на K-й assistant (если есть)

Ожидание: модель учится на КАЖДОМ ходе, а --mask-prompt корректно
маскирует только промпт (всё до последнего assistant).
На практике улучшения не наблюдалось.

Структура вывода повторяет исходную:
  data/split/seeds/      — разбитые из data/seeds/
  data/split/synthetic/  — разбитые из data/synthetic/

Именование: <исходное_имя>__turn_NN.json
  golden_01_add_dep_with_replan__turn_01.json
  golden_01_add_dep_with_replan__turn_02.json
  ...

Использование:
    python -m src.dataset.split_turns                # разбить всё
    python -m src.dataset.split_turns --dry-run      # показать статистику
    python -m src.dataset.split_turns --clean        # удалить data/split/ и пересоздать

После запуска — пересобрать датасет:
    python -m src.dataset.mix_and_split \\
        --seeds-dir data/split/seeds \\
        --synthetic-dir data/split/synthetic
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def split_example(ex: dict) -> list[dict]:
    """Разбить один пример на single-turn примеры.

    Sliding window: каждый turn заканчивается на assistant-сообщении.
    Это target для обучения. Всё до него — контекст (маскируется --mask-prompt).

    Tool-ответы на ПРЕДЫДУЩИЕ assistant-ходы входят как контекст,
    но tool-ответ на ТЕКУЩИЙ assistant НЕ включается.

    Пример turn_03 из golden_01:
      system → user → asst(plan_write) → tool → asst(step_read) → tool → asst(list_dir)
      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^    ^^^^^^^^^^^^^^
                         prompt (маскируется --mask-prompt)               target (учим)
    """
    messages = ex["messages"]
    meta = ex.get("_meta", {})

    # Находим индексы всех assistant-сообщений
    assistant_indices = [i for i, m in enumerate(messages) if m["role"] == "assistant"]

    if not assistant_indices:
        return [ex]  # нечего разбивать

    turns: list[dict] = []

    for turn_num, asst_idx in enumerate(assistant_indices, start=1):
        # Срез: от начала ДО assistant включительно (без tool-ответа)
        turn_messages = messages[:asst_idx + 1]

        # Мета-данные: добавляем номер turn'а и источник
        turn_meta = dict(meta)
        turn_meta["turn"] = turn_num
        turn_meta["total_turns"] = len(assistant_indices)
        turn_meta["source_file"] = meta.get("source_file", "")

        turn_ex = {"_meta": turn_meta, "messages": turn_messages}
        turns.append(turn_ex)

    return turns


def process_directory(
    src_dir: Path,
    dst_dir: Path,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Обработать одну папку. Возвращает (файлов, примеров_вход, turns_выход)."""
    if not src_dir.is_dir():
        return 0, 0, 0

    files = sorted(src_dir.glob("*.json"))
    total_in = len(files)
    total_turns = 0

    if not dry_run:
        dst_dir.mkdir(parents=True, exist_ok=True)

    for path in files:
        with path.open(encoding="utf-8") as f:
            ex = json.load(f)

        # Запоминаем имя исходного файла в мете
        if "_meta" not in ex:
            ex["_meta"] = {}
        ex["_meta"]["source_file"] = path.name

        turns = split_example(ex)
        total_turns += len(turns)

        # Базовое имя без .json
        stem = path.stem

        for turn in turns:
            turn_num = turn["_meta"]["turn"]
            out_name = f"{stem}__turn_{turn_num:02d}.json"

            if dry_run:
                n_msgs = len(turn["messages"])
                n_asst = sum(1 for m in turn["messages"] if m["role"] == "assistant")
                print(f"  {out_name}  ({n_msgs} msgs, {n_asst} asst)")
            else:
                out_path = dst_dir / out_name
                with out_path.open("w", encoding="utf-8") as f:
                    json.dump(turn, f, ensure_ascii=False, indent=2)
                    f.write("\n")

    return total_in, total_in, total_turns


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Разбивка multi-turn примеров на single-turn для --mask-prompt"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Показать статистику без записи файлов")
    ap.add_argument("--clean", action="store_true",
                    help="Удалить data/split/ перед созданием")
    ap.add_argument("--split-dir", type=Path,
                    default=ROOT / "data" / "split",
                    help="Папка для результатов (по умолчанию data/split/)")
    args = ap.parse_args()

    split_dir = args.split_dir

    # Очистка если просят
    if args.clean and split_dir.exists() and not args.dry_run:
        shutil.rmtree(split_dir)
        print(f"Удалена {split_dir}")

    seeds_src = ROOT / "data" / "seeds"
    synth_src = ROOT / "data" / "synthetic"
    seeds_dst = split_dir / "seeds"
    synth_dst = split_dir / "synthetic"

    print("=== Разбивка multi-turn → single-turn ===\n")

    print(f"seeds ({seeds_src}):")
    f1, in1, out1 = process_directory(seeds_src, seeds_dst, args.dry_run)
    print(f"  {in1} примеров → {out1} turns\n")

    print(f"synthetic ({synth_src}):")
    f2, in2, out2 = process_directory(synth_src, synth_dst, args.dry_run)
    print(f"  {in2} примеров → {out2} turns\n")

    print(f"Итого: {in1 + in2} примеров → {out1 + out2} single-turn примеров")

    if args.dry_run:
        print("\nDRY RUN — файлы не созданы.")
        print(f"Для создания: python -m src.dataset.split_turns")
    else:
        print(f"\nФайлы записаны в {split_dir}/")
        print(f"\nСледующий шаг — пересборка датасета:")
        print(f"  python -m src.dataset.mix_and_split \\")
        print(f"      --seeds-dir {seeds_dst} \\")
        print(f"      --synthetic-dir {synth_dst}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
