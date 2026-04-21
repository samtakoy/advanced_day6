# Day 6 — Fine-tune dataset для KMP state-machine агента

Python-проект для Дня 6: подготовка датасета (50 JSONL), валидатор, baseline через `gpt-4o-mini` и fine-tune клиент для OpenAI API.

Полный план: [`../plans/adv_day6_impl_B.md`](../plans/adv_day6_impl_B.md)
Анализ и обоснование архитектуры: [`../plans/adv_day6_analisys.md`](../plans/adv_day6_analisys.md), [`../plans/adv_day6_variants.md`](../plans/adv_day6_variants.md)

## Архитектура (кратко)

Модель учится работать со **split tool-контрактом**:

- **State tools** (5 шт., семантические): `plan_write`, `step_read`, `step_update_result`, `task_status`, `plan_revise` — управление собственным планом задачи, скопированное по `task_id`.
- **Project tools** (4 шт.): `read_file`, `list_dir`, `search_and_replace`, `write_file` — работа с реальным кодом проекта.

В B-реализации state tools под капотом пишут/читают JSON в `.tasks/<task_id>/`. При переходе на вариант A (MCP Memory Layer) меняются только реализации state tools — модель не переобучается.

## Setup

```bash
# из этой папки
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
# или .venv\Scripts\activate.bat  # cmd
# или source .venv/bin/activate    # Unix

pip install -r requirements.txt
cp .env.example .env
# прописать OPENAI_API_KEY и ANTHROPIC_API_KEY в .env
```

## Структура

| Папка | Назначение |
|---|---|
| `contracts/` | Контракты: OpenAI tool schemas + JSON schemas для Step/Plan |
| `prompts/` | `system_agent.md` / `system_plain.md` + мета-промпты для генерации |
| `dataset/` | Golden example, реальные примеры, генератор, train/eval |
| `validator/` | Структурные и семантические проверки JSONL |
| `baseline/` | Прогон 10 eval через `gpt-4o-mini` без FT |
| `criteria/` | Критерии оценки "стало лучше" |
| `ft_client/` | Upload + create job + poll (default dry-run) |
| `runner/` | (stub) Исполнитель агента для Дня 7+ |

## Пайплайн (как прогнать всё от начала до конца)

```bash
# 1. Синтетика (батчами по моделям для стилевого разнообразия)
python -m dataset.gen_synthetic --count 10 --type develop --model openai/gpt-4o --seed 31
python -m dataset.gen_synthetic --count 5 --type bugfix --model anthropic/claude-3.7-sonnet --seed 42
# ... и так далее по типам (см. scenarios.py квоты)

# 2. Валидация всех примеров (seeds + synthetic)
python -m validator.validate dataset/seeds
python -m validator.validate dataset/synthetic

# 3. Сборка train/eval (80/20 stratified)
python -m dataset.mix_and_split
# -> dataset/train.jsonl, dataset/eval.jsonl

# 4. Baseline (без FT)
python -m baseline.run_baseline
# -> baseline/outputs/summary.md

# 5. Fine-tune (потребует прямой OPENAI_API_KEY)
python -m ft_client.upload --validation dataset/eval.jsonl
python -m ft_client.create_job           # dry-run
python -m ft_client.create_job --confirm # реальная отправка
python -m ft_client.poll
```

## Фазы (чеклист на сдачу)

- [x] 0. Setup + контракты + golden example.
- [x] 1. Scenarios и типология задач (5 типов agent + question + plain).
- [x] 2. Синтетика (генератор с retry-on-validation-fail + двумя моделями).
- [x] 3. 8 seed-примеров вручную (golden × 2 + refactor/bugfix/research/tests/question/plain).
- [x] 4. Валидатор (структурный + семантический + dedup).
- [x] 5. Mix + train/eval split (stratified).
- [x] 6. Baseline через `gpt-4o-mini`.
- [x] 7. Критерии: 5 авто + 2 LLM-judge (`criteria/criteria.md`).
- [x] 8. FT-клиент: upload + create_job (`--confirm` guard) + poll.
- [x] `eval_plain.jsonl` — mini-eval на plain-mode для анти-catastrophic-forgetting.

## Провайдеры API

Генерация/baseline работает через:
- **OpenRouter** (один ключ на все модели) — если выставлен `OPENROUTER_API_KEY`. Имена моделей: `openai/gpt-4o`, `anthropic/claude-sonnet-4`, `anthropic/claude-3.7-sonnet`.
- **OpenAI direct** — если `OPENAI_API_KEY`. Fine-tune требует именно этого (OpenRouter FT не поддерживает).
