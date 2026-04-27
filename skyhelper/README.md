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

## Прогресс по slice'ам

- [x] **Slice 1** — walking skeleton: FastAPI + LLM-чат + HTML-страница, без тулов
- [x] **Slice 2** — `search_flights` end-to-end: native tool-calling loop, каталог рейсов
- [ ] Slice 3 — booking flow (apply_voucher, propose_booking, book_flight + HITL)
- [ ] Slice 4 — `fetch_url` + indirect injection setup
- [ ] Slice 5 — `list_my_bookings` + multi-user (X-User-Id, seed)
- [ ] Slice 6 — output guard + canary
- [ ] Slice 7 — Bearer auth + rate limit
- [ ] Slice 8 — Cloudflared tunnel + partner_brief.md
