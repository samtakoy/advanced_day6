# Day 6 — Fine-tune dataset для KMP state-machine агента

Python-проект для Дня 6: подготовка датасета (58 JSONL), валидатор, baseline через `gpt-4o-mini` и fine-tune клиенты (OpenAI API + локальный MLX).

Полный план: [`plans/adv_day6_impl_B.md`](plans/adv_day6_impl_B.md)
Расширение (локальный FT): [`plans/day6_plan_detailed.md`](plans/day6_plan_detailed.md)

## Архитектура (кратко)

Модель учится работать со **split tool-контрактом**:

- **State tools** (5 шт., семантические): `plan_write`, `step_read`, `step_update_result`, `task_status`, `plan_revise` — управление собственным планом задачи, скопированное по `task_id`.
- **Project tools** (4 шт.): `read_file`, `list_dir`, `search_and_replace`, `write_file` — работа с реальным кодом проекта.

В B-реализации state tools под капотом пишут/читают JSON в `.tasks/<task_id>/`. При переходе на вариант A (MCP Memory Layer) меняются только реализации state tools — модель не переобучается.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate    # Unix
pip install -r requirements.txt
cp .env.example .env
# прописать OPENAI_API_KEY и/или OPENROUTER_API_KEY в .env

# Для локального MLX fine-tuning (опционально):
pip install mlx mlx-lm
```

## Структура

```
advanced_day6/
├── src/                        # весь исполняемый код
│   ├── baseline/               # baseline eval
│   ├── dataset/                # генерация и обработка датасета
│   ├── ft_client/openai/       # OpenAI FT (upload, create_job, poll)
│   ├── ft_client/mlx/          # MLX local FT (train, export)
│   └── validator/              # валидация JSONL
├── data/                       # все данные
│   ├── contracts/              # tool schemas + JSON schemas
│   ├── prompts/                # system + meta промпты
│   ├── seeds/                  # hand-crafted примеры (12)
│   ├── synthetic/              # сгенерированные примеры (~46)
│   └── out/                    # артефакты: train.jsonl, eval.jsonl
├── plans/                      # планы и анализ
├── criteria/                   # критерии оценки
└── requirements.txt
```

## Пайплайн (как прогнать всё от начала до конца)

```bash
# 1. Синтетика (батчами по моделям для стилевого разнообразия)
python -m src.dataset.gen_synthetic --count 10 --type develop --model openai/gpt-4o --seed 31

# 2. Валидация всех примеров (seeds + synthetic)
python -m src.validator.validate data/seeds
python -m src.validator.validate data/synthetic

# 3. Сборка train/eval (80/20 stratified)
python -m src.dataset.mix_and_split
# -> data/out/train.jsonl, data/out/eval.jsonl

# 4. Baseline (без FT)
python -m src.baseline.run_baseline
# -> src/baseline/outputs_eval/summary.md

# 5a. Fine-tune через OpenAI API (потребует OPENAI_API_KEY)
python -m src.ft_client.openai.upload --validation data/out/eval.jsonl
python -m src.ft_client.openai.create_job           # dry-run
python -m src.ft_client.openai.create_job --confirm # реальная отправка
python -m src.ft_client.openai.poll

# 5b. Fine-tune локально через MLX (Apple Silicon, бесплатно)
python -m src.ft_client.mlx.train --iters 600       # QLoRA обучение
python -m src.ft_client.mlx.export                  # merge + экспорт в Ollama

# 6. Post-FT eval через Ollama (локальные модели)
python -m src.baseline.run_baseline --provider ollama --model kmp-agent-ft
```

## Провайдеры API

Генерация/baseline работает через:
- **OpenRouter** (один ключ на все модели) — если выставлен `OPENROUTER_API_KEY`.
- **OpenAI direct** — если `OPENAI_API_KEY`. Fine-tune через OpenAI требует именно этого.
- **Ollama** (локально) — `--provider ollama`. Для baseline/eval на локальных моделях. Без API ключа.
