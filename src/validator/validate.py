#!/usr/bin/env python3
"""Validator for extraction fine-tune dataset (JSONL).

Проверки:
    - каждая строка — валидный JSON
    - messages: 3 элемента с ролями [system, user, assistant]
    - все content непустые
    - assistant.content парсится как JSON и соответствует схеме extraction
    - gold не содержит полей сверх 7 разрешённых (strict schema)
    - type, block — из enum
    - modules[i] — либо из alias-таблицы, либо начинается с "NEW:"
    - dependsOn[i] — целое число в 1..99
    - acceptanceCriteria, outOfScope — массивы строк (допускаются пустые)
    - нет дублей внутри modules / dependsOn / acceptanceCriteria / outOfScope
    - длина всего примера в оценочных токенах — в [50, 4096]
    - нет точных дубликатов по user.content внутри файла и между train <-> eval (leakage)
    - system prompt идентичен во всех строках обоих файлов и совпадает с data/extraction/system.md
    - JSONL-гигиена: нет BOM, нет пустых строк в середине, файл заканчивается \\n

Usage:
    python -m src.validator.validate
    python -m src.validator.validate data/out/train.jsonl
    python -m src.validator.validate data/out/eval.jsonl

Exit code: 0 если всё зелёное, 1 если есть ошибки.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# --- Taxonomy ---

MODULE_ALIASES = {
    "m-main", "m-data", "m-settings", "m-analysis", "m-alerts",
    "m-portfolio", "m-pickers",
    "fa-pickers", "fa-workspaces",
    "cf-stocks", "cf-workspaces", "cf-indicators", "cf-experiments",
    "cf-alerts", "cf-portfolio",
    "db", "net", "uikit", "utils", "theme", "resources", "mainentry",
}
TYPES = {"feat", "refactor", "research"}
BLOCKS = {
    "workspace_foundation", "indicators", "analysis",
    "polish_and_glue", "breadth", "tech_debt_refactor",
}
VALID_DEPS_MAX = 99
REQUIRED_FIELDS = (
    "title", "type", "block", "modules",
    "dependsOn", "acceptanceCriteria", "outOfScope",
)

MIN_TOKENS = 50
MAX_TOKENS = 4096


def estimate_tokens(text: str) -> int:
    return len(text) // 4


# --- Gold validation ---

def validate_gold(gold: dict, prefix: str) -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in gold:
            errors.append(f"{prefix}: gold.{field} отсутствует")
    if errors:
        return errors

    extra = set(gold.keys()) - set(REQUIRED_FIELDS)
    if extra:
        errors.append(
            f"{prefix}: gold содержит лишние поля сверх схемы: {sorted(extra)}"
        )

    if not isinstance(gold["title"], str) or not gold["title"].strip():
        errors.append(f"{prefix}: gold.title должен быть непустой строкой")

    if gold["type"] not in TYPES:
        errors.append(
            f"{prefix}: gold.type '{gold['type']}' не в {sorted(TYPES)}"
        )
    if gold["block"] not in BLOCKS:
        errors.append(
            f"{prefix}: gold.block '{gold['block']}' не в {sorted(BLOCKS)}"
        )

    if not isinstance(gold["modules"], list):
        errors.append(f"{prefix}: gold.modules должен быть list")
    else:
        for mod in gold["modules"]:
            if not isinstance(mod, str):
                errors.append(f"{prefix}: modules содержит не-строку {mod!r}")
                continue
            if mod in MODULE_ALIASES or mod.startswith("NEW:"):
                continue
            errors.append(
                f"{prefix}: modules[{mod!r}] — не алиас и не NEW:"
            )
        if len(gold["modules"]) != len(set(gold["modules"])):
            errors.append(f"{prefix}: modules содержит дубли")

    if not isinstance(gold["dependsOn"], list):
        errors.append(f"{prefix}: gold.dependsOn должен быть list")
    else:
        for d in gold["dependsOn"]:
            if not isinstance(d, int) or isinstance(d, bool):
                errors.append(
                    f"{prefix}: dependsOn содержит не-int {d!r}"
                )
            elif d < 1 or d > VALID_DEPS_MAX:
                errors.append(
                    f"{prefix}: dependsOn[{d}] вне 1..{VALID_DEPS_MAX}"
                )
        if len(gold["dependsOn"]) != len(set(gold["dependsOn"])):
            errors.append(f"{prefix}: dependsOn содержит дубли")

    for field in ("acceptanceCriteria", "outOfScope"):
        value = gold[field]
        if not isinstance(value, list):
            errors.append(f"{prefix}: gold.{field} должен быть list")
            continue
        for item in value:
            if not isinstance(item, str):
                errors.append(
                    f"{prefix}: {field} содержит не-строку {item!r}"
                )
            elif not item.strip():
                errors.append(
                    f"{prefix}: {field} содержит пустую строку"
                )
        str_items = [x for x in value if isinstance(x, str)]
        if len(str_items) != len(set(str_items)):
            errors.append(f"{prefix}: {field} содержит дубли")

    return errors


# --- Line-level validation ---

def validate_line(line: str, line_no: int) -> tuple[list[str], str | None, str | None]:
    """Возвращает (errors, system_content, user_content) для cross-line проверок."""
    prefix = f"line {line_no}"
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        return [f"{prefix}: невалидный JSON ({e})"], None, None

    msgs = obj.get("messages")
    if not isinstance(msgs, list) or len(msgs) != 3:
        return [f"{prefix}: messages должен быть list длины 3"], None, None

    errors: list[str] = []
    expected_roles = ("system", "user", "assistant")
    for i, (msg, role) in enumerate(zip(msgs, expected_roles)):
        if not isinstance(msg, dict):
            errors.append(f"{prefix}: messages[{i}] должен быть объектом")
            continue
        if msg.get("role") != role:
            errors.append(
                f"{prefix}: messages[{i}].role должно быть '{role}', "
                f"получено {msg.get('role')!r}"
            )
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"{prefix}: messages[{i}].content пустой или не строка")

    if errors:
        return errors, None, None

    try:
        gold = json.loads(msgs[2]["content"])
    except json.JSONDecodeError as e:
        return [f"{prefix}: assistant.content не парсится как JSON ({e})"], None, None

    errors.extend(validate_gold(gold, prefix))

    total_text = msgs[0]["content"] + msgs[1]["content"] + msgs[2]["content"]
    est = estimate_tokens(total_text)
    if est < MIN_TOKENS:
        errors.append(
            f"{prefix}: оценочная длина {est} токенов < {MIN_TOKENS} — слишком короткий пример"
        )
    if est > MAX_TOKENS:
        errors.append(
            f"{prefix}: оценочная длина {est} токенов > {MAX_TOKENS} — превышен hard cap"
        )

    return errors, msgs[0]["content"], msgs[1]["content"]


# --- File hygiene ---

def check_file_hygiene(path: Path) -> list[str]:
    errors: list[str] = []
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append(f"{path.name}: файл начинается с UTF-8 BOM")
    if not raw.endswith(b"\n"):
        errors.append(f"{path.name}: файл не заканчивается переводом строки")

    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"{path.name}:{i}: пустая строка в середине файла")
    return errors


# --- Full file validation ---

def validate_file(
    path: Path,
) -> tuple[int, list[str], dict[str, int], dict[str, int]]:
    """Возвращает (count, errors, user→line_no map, system→line_no map)."""
    all_errors: list[str] = []
    seen_user: dict[str, int] = {}
    seen_system: dict[str, int] = {}
    line_count = 0

    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        line_count += 1
        errors, system_content, user_content = validate_line(line, i)
        all_errors.extend(errors)

        if user_content is not None:
            if user_content in seen_user:
                all_errors.append(
                    f"дубль user.content: строки {seen_user[user_content]} и {i}"
                )
            else:
                seen_user[user_content] = i

        if system_content is not None and system_content not in seen_system:
            seen_system[system_content] = i

    return line_count, all_errors, seen_user, seen_system


def load_system_md() -> str | None:
    """Парсит data/extraction/system.md — текст после первого '---'."""
    path = ROOT / "data" / "extraction" / "system.md"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("\n---\n", 1)
    if len(parts) != 2:
        return None
    return parts[1].strip()


# --- CLI ---

def main() -> int:
    ap = argparse.ArgumentParser(description="Validate extraction fine-tune dataset")
    ap.add_argument("files", nargs="*", type=Path,
                    help="JSONL files to validate (default: data/out/train.jsonl + eval.jsonl)")
    args = ap.parse_args()

    files = args.files
    if not files:
        files = [
            ROOT / "data" / "out" / "train.jsonl",
            ROOT / "data" / "out" / "eval.jsonl",
        ]

    ok = True
    stats: dict[str, tuple[dict[str, int], dict[str, int]]] = {}

    for path in files:
        if not path.exists():
            print(f"[fail] {path.name}: file not found -- run build_dataset.py first")
            ok = False
            continue

        hygiene_errors = check_file_hygiene(path)
        count, errors, seen_user, seen_system = validate_file(path)
        errors = hygiene_errors + errors

        if errors:
            print(f"[fail] {path.name}: {count} lines, {len(errors)} errors:")
            for err in errors:
                print(f"  - {err}")
            ok = False
        else:
            print(f"[ok] {path.name}: {count} lines valid")

        stats[path.name] = (seen_user, seen_system)

    # cross-file checks (only if both train and eval loaded)
    if "train.jsonl" in stats and "eval.jsonl" in stats:
        (train_user, train_sys) = stats["train.jsonl"]
        (eval_user, eval_sys) = stats["eval.jsonl"]

        overlap = set(train_user) & set(eval_user)
        if overlap:
            print(f"[fail] leakage: {len(overlap)} user.content совпадают между train и eval:")
            for u in list(overlap)[:5]:
                print(
                    f"  - train.jsonl:{train_user[u]} <-> eval.jsonl:{eval_user[u]}"
                )
            ok = False
        else:
            print("[ok] no train<->eval user.content leakage")

        all_systems = set(train_sys) | set(eval_sys)
        if len(all_systems) > 1:
            print(f"[fail] system prompt различается: {len(all_systems)} разных вариантов")
            ok = False
        elif all_systems:
            system_md = load_system_md()
            if system_md is None:
                print("[warn] data/extraction/system.md не найден — пропускаю сверку")
            elif system_md != next(iter(all_systems)):
                print("[fail] system prompt в JSONL не совпадает с system.md — забыли запустить build_dataset.py?")
                ok = False
            else:
                print("[ok] system prompt идентичен во всех строках и совпадает с system.md")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
