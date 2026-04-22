#!/usr/bin/env python3
"""Замена system prompt во всех примерах (seeds + synthetic) на compact-версию.

Скрипт:
  1. Читает compact-промпт из data/prompts/system_agent_compact.md
  2. Проходит по всем .json в data/seeds/ и data/synthetic/
  3. В agent-примерах (содержат plan_write в system) заменяет system content,
     сохраняя оригинальный task_id
  4. Plain-примеры не трогает

После запуска нужно п��ресобрать датасет:
  python -m src.dataset.mix_and_split

Usage:
    python -m src.dataset.replace_system_prompt --dry-run   # показать что изменится
    python -m src.dataset.replace_system_prompt              # применить замену
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def extract_task_id(content: str) -> str | None:
    """Извлечь task_id из system prompt (строка вида TASK_ID: t-1234)."""
    m = re.search(r"TASK_ID:\s*(t-\w+)", content)
    return m.group(1) if m else None


def is_agent_prompt(content: str) -> bool:
    """Определить — это agent system prompt (содержит plan_write)."""
    return "plan_write" in content


def main() -> int:
    ap = argparse.ArgumentParser(description="Замена system prompt на compact-версию")
    ap.add_argument("--dry-run", action="store_true",
                    help="Показать что изменится, без записи")
    args = ap.parse_args()

    # Читаем compact-промпт
    compact_path = ROOT / "data" / "prompts" / "system_agent_compact.md"
    compact_template = compact_path.read_text(encoding="utf-8").strip()
    print(f"Compact prompt: {len(compact_template)} символов (~{len(compact_template)//4} токенов)")

    # Собираем все .json примеры
    dirs = [ROOT / "data" / "seeds", ROOT / "data" / "synthetic"]
    json_files = []
    for d in dirs:
        if d.is_dir():
            json_files.extend(sorted(d.glob("*.json")))

    print(f"Найдено {len(json_files)} файлов")

    replaced = 0
    skipped_plain = 0
    skipped_no_task_id = 0

    for path in json_files:
        with path.open(encoding="utf-8") as f:
            ex = json.load(f)

        msgs = ex.get("messages", [])
        if not msgs or msgs[0].get("role") != "system":
            continue

        old_content = msgs[0]["content"]

        # Пропускаем plain-примеры
        if not is_agent_prompt(old_content):
            skipped_plain += 1
            continue

        # Извлекаем task_id из старого промпта
        task_id = extract_task_id(old_content)
        if not task_id:
            skipped_no_task_id += 1
            print(f"  SKIP (no task_id): {path.name}")
            continue

        # Подставляем task_id в compact-промпт
        new_content = compact_template.replace("<<TASK_ID>>", task_id)

        saved = len(old_content) - len(new_content)

        if args.dry_run:
            print(f"  {path.name}: {len(old_content)} → {len(new_content)} символов (экономия {saved})")
        else:
            msgs[0]["content"] = new_content
            with path.open("w", encoding="utf-8") as f:
                json.dump(ex, f, ensure_ascii=False, indent=2)
                f.write("\n")

        replaced += 1

    print(f"\nИтого: {replaced} заменено, {skipped_plain} plain (не тронуты), "
          f"{skipped_no_task_id} без task_id (пропущены)")

    if args.dry_run:
        print("\nDRY RUN — файлы не изменены.")
        print("Для применения: python -m src.dataset.replace_system_prompt")
    else:
        print(f"\nГотово. Пересоберите датасет: python -m src.dataset.mix_and_split")

    return 0


if __name__ == "__main__":
    sys.exit(main())
