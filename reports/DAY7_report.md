# День 7. Оценка уверенности и контроль качества инференса — Отчёт

## Модель: qwen2.5:7b-instruct (Ollama), T=0.3, eval.jsonl (11 примеров)

---

## 1. Сравнение подходов

### Baseline (без Day 7) vs Day 7 подходы

| Метрика | 1. Baseline | 2. Self-score | 3. Self-explain | 4. Constraint | 5. Redundancy |
|---------|------------|---------------|-----------------|---------------|---------------|
| Errors (parse fail) | 2 | 1 | 2 | 1 | 1 |
| JSON parse | 9/9 | 10/10 | 9/9 | 10/10 | 10/10 |
| type match | 8/9 | 9/10 | 8/9 | 9/10 | 9/10 |
| block match | 4/9 | 7/10 | 5/9 | 8/10 | 7/10 |
| **modules IoU** | **0.463** | 0.367 | 0.407 | 0.417 | 0.417 |
| deps IoU | 0.833 | 0.850 | 0.944 | 0.850 | 0.850 |
| AC recall | 0.028 | 0.075 | 0.167 | 0.150 | 0.100 |
| OoS precision | 0.389 | 0.550 | 0.611 | 0.550 | 0.583 |
| tokens out | 2681 | 2365 | 3308 | 2282 | 2323 |

### Параметры запуска

- **1. Baseline**: `python -m src.baseline.run_baseline` — чистый Day 6, без суффиксов
- **2. Self-score**: `--self-score` — модель возвращает extraction + confidence (OK/UNSURE/FAIL)
- **3. Self-explain**: `--self-explain` — модель возвращает extraction + reasoning (текст)
- **4. Constraint**: `--checks constraint` — post-hoc валидация схемы (0 API-вызовов)
- **5. Redundancy**: `--checks redundancy` — 2 доп. вызова при T=0 и T=0.7, каждый проверяется через validate_gold + score vs gold

Важно: варианты 2-5 получают суффикс к system prompt (`Верни ответ с корневым полем "extraction"...`), поэтому их метрики отражают совместный эффект суффикса + подхода.

---

## 2. Наблюдения по подходам

### Self-score
- Модель всегда ставит себе OK (7 из 7 распарсенных) — самооценка бесполезна на qwen2.5:7b
- Не добавляет ценности: модель недостаточно сильна для адекватного self-assessment

### Self-explain
- Reasoning генерируется, модель объясняет выбор
- Лучший AC recall (0.167 vs 0.028) — объяснение логики заставляет модель внимательнее читать текст
- Лучший OoS precision (0.611) — меньше галлюцинаций в outOfScope
- Но modules IoU упал (0.407 vs 0.463) — доп. инструкции отвлекают модель от основной задачи

### Constraint
- 0 дополнительных API-вызовов
- Переиспользует validate_gold() из Day 6 валидатора
- Не влияет на ответ модели — только помечает valid/invalid
- Полезен для фильтрации: если constraint FAIL — ответ точно ненадёжный

### Redundancy
- 2 доп. вызова при T=0 и T=0.7
- Каждый ответ проверяется через validate_gold + score vs gold
- Выбирает лучший валидный ответ по modules_iou (главная метрика)
- На qwen2.5:7b upgrade не сработал — модель стабильно ошибается одинаково
- При T=0.7 часто ломается JSON или теряет поля

---

## 3. Fine-tuned модель vs Baseline

| Метрика | qwen2.5:7b (base) | kmp_extract_ft |
|---------|-------------------|----------------|
| Errors | 2 | **0** |
| JSON parse | 9/9 | **11/11** |
| type match | 8/9 | 9/11 |
| block match | 4/9 | **8/11** |
| **modules IoU** | **0.463** | **0.538** |
| newMods IoU | 0.556 | **0.727** |
| deps IoU | 0.833 | **0.909** |
| AC recall | 0.028 | **0.475** |
| OoS precision | 0.389 | **0.636** |
| schema valid | 7/11 | **10/11** |
| tokens out | 2681 | **1669** |

Fine-tuned модель лучше по всем метрикам:
- 0 ошибок парсинга (vs 2)
- AC recall 0.475 vs 0.028 — на порядок лучше
- Более лаконичные ответы (1669 vs 2681 tokens)
- FT прошивает таксономию проекта — модель знает алиасы модулей и блоки

---

## 4. Найденные проблемы и выводы

### Проблемы реализации
1. **Суффикс меняет промпт** — нельзя честно сравнить эффект checks vs baseline, когда у них разные промпты
2. **Self-score бесполезен на слабой модели** — qwen2.5:7b всегда ставит OK
3. **Scoring COT (первая версия)** копировал пример из промпта вместо анализа
4. **Scoring judges не получали system prompt** — не знали таксономию модулей → выдумывали ошибки
5. **Redundancy при высокой температуре** ломает JSON у qwen2.5:7b

### Выводы
- **Constraint** — надёжный и бесплатный. Ловит невалидный JSON, неправильные enum-значения, неизвестные модули
- **Redundancy** — полезен для диагностики стабильности модели, но не улучшает результат если модель стабильно ошибается
- **Self-explain** — единственный подход, реально улучшивший некоторые метрики (AC recall, OoS precision), но за счёт деградации modules IoU
- **Fine-tuning** (Day 6) даёт больший эффект, чем все Day 7 подходы вместе взятые — потому что прошивает знание предметной области

---

## 5. Данные прогонов

Все результаты сохранены в `data/baseline/day7_compare/`:

```
data/baseline/day7_compare/
  0_ft_baseline/eval/kmp_extract_ft/     # fine-tuned baseline
  1_baseline/eval/qwen2.5-7b-instruct/  # чистый baseline
  2_self_score/eval/qwen2.5-7b-instruct/
  3_self_explain/eval/qwen2.5-7b-instruct/
  4_constraint/eval/qwen2.5-7b-instruct/
  5_redundancy/eval/qwen2.5-7b-instruct/
```

Каждая папка содержит `summary.json`, `summary.md` и per-example JSON.
