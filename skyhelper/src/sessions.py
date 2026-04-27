"""In-memory session storage. Slice 3: добавлены pending_booking и turn_count."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


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
    history: list[dict] = field(default_factory=list)
    pending_booking: BookingDraft | None = None
    turn_count: int = 0


_sessions: dict[str, Session] = {}


def get_or_create(session_id: str | None) -> Session:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    new_id = session_id or str(uuid.uuid4())
    session = Session(session_id=new_id)
    _sessions[new_id] = session
    return session
