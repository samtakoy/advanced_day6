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
    # Телефон РФ
    (
        "PHONE_RU",
        re.compile(r"(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"),
        "[REDACTED_PHONE]",
    ),
    # Международный телефон (7+ цифр с +)
    (
        "PHONE_INTL",
        re.compile(r"\+(?!7)\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}"),
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
    return findings


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
# mask_messages — удобная обёртка для списка messages
# ---------------------------------------------------------------------------

def mask_messages(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Применить mask() к полю content каждого сообщения.

    Returns:
        (masked_messages, all_findings)
    """
    all_findings: list[dict] = []
    result = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            masked_content, findings = mask(content)
            # Также проверяем base64
            b64_findings = scan_base64(content)
            if b64_findings:
                # Маскируем base64-блоки с найденными секретами
                for f in sorted(b64_findings, key=lambda x: x["start"], reverse=True):
                    mask_label = _get_mask_label(f["type"])
                    masked_content = (
                        masked_content[: f["start"]] + mask_label + masked_content[f["end"]:]
                    )
                all_findings.extend(b64_findings)
            all_findings.extend(findings)
            result.append({**msg, "content": masked_content})
        else:
            result.append(msg)
    return result, all_findings
