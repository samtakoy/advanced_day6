"""In-memory session storage. Slice 5: добавлен user_id для multi-user threat model."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BookingDraft:
    """Сохранённый предложенный draft бронирования. Гейт для book_flight."""
    flight_id: str
    passengers: list[str]
    voucher_code: str | None
    final_price_rub: int
    proposed_at_turn: int


@dataclass
class Session:
    session_id: str
    user_id: str = "ANON"
    history: list[dict] = field(default_factory=list)
    pending_booking: BookingDraft | None = None
    turn_count: int = 0
    sanitize: bool = True
    validate_output: bool = True
    prompt_mode: str = "hardened"
    summary: str | None = None
    summarized_count: int = 0
    # voucher brute-force protection
    failed_voucher_attempts: int = 0
    voucher_locked_until: datetime | None = None
    # Reject-if-busy: пока ассистент обрабатывает предыдущее сообщение,
    # повторные /chat в ту же сессию отбиваем 409. Иначе случались гонки на
    # session.history (см. test_history.py — dangling tool_calls / orphan tool).
    # Атомарность check-and-set держится на single-thread asyncio: сетится в
    # app.chat() без await между check и set. Для multi-worker / shared
    # storage потребуется внешний лок (Redis SETNX, PG advisory lock).
    in_flight: bool = False


_sessions: dict[str, Session] = {}


def get_or_create(session_id: str | None, user_id: str = "ANON") -> Session:
    if session_id and session_id in _sessions:
        sess = _sessions[session_id]
        # user_id обновляется на каждый запрос — header это source of truth.
        sess.user_id = user_id
        return sess
    new_id = session_id or str(uuid.uuid4())
    session = Session(session_id=new_id, user_id=user_id)
    _sessions[new_id] = session
    return session
