# День 7. Оценка уверенности и контроль качества инференса

## Что это

Модуль `src/quality/` добавляет слой контроля качества поверх extraction-инференса из Дня 6. Вместо того чтобы слепо принимать ответ модели, pipeline проверяет его тремя независимыми подходами и выносит вердикт: **ACCEPTED**, **ACCEPTED_WITH_WARNINGS** или **REJECTED**.

Задача — ответить на вопрос: *"Можно ли доверять этому конкретному извлечению?"*

---

## Три подхода

### 1. Constraint-based (детерминистический)
**0 дополнительных API-вызовов.**

Переиспользует `validate_gold()` из валидатора датасета + добавляет доменные инварианты:
- JSON валиден, все 8 полей на месте, типы корректны
- `type` / `block` из enum, `modules` из таблицы алиасов
- `title` от 5 до 200 символов
- `acceptanceCriteria` не пуст для `type=feat`
- `modules` или `newModules` не пусты для `type=feat|refactor`

**Вердикт:** `FAIL` (ошибка схемы) → retry | `UNSURE` (инвариант нарушен) | `OK`

### 2. Redundancy (N-вызовов, сравнение)
**N-1 дополнительных API-вызовов** (по умолчанию N=3, т.е. +2 вызова).

Один и тот же запрос отправляется модели N раз при `temperature=0.7`. Ответы сравниваются поле-за-полем: скалярные поля — exact match, списковые — IoU ≥ 0.8.

Consensus = доля полей с единогласным ответом.
- consensus ≥ 0.85 и `type`/`block` совпадают → `OK`
- consensus ≥ 0.6 → `UNSURE`
- ниже → `FAIL`

Возвращает majority-vote extraction — наиболее частый ответ по каждому полю.

### 3. Scoring (self-assessment)
**1 дополнительный API-вызов.**

Второй вызов LLM с `temperature=0`: модель оценивает своё собственное извлечение. Получает оригинальный текст задачи и JSON-результат, возвращает per-field confidence (`OK`/`UNSURE`/`FAIL`) и краткое пояснение.

---

## Pipeline

```
Input → LLM call → Extraction JSON
  ↓
1. Constraint check (бесплатно)
   FAIL → retry (до max_retries) → все FAIL → REJECTED
  ↓
2. Redundancy check (2 доп. вызова)
   FAIL → REJECTED
  ↓
3. Scoring check (1 доп. вызов)
  ↓
Агрегация: ACCEPTED / ACCEPTED_WITH_WARNINGS / REJECTED
```

Constraint идёт первым — он бесплатный. Если JSON невалиден, экономим на redundancy и scoring.

Каждый check можно включать/отключать через `--checks`.

---

## Структура файлов

```
src/quality/
  __init__.py
  models.py              # CheckVerdict, PipelineResult, PipelineConfig
  checks/
    __init__.py
    constraint.py         # Подход 1
    redundancy.py         # Подход 2
    scoring.py            # Подход 3
  pipeline.py             # Оркестратор с retry-логикой
  report.py               # Агрегация метрик + JSON/markdown отчёт
  run_quality.py          # CLI entry point

data/quality/
  inputs/
    edge_cases.jsonl      # 6 пограничных примеров
    noisy.jsonl           # 6 зашумлённых примеров
  eval/<model-slug>/      # результаты по модели
    <input-set>/
      summary.json
      summary.md
      <example>.json      # детализация по каждому примеру
```

---

## Тестовые наборы данных

| Набор | Кол-во | Описание |
|-------|--------|----------|
| `eval` | 11 | Штатные примеры из eval.jsonl с gold-ответами |
| `edge_cases` | 6 | Минимальный вход, неоднозначный type, смешанный feat+refactor, research без модулей |
| `noisy` | 6 | Опечатки в модулях, английский текст, обрезанный вход, лишний контекст (meeting notes), эмоциональный стиль |

---

## Запуск

```bash
# Активировать venv (обязательно!)
source .venv/bin/activate

# Dry run — проверить что всё загружается
python -m src.quality.run_quality --dry-run

# Только constraint check (без API, мгновенно)
python -m src.quality.run_quality --checks constraint \
    --provider ollama --model qwen2.5:7b-instruct

# Constraint + scoring (без redundancy — экономим 2 вызова)
python -m src.quality.run_quality --checks constraint,scoring \
    --provider ollama --model qwen2.5:7b-instruct

# Полный pipeline (все 3 проверки)
python -m src.quality.run_quality \
    --provider ollama --model qwen2.5:7b-instruct

# На другом наборе данных
python -m src.quality.run_quality --input-set edge_cases \
    --provider ollama --model qwen2.5:7b-instruct

# На всех наборах сразу
python -m src.quality.run_quality --input-set all \
    --provider ollama --model qwen2.5:7b-instruct

# OpenAI / OpenRouter
python -m src.quality.run_quality --model gpt-4o-mini
python -m src.quality.run_quality --provider openrouter --model gpt-4o-mini

# Ограничить количество примеров
python -m src.quality.run_quality --limit 3

# Настроить параметры pipeline
python -m src.quality.run_quality --redundancy-n 5 --max-retries 3

# По трейн данным
python -m src.quality.run_quality --from-jsonl data/out/train.jsonl --dry-run
```

### Параметры CLI

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `--checks` | `constraint,redundancy,scoring` | Какие проверки запускать |
| `--input-set` | `eval` | Набор данных: `eval`, `edge_cases`, `noisy`, `all` |
| `--from-jsonl` | — | Явный путь к JSONL-файлу |
| `--model` | `gpt-4o-mini` | Модель |
| `--provider` | `auto` | `openai`, `openrouter`, `ollama`, `auto` |
| `--temperature` | `0.3` | Температура для основного вызова |
| `--redundancy-n` | `3` | Кол-во вызовов для redundancy (включая исходный) |
| `--max-retries` | `2` | Макс. повторов при constraint FAIL |
| `--limit` | — | Ограничить кол-во примеров |
| `--num-ctx` | — | Размер контекста (только Ollama) |
| `--dry-run` | — | Проверка без API-вызовов |

---

## Метрики в отчёте

| Метрика | Описание |
|---------|----------|
| Acceptance rate | Доля принятых без замечаний |
| Warning rate | Доля принятых с предупреждениями |
| Rejection rate | Доля отклонённых |
| Avg attempts | Среднее кол-во попыток (1 = сразу прошёл) |
| Avg API calls | Среднее кол-во API-вызовов на пример |
| Cost multiplier | Во сколько раз дороже baseline (по токенам) |
| Accuracy on accepted | modules_iou, type/block match — только по принятым (где есть gold) |
| False reject rate | Доля отклонённых, которые были правильными |
| Per-check breakdown | OK/UNSURE/FAIL по каждой проверке отдельно |

---

## Связь с другими модулями

- **Переиспользует из Day 6:** `validate_gold()`, `score()`, `iou()`, `load_eval()`, `call_api()`, `model_slug()`
- **Входные данные:** `data/out/eval.jsonl` (штатный eval-датасет)
- **Выходные данные:** `data/quality/eval/<model-slug>/<input-set>/`
