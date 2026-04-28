"""Output guard и pre-process retrieved-контента.

Slice 6: фокусируемся на двух вещах —
  1) Canary leak detection в финальном assistant-тексте (защита от
     successful prompt extraction).
  2) Strip явных носителей injection в retrieved-контенте (HTML-комменты,
     hidden span'ы) — второй эшелон против indirect injection.

Намеренно НЕ покрываем здесь: PII detection (email/phone/cards),
hallucination, sophisticated obfuscation (base64). Это можно добавить
отдельно как stretch.
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
      - Markdown-блоки в footer типа `[SYSTEM NOTE]` — это plain text,
        формально валидный markdown. Защита промпт-уровня в §5 правил.
    """
    if not text:
        return text
    text = _HTML_COMMENT_RE.sub("[STRIPPED: HTML comment]", text)
    text = _HIDDEN_SPAN_RE.sub("[STRIPPED: hidden span]", text)
    return text
