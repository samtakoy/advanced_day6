# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fine-tune dataset pipeline for a **task extraction** model. The project builds, validates, and manages a 56-example JSONL dataset used to fine-tune LLMs on extracting structured task JSON from free-form descriptions of KMP (Kotlin Multiplatform) project tasks. Supports two FT backends: **OpenAI API** (`gpt-4o-mini`) and **local MLX** (Qwen 2.5 on Mac Apple Silicon).

FT goal: teach the model to extract `title`, `type`, `block`, `modules`, `dependsOn`, `acceptanceCriteria`, `outOfScope` from a Slack-like task description — using project-specific taxonomy of 21 module aliases and 6 roadmap blocks. The key metric is `modules IoU` — baseline models confuse module names with class/package names without domain-specific training.

## Project Structure

```
advanced_day6/
├── src/                        # весь исполняемый код
│   ├── baseline/               # baseline eval (run_baseline.py)
│   ├── dataset/                # сборка датасета из gold.md → JSONL
│   │   └── build_dataset.py    #   gold.md + prose → train.jsonl + eval.jsonl
│   ├── ft_client/              # fine-tuning бэкенды
│   │   ├── openai/             #   OpenAI API (upload, create_job, poll)
│   │   └── mlx/                #   MLX local (train, export)
│   ├── multistage/             # Day 9: multi-stage inference decomposition
│   └── validator/              # валидация extraction JSONL
├── data/                       # все данные
│   ├── extraction/             # source-of-truth для датасета
│   │   ├── system.md           #   system prompt (единый для всех примеров)
│   │   ├── gold.md             #   56 gold-JSON с маркерами [TRAIN]/[EVAL]
│   │   ├── tasks1_prose.md     #   прозаические user-входы для задач 1-25
│   │   ├── tasks2.md           #   user-входы для задач 26-50
│   │   └── tasks_adversarial.md #  adversarial user-входы для задач 51-56
│   ├── out/                    # generated artifacts (train.jsonl, eval.jsonl)
│   ├── mlx/                    # артефакты MLX-обучения, по модели
│   │   └── <model-slug>/       #   e.g. qwen2.5-7b-instruct
│   │       ├── mlx_data/       #     train.jsonl + valid.jsonl для mlx_lm
│   │       ├── adapters/       #     LoRA-адаптеры
│   │       └── fused/          #     merged модель (safetensors)
│   └── baseline/               # результаты baseline-оценки
│       └── eval/<model-slug>/  #   eval JSON + summary per model
├── docs/                       # документация
├── plans/                      # planning docs
├── criteria/                   # eval criteria
└── requirements.txt
```

### Source of truth

Содержание датасета живёт в markdown — не в JSONL. JSONL-файлы перегенерируются из markdown одной командой (`build_dataset.py`). Причина: 56 gold-JSON легче ревьюить и править в markdown-блоках, чем в однострочных JSONL.

### Конвенция `<model-slug>`

Папки `data/mlx/`, `data/baseline/eval/` делятся на подпапки по slug модели. Slug — имя модели в нижнем регистре без провайдера, например:
- `qwen2.5-7b-instruct` — базовая модель
- `gpt-4o-mini` — OpenAI baseline
- `kmp-extract-ft` — fine-tuned модель

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Unix
pip install -r requirements.txt
cp .env.example .env        # fill in OPENAI_API_KEY and/or OPENROUTER_API_KEY
```

## Key Commands

```bash
# Build train/eval JSONL from source-of-truth markdown
python -m src.dataset.build_dataset

# Validate JSONL (schema, taxonomy, dedup, leakage)
python -m src.validator.validate
python -m src.validator.validate data/out/train.jsonl

# Run baseline evaluation
python -m src.baseline.run_baseline                                    # OpenAI/OpenRouter
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:14b-instruct  # Ollama

# OpenAI fine-tune workflow
python -m src.ft_client.openai.upload --validation data/out/eval.jsonl
python -m src.ft_client.openai.create_job           # dry-run by default
python -m src.ft_client.openai.create_job --confirm # actual submission
python -m src.ft_client.openai.poll

# Local MLX fine-tune workflow
pip install mlx mlx-lm
python -m src.ft_client.mlx.train --model Qwen/Qwen2.5-7B-Instruct
python -m src.ft_client.mlx.export --ollama-name kmp-extract-ft
python -m src.baseline.run_baseline --provider ollama --model kmp-extract-ft

# Day 9: Multi-stage inference (monolithic vs 3-stage decomposition)
python -m src.multistage.run_multistage --dry-run
python -m src.multistage.run_multistage                                        # OpenAI/OpenRouter
python -m src.multistage.run_multistage --provider ollama --model qwen2.5:7b-instruct
python -m src.multistage.run_multistage --no-mono                              # skip monolithic comparison
```

## Dataset Format

Single-turn extraction: system + user → assistant JSON. 56 примеров (45 train / 11 eval), стратифицировано по 6 блокам.

### Extraction schema

```json
{
  "title": "string",
  "type": "feat | refactor | research",
  "block": "workspace_foundation | indicators | analysis | polish_and_glue | breadth | tech_debt_refactor",
  "modules": ["string"],
  "dependsOn": [0],
  "acceptanceCriteria": ["string"],
  "outOfScope": ["string"]
}
```

### Eval metrics

- `type` / `block`: exact match
- `modules`: IoU (Jaccard) — **главная метрика**
- `dependsOn`: IoU
- `acceptanceCriteria`: recall
- `outOfScope`: precision

## Language

Project documentation and scenarios are in Russian. Code, variable names, and tool contracts are in English.

## MLX Fine-tuning: важные грабли

### venv обязателен
**ВСЕГДА** запускать через `source .venv/bin/activate`. Системный Anaconda python содержит MPICH, несовместимый с MLX — вызывает тихий SIGABRT при загрузке модели. Диагностировать сложно: нет traceback, только `exit code -6`.

### Ollama перед обучением
Перед запуском `mlx.train` убить Ollama (`pkill -f ollama`) — она держит модели в GPU-памяти (15+ GB), что вызывает OOM при обучении.

### Single-turn и --mask-prompt (MLX)
Новый датасет single-turn (3 сообщения: system, user, assistant), поэтому проблема `--mask-prompt` с multi-turn больше не актуальна. `--mask-prompt` корректно маскирует system+user и учит только на assistant-ответе.

### GGUF обязателен для Ollama
Импорт из safetensors (`FROM <папка>`) теряет chat template. Всегда конвертировать в GGUF и прописывать TEMPLATE в Modelfile явно. Конвертер: `/private/tmp/llama.cpp/convert_hf_to_gguf.py`.
