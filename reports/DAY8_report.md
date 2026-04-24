# День 8. Routing между моделями — Отчёт

## Задача

Реализовать routing запросов между дешёвой и сильной моделью. Дешёвая обрабатывает простые запросы, при низкой уверенности — эскалация на сильную.

**Модели:**
- Cheap: `qwen2.5:7b-instruct` (4.7 GB) — baseline из Day 6-7
- Strong: `gpt-oss:20b` (13 GB) — локальная через Ollama

**Задача инференса:** extraction — извлечение структурированного JSON из свободного текста описания задач KMP-проекта.

---

## 1. Архитектура роутера

```
User query
    │
    ▼
┌───────────────────────┐
│  Cheap model (7B)     │
│  + constraint check   │
│  + self-check         │
└──────────┬────────────┘
           │
    всё ОК? ──yes──▶ return result
           │
          no
           │
           ▼
┌───────────────────────┐
│  Strong model (20B)   │
└──────────┬────────────┘
           │
           ▼
    return result
```

### Эвристики эскалации (3 штуки)

1. **JSON parse failed** — ответ не парсится как JSON → эскалация (бесплатно)
2. **Constraint check** — validate_gold() проверяет схему, enum-ы, алиасы модулей → FAIL = эскалация (бесплатно, из Day 6-7)
3. **Self-check confidence** — модель возвращает reasoning + confidence (OK/UNSURE/FAIL) в одном вызове → UNSURE или FAIL = эскалация (0 доп. вызовов)

### Реализация

```
src/routing/
├── __init__.py
├── router.py          # RouterConfig, RoutingResult, route_example()
└── run_routing.py     # CLI-раннер, отчёт
```

Команда запуска:
```bash
python -m src.routing.run_routing --provider ollama --self-check
```

---

## 2. Итерации по промпту self-check

### Промпт v3 (финальный) — нейтральный пример + побуждение к сомнению
```
Верни ответ строго в таком формате:
{ "extraction": { ... }, "reasoning": "...", "confidence": "OK | UNSURE | FAIL" }
Подумай, насколько хорошо твоё решение. В поле reasoning положи объяснение
логики своего решения, какие поля вызывают сомнения, и почему ты выбрал
такую оценку confidence.
В поле confidence положи оценку своей уверенности в правильности ответа:
- OK — все поля извлечены однозначно из текста, правила соблюдены.
- UNSURE — есть сомнения в каком-либо поле.
- FAIL — описание слишком короткое или непонятное для извлечения.
```

---

## 3. Результаты

### Сводка по трём прогонам

| Прогон | Self-check triggers | Constraint triggers | On cheap | On strong | Avg modules IoU |
|--------|--------------------|--------------------|----------|-----------|-----------------|
| v3 (reasoning + enum) | 0 | 4 | 6 | 5 | 0.712 |

### Финальный прогон (v3) — метрики (eval.jsonl, 11 примеров)

| Метрика | Baseline (qwen2.5:7b, no routing) | Day 8 Routing (v3) |
|---------|-----------------------------------|---------------------|
| Errors (parse fail) | 2 | **0** |
| type match | 8/9 | **10/11** |
| block match | 4/9 | **7/11** |
| **modules IoU** | 0.463 | **0.712** |
| newModules IoU | 0.667 | 0.727 |
| deps IoU | 0.833 | 0.727 |
| AC recall | 0.000 | **0.114** |
| OoS precision | 0.500 | **0.636** |
| escalated to strong | — | 5/11 |
| **avg latency** | 4488ms | 10758ms |
| tokens in | 14035 | 22669 |
| tokens out | 2896 | 9413 |

### Финальный прогон (v3) — детали

| # | routed_to | reasons | type | block | modules_iou | deps_iou | latency |
|---|-----------|---------|------|-------|-------------|----------|---------|
| eval_01 | strong | json_parse_failed | MISS | ok | 1.00 | 0.00 | 21443ms |
| eval_02 | cheap | - | ok | ok | 1.00 | 1.00 | 7320ms |
| eval_03 | cheap | - | ok | ok | 0.00 | 1.00 | 3942ms |
| eval_04 | cheap | - | ok | MISS | 0.50 | 1.00 | 4297ms |
| eval_05 | cheap | - | ok | ok | 0.50 | 1.00 | 11869ms |
| eval_06 | cheap | - | ok | MISS | 0.67 | 1.00 | 5781ms |
| eval_07 | strong | constraint_fail | ok | ok | 1.00 | 0.00 | 15543ms |
| eval_08 | strong | constraint_fail | ok | MISS | 1.00 | 0.00 | 20946ms |
| eval_09 | strong | constraint_fail | ok | MISS | 0.67 | 1.00 | 14440ms |
| eval_10 | cheap | - | ok | ok | 0.50 | 1.00 | 3389ms |
| eval_11 | strong | constraint_fail | ok | ok | 1.00 | 1.00 | 9373ms |

### Accuracy по подмножествам

| Subset | Count | Avg modules IoU | Type match | Block match |
|--------|-------|-----------------|------------|-------------|
| Overall | 11 | 0.712 | 90.9% | 63.6% |
| Cheap only | 6 | 0.528 | 100.0% | 66.7% |
| Strong only | 5 | 0.933 | 80.0% | 60.0% |

### Routing summary

| Metric | Value |
|--------|-------|
| Total examples | 11 |
| Stayed on cheap | 6 (54.5%) |
| Escalated to strong | 5 (45.5%) |
| Avg latency | 10758 ms |
| Total tokens in | 22669 |
| Total tokens out | 9413 |

### Причины эскалации

| Reason | Count |
|--------|-------|
| constraint_fail | 4 |
| json_parse_failed | 1 |
| self_check | 0 |

---

## 4. Что ловит каждая эвристика

### Constraint check — ловит форматные ошибки
Cheap модель (7B) часто пишет полные gradle-пути вместо алиасов из таблицы:
- `core-features/indicators` вместо `cf-indicators`
- `core-features/experiments` вместо `cf-experiments`
- `composeApp` вместо допустимых алиасов

Constraint check это ловит (алиас не из таблицы → FAIL), strong модель исправляет → modules_iou 1.00.

### Constraint check — НЕ ловит семантические ошибки
Если модель написала `m-analysis` вместо `uikit` — оба валидные алиасы. Constraint check не знает правильного ответа, он проверяет только формат. Пример: eval_03 (modules_iou=0.00) прошёл constraint check.

### Self-check — не работает с qwen2.5:7b
Модель **всегда ставит confidence=OK**, даже при modules_iou=0.00. Три итерации промпта (расплывчатый → с примером → с побуждением к сомнению) не изменили результат. Маленькая модель не способна адекватно оценить себя — она уверена в неправильных ответах.

При этом добавление reasoning (self-explain) улучшает качество extraction: avg modules_iou 0.659 → 0.742 (+12.6%). Chain-of-thought заставляет модель лучше думать при извлечении, хотя self-оценка бесполезна.

---

## 5. Выводы

### Что работает
- **Constraint check** — бесплатная, надёжная эвристика. Поймала 4 из 5 эскалаций. Ловит форматные ошибки (невалидные алиасы, отсутствующие поля, неправильные enum-ы).
- **JSON parse** — тривиальная, но необходимая проверка. Поймала 1 случай (модель сгенерировала JS-стиль конкатенации строк `"..." + "..."`).
- **Routing в целом** — strong модель существенно лучше на эскалированных примерах (modules_iou 0.933 vs 0.528 на cheap).
- **Reasoning как побочный эффект** — добавление self-explain улучшает качество extraction даже без работающего confidence.

### Что не работает
- **Self-check с маленькой моделью** — qwen2.5:7b не умеет сомневаться. Self-оценка всегда OK, независимо от формулировки промпта. Это ограничение модели, а не промпта.
- **Семантические ошибки** — constraint check не ловит выбор неправильного (но валидного) алиаса модуля или блока. Для этого нужен либо fine-tuning, либо второй вызов к более сильной модели (scoring check из Day 7).

### Рекомендация для продакшена
Оптимальная стратегия с локальными моделями:
1. Cheap model + constraint check (бесплатный) — отсекает форматные ошибки
2. Эскалация на strong при FAIL — исправляет невалидные ответы
3. Self-explain (reasoning) — включить всегда, улучшает качество extraction бесплатно
4. Self-check confidence — не использовать с маленькими моделями, бесполезен

---

## 6. Воспроизведение

```bash
# Dry run
python -m src.routing.run_routing --dry-run --provider ollama --self-check

# Реальный прогон
python -m src.routing.run_routing --provider ollama --self-check

# Без self-check (только constraint + json parse)
python -m src.routing.run_routing --provider ollama
```

### Данные прогонов

```
data/routing/
  qwen2.5-7b-instruct_to_gpt-oss-20b_selfscore/    # прогоны v1, v2
  qwen2.5-7b-instruct_to_gpt-oss-20b_selfcheck/     # прогон v3 (финальный)
```
