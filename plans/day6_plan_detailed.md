# День 6 — Детальный план: локальный fine-tune + расширение проекта

> Документ фиксирует итоговое решение по Дню 6 после анализа проекта изнутри.
> Исходная постановка — `plans/day6_plan.md`. Реализация — `plans/adv_day6_impl_B.md`.
> Предыдущая версия этого документа писалась "со стороны" и предлагала форк — это было ошибкой.
> Мы работаем внутри существующего проекта, расширяя его под локальное обучение.
> Дата актуализации — 2026-04-22.

---

## 1. Текущее состояние проекта

Проект полностью реализован по `adv_day6_impl_B.md`:

| Компонент | Статус | Что есть |
|-----------|--------|----------|
| `contracts/` | Готово | 9 тулов (5 state + 4 project), step/plan schemas |
| `prompts/` | Готово | system_agent.md, system_plain.md, 3 мета-промпта |
| `dataset/seeds/` | Готово | 12 hand-crafted seeds |
| `dataset/synthetic/` | Готово | ~46 синтетических примеров |
| `dataset/train.jsonl` + `eval.jsonl` | Готово | 47/11 stratified split |
| `dataset/eval_plain.jsonl` | Готово | 5 концептуальных вопросов |
| `validator/` | Готово | structural + semantic проверки |
| `baseline/` | Готово | gpt-4o-mini baseline замерен |
| `criteria/` | Готово | 5 авто + 2 LLM-judge метрики |
| `ft_client/` | Готово | upload + create_job (--confirm) + poll — **только OpenAI** |

**Что отсутствует:** локальный fine-tune через MLX, baseline на локальных моделях, dual-backend архитектура.

---

## 2. Что мы хотим добавить

### 2.1 Цель

Расширить проект для **локального fine-tuning** на Mac M4 Max 48GB:
- Обучение через MLX (Apple Silicon native)
- Baseline и post-FT eval через Ollama (OpenAI-compat API)
- Сравнительная таблица: OpenAI FT vs MLX FT

### 2.2 Зачем

- Бесплатно (нет расходов на OpenAI FT API)
- Приватно (данные не покидают машину)
- Показывает что FT-подход работает на разных классах моделей
- Практический навык локального fine-tuning для дальнейшего применения

---

## 3. Выбор модели для локального FT

### Hardware: Mac M4 Max, 48GB unified memory

### Кандидаты (из Ollama):

| Модель | GGUF size | bf16 size (для MLX) | QLoRA peak RAM | Вердикт |
|--------|-----------|---------------------|----------------|---------|
| **Qwen 2.5 7B Instruct** | ~4.7 GB | ~14 GB | ~8-10 GB | **Основной кандидат.** Быстро, безопасно, есть на HF |
| **Qwen 2.5 14B Instruct** | 9.0 GB | ~28 GB | ~18-22 GB | Альтернатива. Сильнее, но дольше. Влезает в 48GB |
| `gpt-oss:20b` | 13 GB | ~40 GB | ~32-38 GB | **Не рекомендуется.** Предельно по RAM. Неизвестно наличие на HF для MLX. Нестандартная модель — сложнее отладить формат |
| `qwen2.5-coder:7b` | 4.7 GB | ~14 GB | ~8-10 GB | Code-специализированная. Может быть хуже на agent-дисциплине (не обучалась на tool_calls формат) |

**Решение:** начинаем с **Qwen 2.5 7B Instruct** (HF: `Qwen/Qwen2.5-7B-Instruct`). Если результаты слабые — пробуем 14B.

> **Важно**: MLX fine-tuning работает с HuggingFace weights (safetensors), не с GGUF из Ollama. Нужно скачать с HF отдельно. После обучения — merge + конвертация в GGUF → загрузка в Ollama.

### gpt-oss:20b — почему откладываем

1. **RAM**: bf16 ~40GB + QLoRA overhead → 48GB впритык, OOM вероятен
2. **Происхождение**: нужно найти HF-репо с safetensors. Если модель доступна только как GGUF — MLX FT невозможен
3. **Tool calling**: неизвестно, обучалась ли на OpenAI tool_calls формат. Qwen 2.5 Instruct — обучалась нативно
4. **Рекомендация**: если очень хочется — попробовать после успешного Qwen 7B, но как эксперимент, не как основной путь

---

## 4. Формат датасета для MLX — РЕШЕНО

> **Решение (2026-04-22):** конвертация НЕ нужна.

`mlx_lm` v0.31+ **нативно поддерживает OpenAI chat format с tool_calls**. В `ChatDataset` (mlx_lm/tuner/datasets.py) есть явный код:
```python
tools = d.get("tools", None)
tokens = self.tokenizer.apply_chat_template(messages, tools=tools, return_dict=False)
```

Наш `train.jsonl` уже в правильном формате `{"messages": [...]}`. Единственное дополнение — нужен top-level ключ `"tools"` в каждой JSONL-строке (список tool schemas из `contracts/tool_schemas.json`), чтобы Qwen chat template корректно вставил tool definitions в промпт.

**Действие:** написать `dataset/inject_tools.py` (~20-30 строк) — добавляет `"tools"` ключ к каждой строке train/eval JSONL. Или делать это на лету в `ft_client/mlx/train.py`.

---

## 5. Архитектура расширений — РЕШЕНО

### 5.1 ft_client/ — подпапки по бэкендам

> **Решение (2026-04-22):** подпапки `openai/` и `mlx/` без абстракций.

Текущие три flat-скрипта переносятся в `ft_client/openai/`. Новые MLX-скрипты — в `ft_client/mlx/`. Общий `__init__.py` не нужен на уровне ft_client (пакеты автономны).

```
ft_client/
├── __init__.py
├── openai/
│   ├── __init__.py
│   ├── upload.py           # (перенесён из ft_client/)
│   ├── create_job.py       # (перенесён из ft_client/)
│   └── poll.py             # (перенесён из ft_client/)
├── mlx/
│   ├── __init__.py
│   ├── train.py            # NEW: MLX QLoRA training
│   └── export.py           # NEW: merge + GGUF + Ollama import
└── last_upload.json        # (generated) OpenAI file IDs — остаётся в корне ft_client
```

**Почему подпапки, а не flat:**
- Зависимости изолированы (MLX imports не мешают OpenAI и наоборот)
- При добавлении 3-го бэкенда — просто новая папка, не `huggingface_train.py` / `huggingface_export.py`
- Вызов понятен: `python -m ft_client.mlx.train` / `python -m ft_client.openai.create_job`

**Без abstract base classes.** У OpenAI и MLX совершенно разные workflow (upload→poll vs local train→export). Общий интерфейс был бы натянут. Абстракция — только если появится реальная дупликация.

### 5.2 baseline/ — поддержка Ollama

`run_baseline.py` уже имеет `--provider` флаг (auto/openai/openrouter). Добавляем `ollama`:

```bash
python -m baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct
```

Минимальная правка: Ollama имеет OpenAI-compat API на `http://localhost:11434/v1`. Нужно добавить `base_url` и убрать проверку API key.

---

## 6. Пайплайн локального обучения

```bash
# 0. Установка MLX зависимостей
pip install mlx mlx-lm

# 1. Baseline на базовой Qwen через Ollama
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct

# 2. MLX QLoRA training
python -m src.ft_client.mlx.train \
    --model Qwen/Qwen2.5-7B-Instruct \
    --data data/out/train.jsonl \
    --iters 600 \
    --lora-layers 16 \
    --batch-size 1

# 3. Merge + export в Ollama
python -m src.ft_client.mlx.export \
    --model Qwen/Qwen2.5-7B-Instruct \
    --adapter ./adapters \
    --ollama-name kmp-agent-ft

# 4. Post-FT eval
python -m src.baseline.run_baseline --provider ollama --model kmp-agent-ft

# 5. Anti-catastrophic-forgetting
python -m src.baseline.run_baseline --provider ollama --model kmp-agent-ft \
    --from-jsonl dataset/eval_plain.jsonl
```

---

## 7. Метрики (без изменений)

Все 7 метрик из `criteria/criteria.md` применяются одинаково к обоим бэкендам.

| # | Метрика | Baseline (gpt-4o-mini) | Baseline (Qwen 7B) | Цель FT |
|---|---------|------------------------|---------------------|---------|
| 1 | Structural compliance | ≥80% | TBD | ≥95% |
| 2 | Tool name validity | 100% | TBD | 100% |
| 3 | Task_id consistency | 100% | TBD | 100% |
| 4 | Read-before-action | <40% | TBD | ≥90% |
| 5 | THOUGHT + SELF-CHECK | 0/8 | TBD | ≥90% |
| 6 | Plan quality (LLM-judge) | 2-3 | TBD | ≥4 |
| 7 | Mode switch | N/A | TBD | ≥90% |

**Ожидание для Qwen 7B baseline**: вероятно хуже gpt-4o-mini по всем метрикам (слабее модель). Это делает эффект FT ещё заметнее.

---

## 8. Порядок работы (фазы)

### Фаза 1 — Baseline на Ollama (30 мин)
- Добавить `--provider ollama` в `run_baseline.py`
- Прогнать Qwen 2.5 7B Instruct через Ollama, зафиксировать метрики
- Сравнить с existing gpt-4o-mini baseline

### Фаза 2 — Реструктуризация ft_client/ (30 мин)
- Перенести upload.py, create_job.py, poll.py в `ft_client/openai/`
- Обновить `__init__.py`, проверить что `python -m ft_client.openai.create_job` работает

### Фаза 3 — MLX training скрипт (1-2 ч)
- Написать `ft_client/mlx/train.py` — обёртка над `mlx_lm.lora`
- Тестовый прогон на 10 итерациях (smoke test)
- Полный прогон (~600 итераций, ~15-30 мин на 7B)

### Фаза 4 — Export + Ollama (1 ч)
- `ft_client/mlx/export.py`: merge adapters → fused model → GGUF → Ollama Modelfile → `ollama create`
- Проверить что модель отвечает через `ollama run kmp-agent-ft`

### Фаза 5 — Post-FT eval (30 мин)
- Прогнать FT-модель через `run_baseline.py --provider ollama --model kmp-agent-ft`
- Прогнать `eval_plain.jsonl` (anti-catastrophic-forgetting)
- Сравнительная таблица: baseline vs FT для обоих бэкендов

---

## 9. Структура проекта (целевая)

Чистая, расширяемая структура без мусора:

```
advanced_day6/
├── src/                        # весь исполняемый код
│   ├── baseline/               # baseline eval (run_baseline.py)
│   ├── dataset/                # генерация/обработка датасета
│   │   ├── gen_synthetic.py    # Generator with retry
│   │   ├── mix_and_split.py    # Stratified split → data/out/
│   │   ├── scenarios.py        # Scenario bank
│   │   ├── build_seeds.py      # Seed builder
│   │   └── summarize.py        # Dataset summary
│   ├── ft_client/
│   │   ├── openai/             # OpenAI FT (upload, create_job, poll)
│   │   └── mlx/                # MLX local FT (train, export)
│   └── validator/              # Structural + semantic checks
├── data/                       # все данные (код → данные разделены)
│   ├── contracts/              # Tool + artifact schemas
│   ├── prompts/                # System + meta prompts
│   ├── seeds/                  # 12 hand-crafted examples
│   ├── synthetic/              # Generated examples
│   └── out/                    # Артефакты (train.jsonl, eval.jsonl) — в .gitignore
├── plans/                      # Planning docs (этот файл)
├── criteria/                   # Eval criteria
├── CLAUDE.md, README.md, EXPLANATION.md, REPORT.md
└── requirements.txt
```

**Принципы структуры:**
- `src/` — код, `data/` — данные. Чёткое разделение
- Бэкенды FT изолированы в подпапках (зависимости не пересекаются)
- `data/out/` содержит генерируемые артефакты (пересобираются через `mix_and_split`)
- Все скрипты вызываются через `python -m src.<package>.<module>`

---

## 10. Deliverables

### Уже готово (из adv_day6_impl_B.md)
- [x] Датасет 58 примеров (train 47 + eval 11)
- [x] Валидатор
- [x] Baseline (gpt-4o-mini)
- [x] Критерии оценки
- [x] FT-клиент (OpenAI)
- [x] eval_plain.jsonl

### Добавлено
- [x] Разделение src/ + data/ (код отдельно от данных)
- [x] Реструктуризация `ft_client/` → подпапки `openai/` и `mlx/`
- [x] `src/baseline/run_baseline.py` — поддержка `--provider ollama`
- [x] `src/ft_client/mlx/train.py` — MLX QLoRA training
- [x] `src/ft_client/mlx/export.py` — merge + GGUF + Ollama import
- [x] Обновить README.md, CLAUDE.md — под новую структуру
- [x] Обновить requirements.txt — добавить mlx, mlx-lm

### Осталось
- [ ] Baseline замер на Qwen 2.5 7B/14B Instruct через Ollama
- [ ] Реальный прогон MLX training (smoke test → full run)
- [ ] Post-FT eval на локальной модели
- [ ] Сравнительная таблица метрик (OpenAI baseline vs Ollama baseline vs Ollama FT)

---

## 11. Риски

| Риск | Страховка |
|------|-----------|
| ~~`mlx_lm` не понимает tool_calls~~ | **Снят**: mlx_lm v0.31+ поддерживает нативно через `tools` ключ |
| Qwen 7B слишком слаба для agent-паттерна | Попробовать 14B (влезает в 48GB) |
| GGUF export из MLX битый | Альтернатива: `mlx_lm.server` как OpenAI-compat endpoint без Ollama |
| QLoRA не закрепляет THOUGHT/SELF-CHECK | Увеличить iters, попробовать full fine-tune (7B влезает) |
| Catastrophic forgetting на Qwen | eval_plain.jsonl + увеличить plain-долю |

---

## Приложение — Эволюция замысла

### Что было в предыдущей версии и почему убрано

1. **"Форк advanced_day6"** — убрано. Мы внутри проекта, не снаружи. Язык "берём как есть" / "не трогаем" заменён на "готово" / "расширяем".

2. **Class hierarchy для FTBackend** — отложено. Два бэкенда не оправдывают абстракцию. Параллельные скрипты проще и быстрее.

3. **gpt-oss:20b как кандидат** — отложен. Риски по RAM и доступности HF weights слишком высоки для первой итерации.

4. **Qwen 2.5 7B** — модели нет в Ollama, но она есть на HuggingFace и скачивается `mlx_lm` автоматически. В Ollama для baseline можно использовать `qwen2.5-coder:7b` или `qwen2.5:14b-instruct` как proxy.

### Что подтвердилось из анализа

1. **FT прошивает форму, не знания** — baseline данные подтверждают (0/8 THOUGHT, 0/8 SELF-CHECK).
2. **Трёхрежимный датасет критичен** — без plain-примеров catastrophic forgetting неизбежен.
3. **Split tool-контракт** переносим между моделями — и OpenAI, и Qwen понимают OpenAI tools format.
4. **Replan discipline** — ключевое отличие от "наивного" агента, именно это FT должен закрепить.
