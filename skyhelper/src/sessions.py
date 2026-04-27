"""In-memory session storage. Slice 1: только история диалога."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class Session:
    session_id: str
    history: list[dict] = field(default_factory=list)


_sessions: dict[str, Session] = {}


def get_or_create(session_id: str | None) -> Session:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    new_id = session_id or str(uuid.uuid4())
    session = Session(session_id=new_id)
    _sessions[new_id] = session
    return session
