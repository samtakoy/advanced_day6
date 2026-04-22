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
│   ├── ft_client/              # fine-tuning бэкенды
│   │   ├── openai/             #   OpenAI API (upload, create_job, poll)
│   │   └── mlx/                #   MLX local (train, export)
│   └── validator/              # валидация JSONL
├── data/                       # все данные
│   ├── contracts/              # tool + artifact JSON schemas
│   ├── prompts/                # system + meta prompts
│   ├── seeds/                  # hand-crafted examples
│   ├── synthetic/              # generated examples
│   └── out/                    # generated artifacts (train.jsonl, eval.jsonl)
├── plans/                      # planning docs
├── criteria/                   # eval criteria
└── requirements.txt
```

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
