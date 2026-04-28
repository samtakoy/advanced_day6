"""Output guard, pre-process retrieved-контента и output validators.

Три слоя защиты:
  1) strip_hidden_html / strip_zero_width — убирают носители инъекции ДО LLM.
  2) contains_canary — детектирует утечку системного промпта в ответе.
  3) validate_alert_summary / validate_fare_answer / validate_web_claims —
     rule-based проверка финального ответа ПОСЛЕ генерации.
     Работают независимо от послушности модели и от session.sanitize.
"""
from __future__ import annotations

import re
import secrets

CANARY_LEAK_REFUSAL = "Запрос отклонён по политике безопасности."


def generate_canary() -> str:
    """Сгенерировать уникальный canary-токен для текущего рантайма."""
    return f"__SH_CANARY_{secrets.token_hex(4)}__"


def contains_canary(text: str, canary: str) -> bool:
    """Точное вхождение canary в текст. Не учитываем кодирования (base64 etc.)."""
    if not text or not canary:
        return False
    return canary in text


# Zero-width и invisible Unicode символы (ZWS, ZWNJ, ZWJ, LRM, RLM, BOM)
_ZERO_WIDTH_RE = re.compile(r"[​‌‍‎‏﻿]")


def strip_zero_width(text: str) -> str:
    """Удалить zero-width символы, используемые для скрытой инъекции."""
    if not text:
        return text
    return _ZERO_WIDTH_RE.sub("", text)


# Pre-compiled patterns для strip_hidden_html
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HIDDEN_SPAN_RE = re.compile(
    r'<span\b[^>]*style\s*=\s*"[^"]*'
    r'(?:display\s*:\s*none|visibility\s*:\s*hidden|color\s*:\s*white)'
    r'[^"]*"[^>]*>.*?</span>',
    flags=re.IGNORECASE | re.DOTALL,
)


def strip_hidden_html(text: str) -> str:
    """Удалить очевидные носители injection из retrieved-контента.

    Что strip'ается:
      - HTML-комментарии `<!-- ... -->` (заменяются маркером)
      - Hidden span'ы со стилем display:none / visibility:hidden / color:white

    Что НЕ strip'ается (намеренно):
      - Markdown-блоки в footer типа `[SYSTEM NOTE]` — plain text,
        защита на уровне промпта + output validator.
    """
    if not text:
        return text
    text = _HTML_COMMENT_RE.sub("[STRIPPED: HTML comment]", text)
    text = _HIDDEN_SPAN_RE.sub("[STRIPPED: hidden span]", text)
    return text


# ---------------------------------------------------------------------------
# Output validators — Шаг 5
# Каждый принимает финальный ответ модели и visible (sanitized) контент,
# возвращает список нарушений (пустой = OK).
# ---------------------------------------------------------------------------

# V1: домены/URL в ответе, которых нет в visible-контенте уведомления
_DOMAIN_RE = re.compile(
    r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)"
    r"+(?:ru|com|net|org|info|io|site|online|рф)\b",
    re.IGNORECASE,
)


def validate_alert_summary(answer: str, visible_content: str) -> list[str]:
    """V1: домены в ответе должны встречаться в visible-контенте уведомления."""
    violations: list[str] = []
    visible_lower = visible_content.lower()
    for domain in _DOMAIN_RE.findall(answer):
        if domain.lower() not in visible_lower:
            violations.append(f"unconfirmed_domain:{domain}")
    return violations


# V2: структурированные факты о тарифе из видимого текста документа
_BAGGAGE_KG_RE = re.compile(r"(\d+)\s*кг", re.IGNORECASE)
# «бесплатный/бесплатно для всех/любого/каждого»
_FREE_ALL_RE = re.compile(
    r"бесплатн\w*\s+для\s+(?:всех|любого|все|каждого)",
    re.IGNORECASE,
)


def extract_fare_facts(visible_content: str) -> dict:
    """V2: извлечь canonical facts (багаж, возврат) из sanitized fare-документа."""
    facts: dict = {}
    kg_vals = [int(m) for m in _BAGGAGE_KG_RE.findall(visible_content)]
    if kg_vals:
        facts["baggage_kg_limits"] = kg_vals
    facts["refundable"] = "невозвратный" not in visible_content.lower()
    return facts


def validate_fare_answer(answer: str, facts: dict) -> list[str]:  # noqa: ARG001
    """V2: ответ не должен утверждать, что багаж бесплатен для всех тарифов."""
    violations: list[str] = []
    if _FREE_ALL_RE.search(answer):
        violations.append("false_claim:baggage_free_for_all_tariffs")
    return violations


# V3: утверждения о времени в ответе должны совпадать с visible-контентом страницы
_TIME_MINUTES_RE = re.compile(r"\b(\d+)\s*минут", re.IGNORECASE)


def validate_web_claims(answer: str, visible_content: str) -> list[str]:
    """V3: каждое «N минут» в ответе должно встречаться в sanitized-контенте страницы."""
    violations: list[str] = []
    visible_times = {int(m.group(1)) for m in _TIME_MINUTES_RE.finditer(visible_content)}
    if not visible_times:
        return violations
    for m in _TIME_MINUTES_RE.finditer(answer):
        t = int(m.group(1))
        if t not in visible_times:
            violations.append(f"unconfirmed_time_claim:{t}min")
    return violations
