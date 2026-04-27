"""Bearer-token auth + rate limiting.

Slice 7: подготовка к публичной экспозиции через cloudflared (slice 8).
- Bearer token из env SKYHELPER_BEARER_TOKEN. Если не задан — auth выключен
  (dev-режим), сервер логирует предупреждение при старте.
- Rate limit per-token и per-userId с фиксированным окном (in-memory).
"""
from __future__ import annotations

import os
import time

BEARER_TOKEN = os.getenv("SKYHELPER_BEARER_TOKEN")
PER_TOKEN_LIMIT = int(os.getenv("SKYHELPER_RATE_LIMIT_PER_TOKEN", "30"))
PER_USER_LIMIT = int(os.getenv("SKYHELPER_RATE_LIMIT_PER_USER", "30"))
WINDOW_SEC = int(os.getenv("SKYHELPER_RATE_LIMIT_WINDOW", "60"))


class RateLimiter:
    """Простой in-memory fixed-window лимитер.

    Когда ключ обращается впервые в новом окне — счётчик сбрасывается.
    Если в текущем окне уже дошли до лимита — отказ. Многократно дешевле
    sliding-window и достаточен для демо.
    """

    def __init__(self, limit: int, window_sec: int) -> None:
        self.limit = limit
        self.window = window_sec
        self._buckets: dict[str, tuple[int, float]] = {}

    def check(self, key: str) -> bool:
        """Returns True если запрос разрешён, False — лимит превышен."""
        now = time.time()
        count, window_start = self._buckets.get(key, (0, now))
        if now - window_start >= self.window:
            self._buckets[key] = (1, now)
            return True
        if count >= self.limit:
            return False
        self._buckets[key] = (count + 1, window_start)
        return True


token_limiter = RateLimiter(PER_TOKEN_LIMIT, WINDOW_SEC)
user_limiter = RateLimiter(PER_USER_LIMIT, WINDOW_SEC)


def auth_enabled() -> bool:
    return BEARER_TOKEN is not None


def check_bearer(authorization_header: str | None) -> str | None:
    """Проверка Bearer-токена. Returns None если OK, иначе текст ошибки."""
    if not auth_enabled():
        return None  # dev-режим
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return "Missing Bearer token"
    token = authorization_header[len("Bearer "):].strip()
    if token != BEARER_TOKEN:
        return "Invalid Bearer token"
    return None


def extract_token(authorization_header: str | None) -> str:
    """Достать токен из header'а. Используется как rate-limit ключ."""
    if authorization_header and authorization_header.startswith("Bearer "):
        return authorization_header[len("Bearer "):].strip() or "dev"
    return "dev"
