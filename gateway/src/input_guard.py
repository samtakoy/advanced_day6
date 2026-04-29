"""Input Guard — детекция и маскирование секретов во входящем промпте.

Два режима:
  block — при обнаружении секрета возвращает список findings, запрос блокируется.
  mask  — заменяет секреты на [REDACTED_*], промпт уходит в LLM.

Дополнительно: scan_base64 — декодирует base64-блоки и прогоняет через основные паттерны.
"""
from __future__ import annotations

import base64
import re

# ---------------------------------------------------------------------------
# Patterns: (name, compiled_regex, mask_label)
# ---------------------------------------------------------------------------

PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # OpenAI key (project format sk-proj-... и legacy sk-...)
    (
        "API_KEY",
        re.compile(r"sk-(?:proj-)?[a-zA-Z0-9_-]{20,}"),
        "[REDACTED_API_KEY]",
    ),
    # GitHub PAT
    (
        "GITHUB_TOKEN",
        re.compile(r"ghp_[a-zA-Z0-9]{36,}"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    # AWS Access Key ID
    (
        "AWS_KEY",
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "[REDACTED_AWS_KEY]",
    ),
    # Email
    (
        "EMAIL",
        re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"),
        "[REDACTED_EMAIL]",
    ),
    # Банковская карта (16 цифр с разделителями — Luhn проверяется отдельно)
    (
        "CARD",
        re.compile(r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b"),
        "[REDACTED_CARD]",
    ),
    # Телефон РФ.
    # (?<!\w) — не матчить 8 или +7 после любого word-символа (цифры, буквы, _).
    # (?!\d)  — не матчить если после номера ещё идут цифры (часть более длинного числа).
    (
        "PHONE_RU",
        re.compile(r"(?<!\w)(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"),
        "[REDACTED_PHONE]",
    ),
    # Международный телефон (7+ цифр с +).
    # (?<!\w) — не матчить + внутри слова (e.g. C++ или URL-параметры).
    # (?!\d)  — не матчить если продолжаются цифры (e.g. математическое выражение).
    (
        "PHONE_INTL",
        re.compile(r"(?<!\w)\+(?!7)\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}(?!\d)"),
        "[REDACTED_PHONE]",
    ),
    # Generic secret: key=value / token=value / password=value
    (
        "GENERIC_SECRET",
        re.compile(
            r"(?i)(?:api[_\-]?key|secret[_\-]?key|secret|token|password|passwd|pwd)"
            r"\s*[:=]\s*['\"]?([^\s'\"]{8,})"
        ),
        "[REDACTED_GENERIC_SECRET]",
    ),
]

# Base64 блок — минимум 20 символов base64-алфавита
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")


# ---------------------------------------------------------------------------
# Luhn check
# ---------------------------------------------------------------------------

def _luhn_check(digits: str) -> bool:
    """Стандартный алгоритм Луна для проверки номера карты."""
    digits = re.sub(r"[\s\-]", "", digits)
    if not digits.isdigit() or len(digits) != 16:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def scan(text: str) -> list[dict]:
    """Найти все секреты в тексте.

    Returns:
        Список {"type": str, "match": str, "start": int, "end": int}
    """
    if not text:
        return []
    findings: list[dict] = []
    for name, pattern, _mask in PATTERNS:
        for m in pattern.finditer(text):
            match_str = m.group(0)
            # Luhn-фильтр для карт
            if name == "CARD" and not _luhn_check(match_str):
                continue
            findings.append({
                "type": name,
                "match": match_str,
                "start": m.start(),
                "end": m.end(),
            })
    # Убираем перекрывающиеся matches: при перекрытии оставляем то,
    # у которого start меньше (покрывает больше текста слева); при равном
    # start — то, у которого end больше (длиннее match = специфичнее).
    # Это корректно для GENERIC_SECRET vs API_KEY: GENERIC захватывает
    # «api_key=sk-proj-...» целиком, а API_KEY — только «sk-proj-...».
    # Победитель — тот кто начинается раньше и/или длиннее.
    return _remove_overlapping(findings)


def _remove_overlapping(findings: list[dict]) -> list[dict]:
    """Из перекрывающихся findings оставить одно — с наименьшим start,
    при равном start — с наибольшим end (самое длинное/раннее).
    """
    if not findings:
        return findings
    # Сортируем: сначала по start (меньший = раньше), при равенстве — по end (больший = длиннее)
    sorted_f = sorted(findings, key=lambda f: (f["start"], -f["end"]))
    result = [sorted_f[0]]
    for current in sorted_f[1:]:
        last = result[-1]
        if current["start"] < last["end"]:
            # Перекрытие: current начинается до конца last.
            # Оставляем last (он раньше/длиннее по сортировке), пропускаем current.
            continue
        result.append(current)
    return result


# ---------------------------------------------------------------------------
# mask
# ---------------------------------------------------------------------------

def mask(text: str) -> tuple[str, list[dict]]:
    """Заменить все секреты на маски.

    Returns:
        (masked_text, findings)
    """
    if not text:
        return text, []
    findings = scan(text)
    if not findings:
        return text, []

    # Сортируем по позиции (от конца к началу, чтобы не сбивать офсеты)
    findings_sorted = sorted(findings, key=lambda f: f["start"], reverse=True)
    result = text
    for f in findings_sorted:
        # Найти маску для этого типа
        mask_label = _get_mask_label(f["type"])
        result = result[: f["start"]] + mask_label + result[f["end"]:]
    return result, findings


def _get_mask_label(secret_type: str) -> str:
    for name, _pattern, label in PATTERNS:
        if name == secret_type:
            return label
    return "[REDACTED]"


# ---------------------------------------------------------------------------
# scan_base64
# ---------------------------------------------------------------------------

def scan_base64(text: str) -> list[dict]:
    """Найти base64-блоки, декодировать и прогнать через scan().

    Returns:
        Список {"type": str, "match": str (base64 original), "decoded": str, "start": int, "end": int}
    """
    if not text:
        return []
    findings: list[dict] = []
    seen_positions: set[tuple[int, int]] = set()
    for m in _BASE64_RE.finditer(text):
        b64_str = m.group(0)
        padding = 4 - len(b64_str) % 4
        b64_str_padded = b64_str + "=" * padding if padding != 4 else b64_str
        try:
            decoded = base64.b64decode(b64_str_padded).decode("utf-8", errors="ignore")
        except Exception:
            continue
        inner = scan(decoded)
        if inner:
            pos = (m.start(), m.end())
            if pos in seen_positions:
                continue
            seen_positions.add(pos)
            # Сообщаем о первом найденном типе секрета
            findings.append({
                "type": inner[0]["type"],
                "match": m.group(0),
                "decoded": inner[0]["match"],
                "start": m.start(),
                "end": m.end(),
            })
    return findings


# ---------------------------------------------------------------------------
# mask_messages — обработка списка messages с учётом роли отправителя
# ---------------------------------------------------------------------------

# Роли, для которых применяется маскирование секретов.
# tool-сообщения — retrieved контент (результат вызова инструмента).
# LLM должен видеть его целиком, иначе теряется смысл вызова.
# Секреты в tool-результатах фиксируются в findings, но текст не изменяется.
_ROLES_TO_MASK = {"user", "system"}


def mask_messages(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Обработать список messages согласно политике по ролям.

    Политика:
      user / system — маскируем секреты: пользователь не должен случайно
                      отправлять свои credentials в LLM.
      tool          — только сканируем и логируем: контент нужен LLM для ответа,
                      маскирование сломает поведение инструмента.
      assistant     — пропускаем: это уже ответы LLM, не пользовательский ввод.

    Returns:
        (обработанные messages, все findings по всем ролям)
    """
    all_findings: list[dict] = []
    result = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if not isinstance(content, str):
            result.append(msg)
            continue

        if role in _ROLES_TO_MASK:
            # Собираем все findings из оригинального контента в одном месте,
            # чтобы позиции не съехали после первой замены.
            regular_findings = scan(content)
            b64_findings = scan_base64(content)
            combined = _remove_overlapping(
                sorted(regular_findings + b64_findings, key=lambda f: (f["start"], -f["end"]))
            )
            # Один проход по оригиналу в обратном порядке — позиции не сдвигаются.
            masked_content = content
            for f in sorted(combined, key=lambda f: f["start"], reverse=True):
                mask_label = _get_mask_label(f["type"])
                masked_content = masked_content[: f["start"]] + mask_label + masked_content[f["end"]:]
            all_findings.extend(combined)
            result.append({**msg, "content": masked_content})

        elif role == "tool":
            # Только сканируем: фиксируем факт наличия секрета в retrieved контенте,
            # но текст не трогаем — LLM должен видеть документ без изменений.
            findings = scan(content) + scan_base64(content)
            for f in findings:
                f["masked"] = False  # явно помечаем что маскирование не применялось
            all_findings.extend(findings)
            result.append(msg)

        else:
            # assistant и прочие роли — пропускаем без изменений
            result.append(msg)

    return result, all_findings
