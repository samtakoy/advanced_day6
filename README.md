# Day 6 — Fine-tune dataset для extraction задач KMP stocks

Python-проект для подготовки датасета (56 JSONL), валидатора и fine-tune клиентов (OpenAI API + локальный MLX) для модели **извлечения структурных задач** из свободных описаний.

## Что делает модель

На входе — описание задачи в свободной форме (Slack-тикет, обсуждение).
На выходе — JSON с полями: `title`, `type`, `block`, `modules`, `newModules`, `dependsOn`, `acceptanceCriteria`, `outOfScope`.

Модель маппит свободный текст на таксономию проекта: 16 алиасов модулей, 6 блоков роадмапа, 3 типа задач.

## Документация

| Файл | Что внутри |
|------|-----------|
| [`CLAUDE.md`](CLAUDE.md) | Инструкции для Claude Code (структура, команды, грабли) |
| [`docs/EXPLANATION.md`](docs/EXPLANATION.md) | Что это за проект и как он устроен |
| [`docs/LOCAL_FINETUNE_TUTORIAL.md`](docs/LOCAL_FINETUNE_TUTORIAL.md) | Пошаговый туториал локального FT на Mac (MLX + Ollama) |
| [`reports/DAY6_intermediate_report.md`](reports/DAY6_intermediate_report.md) | Промежуточные эксперименты и метрики |

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
│   ├── baseline/               # baseline eval (extraction метрики)
│   ├── dataset/                # сборка датасета из gold.md → JSONL
│   ├── ft_client/openai/       # OpenAI FT (upload, create_job, poll)
│   ├── ft_client/mlx/          # MLX local FT (train, export)
│   └── validator/              # валидация extraction JSONL
├── data/
│   ├── extraction/             # source-of-truth (gold.md, system.md, prose)
│   └── out/                    # артефакты: train.jsonl, eval.jsonl
├── reports/                    # отчёты по экспериментам
├── docs/                       # документация
└── requirements.txt
```

## Пайплайн

```bash
# 1. Сборка train/eval JSONL из source-of-truth markdown
python -m src.dataset.build_dataset

# 2. Валидация (схема, таксономия, дубли, leakage)
python -m src.validator.validate

# 3. Baseline (без FT)
python -m src.baseline.run_baseline --provider ollama --model qwen2.5:7b-instruct \
  --from-jsonl data/out/eval.jsonl --num-ctx 4096

# 4a. Fine-tune локально через MLX (Apple Silicon)
pkill -f ollama  # освободить GPU
python -m src.ft_client.mlx.train --iters 200 --batch-size 1 --grad-accum-steps 2 \
  --learning-rate 1e-5 --max-seq-length 3072

# 4b. Fine-tune через OpenAI API
python -m src.ft_client.openai.upload --validation data/out/eval.jsonl
python -m src.ft_client.openai.create_job --confirm
python -m src.ft_client.openai.poll

# 5. Экспорт в Ollama (после MLX)
python -m src.ft_client.mlx.export --ollama-name kmp_extract_ft

# 6. Post-FT eval
python -m src.baseline.run_baseline --provider ollama --model kmp_extract_ft \
  --from-jsonl data/out/eval.jsonl --num-ctx 4096
```

## Провайдеры

- **Ollama** (локально) — `--provider ollama`. Основной для baseline/eval.
- **OpenRouter** — если выставлен `OPENROUTER_API_KEY`.
- **OpenAI** — если `OPENAI_API_KEY`. Для OpenAI fine-tune.
