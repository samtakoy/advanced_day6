# REPORT — День 6. DataSet

Отчёт по заданию «🔥 День 6. DataSet». Структура повторяет пункты задания.

---

## 1. Выбор задачи

**Класс задачи: генерация.**

Точнее — **мультитурн-генерация ответов агента с tool_calls** в формате OpenAI. Это внутри «генерации» по официальной классификации (модель продуцирует структурированный текст, а не метку и не извлечённые сущности), но с очень жёстким форматом: каждый assistant-ход обязан содержать `THOUGHT:` + `SELF-CHECK:` в `content` и один `tool_call`, а state-tool вызовы должны нести `task_id` из `# Current session` блока system-промпта.

**Сценарий продукта:** «weak LLM (gpt-4o-mini) учится быть дисциплинированным агентом-исполнителем задач в Kotlin Multiplatform проекте». Базовый замер показывает, что неподготовленная модель не держит формат (детали — §4), поэтому именно fine-tune под данный формат — единственно рентабельное решение.

---

## 2. Сборка датасета

**Итог: 58 примеров в JSONL формате** (цель по заданию — ≥50).

| Источник | Кол-во | Способ получения |
|---|---|---|
| Hand-crafted seeds (реальные) | **12** | Написаны вручную, опираясь на задачи из реального KMP-проекта `C:\devs\kmm\stocks\task\board\pool` |
| Synthetic via `openai/gpt-4o` | 14 | Платный генератор через OpenRouter, с ретраями по валидатору |
| Synthetic via `openai/gpt-oss-120b:free` | 32 | Бесплатный генератор через OpenRouter, лучший из smoke-теста |
| **ВСЕГО** | **58** |  |

**Формат каждого примера:**
```jsonc
{
  "messages": [
    {"role": "system", "content": "<system prompt, содержит TASK_ID: t-NNNN>"},
    {"role": "user", "content": "<естественный запрос разработчика>"},
    {"role": "assistant",
     "content": "THOUGHT: ...\nSELF-CHECK: ...",
     "tool_calls": [{"id": "c1", "type": "function",
                     "function": {"name": "plan_write", "arguments": "{...}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "{...}"},
    …
  ]
}
```
Три роли (system/user/assistant) присутствуют в каждом примере; для агентских ещё и `tool` — это допускается OpenAI FT API.

**Соотношение real/synth: 12/58 = 20.7% реальных.** Превышает требуемый порог задания ≥20%. Все 12 seeds — полные эталоны с 3-39 сообщениями каждый, включая replan-сценарий (`golden_01_add_dep_with_replan`). Все синтетические сценарии так же seed'нуты из реального task board KMP-проекта (`src/dataset/scenarios.py` ссылается на `C:\devs\kmm\stocks\task\board\pool`).

**Список seeds (12 hand-crafted реальных):**

| Файл | Тип | Режим | Особенность |
|---|---|---|---|
| `golden_01_add_dep_with_replan.json` | develop | agent | Эталон с replan-веткой (ошибка на шаге 3 → `plan_revise`) |
| `golden_02_happy_path.json` | develop | agent | Happy path без replan — чтобы модель не выучила «ошибка всегда» |
| `develop_01_expect_device_timezone.json` | develop | agent | expect/actual на 3 sourceSet'ах + `write_file` |
| `refactor_01_dispatchers_no_violations.json` | refactor | agent | «Нарушений нет → изменения не требуются» — ветка no-op |
| `bugfix_01_table_wrap.json` | bugfix | agent | Два search_and_replace в одном файле + импорты |
| `bugfix_02_formatprice_npe.json` | bugfix | agent | NPE fallback, Double → Double? + ранний return |
| `research_01_presets_map.json` | research | agent | Read-only → write_file итогового `.md` |
| `research_02_koin_modules_inventory.json` | research | agent | list_dir + 3×read_file → markdown-таблица с колизиями |
| `tests_01_get_sectors_usecase.json` | tests | agent | `write_file` commonTest c Mokkery + Turbine |
| `golden_03_question_branch.json` | — | agent_question | `library_choice` ambiguity — нет имени библиотеки |
| `question_02_scope_breadth.json` | — | agent_question | `scope_breadth` ambiguity — «перенеси всё на Voyager» |
| `plain_01_expect_actual_vs_interface.json` | — | plain | Концептуальный вопрос, проза без tool calls |

**Три режима в датасете (композиция после mix & split):**

| Режим | train | eval | target % | actual % (train) |
|---|---|---|---|---|
| agent (task execution) | 33 | 8 | 70 | **70** |
| agent_question (уточняющие вопросы) | 8 | 2 | 16 | 17 |
| plain (конcept Q&A, без tool calls) | 6 | 1 | 14 | 13 |
| **ИТОГО** | **47** | **11** |  |  |

---

## 3. Подготовка данных

### Фильтрация мусора

- **Пустые/короткие:** валидатор требует `len(content) > 10` для не-tool messages.
- **Слишком длинные:** `len(content) < 8000`.
- **Дубли user-текста:** dedup-проход сравнивает первый user-message попарно. На финальном прогоне вручную отброшено **4 примера** (три итерации одного develop-сценария + один polymorphic-serialization plain), помеченные как `DUP_USER_TEXT` валидатором.

### Train/Eval split

- **Пропорция: 80/20** (требование задания).
- **Метод: stratified** — доли режимов (agent / agent_question / plain) сохраняются в обеих частях. Это важно: если бы eval оказался без plain-примеров, мы не смогли бы замерить catastrophic-forgetting.
- **Seed: 42** для воспроизводимости (`random.Random(42)`).
- **Файлы:** `data/out/train.jsonl` (47 строк), `data/out/eval.jsonl` (11 строк).

### Скрипт валидации

**Файл: `src/validator/validate.py`.** Три независимых прохода:

**Structural checks:**
- каждая строка — валидный JSON
- есть ключ `messages`, это массив
- каждый message имеет `role` ∈ {system, user, assistant, tool}
- у не-tool сообщений непустой `content` (10–8000 символов)
- `tool_calls.arguments` — валидный JSON

**Semantic checks (agent-режим):**
- первый `tool_call` первого assistant = `plan_write` (жёсткий инвариант workflow)
- `task_id` присутствует во всех state-tool вызовах (5 инструментов: plan_write, step_read, step_update_result, task_status, plan_revise)
- перед каждым project-tool вызовом в текущем шаге есть `step_read` этого же шага — прошитый паттерн «read-before-action»
- все tool names ∈ разрешённый список 9 инструментов
- в `content` assistant-сообщения есть `THOUGHT:` и `SELF-CHECK:`
- `arguments` каждого tool_call соответствует его JSON Schema

**Dedup check:** попарное сравнение первого user-message по всем примерам; дубли помечаются как warning.

**Команда:** `python -m src.validator.validate data/synthetic/`

**Результат финального прогона:** 0 errors, 0 warnings (после устранения 3 дублей).

---

## 4. Baseline

**Файл: `src/baseline/run_baseline.py`.** Прогон сделан ДВАЖДЫ для двойной проверки:

1. **На 8 seeds** (исходный прогон) → `baseline/outputs/summary.md`
2. **На 11 примерах `eval.jsonl`** (после финального mix+split, ровно по требованию задания) → `baseline/outputs_eval/summary.md`

Скрипт параметризован флагом `--from-jsonl`: `python -m src.baseline.run_baseline --from-jsonl data/out/eval.jsonl`.

### Результаты baseline на `eval.jsonl` (n=11, gpt-4o-mini, T=0.3)

| Метрика | Результат (agent n=8) | Комментарий |
|---|---|---|
| Первый tool_call = `plan_write` | **8/8** ✅ | Единственное, что gpt-4o-mini делает стабильно |
| Все tool names валидны | **11/11** (всех примеров) ✅ | Галлюцинаций имён инструментов нет |
| task_id во всех state-tool args | **8/8** agent ✅ | Базовая модель уважает session-id |
| **`THOUGHT:` в content** | **0/8** agent ❌ | Полный провал — модель пишет всё в `arguments` |
| **`SELF-CHECK:` в content** | **0/8** agent ❌ | Аналогично |
| Mode-switch на `agent_question` | **0/2** ❌ | Обе ambiguity-запроса → `plan_write` на угаданных параметрах, вместо `QUESTION:` |
| Mode-switch на `plain` | **1/1** ✅ | Корректно ответила прозой без tool_calls |
| Tokens (вход/выход) | 19506 / 2813 | ≈ $0.10 через OpenRouter |

**Сигнал для fine-tune очевиден:** модель физически не пишет ни THOUGHT, ни SELF-CHECK в content — весь семантический «разум» прячется в аргументах. После FT это должно ликвидироваться.

### Baseline на локальных моделях (Ollama, eval.jsonl n=11)

Для выбора базовой модели для локального MLX fine-tune прогнаны три модели:

| Метрика (agent n=8) | qwen2.5:7b-instruct | qwen2.5-coder:7b-instruct | qwen2.5:14b-instruct |
|---|---|---|---|
| Первый tool = `plan_write` | **6/8 (75%)** | 0/8 (0%) | 3/8 (37%) |
| `THOUGHT:` в content | 7/8 (87%) | **8/8 (100%)** | 3/8 (37%) |
| `SELF-CHECK:` в content | 7/8 (87%) | **8/8 (100%)** | 3/8 (37%) |
| task_id в state-tool args | **7/8 (87%)** | 0/8 (0%) | 3/8 (37%) |
| Все tool names валидны | 8/8 (100%) | 8/8 (100%) | 8/8 (100%) |

**Выводы:**
- **7B coder** — пишет THOUGHT/SELF-CHECK идеально, но **ни разу не вызвала tool call** `plan_write`. Весь план пишет в content, не понимает tool calling протокол. FT должен будет учить tool calling с нуля.
- **14B instruct** — 37% по всем метрикам. Часто прыгает к `read_file`/`list_dir` вместо `plan_write`. Пишет "Почемучто..." вместо `THOUGHT:`. Плюс QLoRA на 14B рискует не влезть в 48GB RAM.
- **7B instruct** — лучший баланс: уже на 75-87% следует протоколу, FT дожмёт до 95%+. Безопасно по RAM (~10GB peak).

**Выбор для FT: `qwen2.5:7b-instruct`** (основной), `qwen2.5-coder:7b-instruct` (второй прогон для сравнения).

Результаты сохранены в `data/baseline/eval/<model-slug>/`.

### Критерии «стало лучше»

**Файл: `criteria/criteria.md`.** Сводная таблица:

| # | Метрика | Baseline | Цель FT |
|---|---|---|---|
| 1 | Structural compliance | 100% | ≥95% |
| 2 | Tool name validity | 100% | 100% |
| 3 | Task_id consistency (agent) | 100% | 100% |
| 4 | Read-before-action (agent) | <40% | ≥90% |
| 5 | **THOUGHT + SELF-CHECK в content** | **0%** | **≥90%** |
| 6 | LLM-judge: plan quality (1-5) | 2–3 (оценочно) | ≥4 на медиане |
| 7 | LLM-judge: mode-switch correctness | не замерено | ≥90% |

Плюс **бонус-метрика** (реплан-дисциплина): после `matches=0` или `ok=false` модель должна сделать `step_update_result(NEEDS_REPLAN)` + `plan_revise`, а не ретраить тот же tool_call. Baseline ~20%, цель ≥80%.

### Анти-catastrophic-forgetting

**Файл: `data/out/eval_plain.jsonl`** — 5 концептуальных KMP-вопросов с `system_plain.md` (без tool calls). Прогон через baseline и FT-модель даст ответ на ключевой вопрос: не поломала ли FT способность отвечать прозой? Требование: LLM-judge plain-ответов FT-модели не хуже baseline более чем на 10%.

---

## 5. FT-клиент

**Папка: `src/ft_client/`** — два бэкенда: `openai/` (API) и `mlx/` (локальный).

**OpenAI бэкенд (`src/ft_client/openai/`):**

| Файл | Команда | Что делает |
|---|---|---|
| `upload.py` | `python -m src.ft_client.openai.upload --validation data/out/eval.jsonl` | `client.files.create(file, purpose="fine-tune")`, сохраняет file id в `last_upload.json` |
| `create_job.py` | `python -m src.ft_client.openai.create_job` (dry-run) <br> `python -m src.ft_client.openai.create_job --confirm` (реальный запуск) | `client.fine_tuning.jobs.create(...)`. **Без `--confirm` только печатает spec** |
| `poll.py` | `python -m src.ft_client.openai.poll <job_id>` | Опрос статуса раз в 30 с |

**MLX бэкенд (`src/ft_client/mlx/`):**

| Файл | Команда | Что делает |
|---|---|---|
| `train.py` | `python -m src.ft_client.mlx.train` | QLoRA обучение через mlx_lm.lora. Автоматически инжектит tool schemas в датасет |
| `export.py` | `python -m src.ft_client.mlx.export` | Merge адаптера → GGUF → Ollama import |

**Значения по умолчанию:**
- Model: `gpt-4o-mini-2024-07-18`
- Epochs: `auto`
- Suffix: `kmp-agent` (итоговая модель: `ft:gpt-4o-mini-2024-07-18:org::kmp-agent:xxxx`)

**Важно:** OpenAI fine-tune идёт через прямой `OPENAI_API_KEY`, не через OpenRouter (OpenRouter не поддерживает FT-jobs). Baseline и генерация синтетики — через OpenRouter. Клиент автоматически переключается.

---

## 6. Чеклист сдачи (по формулировке задания)

- [x] Выбрана задача: **генерация** (мультитурн agent-диалоги с tool_calls)
- [x] **58 примеров** в JSONL (≥50 требовалось)
- [x] Каждый пример — объект с `messages`: system + user + assistant (+ tool для агентских)
- [x] assistant — эталонный ответ
- [x] **20.7% реальных** (12 hand-crafted seeds из реальных KMP-задач) — ≥20% порог выполнен
- [x] Убран мусор: dedup, пустые, длины в пределах
- [x] **Train 47 (80%) + Eval 11 (20%)**, stratified
- [x] Скрипт валидации: `src/validator/validate.py` — structural + semantic + dedup
- [x] **Baseline на 11 примерах `eval.jsonl`** через `gpt-4o-mini` без FT, отчёт в `src/baseline/outputs_eval/summary.md`
- [x] Критерии «стало лучше» — 5 авто + 2 LLM-judge в `criteria/criteria.md`
- [x] Клиент fine-tune: `src/ft_client/openai/` (OpenAI) + `src/ft_client/mlx/` (локальный MLX) — **dry-run, не запущен**

---

## 7. Ограничения и что намеренно не сделано

1. **LLM-judge метрики пока без runner-скрипта.** Шаблон промпта для judge заложен, но автоматический прогон — задача Дня 7+ (смысл его крутить до FT ограничен).
2. **Fine-tune не запущен.** Это прямое требование задания — «пока не запускайте».
3. **Runner агента (исполнение инструментов в реальной FS) отложен на День 7+.** Для Дня 6 достаточно, чтобы датасет и контракты существовали; исполнение приложения мы запустим потом.

---

## 8. Локальное обучение (MLX)

Помимо OpenAI API, проект поддерживает **локальный fine-tuning на Mac Apple Silicon** через MLX:

- **Модель**: Qwen 2.5 7B Instruct (HF: `Qwen/Qwen2.5-7B-Instruct`), ~8-10 GB peak RAM при QLoRA
- **Датасет переносим на 100%** — `mlx_lm` v0.31+ нативно поддерживает OpenAI chat format с `tool_calls`
- **Бэкенд**: `src/ft_client/mlx/train.py` (обучение) + `src/ft_client/mlx/export.py` (merge → GGUF → Ollama)
- **Eval**: `src/baseline/run_baseline.py --provider ollama --model kmp-agent-ft`

OpenAI-скрипты (`src/ft_client/openai/`) остаются рабочими для cross-проверки.

---

## 9. Файлы для сдачи

- `data/out/train.jsonl` — **47** строк
- `data/out/eval.jsonl` — **11** строк
- `data/out/eval_plain.jsonl` — 5 строк (anti-catastrophic-forgetting)
- `data/seeds/*.json` — **12** исходных seed-примеров
- `data/synthetic/*.json` — **46** сгенерированных
- `src/validator/validate.py` — скрипт валидации
- `src/baseline/run_baseline.py` + `src/baseline/outputs_eval/` — бейзлайн и отчёты
- `criteria/criteria.md` — критерии оценки
- `src/ft_client/openai/` — OpenAI FT клиент
- `src/ft_client/mlx/` — локальный MLX FT клиент
- `README.md` / `EXPLANATION.md` / `REPORT.md` — документация

**Воспроизведение с нуля** (при наличии API-ключей в `.env`):
```bash
pip install -r requirements.txt
python -m src.dataset.gen_synthetic --count 46 --model openai/gpt-oss-120b:free --seed 42
python -m src.validator.validate data/synthetic
python -m src.dataset.mix_and_split
python -m src.baseline.run_baseline
python -m src.dataset.summarize
```
