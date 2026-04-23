# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fine-tune dataset pipeline for a KMP (Kotlin Multiplatform) state-machine agent. The project generates, validates, and manages a 58-example JSONL dataset used to fine-tune LLMs on agent discipline format. Supports two FT backends: **OpenAI API** (`gpt-4o-mini`) and **local MLX** (Qwen 2.5 on Mac Apple Silicon). The agent learns a **split tool-contract**: 5 state tools (`plan_write`, `step_read`, `step_update_result`, `task_status`, `plan_revise`) for managing its own plan, and 4 project tools (`read_file`, `list_dir`, `search_and_replace`, `write_file`) for code changes.

FT goal: teach discipline (THOUGHT + SELF-CHECK markers, read-before-action, replan-on-error), not domain knowledge. The same dataset works for both OpenAI and local models.

## Project Structure

```
advanced_day6/
├── src/                        # весь исполняемый код
│   ├── baseline/               # baseline eval (run_baseline.py)
│   ├── dataset/                # генерация/обработка датасета
│   │   └── split_turns.py      #   sliding window для multi-turn → single-turn
│   ├── ft_client/              # fine-tuning бэкенды
│   │   ├── openai/             #   OpenAI API (upload, create_job, poll)
│   │   └── mlx/                #   MLX local (train, export)
│   └── validator/              # валидация JSONL
├── data/                       # все данные
│   ├── contracts/              # tool + artifact JSON schemas
│   ├── prompts/                # system + meta prompts
│   ├── seeds/                  # hand-crafted examples (оригинал)
│   ├── synthetic/              # generated examples (оригинал)
│   ├── split/                  # данные после split_turns.py (см. docstring скрипта)
│   │   ├── seeds/              #   split-версии hand-crafted
│   │   └── synthetic/          #   split-версии generated
│   ├── out/                    # generated artifacts (train.jsonl, eval.jsonl)
│   ├── mlx/                    # артефакты MLX-обучения, по модели
│   │   └── <model-slug>/       #   e.g. qwen2.5-7b-instruct
│   │       ├── mlx_data/       #     train.jsonl + valid.jsonl для mlx_lm
│   │       ├── adapters/       #     LoRA-адаптеры
│   │       └── fused/          #     merged модель (safetensors)
│   └── baseline/               # результаты baseline-оценки, по модели
│       ├── eval/<model-slug>/  #   eval JSON + summary per model
│       ├── seeds/<model-slug>/ #   eval на seeds per model
│       └── train/<model-slug>/ #   eval на train per model
├── docs/                       # документация (EXPLANATION, REPORT, tutorial)
├── plans/                      # planning docs
├── criteria/                   # eval criteria
└── requirements.txt
```

### Конвенция `<model-slug>`

Папки `data/mlx/`, `data/baseline/eval/`, `data/baseline/seeds/`, `data/baseline/train/` делятся на подпапки по slug модели. Slug — имя модели в нижнем регистре без провайдера, например:
- `qwen2.5-7b-instruct` — базовая модель
- `qwen2.5-3b-instruct` — маленькая модель
- `qwen2.5-coder-7b-instruct` — coder-вариант
- `kmp-agent-ft`, `kmp-3b-ft`, `kmp-coder-ft` — fine-tuned модели
- `gpt-4o-mini` — OpenAI baseline

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Unix
pip install -r requirements.txt
cp .env.example .env        # fill in OPENAI_API_KEY and/or OPENROUTER_API_KEY
```

## Key Commands

```bash
# Generate synthetic examples
python -m src.dataset.gen_synthetic --count 10 --type develop --model openai/gpt-4o --seed 31

# Validate examples (accepts dir of .json files or .jsonl)
python -m src.validator.validate data/seeds
python -m src.validator.validate data/out/train.jsonl

# Build train/eval split (80/20 stratified)
python -m src.dataset.mix_and_split

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
python -m src.ft_client.mlx.export --ollama-name kmp-agent-ft
python -m src.baseline.run_baseline --provider ollama --model kmp-agent-ft
```

## Dataset Modes

Examples fall into three modes (detected automatically by the validator):
- **agent** (~70%): Full plan → step_read → action → SELF-CHECK → update cycle
- **agent_question** (~20%): Model asks clarifying QUESTION: instead of acting
- **plain** (~10%): Free prose response, no tool calls

## Language

Project documentation and scenarios are in Russian. Code, variable names, and tool contracts are in English.

## MLX Fine-tuning: важные грабли

### venv обязателен
**ВСЕГДА** запускать через `source .venv/bin/activate`. Системный Anaconda python содержит MPICH, несовместимый с MLX — вызывает тихий SIGABRT при загрузке модели. Диагностировать сложно: нет traceback, только `exit code -6`.

### Ollama перед обучением
Перед запуском `mlx.train` убить Ollama (`pkill -f ollama`) — она держит модели в GPU-памяти (15+ GB), что вызывает OOM при обучении.

### --mask-prompt и multi-turn (только MLX)
`--mask-prompt` в mlx_lm маскирует всё до **последнего** сообщения, а не по ролям. Для multi-turn диалогов это значит: учится только финальный assistant-ход, все предыдущие (включая plan_write) маскируются. Альтернатива: `split_turns.py` — см. docstring скрипта для деталей и статуса. **OpenAI API** эту проблему не имеет — автоматически маскирует по ролям, multi-turn работает из коробки.

### data/out/ — единый выход mix_and_split
`mix_and_split` перезаписывает `data/out/train.jsonl`. По умолчанию берёт `data/seeds/` и `data/synthetic/`. Для split-данных — явно указывать `--seeds-dir data/split/seeds --synthetic-dir data/split/synthetic`.

### GGUF обязателен для Ollama с tool calling
Импорт из safetensors (`FROM <папка>`) теряет chat template — модель не поддерживает tool calling. Всегда конвертировать в GGUF и прописывать TEMPLATE в Modelfile явно. Конвертер: `/private/tmp/llama.cpp/convert_hf_to_gguf.py`.
