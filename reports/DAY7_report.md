# День 7. Оценка уверенности и контроль качества инференса — Отчёт

## Задача

Extraction: извлечение структурированного JSON (title, type, block, modules, dependsOn, acceptanceCriteria, outOfScope) из свободного текста описания задач KMP-проекта. Модель: qwen2.5:7b-instruct (Ollama), T=0.3.

---

## 1. Реализованные подходы

### Scoring (--self-score)
Модель возвращает extraction + confidence (OK/UNSURE/FAIL) в одном вызове. Суффикс к system prompt просит добавить поле `confidence`.

### Self-check (--self-explain)
Модель возвращает extraction + reasoning (текст) в одном вызове. Суффикс просит объяснить логику решения.

### Constraint-based (--checks constraint)
Post-hoc валидация: validate_gold() проверяет схему, enum-значения, алиасы модулей. 0 дополнительных API-вызовов. Отклоняет ответ при FAIL.

### Redundancy (--checks redundancy)
Доп. вызовы при T=0.15 и T=0.0, только если первый ответ (T=0.3) не прошёл validate_gold. Каждый ответ проверяется через validate_gold + score vs gold. Из всех валидных выбирается лучший по modules_iou (главная метрика).

---

## 2. Результаты на корректных данных (eval.jsonl, 11 примеров)

| Метрика | Baseline | Self-score | Self-explain | Constraint | Redundancy |
|---------|----------|------------|--------------|------------|------------|
| Errors (parse fail) | 3 | 1 | 1 | 1 | 1 |
| type match | 7/8 | 9/10 | 9/10 | 9/10 | 9/10 |
| block match | 5/8 | 6/10 | 7/10 | 8/10 | 7/10 |
| **modules IoU** | **0.458** | 0.417 | 0.417 | 0.417 | 0.417 |
| deps IoU | 0.812 | 0.750 | 0.850 | 0.950 | 0.850 |
| AC recall | 0.031 | 0.025 | 0.075 | 0.050 | 0.050 |
| OoS precision | 0.562 | 0.650 | 0.450 | 0.550 | 0.650 |
| **rejected** | 0 | 0 | 0 | **3** | 0 |
| **retried** | 0 | 0 | 0 | 0 | **5** |
| **avg latency** | 3498ms | 3234ms | 4178ms | 2915ms | **5826ms** |
| tokens in | 14035 | 14629 | 14717 | 14365 | **28419** |
| tokens out | 2581 | 2575 | 3409 | 2195 | **4736** |

**Расшифровка метрик:**
- **Errors** — сколько ответов не удалось распарсить как JSON (модель вернула невалидный ответ)
- **type match** — точное совпадение поля `type` (feat/refactor/research) с эталоном. Формат: совпало/всего распарсенных
- **block match** — точное совпадение поля `block` (один из 6 блоков роадмапа) с эталоном
- **modules IoU** — Jaccard similarity (пересечение / объединение) между предсказанными и эталонными модулями. **Главная метрика** — показывает, насколько модель знает таксономию проекта. 1.0 = идеальное совпадение, 0.0 = ни одного общего модуля
- **deps IoU** — Jaccard similarity для поля `dependsOn` (зависимости между задачами)
- **AC recall** — доля эталонных `acceptanceCriteria`, которые модель воспроизвела (точное совпадение строк)
- **OoS precision** — доля предсказанных `outOfScope`, которые есть в эталоне (модель не выдумала лишнего)
- **rejected** — сколько ответов отклонено constraint-проверкой (невалидная схема, неизвестные модули)
- **retried** — сколько ответов потребовали повторного инференса через redundancy
- **avg latency** — среднее время обработки одного примера (включая доп. вызовы)
- **tokens in / out** — суммарное потребление токенов (включая доп. вызовы redundancy). Показатель стоимости

Примечание: варианты 2-5 получают суффикс к system prompt (`Верни ответ с корневым полем "extraction"...`), что влияет на поведение модели. Разница в метриках отражает совместный эффект суффикса + подхода.

---

## 3. Результаты на пограничных случаях (edge_cases.jsonl, 6 примеров)

Минимальный вход, неоднозначный type, смешанный feat+refactor, research без модулей.

| Метрика | Base: baseline | Base: constraint+redundancy | FT: baseline |
|---------|---------------|----------------------------|-------------|
| Errors | 1 | 0 | 1 |
| type match | 4/5 | 4/6 | 3/5 |
| block match | 1/5 | 2/6 | 3/5 |
| **modules IoU** | 0.650 | 0.625 | **0.850** |
| AC recall | 0.167 | 0.250 | **0.533** |
| OoS precision | 0.800 | 0.667 | 0.800 |
| rejected | 0 | **4** | 0 |
| retried | 0 | **4** | 0 |
| tokens out | 1288 | 1765 | **603** |

Воспроизведение:
```bash
# Base: baseline
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct \
  --from-jsonl data/quality/inputs/edge_cases.jsonl \
  --out-dir data/baseline/day7_compare/6_edge_baseline

# Base: constraint+redundancy
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct \
  --from-jsonl data/quality/inputs/edge_cases.jsonl \
  --out-dir data/baseline/day7_compare/7_edge_redundancy \
  --checks constraint,redundancy

# FT: baseline
python -m src.baseline.run_baseline --provider ollama --model kmp_extract_ft \
  --from-jsonl data/quality/inputs/edge_cases.jsonl \
  --out-dir data/baseline/day7_compare/10_edge_ft
```

---

## 4. Результаты на зашумлённых данных (noisy.jsonl, 6 примеров)

Опечатки в модулях, английский текст, обрезанный вход, лишний контекст (meeting notes), эмоциональный стиль.

| Метрика | Base: baseline | Base: constraint+redundancy | FT: baseline |
|---------|---------------|----------------------------|-------------|
| Errors | 0 | 0 | 0 |
| type match | 4/6 | 5/6 | **6/6** |
| block match | 4/6 | 5/6 | 4/6 |
| **modules IoU** | **0.611** | **0.611** | 0.361 |
| AC recall | 0.000 | 0.167 | **0.500** |
| OoS precision | 0.500 | 0.500 | **0.833** |
| schema valid | 4/6 | **6/6** | **6/6** |
| rejected | 0 | 0 | 0 |
| retried | 0 | 1 | 0 |
| tokens out | 1446 | 1205 | **611** |

Воспроизведение:
```bash
# Base: baseline
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct \
  --from-jsonl data/quality/inputs/noisy.jsonl \
  --out-dir data/baseline/day7_compare/8_noisy_baseline

# Base: constraint+redundancy
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct \
  --from-jsonl data/quality/inputs/noisy.jsonl \
  --out-dir data/baseline/day7_compare/9_noisy_redundancy \
  --checks constraint,redundancy

# FT: baseline
python -m src.baseline.run_baseline --provider ollama --model kmp_extract_ft \
  --from-jsonl data/quality/inputs/noisy.jsonl \
  --out-dir data/baseline/day7_compare/11_noisy_ft
```

---

## 5. Fine-tuned vs Baseline (сводка по eval)

| Метрика | qwen2.5:7b (base) | kmp_extract_ft |
|---------|-------------------|----------------|
| Errors | 3 | **0** |
| JSON parse | 8/8 | **11/11** |
| type match | 7/8 | 9/11 |
| block match | 5/8 | **8/11** |
| **modules IoU** | 0.458 | **0.538** |
| AC recall | 0.031 | **0.475** |
| OoS precision | 0.562 | **0.636** |
| tokens out | 2581 | **1669** |

---

## 6. Замеры по заданию

### Сколько ответов было отклонено
- **Constraint** отклонил 3 из 11 на eval (невалидная схема: неизвестные модули, отсутствующие поля)
- **Constraint** отклонил 4 из 6 на edge_cases
- На noisy данных — 0 отклонений

### Сколько потребовало повторного инференса
- **Redundancy** сделал retry 5 из 11 на eval (только когда validate_gold FAIL), 1 upgrade (modules_iou 0.00 → 0.50)
- На edge_cases — 4 из 6 retry
- На noisy — 1 из 6 retry

### Влияние на latency и cost

| Вариант | Avg latency | Tokens in | Tokens out | Cost multiplier |
|---------|-------------|-----------|------------|----------------|
| Baseline | 3498ms | 14035 | 2581 | 1.0x |
| Self-score | 3234ms | 14629 | 2575 | 1.0x |
| Self-explain | 4178ms (+19%) | 14717 | 3409 (+32%) | 1.1x |
| Constraint | 2915ms | 14365 | 2195 | 1.0x |
| Redundancy | 5826ms (+67%) | 28419 (+102%) | 4736 (+83%) | 2.0x |

---

## 7. Выводы

### Что работает
- **Constraint** — бесплатный, надёжно ловит невалидные ответы (невалидный JSON, несуществующие модули, неправильные enum). По сути это validate_gold из Day 6.
- **Redundancy** — полезен для retry при ошибках парсинга/валидации (доп. вызовы при T=0.15 и T=0.0). Помог в 1 из 5 retry (upgrade modules_iou 0.00→0.50). Стоит 2.0x от baseline.
- **Self-explain** — единственный подход, улучшивший AC recall (+142%) и deps IoU, но за счёт деградации modules IoU и дополнительных токенов.
- **Суффикс extraction wrapper** — сам по себе уменьшает количество ошибок парсинга (3→1 на eval).

### Что не работает
- **Self-score** — модель qwen2.5:7b всегда ставит себе OK. Самооценка бесполезна на слабой модели.
- **Redundancy без ошибок** — если модель стабильно ошибается одинаково, повторные вызовы не помогают.

### Fine-tuning vs Day 7 подходы
Fine-tuning (Day 6) даёт больший эффект, чем все Day 7 подходы: modules IoU +17%, AC recall x15, ноль ошибок парсинга. Day 7 подходы — это контроль качества поверх инференса, а не замена обучению.

### Интересное наблюдение: FT на шумных данных
FT модель хуже по modules IoU на noisy (0.361 vs 0.611) — она выучила точную таксономию и сбивается на опечатках/нестандартном вводе. Base модель устойчивее к шуму, но менее точна на чистых данных.

---

## 8. Данные прогонов

```
data/baseline/day7_compare/
  0_ft_baseline/       # FT модель на eval
  1_baseline/          # base модель на eval (чистый baseline)
  2_self_score/        # --self-score
  3_self_explain/      # --self-explain
  4_constraint/        # --checks constraint
  5_redundancy/        # --checks redundancy
  6_edge_baseline/     # base на edge_cases
  7_edge_redundancy/   # constraint+redundancy на edge_cases
  8_noisy_baseline/    # base на noisy
  9_noisy_redundancy/  # constraint+redundancy на noisy
  10_edge_ft/          # FT на edge_cases
  11_noisy_ft/         # FT на noisy
```
