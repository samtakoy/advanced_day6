"""Per-session audit-лог: каждый турн в logs/sessions/<sid>.jsonl.

Используется для post-mortem анализа атак (что делал партнёр, какие тулы
вызывались, что отбилось).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs" / "sessions"


def log_turn(
    session_id: str,
    turn: int,
    user_message: str,
    tool_calls: list[dict],
    assistant_reply: str,
    user_id: str = "ANON",
    guard_alerts: list[str] | None = None,
    prompt_mode: str = "hardened",
) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"{session_id}.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "turn": turn,
        "user_id": user_id,
        "prompt_mode": prompt_mode,
        "user_message": user_message,
        "tool_calls": tool_calls,
        "assistant_reply": assistant_reply,
        "guard_alerts": guard_alerts or [],
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
