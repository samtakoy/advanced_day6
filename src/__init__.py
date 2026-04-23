# src — корневой пакет проекта.
# Содержит весь исполняемый код:
#   src.baseline    — прогон baseline eval (extraction метрики)
#   src.dataset     — сборка датасета из gold.md + prose → JSONL
#   src.ft_client   — fine-tuning бэкенды (openai, mlx)
#   src.validator   — валидация extraction JSONL (схема, таксономия, дубли)
