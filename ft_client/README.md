# ft_client — запуск fine-tune в OpenAI

Сквозной путь: upload → create_job → poll. Все шаги должны выполняться **только поверх прямого OpenAI API** (не OpenRouter — fine-tuning через прокси не работает). Ключ берётся из `OPENAI_API_KEY` в `.env`.

## Команды

```bash
# 1. Загрузить train.jsonl (и опционально eval.jsonl) в OpenAI Files
python -m ft_client.upload --validation dataset/eval.jsonl

# 2. Посмотреть, что будет отправлено (dry-run, без расходов)
python -m ft_client.create_job

# 3. Реально создать job (стоит деньги — оборонено флагом)
python -m ft_client.create_job --confirm

# 4. Мониторить статус
python -m ft_client.poll
```

## Файлы-состояния

- `last_upload.json` — сохраняется после `upload.py`, содержит `training_file` и `validation_file` id-шники.
- `last_job.json` — сохраняется после `create_job.py --confirm`, содержит `job_id` и стартовый статус.

## Параметры по умолчанию

- **Model**: `gpt-4o-mini-2024-07-18`
- **Epochs**: `auto`
- **Suffix**: `kmp-agent` (итоговая модель: `ft:gpt-4o-mini-2024-07-18:org::kmp-agent:xxxx`)

Переопределяются флагами:
```bash
python -m ft_client.create_job --model gpt-4o-mini-2024-07-18 --epochs 3 --suffix v2 --confirm
```

## Оценка стоимости (50 примеров, ~15-20k токенов суммарно)

- train: ~$1-3 (OpenAI tier-dependent)
- eval validation_file не стоит отдельно (читает бесплатно)

## Что делать после `succeeded`

1. Модель доступна по `ft:...` id.
2. Прогнать `python -m baseline.run_baseline --model ft:... --in dataset/eval.jsonl` (или эквивалент) и сравнить с baseline.
3. Сверить с `criteria/criteria.md`.
