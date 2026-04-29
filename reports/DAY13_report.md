# День 13: LLM Gateway — отчёт

## Задание

Построить HTTP-прокси между пользователем и LLM с четырьмя слоями защиты:
input guard (детекция и маскирование секретов), output guard (проверка ответа модели),
rate limiting (ограничение запросов по IP) и cost tracking (подсчёт токенов и стоимости).
Минимум 10 тест-кейсов с зафиксированными результатами.

---

## Реализация

### Структура модуля

```
gateway/
├── src/
│   ├── app.py           # FastAPI-приложение, основной request flow
│   ├── proxy.py         # Проксирование в OpenAI / OpenRouter
│   ├── input_guard.py   # Детекция и маскирование секретов во входе
│   ├── output_guard.py  # Проверка ответа модели
│   ├── rate_limiter.py  # Sliding window per-IP лимитер
│   ├── cost_tracker.py  # Подсчёт стоимости, /stats
│   └── audit.py         # JSONL-логирование каждого запроса
├── tests/
│   └── test_guards.py   # 19 тест-кейсов
└── logs/
    └── audit.jsonl      # Аудит-лог
```

### Endpoint

`POST /v1/chat/completions` — OpenAI-compatible формат.
Клиент может подключиться к gateway вместо OpenAI/OpenRouter, сменив только `base_url`.

---

## Выполнение требований задания

### ✅ HTTP-прокси + аудит-лог

FastAPI-приложение (`gateway/src/app.py`) принимает запросы в формате OpenAI,
прогоняет через guard-цепочку и проксирует в OpenAI/OpenRouter через Python SDK.

Все запросы логируются в `gateway/logs/audit.jsonl` с полями:
- таймстемп, IP клиента, модель
- результат input guard: какие секреты найдены, режим, действие
- результат output guard: алерты, количество замаскированных секретов
- usage: токены, стоимость, источник (provider / calculated)
- preview первых 100 символов запроса и ответа

### ✅ Input Guard — детекция секретов

Обнаруживаемые паттерны (`gateway/src/input_guard.py`, словарь `PATTERNS`):

| Тип | Паттерн | Маска |
|---|---|---|
| OpenAI key | `sk-(?:proj-)?[a-zA-Z0-9_-]{20,}` | `[REDACTED_API_KEY]` |
| GitHub PAT | `ghp_[a-zA-Z0-9]{36,}` | `[REDACTED_GITHUB_TOKEN]` |
| AWS Access Key | `AKIA[0-9A-Z]{16}` | `[REDACTED_AWS_KEY]` |
| Email | стандартный RFC-паттерн | `[REDACTED_EMAIL]` |
| Банковская карта | 16 цифр + проверка Luhn | `[REDACTED_CARD]` |
| Телефон РФ | `+7` / `8` + 10 цифр | `[REDACTED_PHONE]` |
| Телефон международный | `+код` + цифры | `[REDACTED_PHONE]` |
| Generic secret | `key=value`, `token=value`, ... | `[REDACTED_GENERIC_SECRET]` |

Дополнительно: `scan_base64()` — декодирует base64-блоки и прогоняет через те же паттерны.

### ✅ Input Guard — блокировка и маскирование

Режим задаётся хедером `X-Gateway-Mode`:

- **`mask`** (дефолт) — секреты в сообщениях `user`/`system` заменяются на маски,
  запрос уходит в LLM. В ответе хедер `X-Gateway-Input-Secrets: N`.
- **`block`** — если найден секрет в `user`/`system` → `400` с описанием типов секретов,
  в LLM ничего не отправляется.

**Важное уточнение по ролям:** сообщения `role: "tool"` (результаты вызова инструментов)
содержат retrieved контент — их LLM должен видеть целиком. Маскирование сломает поведение
инструмента. Для tool-сообщений применяется политика `scan + log only`: секреты фиксируются
в аудит-логе, но текст не изменяется. Блокировка в `block`-режиме также не срабатывает
на tool-секреты.

### ✅ Output Guard

Четыре типа проверок ответа модели (`gateway/src/output_guard.py`):

1. **Секреты** — те же regex что в input guard. Модель иногда галлюцинирует ключи.
   При обнаружении — маскируем в ответе, добавляем `output_secrets_masked` в алерты.

2. **System prompt leak** — эвристики: `You are a`, `[SYSTEM]`, `<|system|>`,
   `Instructions:`, `As an AI`. При срабатывании — алерт в хедере, ответ не блокируется.

3. **Подозрительные URL** — `javascript:`, `data:`, `file://`, URL на IP-адрес.

4. **Подозрительные команды** — `curl|bash`, `rm -rf /`, `chmod 777`, `eval(`,
   `exec(`, `DROP TABLE`, `DELETE FROM`, SQL-инъекции.

Алерты собираются в хедере `X-Gateway-Output-Alerts: alert1,alert2,...`.

### ✅ Rate Limiting

Sliding window per-IP (`gateway/src/rate_limiter.py`, класс `SlidingWindowLimiter`).
При превышении — `429` с хедером `Retry-After`.

Конфигурация через env:
- `GATEWAY_RATE_LIMIT` (дефолт: 20 запросов)
- `GATEWAY_RATE_WINDOW` (дефолт: 60 секунд)

В отличие от fixed window (как в skyhelper) — sliding window не позволяет удвоить
нагрузку на границе окна.

### ✅ Cost Tracking

`gateway/src/cost_tracker.py`, функция `extract_cost()`.

Двухуровневая стратегия:
1. **OpenRouter** возвращает `usage.cost` напрямую — берём его (`response.usage.model_dump().get("cost")`).
   Точное значение, рассчитанное провайдером.
2. **OpenAI direct** (или если поле отсутствует) — считаем по таблице `tokens × rate`.

В аудит-логе фиксируется `cost_source: "provider" | "calculated"`.
Кумулятивная статистика доступна на `GET /stats`.
В каждом ответе — хедер `X-Gateway-Cost-USD`.

---

## Тест-кейсы

Все тесты в `gateway/tests/test_guards.py`. Запуск: `python -m pytest gateway/tests/test_guards.py -v`.

### Результаты: 19/19 passed ✅

```
gateway/tests/test_guards.py::test_aws_key_detected              PASSED
gateway/tests/test_guards.py::test_card_number_detected          PASSED
gateway/tests/test_guards.py::test_card_luhn_invalid_not_detected PASSED
gateway/tests/test_guards.py::test_base64_secret_detected        PASSED
gateway/tests/test_guards.py::test_split_secret_detected         PASSED
gateway/tests/test_guards.py::test_clean_prompt_not_blocked      PASSED
gateway/tests/test_guards.py::test_email_detected                PASSED
gateway/tests/test_guards.py::test_phone_ru_detected             PASSED
gateway/tests/test_guards.py::test_github_pat_detected           PASSED
gateway/tests/test_guards.py::test_openai_new_format_key_detected PASSED
gateway/tests/test_guards.py::test_mask_replaces_secret          PASSED
gateway/tests/test_guards.py::test_no_duplicate_findings         PASSED
gateway/tests/test_guards.py::test_output_secret_detected        PASSED
gateway/tests/test_guards.py::test_output_system_prompt_leak     PASSED
gateway/tests/test_guards.py::test_output_suspicious_url         PASSED
gateway/tests/test_guards.py::test_output_suspicious_command     PASSED
gateway/tests/test_guards.py::test_output_clean_no_alerts        PASSED
gateway/tests/test_guards.py::test_output_ip_url_detected        PASSED
gateway/tests/test_guards.py::test_output_mask_secrets           PASSED
```

### Детали по обязательным кейсам из задания

| # | Кейс | Результат | Примечание |
|---|---|---|---|
| 1 | AWS-ключ `AKIAIOSFODNN7EXAMPLE` | ✅ Поймали | `type=AWS_KEY` |
| 2 | Номер карты `4111 1111 1111 1111` | ✅ Поймали | Luhn проходит → detection |
| 3 | Base64-encoded `sk-proj-abc123...` | ✅ Поймали | decode → rescan → found |
| 4 | Разбитый секрет `"sk-" + "proj-abc..."` | ✅ Поймали | Python конкатенирует до scan |
| 5 | Чистый промпт | ✅ Пропустили | Без ложных срабатываний |

### Что ловим / что пропускаем

**Ловим:**
- Явные секреты в тексте (OpenAI, GitHub, AWS, email, карты, телефоны)
- Base64-encoded секреты (одним уровнем кодирования)
- Секреты в ответе модели (галлюцинации ключей)
- Подозрительные URL и shell-команды в ответе

**Не ловим (known limitations):**
- Секрет разбитый по нескольким отдельным API-запросам (статически неопределимо)
- Двойное/тройное base64 кодирование
- Hex-encoded секреты (`73 6b 2d 70 72 6f 6a ...`)
- Секрет в изображении или бинарном контенте
- Контекстуальные секреты без явных паттернов ("мой пароль состоит из первых букв...")
- Streaming-режим (`stream=True`) — не реализован

---

## Tool calls

**Раздельная политика по ролям сообщений** — обнаруженное в процессе реализации:

Маскирование контента в `role: "tool"` (результатах вызова инструментов) ломает
поведение LLM: он получает `[REDACTED_EMAIL]` вместо адреса из документа и не может
корректно ответить. Реализована трёхуровневая политика:

| `role` | Действие | Логика |
|---|---|---|
| `user`, `system` | маскируем | защита от случайной утечки credentials |
| `tool` | scan + log | retrieved контент нужен LLM целиком |
| `assistant` | пропускаем | это уже ответы LLM |

---

## Запуск

```bash
source .venv/bin/activate
uvicorn gateway.src.app:app --port 8001

# Тесты
python -m pytest gateway/tests/test_guards.py -v

# Проверка block-режима
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "X-Gateway-Mode: block" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"мой ключ AKIAIOSFODNN7EXAMPLE"}]}'

# Статистика
curl http://localhost:8001/stats
```

## Запуск для демо в связке со SkyHelper: 

### Терминал 1 — Gateway
```bash
source .venv/bin/activate                                                                                                                                     
uvicorn gateway.src.app:app --port 8001
```

### Терминал 2 — SkyHelper
```bash
source .venv/bin/activate                                                                                                                                     
uvicorn skyhelper.src.app:app --port 8000 --reload
```

Открыть http://localhost:8000 — появится строка "Через Gateway :8001" с чекбоксом под настройками валидации. Состояние сохраняется в localStorage.

При включённой галочке каждый запрос оставляет запись в gateway/logs/audit.jsonl — видны tool calls skyhelper'а, guard-проверки, стоимость запроса от         
OpenRouter. При выключенной — запросы идут напрямую в OpenRouter как раньше, лога в gateway нет.   



### 📋 Тестовые данные

| Паттерн | ✅ Должен сработать (Positive) | ❌ Не должен сработать (Negative) |
|:---|:---|:---|
| `API_KEY` | `sk-proj-abc123DEF456ghi789JKL012`<br>`sk-ValidKey_12345678901234` | `sk-ShortKey`<br>`sk-proj-123`<br>`api_sk_12345678901234567890` |
| `GITHUB_TOKEN` | `ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij`<br>`ghp_123456789012345678901234567890123456` | `ghp_shorttoken123`<br>`ghp_!@#$%^&*()`<br>`token: ghp_abc` |
| `AWS_KEY` | `AKIAIOSFODNN7EXAMPLE`<br>`AKIA1234567890ABCDEF`<br>`AWSAKIA1234567890ABCDEF` ⚠️ тоже срабатывает (нет word boundary) | `AKIA123456789` (слишком короткий)<br>`akiaiosfodnn7example` (строчные не проходят) |
| `EMAIL` | `user.name+tag@example.co.uk`<br>`test_email-123@test-domain.org`<br>`user name@domain.com` ⚠️ матчит `name@domain.com` как подстроку | `user@.com`<br>`@domain.com` |
| `CARD` | `4111 1111 1111 1111`<br>`5500-0000-0000-0004`<br>`4111-1111-1111-1111-2222` ⚠️ матчит `4111-1111-1111-1111` внутри | `4111 111 111 111` (15 цифр)<br>`1234567890123456` (Luhn-невалидная)<br>`4111.1111.1111.1111` |
| `PHONE_RU`<br>*(рекомендуемое завершение)*<br>`(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}` | `+7 (999) 123-45-67`<br>`89161234567`<br>`+79001234567` | `+1 (999) 123-45-67`<br>`79991234567`<br>`+7 999 123 45` (не хватает цифр) |
| `GENERIC_SECRET`<br>*(рекомендуемое завершение)*<br>`(?i)(?:api_key\|secret\|token\|password)\s*[:=]\s*\S+` | `api_key: my_secret_value_123`<br>`password = "super_secret"`<br>`TOKEN=ghp_abc123...` | `my_secret = value`<br>`api_key myvalue`<br>`username: admin` |


### Для тестов BASE64

Реальные маски берутся из типа обнаруженного секрета — лейбла `[REDACTED_B64_SECRET]` не существует.
Код заменяет весь base64-блок на маску типа обнаруженного секрета внутри.

| № | Base64-блок (в тексте) | Раскодированный текст | Сработает паттерн | Ожидаемый результат (реальная маска) |
|:--|:---|:---|:---|:---|
| **1** | `YWRtaW5AZXhhbXBsZS5jb20=` | `admin@example.com` | `EMAIL` | ✅ `[REDACTED_EMAIL]` |
| **2** | `Z2hwX0FCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFlaYWJjZGVmZ2hpag==` | `ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij` | `GITHUB_TOKEN` | ✅ `[REDACTED_GITHUB_TOKEN]` |
| **3** | `QUtJQUlPU0ZPRE5ON0VYQU1QTEU=` | `AKIAIOSFODNN7EXAMPLE` | `AWS_KEY` | ✅ `[REDACTED_AWS_KEY]` |
| **4** | `NDExMTExMTExMTExMTExMQ==` | `4111111111111111` | `CARD` | ✅ `[REDACTED_CARD]` |
| **5** | `cGFzc3dvcmQ6IG15X3N1cGVyX3NlY3JldA==` | `password: my_super_secret` | `GENERIC_SECRET` | ✅ `[REDACTED_GENERIC_SECRET]` |
| **6** *(Дедупликация)* | `YXBpX2tleT0ic2stcHJvai1hYmMxMjNERUY0NTZnaGk3ODlKS0wwMTIi` | `api_key="sk-proj-abc123DEF456ghi789JKL012"` | `GENERIC_SECRET` (покрывает `api_key="..."` целиком, стоит раньше `API_KEY`) | ✅ **Один** `[REDACTED_GENERIC_SECRET]` |
| **7** *(False Negative)* | `U29tZSByYW5kb20gdGV4dCB3aXRoIG5vIHNlY3JldHMgaGVyZS4=` | `Some random text with no secrets here.` | Нет | ❌ Не трогать, оставить как есть |
| **8** *(Too Short)* | `dGVzdA==` | `test` | — | ❌ Игнорировать (длина < 20) |
| **9** *(Charset `+/`)* | `YXNkZi8rZ2hpamtsbW5vcHFyc3R1dnd4eXo=` | `asdf/+ghijklmnopqrstuvwxyz` | Нет | ❌ Не трогать (валидный Base64, но секретов нет) |

---

### 🔒 Проверка block-режима через curl

Block-режим возвращает `400` **до** обращения к LLM — API-ключ для этих тестов не нужен.
Предварительно: `uvicorn gateway.src.app:app --port 8001`.

---

**Пример 1 — одиночный секрет → заблокирован**

```bash
curl -s -X POST http://localhost:8001/v1/chat/completions \
  -H "X-Gateway-Mode: block" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"мой ключ AKIAIOSFODNN7EXAMPLE"}]}' \
  | python3 -m json.tool
```

Ожидаемый ответ (`HTTP 400`):
```json
{
    "error": {
        "message": "Request blocked: secrets detected in input",
        "type": "input_guard_violation",
        "secrets_found": ["AWS_KEY"],
        "count": 1
    }
}
```

---

**Пример 2 — несколько типов секретов → заблокированы все**

```bash
curl -s -X POST http://localhost:8001/v1/chat/completions \
  -H "X-Gateway-Mode: block" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"ключ AKIAIOSFODNN7EXAMPLE и карта 4111 1111 1111 1111"}]}' \
  | python3 -m json.tool
```

Ожидаемый ответ (`HTTP 400`):
```json
{
    "error": {
        "message": "Request blocked: secrets detected in input",
        "type": "input_guard_violation",
        "secrets_found": ["AWS_KEY", "CARD"],
        "count": 2
    }
}
```

---

**Пример 3 — секрет в `tool`-сообщении → НЕ блокируется**

Tool-сообщения содержат retrieved контент (результат вызова инструмента) — LLM должен видеть
их целиком, маскирование сломает поведение. Поэтому block не срабатывает на `role: "tool"`.

```bash
curl -s -X POST http://localhost:8001/v1/chat/completions \
  -H "X-Gateway-Mode: block" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user",      "content": "найди рейс"},
      {"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}]},
      {"role": "tool",      "content": "результат: contact support@airline.com", "tool_call_id": "call_1"}
    ]
  }' | python3 -m json.tool
```

Ожидаемый ответ: запрос **проходит** в LLM (`HTTP 200` или `502` если нет API-ключа).
Email в tool-сообщении зафиксируется в `audit.jsonl`, но не заблокирует запрос.
