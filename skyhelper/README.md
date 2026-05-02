# SkyHelper

Travel-booking чат-бот для security-демо. Реализует многоуровневую защиту от prompt injection, indirect injection и brute-force атак.

> **Совместимость:** чат-бот проверялся с моделью `gpt-4o-mini` (через OpenAI и OpenRouter). Работа с другими моделями не гарантируется — качество tool-calling и следования инструкциям зависит от модели.

---

## Архитектура

```
Браузер / curl
      │
      ▼  :8000
┌─────────────────┐
│   SkyHelper     │  FastAPI — чат, tools, guards, session
│  (skyhelper/)   │
└────────┬────────┘
         │ опционально (use_gateway: true)
         ▼  :8001
┌─────────────────┐
│   LLM Gateway   │  FastAPI proxy — input/output guard, rate limit, audit
│   (gateway/)    │
└────────┬────────┘
         │
         ▼
    OpenAI / OpenRouter / Ollama
```

Gateway опционален. Без него SkyHelper ходит в LLM напрямую. С ним — запросы проходят через дополнительный слой input/output guard и полный audit-лог.
Нужна галочка в клиенте.
---

## Быстрый старт

### 1. Предварительные требования

- Python 3.11+
- Один из API-ключей: `OPENROUTER_API_KEY` или `OPENAI_API_KEY`

### 2. Установка

```bash
# из корня репозитория advanced_day6/
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env   # заполнить API-ключ
```

### 3. Запуск SkyHelper (минимум)

```bash
uvicorn skyhelper.src.app:app --reload --port 8000
```

Открыть: <http://localhost:8000/>

### 4. Запуск с Gateway (полный стек)

Два терминала:

```bash
# Терминал 1 — Gateway
uvicorn gateway.src.app:app --reload --port 8001

# Терминал 2 — SkyHelper
uvicorn skyhelper.src.app:app --reload --port 8000
```

В UI включить чекбокс **«Через Gateway :8001»** — или передать `"use_gateway": true` в теле запроса.

### 5. Smoke-test

```bash
# Базовый запрос (без auth)
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "найди рейс в Дубай на октябрь"}' | python -m json.tool

# Healthcheck
curl http://localhost:8000/healthz
curl http://localhost:8001/healthz
```

---

## Конфигурация SkyHelper

| Переменная | Дефолт | Назначение |
|---|---|---|
| `OPENROUTER_API_KEY` или `OPENAI_API_KEY` | (обязателен один) | Если задан `OPENROUTER_API_KEY` — клиент идёт через OpenRouter, модель префиксуется `openai/`. Иначе — напрямую в OpenAI. |
| `SKYHELPER_MODEL` | `gpt-4o-mini` | Модель для чата. Без префикса (`gpt-4o-mini`) — работает с обоими провайдерами. С префиксом `openai/gpt-4o-mini` или `anthropic/claude-haiku-4-5-20251001` — только через OpenRouter. |
| `SKYHELPER_BEARER_TOKEN` | (нет) | Если задан — `/chat` требует `Authorization: Bearer <token>`. Если не задан — auth выключен (dev-режим, предупреждение в лог). **Обязательно задать перед публичной экспозицией.** |
| `SKYHELPER_RATE_LIMIT_PER_TOKEN` | `30` | Лимит запросов в окно на один Bearer-токен. |
| `SKYHELPER_RATE_LIMIT_PER_USER` | `30` | Лимит запросов в окно на один `X-User-Id`. |
| `SKYHELPER_RATE_LIMIT_WINDOW` | `60` | Размер окна в секундах для обоих rate-limit'ов. |
| `SKYHELPER_GATEWAY_URL` | `http://localhost:8001` | URL Gateway-прокси. Используется когда `use_gateway: true`. |
| `SKYHELPER_LOCK_SETTINGS` | `true` | Если `true` — замораживает настройки безопасности: всегда `hardened`-промпт, санитизация и валидация ответа включены. Переписывается на сервере независимо от значений в запросе. UI показывает `🔒 заморожено`. |

## Конфигурация Gateway

| Переменная | Дефолт | Назначение |
|---|---|---|
| `OPENROUTER_API_KEY` или `OPENAI_API_KEY` | (обязателен один) | Ключ для upstream LLM. Gateway авторизуется сам — клиент ключ не передаёт. |
| `OLLAMA_BASE_URL` | (нет) | Если задан — Gateway ходит в Ollama (приоритет > OpenRouter > OpenAI). |
| `GATEWAY_RATE_LIMIT` | `20` | Макс. запросов в окно per IP. |
| `GATEWAY_RATE_WINDOW` | `60` | Размер окна в секундах. |
| `GATEWAY_LOG_FULL` | `false` | Если `true` — в `gateway/logs/audit.jsonl` пишутся полные тексты `messages_full` и `response_full`. Нужно для наблюдения за суммаризацией и реальным содержимым запросов к LLM. |

---

## Работа через Ollama (локальная LLM)

Ollama позволяет запускать LLM полностью локально — без API-ключей и без отправки данных наружу. SkyHelper сам не умеет ходить в Ollama напрямую — только через Gateway.

### 1. Установить Ollama

Скачать с [ollama.com](https://ollama.com) и установить. После установки Ollama запускается как фоновый сервис на `http://localhost:11434`.

### 2. Скачать модель

```bash
ollama pull <имя-модели>
ollama list   # проверить что модель доступна
```

### 3. Запуск: SkyHelper → Gateway → Ollama

Gateway выбирает Ollama автоматически если задан `OLLAMA_BASE_URL`.

**Терминал 1 — Gateway с Ollama:**

```bash
# Linux / macOS
export OLLAMA_BASE_URL=http://localhost:11434/v1
uvicorn gateway.src.app:app --reload --port 8001
```

```powershell
# Windows (PowerShell)
$env:OLLAMA_BASE_URL = "http://localhost:11434/v1"
uvicorn gateway.src.app:app --reload --port 8001
```

**Терминал 2 — SkyHelper:**

```bash
# Linux / macOS
export SKYHELPER_MODEL=<имя-модели-в-ollama>
# OPENROUTER_API_KEY НЕ задавать (см. примечание ниже)
uvicorn skyhelper.src.app:app --reload --port 8000
```

```powershell
# Windows (PowerShell)
$env:SKYHELPER_MODEL = "<имя-модели-в-ollama>"
uvicorn skyhelper.src.app:app --reload --port 8000
```

В UI включить чекбокс **«Через Gateway :8001»**.

### Важно: не задавать OPENROUTER_API_KEY вместе с Ollama

Если `OPENROUTER_API_KEY` задан — SkyHelper автоматически добавляет префикс `openai/` к имени модели. Ollama такой формат не понимает и вернёт ошибку. Если нужен OpenRouter для прямых запросов и Ollama для gateway — не задавайте `OPENROUTER_API_KEY`, модель указывайте без префикса.

---

## Auth и rate-limit

**Генерация токена:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

**Через UI:** поле «Bearer» вверху страницы (сохраняется в localStorage). `X-User-Id` — отдельным полем.

**Через curl:**

```bash
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "X-User-Id: PARTNER_001" \
  -H "Content-Type: application/json" \
  -d '{"message": "найди билет в Бали"}'
```

При превышении лимита — `429 Rate limit exceeded`. При неверном токене — `401 Invalid Bearer token`.

---

## Запуск для Red Team сессии

### 1. Сгенерировать токен и запустить

```bash
# Linux / macOS
export SKYHELPER_BEARER_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
export SKYHELPER_LOCK_SETTINGS=true   # заморозить защиты
uvicorn skyhelper.src.app:app --port 8000

# Windows (PowerShell)
$env:SKYHELPER_BEARER_TOKEN = $(python -c "import secrets; print(secrets.token_urlsafe(24))")
$env:SKYHELPER_LOCK_SETTINGS = "true"
uvicorn skyhelper.src.app:app --port 8000
```

### 2. Открыть публичный доступ

```bash
# cloudflared (бесплатно, без регистрации)
cloudflared tunnel --url http://localhost:8000

# или ngrok
ngrok http 8000
```

В выводе будет URL вида `https://<random>.trycloudflare.com`.

### 3. Передать партнёру

- Публичный URL
- Bearer token (через защищённый канал: Signal, encrypted DM)
- `X-User-Id`: например, `PARTNER_001`
- Файл `PARTNER_BRIEF.md` — описание атакуемой системы

### 4. Безопасность во время сессии

- Перезапускать сервер с новым токеном между сессиями — старый токен может утечь в чате или логах
- Сбросить seed-брони: удалить `skyhelper/logs/bookings.jsonl` (пересоздастся при старте из `seed_bookings.json`)
- Cloudflared free-tunnel URL временный — каждый запуск новый, это плюс для безопасности

---

## Слои защиты

| # | Слой | Где | Что делает |
|---|---|---|---|
| 0 | Tool descriptions | `tools.py` | В hardened-режиме UNTRUSTED-хинты в описаниях инструментов |
| 1 | System prompt | `prompts/system_hardened.md` | Инструкции по roleplay-устойчивости, canary-токен |
| 2 | Input sanitization | `guards.py` | Удаление скрытого HTML и zero-width символов из retrieved контента |
| 3 | Tool policies | `policies.py` | Проверки перед каждым tool-вызовом (HITL-гейт, rate-limit промокодов) |
| 4 | Output validation | `guards.py` + `llm.py` | Canary leak detection, LLM-based output validator |
| 5 | HTTP middleware | `app.py` | Bearer auth, rate-limit per-token и per-user |
| 6 | Gateway | `gateway/` | Input/output guard на уровне HTTP-прокси, audit-лог |

---

## Логи

- `skyhelper/logs/bookings.jsonl` — все созданные бронирования
- `gateway/logs/audit.jsonl` — полный audit-лог Gateway (при `GATEWAY_LOG_FULL=true` включает `messages_full` и `response_full`)
