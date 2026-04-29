"""Output Guard — проверка ответа модели перед отдачей клиенту.

Четыре типа проверок:
  1. scan_secrets       — те же regex что в input_guard (модель может галлюцинировать ключи)
  2. scan_prompt_leak   — эвристики утечки system prompt
  3. scan_suspicious_urls  — javascript:, data:, file://, IP-based URL
  4. scan_suspicious_commands — curl|bash, rm -rf, eval(), DROP TABLE, и т.д.

check() — агрегирует все проверки.
mask_secrets() — заменяет секреты на маски (аналог input_guard.mask).
"""
from __future__ import annotations

import re

from gateway.src.input_guard import PATTERNS, mask

# ---------------------------------------------------------------------------
# Prompt leak patterns
# ---------------------------------------------------------------------------

_LEAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)^you are a\b"),
    re.compile(r"(?i)\bsystem\s+prompt\b"),
    re.compile(r"(?i)^instructions?:\s", re.MULTILINE),
    re.compile(r"<\|?system\|?>"),
    re.compile(r"\[SYSTEM\]"),
    re.compile(r"(?i)^as an? (ai|assistant|language model)\b", re.MULTILINE),
]

# ---------------------------------------------------------------------------
# Suspicious URL patterns
# ---------------------------------------------------------------------------

_SUSPICIOUS_URL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("javascript_url",    re.compile(r"javascript\s*:", re.IGNORECASE)),
    # data: только как MIME data URL (data:image/, data:text/, data:application/)
    # чтобы не срабатывать на "data: [...]" или "the data: field"
    ("data_url",          re.compile(r"\bdata:[a-zA-Z]+/", re.IGNORECASE)),
    ("file_url",          re.compile(r"file://", re.IGNORECASE)),
    ("ip_url",            re.compile(r"https?://\d{1,3}(?:\.\d{1,3}){3}")),
]

# ---------------------------------------------------------------------------
# Suspicious command patterns
# ---------------------------------------------------------------------------

_SUSPICIOUS_CMD_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("curl_pipe_bash",     re.compile(r"curl\b.+\|\s*(?:bash|sh)\b", re.IGNORECASE)),
    ("wget_pipe_sh",       re.compile(r"wget\b.+\|\s*(?:bash|sh)\b", re.IGNORECASE)),
    ("rm_rf_root",         re.compile(r"rm\s+-rf\s+/", re.IGNORECASE)),
    ("chmod_777",          re.compile(r"chmod\s+777", re.IGNORECASE)),
    # shell eval только с подстановкой команды $(...) — безопасно не матчить
    # "eval() в Python" или "как работает eval"
    ("shell_eval",         re.compile(r"\beval\s*\$\(", re.IGNORECASE)),
    # exec только как вызов os-модуля — exec(user_input) из кода слишком
    # часто встречается в образовательном тексте
    ("os_exec",            re.compile(r"\bos\.(?:system|popen|exec[lve]*)\s*\(", re.IGNORECASE)),
    ("sql_drop",           re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)),
    ("sql_delete",         re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)),
    ("sql_comment_inject", re.compile(r";\s*--")),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_secrets(text: str) -> list[dict]:
    """Найти секреты в тексте ответа модели (те же паттерны что input_guard)."""
    if not text:
        return []
    from gateway.src.input_guard import scan  # noqa: PLC0415
    return scan(text)


def scan_prompt_leak(text: str) -> list[str]:
    """Вернуть список описаний сработавших leak-паттернов."""
    if not text:
        return []
    alerts: list[str] = []
    for pattern in _LEAK_PATTERNS:
        if pattern.search(text):
            alerts.append(f"prompt_leak:{pattern.pattern[:40]}")
    return alerts


def scan_suspicious_urls(text: str) -> list[str]:
    """Вернуть список найденных типов подозрительных URL."""
    if not text:
        return []
    found: list[str] = []
    for name, pattern in _SUSPICIOUS_URL_PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found


def scan_suspicious_commands(text: str) -> list[str]:
    """Вернуть список найденных типов подозрительных команд."""
    if not text:
        return []
    found: list[str] = []
    for name, pattern in _SUSPICIOUS_CMD_PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found


def check(text: str) -> dict:
    """Агрегировать все output-проверки.

    Returns:
        {
            "secrets": [...],
            "prompt_leak": [...],
            "suspicious_urls": [...],
            "suspicious_commands": [...],
            "has_alerts": bool,
        }
    """
    secrets = scan_secrets(text)
    prompt_leak = scan_prompt_leak(text)
    suspicious_urls = scan_suspicious_urls(text)
    suspicious_commands = scan_suspicious_commands(text)
    return {
        "secrets": secrets,
        "prompt_leak": prompt_leak,
        "suspicious_urls": suspicious_urls,
        "suspicious_commands": suspicious_commands,
        "has_alerts": bool(secrets or prompt_leak or suspicious_urls or suspicious_commands),
    }


def mask_secrets(text: str) -> tuple[str, list[dict]]:
    """Замаскировать секреты в тексте ответа (реиспользуем input_guard.mask)."""
    return mask(text)
