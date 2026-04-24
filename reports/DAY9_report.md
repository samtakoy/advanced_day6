# День 9. Декомпозиция инференса — Отчёт

## Задача

Разбить монолитный extraction-запрос (один промпт → 8-полевой JSON) на цепочку коротких специализированных стадий. Сравнить качество и стоимость.

**Модель:** `qwen2.5:7b-instruct` (4.7 GB, Ollama)
**Eval set:** 11 примеров из eval.jsonl

---

## 1. Архитектура: 4 стадии

```
User text
    │
    ├──▶ Stage 1: Analyze (LLM)    → {modules, newModules, dependsOn}
    ├──▶ Stage 2: Classify (LLM)   → {type, block}
    ├──▶ Stage 3: Extract (LLM)    → {title, acceptanceCriteria, outOfScope}
    │
    ▼
Stage 4: Assemble (код)  → финальный 8-полевой JSON
```

### Принципы декомпозиции

- Каждая LLM-стадия отвечает за 2-3 поля, промпт короткий и сфокусированный.
- Stage 2 (classify) — строгий enum-формат: `type` (3 значения) × `block` (6 значений).
- Stage 1 (analyze) — массивы из enum-алиасов модулей + числа dependsOn.
- Stage 3 (extract) — свободные строки (title, criteria), наименее строгий формат, но это природа данных.
- Stage 4 (assemble) — детерминированный merge без LLM, формат выхода гарантирован кодом.

### Почему такое разбиение

- **modules IoU** — главная метрика, главная ошибка baseline. Отдельная стадия с таблицей алиасов и focused промптом позволяет модели сконцентрироваться на маппинге.
- **type/block** — два enum-поля, решаются classification-промптом. Получают полный оригинальный текст (не summary — summary теряет сигналы для block).
- **acceptanceCriteria/outOfScope** — извлечение из текста, отделено от сборки. Ранняя версия объединяла извлечение и сборку в одну LLM-стадию — модель ломала JSON (JS-конкатенация строк). После выделения в отдельный extract — 0 ошибок парсинга.

### Реализация

```
src/multistage/
├── __init__.py
├── prompts.py          # 3 коротких промпта (analyze, classify, extract)
├── stages.py           # run_analyze(), run_classify(), run_extract(), assemble()
├── pipeline.py         # оркестратор + monolithic для сравнения
└── run_multistage.py   # CLI-раннер
```

Команда запуска:
```bash
python -m src.multistage.run_multistage --provider ollama --model qwen2.5:7b-instruct
python -m src.multistage.run_multistage --provider ollama --model qwen2.5:7b-instruct --temperature 0
python -m src.multistage.run_multistage --no-mono   # без monolithic-сравнения
```

---

## 2. Результаты

### Сравнение трёх подходов (qwen2.5:7b, T=0.3)

| Метрика | Monolithic (7b) | Multi-stage (7b) | Day 8 Routing (7b→20b) |
|---------|----------------|-----------------|----------------------|
| **modules IoU** | 0.417 | **0.642 (+54%)** | 0.712 |
| type match | 90.0% | **100%** | 90.9% |
| block match | 80.0% | **81.8%** | 63.6% |
| dependsOn IoU | 0.750 | **0.955** | 0.727 |
| AC recall | 0.100 | **0.263** | 0.114 |
| OoS precision | 0.550 | **0.636** | 0.636 |
| Parse errors | 2/11 | **0/11** | 0/11 |
| Avg latency | **4058ms** | 5317ms | 10758ms |
| Tokens in | **14365** | 27057 | 22669 |
| Tokens out | 2290 | **2179** | 9413 |

### Per-example (T=0.3)

| # | mono modules_iou | ms modules_iou | mono type | ms type | mono block | ms block |
|---|-----------------|----------------|-----------|---------|------------|----------|
| eval_01 | ERR | 0.67 | ERR | ok | ERR | ok |
| eval_02 | 1.00 | 1.00 | ok | ok | ok | ok |
| eval_03 | 0.00 | 0.50 | ok | ok | ok | ok |
| eval_04 | 0.50 | 0.40 | ok | ok | ok | MISS |
| eval_05 | 0.50 | 0.50 | ok | ok | ok | ok |
| eval_06 | 0.67 | 0.25 | ok | ok | MISS | ok |
| eval_07 | 0.00 | 1.00 | ok | ok | ok | ok |
| eval_08 | 0.00 | 1.00 | ok | ok | ok | ok |
| eval_09 | 0.00 | 0.25 | ok | ok | MISS | MISS |
| eval_10 | 0.50 | 0.50 | ok | ok | ok | ok |
| eval_11 | 1.00 | 1.00 | MISS | ok | ok | ok |

### Per-stage breakdown

| Stage | Calls | Errors | Tokens in | Tokens out | Avg latency |
|-------|-------|--------|-----------|------------|-------------|
| analyze | 11 | 0 | 11021 | 406 | 1665ms |
| classify | 11 | 0 | 8359 | 213 | 1151ms |
| extract | 11 | 0 | 7677 | 1560 | 2501ms |
| assemble | 11 | 0 | 0 | 0 | 0ms |

### Влияние температуры

| Метрика | T=0.3 | T=0.0 |
|---------|-------|-------|
| modules IoU | **0.642** | 0.597 |
| type match | 100% | 100% |
| block match | 81.8% | 81.8% |
| Avg latency | 5317ms | **4952ms** |

T=0.3 чуть лучше по modules IoU (+0.045). Небольшая вариативность помогает модели находить правильные алиасы. T=0 немного быстрее.

---

## 3. Что работает

- **modules IoU +54%** на той же модели — декомпозиция даёт сравнимый с routing эффект (0.642 vs 0.712), но без второй модели и вдвое быстрее (5.3s vs 10.8s).
- **0 parse errors** — каждая стадия генерирует маленький JSON (2-3 поля), что надёжнее монолитного 8-полевого ответа.
- **type match 100%** — focused classify-промпт с enum-описаниями точнее, чем монолитный промпт со всей схемой.
- **dependsOn IoU 0.955** — отдельная стадия с явным указанием «целые числа, не имена модулей» почти идеальна.
- **Tokens out -5%** — стадии отвечают компактнее (суммарно 2179 vs 2290 у монолита).

## 4. Что не работает

- **block match** — улучшение минимальное (80% → 81.8%). Ранняя версия с classify на summary давала 63.6% — пришлось передавать оригинальный текст. Даже с ним eval_04 и eval_09 ошибаются.
- **Tokens in ×1.9** — каждая стадия получает свой системный промпт, три из них видят полный user-текст. Цена декомпозиции.
- **newModules IoU -0.155** — модули вне таблицы хуже извлекаются отдельной стадией, чем монолитом с полным контекстом схемы.

---

## 5. Выводы

Multi-stage декомпозиция — эффективная альтернатива routing между моделями:

| | Routing (Day 8) | Multi-stage (Day 9) |
|---|---|---|
| Модели | 7b + 20b (18 GB) | только 7b (4.7 GB) |
| modules IoU | 0.712 | 0.642 |
| block match | 63.6% | 81.8% |
| Latency | 10.8s | 5.3s |
| Tokens out | 9413 | 2179 |

Для production оптимально комбинировать: multi-stage + routing (эскалация на сильную модель только при FAIL на одной из стадий).

---

## 6. Воспроизведение

```bash
# Multi-stage с T=0.3
python -m src.multistage.run_multistage --provider ollama --model qwen2.5:7b-instruct

# Multi-stage с T=0
python -m src.multistage.run_multistage --provider ollama --model qwen2.5:7b-instruct --temperature 0

# Только multi-stage (без monolithic-сравнения)
python -m src.multistage.run_multistage --provider ollama --model qwen2.5:7b-instruct --no-mono
```

### Данные прогонов

```
data/multistage/
  qwen2.5-7b-instruct/
    eval_01.json ... eval_11.json
    summary.json
    summary.md
```
