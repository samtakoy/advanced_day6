# OpenAI fine-tuning бэкенд.
# Скрипты:
#   python -m ft_client.openai.upload          — загрузка train.jsonl в OpenAI Files API
#   python -m ft_client.openai.create_job      — создание FT job (dry-run по умолчанию)
#   python -m ft_client.openai.poll            — polling статуса job
