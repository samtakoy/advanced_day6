"""
Собирает data/out/{train,eval}.jsonl из source-of-truth файлов:

    data/extraction/system.md          — system prompt (один на все примеры)
    data/extraction/gold.md            — 56 gold-JSON с маркерами [TRAIN]/[EVAL]
    data/extraction/tasks1_prose.md    — прозаические user-входы для задач 1-25
    data/extraction/tasks2.md          — user-входы для задач 26-50
    data/extraction/tasks_adversarial.md — user-входы для задач 51-56

Usage:
    python -m src.dataset.build_dataset
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data" / "extraction"
OUT = ROOT / "data" / "out"
EXPECTED_TASK_IDS = set(range(1, 57))


def load_system_prompt() -> str:
    """Текст system из system.md — всё после первого '---'."""
    raw = (DATA / "system.md").read_text(encoding="utf-8")
    parts = raw.split("\n---\n", 1)
    if len(parts) != 2:
        raise ValueError("system.md: ожидался '---' после вводного абзаца")
    return parts[1].strip()


def load_prose_sections(filename: str) -> dict[int, str]:
    """
    Разбивает prose-файл на секции по заголовкам вида '## N. Title' или '### N. Title'.
    Возвращает {task_id: тело_секции_без_заголовка_и_trailing_separators}.
    """
    path = DATA / filename
    if not path.exists():
        raise FileNotFoundError(f"prose-файл не найден: {filename}")

    content = path.read_text(encoding="utf-8")
    heading_re = re.compile(r"^#{2,3} (\d+)\. (.+?)$", re.MULTILINE)
    matches = list(heading_re.finditer(content))

    sections: dict[int, str] = {}
    for i, m in enumerate(matches):
        task_id = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end]
        body = re.sub(r"\n---\s*$", "", body).strip()
        sections[task_id] = body
    return sections


def load_gold_entries() -> list[dict]:
    """Парсит gold.md — извлекает task_id, split, prose-ссылку и gold-JSON."""
    content = (DATA / "gold.md").read_text(encoding="utf-8")

    header_re = re.compile(
        r"^## Task (\d+) — (.+?) \[(TRAIN|EVAL)\]\s*$", re.MULTILINE
    )
    user_re = re.compile(r"\*\*User:\*\*\s*`([^`]+)`\s*§(\d+)")
    json_re = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

    headers = list(header_re.finditer(content))
    entries = []
    for i, m in enumerate(headers):
        task_id = int(m.group(1))
        title = m.group(2).strip()
        split = m.group(3)
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        block = content[start:end]

        user_m = user_re.search(block)
        if not user_m:
            raise ValueError(f"Task {task_id}: не найдена ссылка **User:**")

        json_m = json_re.search(block)
        if not json_m:
            raise ValueError(f"Task {task_id}: не найден ```json блок")

        try:
            gold = json.loads(json_m.group(1))
        except json.JSONDecodeError as e:
            raise ValueError(f"Task {task_id}: невалидный gold-JSON ({e})") from e

        entries.append(
            {
                "task_id": task_id,
                "title": title,
                "split": split,
                "prose_file": user_m.group(1),
                "prose_section": int(user_m.group(2)),
                "gold": gold,
            }
        )
    return entries


def _resolve_prose_filename(ref: str) -> str:
    """Преобразует ссылку вида 'plans/tasks1_prose.md' в имя файла 'tasks1_prose.md'."""
    return Path(ref).name


def main() -> None:
    system_prompt = load_system_prompt()
    entries = load_gold_entries()

    gold_ids = {e["task_id"] for e in entries}
    missing = EXPECTED_TASK_IDS - gold_ids
    extra = gold_ids - EXPECTED_TASK_IDS
    if missing:
        raise ValueError(f"В gold.md не хватает задач: {sorted(missing)}")
    if extra:
        raise ValueError(f"В gold.md лишние задачи: {sorted(extra)}")

    # Загружаем prose-файлы (ссылки в gold.md вида 'plans/tasks1_prose.md §N')
    prose_refs = {e["prose_file"] for e in entries}
    prose_cache: dict[str, dict[int, str]] = {}
    for ref in prose_refs:
        filename = _resolve_prose_filename(ref)
        prose_cache[ref] = load_prose_sections(filename)

    train_lines: list[str] = []
    eval_lines: list[str] = []

    for e in sorted(entries, key=lambda x: x["task_id"]):
        prose = prose_cache[e["prose_file"]].get(e["prose_section"])
        if not prose:
            raise ValueError(
                f"Task {e['task_id']}: секция §{e['prose_section']} не найдена "
                f"в {e['prose_file']}"
            )

        record = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prose},
                {
                    "role": "assistant",
                    "content": json.dumps(e["gold"], ensure_ascii=False),
                },
            ]
        }
        line = json.dumps(record, ensure_ascii=False)
        target = train_lines if e["split"] == "TRAIN" else eval_lines
        target.append(line)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "train.jsonl").write_text(
        "\n".join(train_lines) + "\n", encoding="utf-8"
    )
    (OUT / "eval.jsonl").write_text(
        "\n".join(eval_lines) + "\n", encoding="utf-8"
    )

    print(f"[ok] train.jsonl: {len(train_lines)} examples")
    print(f"[ok] eval.jsonl:  {len(eval_lines)} examples")


if __name__ == "__main__":
    main()
