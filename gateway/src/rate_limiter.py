"""Per-IP Sliding Window Rate Limiter.

Конфигурация через env:
  GATEWAY_RATE_LIMIT  — макс. запросов в окно (дефолт 20)
  GATEWAY_RATE_WINDOW — размер окна в секундах (дефолт 60)
"""
from __future__ import annotations

import os
import time
from collections import deque

RATE_LIMIT = int(os.getenv("GATEWAY_RATE_LIMIT", "20"))
RATE_WINDOW = int(os.getenv("GATEWAY_RATE_WINDOW", "60"))


class SlidingWindowLimiter:
    """In-memory sliding window rate limiter.

    Хранит deque таймстемпов для каждого ключа.
    При каждом check() удаляет устаревшие записи, затем проверяет лимит.
    """

    def __init__(self, limit: int, window_sec: int) -> None:
        self.limit = limit
        self.window = window_sec
        self._windows: dict[str, deque] = {}

    def check(self, key: str) -> bool:
        """Returns True если запрос разрешён, False — лимит превышен."""
        now = time.time()
        dq = self._windows.setdefault(key, deque())
        # Удалить таймстемпы старше окна
        while dq and dq[0] < now - self.window:
            dq.popleft()
        if len(dq) >= self.limit:
            return False
        dq.append(now)
        return True

    def remaining(self, key: str) -> int:
        """Сколько запросов осталось в текущем окне."""
        now = time.time()
        dq = self._windows.get(key, deque())
        active = sum(1 for ts in dq if ts >= now - self.window)
        return max(0, self.limit - active)


# Глобальный экземпляр
limiter = SlidingWindowLimiter(RATE_LIMIT, RATE_WINDOW)
