"""Code-policies для критичных тулов. Slice 3: BookFlightPolicy для HITL-гейта.

Эти проверки выполняются в диспетчере **до** реального исполнения тула.
Если policy.check() возвращает не-None — диспетчер отвергает вызов и
возвращает текст ошибки модели (она увидит и адаптируется), реальное
действие не происходит.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from skyhelper.src.sessions import BookingDraft, Session

VOUCHER_MAX_ATTEMPTS = 3
VOUCHER_LOCKOUT_SECONDS = 60  # 1 минут

PENDING_TIMEOUT_TURNS = 5

# Confirmation tokens — что считается явным согласием пользователя.
# Намеренно НЕ включаем "забронируй", "book" — это запрос начать процесс,
# а не подтверждение конкретного draft'а.
_CONFIRMATION_RE = re.compile(
    r"\b(да|yes|ok|ок|давай|готово|бронируем|подтверждаю|подтверждено|"
    r"подтвердить|confirm|confirmed|согласен|согласна)\b",
    re.IGNORECASE,
)


def _has_confirmation(text: str) -> bool:
    if not text:
        return False
    return bool(_CONFIRMATION_RE.search(text))


def _last_user_message(session: Session) -> str:
    for msg in reversed(session.history):
        if msg.get("role") == "user":
            return msg.get("content") or ""
    return ""


def _recent_user_text(session: Session, last_n: int = 3) -> str:
    """Конкатенация последних N user-сообщений для intent-checks."""
    msgs = [
        msg.get("content", "") or ""
        for msg in session.history
        if msg.get("role") == "user"
    ]
    return " ".join(msgs[-last_n:])


def _normalize_passenger(name: str) -> str:
    """Для сравнения args c pending — игнорируем регистр и пробелы."""
    return " ".join((name or "").lower().split())


def check_pending_timeout(session: Session) -> None:
    """Сбросить просроченный pending_booking. Вызывается в начале каждого user-турна."""
    pb = session.pending_booking
    if pb is None:
        return
    if session.turn_count - pb.proposed_at_turn > PENDING_TIMEOUT_TURNS:
        session.pending_booking = None


def check_book_flight(
    flight_id: str,
    passengers: list[str],
    voucher_code: str | None,
    session: Session,
) -> str | None:
    """Вернёт текст ошибки или None, если все проверки пройдены."""
    pending = session.pending_booking
    if pending is None:
        return (
            "No pending booking. Call propose_booking first, show the draft to "
            "the user, and wait for their explicit confirmation in the next "
            "message before calling book_flight."
        )

    # Бронь должна быть предложена в ПРЕДЫДУЩЕМ турне, не в текущем —
    # это предотвращает chain "propose+book" в одном ходу.
    if session.turn_count <= pending.proposed_at_turn:
        return (
            "Cannot book in the same turn as propose_booking. The user must "
            "confirm in a separate message. Show the draft and wait."
        )

    if flight_id != pending.flight_id:
        return (
            f"flight_id mismatch with pending booking "
            f"(pending: {pending.flight_id}, called with: {flight_id}). "
            "If user wants different flight, call propose_booking again."
        )

    pending_set = sorted(_normalize_passenger(p) for p in pending.passengers)
    args_set = sorted(_normalize_passenger(p) for p in passengers)
    if pending_set != args_set:
        return (
            "passengers mismatch with pending booking. Re-propose with new "
            "passenger list and get fresh confirmation."
        )

    if voucher_code != pending.voucher_code:
        return (
            f"voucher_code mismatch with pending booking "
            f"(pending: {pending.voucher_code}, called with: {voucher_code}). "
            "Re-propose with the correct voucher."
        )

    last_user = _last_user_message(session)
    if not _has_confirmation(last_user):
        return (
            "User has not explicitly confirmed in their last message. "
            "Show the draft and wait for explicit yes/да/подтверждаю/ok/бронируй/etc."
        )

    return None


_LIST_BOOKINGS_RE = re.compile(
    r"мои.{0,10}брон|список.{0,10}брон|покажи.{0,10}брон|"
    r"my.{0,5}booking|list.{0,5}booking|show.{0,5}booking|"
    r"мои рейс|мои билет",
    re.IGNORECASE,
)


def check_list_my_bookings(session: Session) -> str | None:
    """Разрешить list_my_bookings только если пользователь явно запросил свои брони."""
    text = _recent_user_text(session)
    if not _LIST_BOOKINGS_RE.search(text):
        return (
            "User did not explicitly ask about their bookings. "
            "Only call list_my_bookings when the user explicitly requests to see their bookings."
        )
    return None


def check_apply_voucher(code: str, session: Session) -> str | None:
    """Разрешить apply_voucher только если пользователь явно назвал код.

    Если в сессии активен voucher cooldown — блокирует вызов и возвращает
    оставшееся время. Истёкший cooldown сбрасывается автоматически.
    """
    if session.voucher_locked_until is not None:
        now = datetime.now(timezone.utc)
        if now < session.voucher_locked_until:
            remaining = int((session.voucher_locked_until - now).total_seconds())
            mins, secs = divmod(remaining, 60)
            time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            return (
                f"voucher_cooldown: {VOUCHER_MAX_ATTEMPTS} failed attempts. "
                f"Locked for {VOUCHER_LOCKOUT_SECONDS // 60} min. "
                f"Remaining: {time_str}. "
                "Inform the user and do not retry until the cooldown expires."
            )
        # Cooldown истёк — сбрасываем и продолжаем
        session.voucher_locked_until = None
        session.failed_voucher_attempts = 0

    text = _recent_user_text(session)
    if not code or code.upper() not in text.upper():
        return (
            "The provided voucher code was not explicitly mentioned by the user. "
            "Only call apply_voucher when the user explicitly provides a code in their message."
        )
    return None


def check_fetch_url(url: str, session: Session) -> str | None:
    """Разрешить fetch_url только если пользователь явно прислал этот URL."""
    text = _recent_user_text(session)
    if not url or url not in text:
        return (
            "The provided URL was not explicitly sent by the user in recent messages. "
            "Only call fetch_url when the user explicitly provides a URL."
        )
    return None
