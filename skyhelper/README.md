# SkyHelper

Travel-booking чат-бот для security-демо (день 12 / парная работа дни 12–14).

Документация по архитектуре и threat-model — см. `plans/day12_bot_spec.md`,
`plans/security.md`.

## Запуск

```bash
# из корня репозитория
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt   # первый раз / при изменении requirements
export OPENAI_API_KEY=sk-...      # либо в .env файле
uvicorn skyhelper.src.app:app --reload --port 8000
```

Открыть в браузере: <http://localhost:8000/>

## Конфигурация (env vars)

| Переменная | Дефолт | Назначение |
|---|---|---|
| `OPENROUTER_API_KEY` или `OPENAI_API_KEY` | (нужен один из двух) | Если задан `OPENROUTER_API_KEY` — клиент идёт через `https://openrouter.ai/api/v1` и префиксует модель `openai/`. Иначе — напрямую в OpenAI. |
| `SKYHELPER_MODEL` | `gpt-4o-mini` | Модель для чата. Можно с явным провайдером (`openai/gpt-4o-mini`, `anthropic/claude-haiku-4-5-20251001`, ...). |
| `SKYHELPER_BEARER_TOKEN` | (нет) | Если задан — `/chat` требует `Authorization: Bearer <token>`. Если не задан — auth выключен (dev-режим, лог-предупреждение при старте). **Перед публичной экспозицией обязательно задать.** Сгенерировать: `python -c "import secrets; print(secrets.token_urlsafe(24))"`. |
| `SKYHELPER_RATE_LIMIT_PER_TOKEN` | `30` | Лимит запросов в окно на один Bearer-токен (защита от token-DoS). |
| `SKYHELPER_RATE_LIMIT_PER_USER` | `30` | Лимит запросов в окно на один X-User-Id (защита от tenancy-enumeration). |
| `SKYHELPER_RATE_LIMIT_WINDOW` | `60` | Размер окна в секундах для обоих лимитов. |

### Использование auth и rate-limit

**Через UI:** введите токен в поле «Bearer» вверху страницы (сохранится в localStorage). X-User-Id — отдельным полем.

**Через curl:**
```bash
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "X-User-Id: PARTNER_001" \
  -H "Content-Type: application/json" \
  -d '{"message":"найди билет в Бали"}'
```

При превышении лимита — `429 Rate limit exceeded ...`. При неверном токене — `401 Invalid Bearer token`.

## Прогресс по slice'ам

- [x] **Slice 1** — walking skeleton: FastAPI + LLM-чат + HTML-страница, без тулов
- [x] **Slice 2** — `search_flights` end-to-end: native tool-calling loop, каталог рейсов
- [x] **Slice 3** — booking flow: apply_voucher / propose_booking / book_flight + HITL-гейт через `policies.check_book_flight`
- [x] **Slice 4** — `fetch_url` + web_mock (3 clean + 3 poisoned) + URL allowlist через `index.json`
- [x] **Slice 4.5** — audit-видимость: tool-calls в ChatResponse + UI-рендер + per-session jsonl лог
- [x] **Slice 5** — multi-user threat model: `X-User-Id` header, seed CRM (10 юзеров, 15 броней), `list_my_bookings` с tenancy-фильтром
- [x] **Slice 6** — output guard + canary, fetch_url pre-process (strip HTML-комментов и hidden span), prompt-hardening (anti-extraction, фикс voucher/passenger guessing)
- [x] **Slice 7** — Bearer auth (опциональный) + rate limit per-token и per-userId
- [ ] Slice 8 — Cloudflared tunnel + partner_brief.md
